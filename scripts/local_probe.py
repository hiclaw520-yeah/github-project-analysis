#!/usr/bin/env python3
"""
local_probe.py — 对已克隆到本地的仓库做体检（不消耗 GitHub API 额度）。

用法:
    git clone --depth 300 https://github.com/owner/repo.git /tmp/repo
    python local_probe.py /tmp/repo

输出 Markdown：提交历史、代码规模、测试比例、技术债标记、依赖规模、工程化信号、安全红旗。
只依赖标准库 + git 命令。
"""
import json
import os
import re
import subprocess
import sys

# 输出强制 UTF-8（replace 兜底）：中文 Windows 下输出被管道/重定向时，Python 会退回
# GBK 等本地编码，遇到 ✓ 等字符抛 UnicodeEncodeError 直接中断；统一 UTF-8 后任何编码环境都不崩。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from collections import Counter, defaultdict
from datetime import datetime, timezone

TEXT_EXT = {".md", ".mdx", ".json", ".yml", ".yaml", ".toml", ".sh", ".txt", ".ini", ".cfg", ".env", ".ps1"}
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__", ".next",
             "vendor", "target", ".idea", ".vscode", "site-packages", "coverage", ".pytest_cache"}
CODE_EXT = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
            ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin",
            ".c": "C", ".cc": "C++", ".cpp": "C++", ".h": "C/C++ header", ".rb": "Ruby",
            ".php": "PHP", ".cs": "C#", ".swift": "Swift", ".vue": "Vue", ".sh": "Shell",
            ".sql": "SQL", ".css": "CSS", ".scss": "CSS", ".html": "HTML"}
TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(_test|\.test|\.spec)\.|(^|/)test_")
DEBT_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
SECRET_RES = [
    (re.compile(r"sk-[A-Za-z0-9]{32,}"), "疑似 OpenAI 风格密钥"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "疑似 AWS Access Key"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "疑似 GitHub Token"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"), "私钥文件内容"),
]
RISK_PATTERNS = [
    (re.compile(r"curl[^\n|]*\|\s*(sudo\s+)?(ba)?sh"), "curl | sh 管道执行"),
    (re.compile(r"child_process[\s\S]{0,200}\.(exec|execSync)\s*\(\s*`"), "child_process.exec 拼接模板字符串（命令注入风险）"),
    (re.compile(r"new Function\s*\("), "new Function()"),
    (re.compile(r"\binnerHTML\s*=|dangerouslySetInnerHTML"), "innerHTML / dangerouslySetInnerHTML（XSS 面）"),
    (re.compile(r"rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*[\"']?0"), "关闭 TLS 校验(Node)"),
    (re.compile(r"subprocess\.[a-z_]+\([^)]*shell\s*=\s*True"), "subprocess shell=True"),
    (re.compile(r"\beval\s*\("), "eval()"),
    (re.compile(r"\bos\.system\s*\("), "os.system()"),
    (re.compile(r"verify\s*=\s*False"), "关闭 TLS 校验"),
    (re.compile(r"allow_origins\s*=\s*\[\s*[\"']\*[\"']\s*\]"), "CORS 通配 allow_origins=*（若同时 allow_credentials=True 需复核鉴权方式）"),
    (re.compile(r"(?i)debug\s*=\s*True"), "debug=True 写死"),
    (re.compile(r"base64\.b64decode\([^)]{200,}"), "超长 base64 内联载荷"),
]


# 所有 git 调用都走这个包装：命令行 -c 优先级高于仓库自带的 .git/config，
# 避免被评估仓库通过 core.fsmonitor / core.sshCommand / hooksPath 等配置在本机执行命令；
# core.quotepath=false 让中文等非 ASCII 路径原样输出（默认会被转义成 "\346\212\200..." 形式，
# 导致脚本拿它对不上真实文件、漏检中文路径）。
GIT_SAFE = ["git", "-c", "core.quotepath=false", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
            "-c", "core.sshCommand=false", "-c", "core.pager=cat", "-c", "credential.helper=",
            "-c", "protocol.allow=never", "-c", "protocol.https.allow=always"]


_CFG = {"root_real": None}


def inside_repo(p):
    """仓库是不可信数据：拒绝符号链接，且真实路径必须落在仓库目录内，
    防止恶意仓库用软链接把沙箱里仓库外的文件（密钥、配置等）读进分析输出。"""
    try:
        if os.path.islink(p):
            return False
        rr = _CFG["root_real"]
        if rr is None:
            return True
        rp = os.path.realpath(p)
        return rp == rr or rp.startswith(rr + os.sep)
    except Exception:
        return False


def sh(cmd, cwd):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60).stdout
    except Exception:
        return ""


def main():
    if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]):
        sys.exit(__doc__)
    root = os.path.abspath(sys.argv[1])
    _CFG["root_real"] = os.path.realpath(root)
    print(f"# 本地体检: {os.path.basename(root)}\n")

    # ---------- git 历史 ----------
    shallow = os.path.exists(os.path.join(root, ".git", "shallow"))
    note_hist = ""
    origin = sh(GIT_SAFE + ["config", "--get", "remote.origin.url"], root).strip()
    if shallow and "--no-unshallow" not in sys.argv and not origin.startswith("https://"):
        note_hist = "未自动补全历史：origin 不是 https 地址（可能是别人提供的现成目录，出于安全不对其发起 fetch）"
    if shallow and "--no-unshallow" not in sys.argv and origin.startswith("https://"):
        try:
            r = subprocess.run(GIT_SAFE + ["fetch", "--quiet", "--unshallow", "--filter=blob:none", "origin"],
                               cwd=root, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=240)
            shallow = os.path.exists(os.path.join(root, ".git", "shallow"))
            note_hist = "已自动补全完整提交历史（仅元数据，不含历史文件内容）" if not shallow else "补全历史失败，仍是浅克隆"
        except Exception as e:
            note_hist = f"补全历史失败（{str(e)[:40]}），仍是浅克隆"
    log = sh(GIT_SAFE + ["log", "--format=%H|%ae|%aI|%s%n%b%x00"], root)
    commits = [c for c in log.split("\x00") if c.strip()]
    if commits:
        rows = []
        for c in commits:
            head, _, body = c.strip().partition("\n")
            parts = head.split("|", 3)
            if len(parts) == 4:
                rows.append((parts[1], parts[2], parts[3], c))
        authors = Counter(r[0] for r in rows)
        dates = [datetime.fromisoformat(r[1]) for r in rows]
        newest, oldest = max(dates), min(dates)
        span = max((newest - oldest).days, 1)
        now = datetime.now(timezone.utc)
        conv = sum(bool(re.match(r"^(feat|fix|docs|refactor|test|chore|perf|ci|build|style)(\(.+\))?!?:", r[2])) for r in rows)
        ai = sum(bool(re.search(r"co-authored-by:.*(claude|copilot|cursor|codex|gemini|openai|aider)|generated with.*(claude|copilot|cursor)", r[3], re.I)) for r in rows)
        month = Counter(d.strftime("%Y-%m") for d in dates)
        fixes = sum(bool(re.match(r"^fix", r[2], re.I)) for r in rows)
        r30 = sum(1 for d in dates if (now - d).days <= 30)
        r90 = sum(1 for d in dates if (now - d).days <= 90)
        active = sum(1 for a, n in authors.items() if n >= 3)
        top = authors.most_common(1)[0][1] * 100 // len(rows)
        print("## 提交历史")
        print(f"- 提交数 {len(rows)}；时间跨度 {span} 天（{oldest.date()} → {newest.date()}）；最近一次 {(now - newest).days} 天前"
              f"{'；' + note_hist if note_hist else ''}")
        print(f"- 近 30 天 {r30} 次、近 90 天 {r90} 次；**近 30 天占全史 {r30 * 100 // len(rows)}%**（>50% 说明刚经历爆发式开发或刚开源，要问为什么）")
        print(f"- 按【邮箱】去重的作者 {len(authors)} 人，其中提交≥3 次的活跃贡献者 {active} 人；头号作者占比 {top}%；Top3 {authors.most_common(3)}")
        print(f"  （>85% 视为单人项目；同一人常用多个 git 用户名，所以按邮箱而非用户名统计；noreply 邮箱已是 GitHub 账号粒度）")
        print(f"- Conventional Commits {conv * 100 // len(rows)}% · fix 类提交 {fixes * 100 // len(rows)}% · AI 共同作者署名 {ai * 100 // len(rows)}%")
        print(f"- 按月提交数（近 12 个月）: {sorted(month.items())[-12:]}")
        if span < 14 or r30 * 100 // len(rows) > 70:
            print("- ⚠ 提交高度集中在极短时间：可能是刚开源/迁移历史/批量自动化提交；热度、维护节奏的判断要据此修正")
        if shallow:
            print("- ⚠ 这是浅克隆，提交数/起始时间只代表最近一段，不代表项目全史")
        print()

    # ---------- 文件扫描 ----------
    loc = Counter()
    files_by_lang = Counter()
    test_loc = 0
    code_loc = 0
    big = []
    debt = 0
    debt_samples = []
    secrets, risks = [], []
    all_paths = []
    max_depth = 0
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        rel_dir = os.path.relpath(dp, root)
        max_depth = max(max_depth, 0 if rel_dir == "." else rel_dir.count(os.sep) + 1)
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")  # 统一正斜杠，Windows 下 TEST_RE/前缀判断才成立
            all_paths.append(rel)
            ext = os.path.splitext(fn)[1].lower()
            if rel.lower().endswith(".env"):
                secrets.append((rel, "仓库里提交了 .env 文件"))
            if ext in TEXT_EXT or fn in (".env", ".env.local", ".npmrc"):
                try:
                    if os.path.getsize(p) <= 600_000 and inside_repo(p) and not fn.endswith(("-lock.json", ".lock")) and fn not in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock"):
                        tt = open(p, encoding="utf-8", errors="ignore").read()
                        fixture = bool(re.search(r"(^|/)(tests?|__tests__|fixtures?|examples?|samples?|docs?|mocks?)/", rel.lower())) or fn.endswith(".example")
                        for rx, name in SECRET_RES:
                            if rx.search(tt):
                                secrets.append((rel, name + ("（位于测试/示例/文档路径，多为占位符，需复核）" if fixture else "")))
                        if ext in (".md", ".mdx", ".txt") and re.search(r"curl[^\n|]*\|\s*(sudo\s+)?(ba)?sh|wget[^\n|]*\|\s*(sudo\s+)?(ba)?sh|irm[^\n|]*\|\s*iex", tt):
                            risks.append((rel, "文档引导 curl|sh / irm|iex（用户会被引导管道执行远程脚本）"))
                except Exception:
                    pass
                continue
            if ext not in CODE_EXT:
                continue
            try:
                if os.path.getsize(p) > 2_000_000 or not inside_repo(p):
                    continue
                text = open(p, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            n = text.count("\n") + 1
            lang = CODE_EXT[ext]
            is_t = bool(TEST_RE.search(rel.lower()))
            if lang not in ("HTML", "CSS", "SQL"):
                if is_t:
                    test_loc += n
                else:
                    code_loc += n
                    big.append((n, rel))
            loc[lang] += n
            files_by_lang[lang] += 1
            for m in DEBT_RE.finditer(text):
                debt += 1
                if len(debt_samples) < 5:
                    debt_samples.append(rel)
            for rx, name in SECRET_RES:
                if rx.search(text):
                    secrets.append((rel, name))
            if ext in (".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".sh", ".ps1") and not is_t:
                for rx, name in RISK_PATTERNS:
                    if rx.search(text):
                        risks.append((rel, name))

    print("## 代码规模")
    print(f"- 按语言行数: {dict(loc.most_common(8))}")
    print(f"- 源码行 {code_loc}（不含测试/HTML/CSS/SQL）；测试代码行 {test_loc}；测试行/源码行 = {test_loc / max(code_loc, 1):.2f}"
          + ("  ⚠ 源码极少，该比值不适用（内容型/配置型仓库请看 content_probe.py）" if code_loc < 300 else ""))
    print(f"- 最大目录深度 {max_depth}；TODO/FIXME/HACK 共 {debt} 处（每千行 {debt * 1000 / max(code_loc, 1):.1f}）")
    big.sort(reverse=True)
    print(f"- 最大的 5 个源码文件: {big[:5]}")
    huge = [b for b in big if b[0] > 1000]
    print(f"- 超过 1000 行的文件 {len(huge)} 个（上帝文件风险）")
    print()

    # ---------- 依赖 ----------
    print("## 依赖规模")
    dep_found = False
    lockfiles = sorted({p for p in all_paths
                        if re.search(r"(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|bun\.lockb|poetry\.lock|uv\.lock|Cargo\.lock|go\.sum|Pipfile\.lock)$", p)})

    def count_reqs(path, seen, depth=0):
        """requirements.txt 实际依赖数：-r/--requirement 引用递归展开（防环，深度限 3）。"""
        if depth > 3 or path in seen:
            return 0
        seen.add(path)
        try:
            lines = open(os.path.join(root, path), encoding="utf-8", errors="ignore").read().splitlines()
        except Exception:
            return 0
        n = 0
        for l in lines:
            l = l.strip()
            if not l or l.startswith("#"):
                continue
            m = re.match(r"^-r\s+(.+)$|^--requirement\s+(.+)$", l)
            if m:
                ref = (m.group(1) or m.group(2)).strip().strip('"\'')
                n += count_reqs(os.path.normpath(os.path.join(os.path.dirname(path), ref)).replace("\\", "/"), seen, depth + 1)
            elif not l.startswith(("-e ", "--editable", "-f ", "--find-links", "-i ", "--index-url", "--extra-index-url", "--trusted-host", "-c ", "--constraint")):
                n += 1
        return n

    for f in ("requirements.txt", "pyproject.toml", "package.json", "go.mod", "Cargo.toml"):
        for rel in all_paths:
            if os.path.basename(rel) == f and rel.count("/") <= 2 and inside_repo(os.path.join(root, rel)):
                dep_found = True
                try:
                    text = open(os.path.join(root, rel), encoding="utf-8", errors="ignore").read()
                except Exception:
                    continue
                if f == "requirements.txt":
                    n = count_reqs(rel, set())
                    pinned = len([l for l in text.splitlines() if "==" in l and not l.strip().startswith(("-r", "#", "-e"))])
                    print(f"- {rel}: 合计 {n} 个依赖（含 -r 引用展开），固定版本 {pinned} 个")
                elif f == "package.json":
                    try:
                        j = json.loads(text)
                        deps = len(j.get("dependencies", {})); dev = len(j.get("devDependencies", {}))
                        scripts = list(j.get("scripts", {}))
                        warn = [s for s in scripts if s in ("preinstall", "postinstall", "install")]
                        print(f"- {rel}: dependencies {deps} / devDependencies {dev}；install 钩子: {warn or '无'}")
                    except Exception:
                        pass
                elif f == "pyproject.toml":
                    m = re.search(r"(?ms)^\s*dependencies\s*=\s*\[(.*?)\]", text)
                    n = len(re.findall(r'["\']', m.group(1))) // 2 if m else 0
                    seg = re.search(r"(?ms)^\[tool\.poetry\.dependencies\]\s*$(.*?)(?=^\[|\Z)", text)
                    po = len(re.findall(r"(?m)^\s{2,}[\w.\-]+\s*=", seg.group(1))) - 1 if seg else 0  # 减 python 自身
                    print(f"- {rel}: PEP621 dependencies {n} 个" + (f"，poetry dependencies {po} 个" if seg else ""))
                elif f == "go.mod":
                    blk = re.search(r"(?ms)^\s*require\s*\((.*?)\)", text)
                    n = len([l for l in blk.group(1).splitlines() if l.strip() and not l.strip().startswith("//")]) if blk else 0
                    n += len(re.findall(r"(?m)^\s*require\s+\S+\s+v[\w.\-+]+", text))
                    print(f"- {rel}: require {n} 个模块")
                elif f == "Cargo.toml":
                    seg = re.search(r"(?ms)^\[dependencies\]\s*$(.*?)(?=^\[|\Z)", text)
                    n = len(re.findall(r"(?m)^\s*[\w.\-]+\s*=", seg.group(1))) if seg else 0
                    print(f"- {rel}: dependencies {n} 个")
                else:
                    print(f"- {rel}: 存在")
    if lockfiles:
        print(f"- 锁文件: ✓ {', '.join(lockfiles)}（依赖可复现）")
    else:
        print("- 锁文件: ✗ 未发现（依赖不可复现，rubric D 的验证性扣分点）")
    if not dep_found:
        print("- 未发现依赖清单文件（requirements.txt / pyproject.toml / package.json / go.mod / Cargo.toml）")
    print()

    # ---------- 工程化信号 ----------
    low = [p.lower() for p in all_paths]
    def has(pred): return any(pred(p) for p in low)
    sig = {
        "CI": has(lambda p: p.startswith(".github/workflows/")),
        "Docker": has(lambda p: "dockerfile" in p),
        "测试": test_loc > 0,
        "LICENSE": has(lambda p: "/" not in p and re.search(r"^(licen[sc]e|copying|unlicense)", p)),
        "CONTRIBUTING": has(lambda p: "contributing" in os.path.basename(p)),
        "SECURITY.md": has(lambda p: os.path.basename(p) == "security.md"),
        "架构文档": has(lambda p: "architecture" in p),
        "docs/目录": has(lambda p: p.startswith("docs/")),
        ".env.example": has(lambda p: p.endswith(".env.example")),
        "Makefile/脚本入口": has(lambda p: os.path.basename(p) in ("makefile", "justfile", "build.sh")),
        "lint/类型配置": has(lambda p: os.path.basename(p) in ("tsconfig.json", "mypy.ini", "ruff.toml", ".eslintrc.json", ".eslintrc.js", ".golangci.yml", "eslint.config.js")),
        "AI 协作配置": has(lambda p: re.search(r"(^|/)(agents?\.md|claude\.md|\.cursorrules|\.agents/|\.claude/)", p) is not None),
    }
    mono = [k for k, v in {"pnpm-workspace": has(lambda p: re.search(r"(^|/)pnpm-workspace\.yaml$", p) is not None),
                           "lerna": has(lambda p: re.search(r"(^|/)lerna\.json$", p) is not None),
                           "turbo": has(lambda p: re.search(r"(^|/)turbo\.json$", p) is not None),
                           "nx": has(lambda p: re.search(r"(^|/)nx\.json$", p) is not None),
                           "go.work": has(lambda p: re.search(r"(^|/)go\.work$", p) is not None)}.items() if v]
    sig["monorepo"] = bool(mono)
    sig["子模块"] = has(lambda p: p == ".gitmodules")
    sig["DISCLAIMER"] = has(lambda p: "disclaimer" in os.path.basename(p))
    sig["Dependabot/Renovate"] = has(lambda p: "dependabot" in p or "renovate" in p)
    print("## 工程化信号")
    print("- " + " · ".join(f"{k}{'✓' if v else '✗'}" for k, v in sig.items()))
    if not sig["LICENSE"]:
        lic = None
        for rel in all_paths:
            if rel.lower() in ("pyproject.toml", "package.json") and inside_repo(os.path.join(root, rel)):
                try:
                    t = open(os.path.join(root, rel), encoding="utf-8", errors="ignore").read(20000)
                except Exception:
                    continue
                m = (re.search(r'(?m)^\s*license\s*=\s*["\']?([^"\'{}\n]+)', t) if rel.lower() == "pyproject.toml"
                     else re.search(r'"license"\s*:\s*"([^"]+)"', t))
                if m:
                    lic = m.group(1).strip()
                    break
        if lic:
            print(f"- LICENSE: 根目录未检出许可证文件，但 {rel} 声明为 {lic}——以声明为准并人工核实全文")
        else:
            print("- LICENSE: 根目录未检出许可证文件，清单也无声明——需人工核实（勿直接判无）")
    wf = [p for p in all_paths if p.startswith(".github/workflows/")]
    print(f"- workflows: {wf}")
    print()

    # ---------- 安全红旗 ----------
    print("## 安全红旗（静态正则，仅提示，需人工复核，误报常见）")
    if not secrets and not risks:
        print("- 未命中")
    for rel, name in sorted(set(secrets))[:10]:
        print(f"- 🔴 {rel}: {name}")
    cnt = Counter(name for _, name in risks)
    for name, n in cnt.most_common():
        files = sorted({r for r, nm in risks if nm == name})[:3]
        print(f"- 🟡 {name}: {n} 处，例如 {files}")
    print("\n> 以上均为客观信号，不是结论。请继续按 SKILL.md 抽样阅读核心代码后再下判断。")


if __name__ == "__main__":
    main()
