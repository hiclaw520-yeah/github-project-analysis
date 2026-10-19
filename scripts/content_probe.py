#!/usr/bin/env python3
"""
content_probe.py — 内容型 / Agent 技能包 / 插件市场 类仓库的体检（只读，不执行仓库里的任何脚本）。

用法:
    python content_probe.py /tmp/repo

检查:
  1. SKILL.md：frontmatter 完整性、name 与目录一致、description 长度与"触发线索"、正文体量、引用文件是否存在
  2. 插件/市场清单：JSON 是否有效、声明的路径是否存在、清单与磁盘目录是否一致
  3. commands/agents 定义：frontmatter 与权限声明
  4. Markdown 相对链接是否失效
  5. 重复与高度相似（description / 名称）
  6. 风险扫描：危险命令、过宽的工具权限、疑似提示注入措辞、技能内携带的脚本与外联
  7. 多平台适配线索与自带校验工具

输出是线索，不是结论。绝不要执行仓库自带的校验/安装脚本，除非已审阅且在隔离环境。
"""
import json
import os
import re
import statistics
import subprocess
import sys
from collections import Counter

SKIP = {".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__"}


def list_files(root):
    try:
        out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, timeout=60).stdout
        fs = [l for l in out.splitlines() if l.strip()]
        if fs:
            return fs
    except Exception:
        pass
    fs = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP]
        fs += [os.path.relpath(os.path.join(dp, f), root) for f in fns]
    return fs


def read(root, rel, limit=600_000):
    try:
        p = os.path.join(root, rel)
        if os.path.getsize(p) > limit:
            return ""
        return open(p, encoding="utf-8", errors="ignore").read()
    except Exception:
        return ""


def frontmatter(text):
    """返回 (dict, body)。极简 YAML：顶层 key: value，支持 > | 多行。"""
    if not text.startswith("---"):
        return None, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return None, text
    fm, cur = {}, None
    for line in m.group(1).splitlines():
        k = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if k and not line.startswith(" "):
            cur = k.group(1)
            v = k.group(2).strip()
            fm[cur] = "" if v in (">", "|", ">-", "|-") else v.strip("\"'")
        elif cur and (line.startswith(" ") or line.startswith("\t")):
            fm[cur] = (fm[cur] + " " + line.strip()).strip()
    return fm, m.group(2)


def words(s):
    return set(re.findall(r"[a-z0-9]{3,}|[\u4e00-\u9fff]", s.lower()))


def jaccard(a, b):
    return len(a & b) / max(len(a | b), 1)


TRIGGER_RE = re.compile(r"\b(use (this )?(skill )?(when|whenever|for|to)|when (the )?user|trigger|invoke)\b|当用户|使用场景|触发|适用于|用于|当你需要", re.I)
DANGER = [
    (re.compile(r"curl[^\n|]*\|\s*(sudo\s+)?(ba)?sh|wget[^\n|]*\|\s*(sudo\s+)?(ba)?sh"), "管道执行远程脚本"),
    (re.compile(r"\brm\s+-rf\s+(/|~|\$HOME|\*)"), "危险删除命令"),
    (re.compile(r"\bsudo\b"), "sudo"),
    (re.compile(r"chmod\s+(-R\s+)?777"), "chmod 777"),
    (re.compile(r"\beval\s*[\(\$\"']"), "eval"),
    (re.compile(r"base64\s+(-d|--decode)"), "base64 解码执行线索"),
]
INJECTION = [
    (re.compile(r"ignore (all )?(previous|prior|above) (instructions|rules)|disregard (the )?(system|previous)", re.I), "覆盖既有指令"),
    (re.compile(r"do not (tell|inform|mention|reveal).{0,30}(user|human)|don'?t (tell|let) the user", re.I), "要求对用户隐瞒"),
    (re.compile(r"\b(send|upload|exfiltrat\w*|forward|transmit)\b.{0,60}(api[_ -]?keys?|tokens?|credentials?|passwords?|secrets?|\.env\b|ssh keys?|private keys?)", re.I), "外传凭据措辞"),
    (re.compile(r"\b(curl|wget|requests\.post|fetch)\b.{0,80}(\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD)\w*|\.env\b|~/\.ssh)", re.I), "带凭据的外联命令"),
    (re.compile(r"(read|cat|print|include).{0,40}(~/\.ssh|\.aws/credentials|id_rsa|\.env\b)", re.I), "读取敏感文件"),
]
PLACEHOLDER_LINK = re.compile(r"^(…|\.\.\.|url|link|path|<[^>]*>|\{[^}]*\}|relative/path\.md|path/to/.*|your[-_].*|example.*|todo|tbd|xxx+)$", re.I)
WIDE_TOOLS = re.compile(r"Bash\(\*\)|Bash\(\s*\)|^\s*\*\s*$|allowed-tools:\s*\"?\*", re.I)


def main():
    if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]):
        sys.exit(__doc__)
    root = os.path.abspath(sys.argv[1])
    files = list_files(root)
    fset = set(files)
    print(f"# 内容/技能包体检: {os.path.basename(root)}（文件 {len(files)}）\n")

    # ================= 1. SKILL.md =================
    skills = [f for f in files if f.lower().endswith("/skill.md") or f.lower() == "skill.md"]
    rows, descs, problems = [], {}, Counter()
    bodies = []
    for s in skills:
        t = read(root, s)
        fm, body = frontmatter(t)
        d = os.path.dirname(s)
        dirname = os.path.basename(d) if d else os.path.basename(root)
        info = {"path": s, "lines": body.count("\n") + 1, "fm": fm}
        if fm is None:
            problems["缺少 frontmatter"] += 1
        else:
            name, desc = fm.get("name", ""), fm.get("description", "")
            if not name:
                problems["缺少 name"] += 1
            elif name != dirname:
                problems["name 与目录名不一致"] += 1
            if name and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
                problems["name 不符合 小写字母/数字/连字符 规范"] += 1
            if not desc:
                problems["缺少 description"] += 1
            else:
                if len(desc) > 1024:
                    problems["description 超过 1024 字符"] += 1
                if len(desc) < 60:
                    problems["description 过短(<60 字符，难以触发)"] += 1
                if not TRIGGER_RE.search(desc):
                    problems["description 缺少触发场景线索"] += 1
                descs[s] = desc
            if "allowed-tools" in fm and WIDE_TOOLS.search(f"allowed-tools: {fm['allowed-tools']}"):
                problems["allowed-tools 权限过宽"] += 1
        if info["lines"] > 500:
            problems["正文 >500 行（建议拆分到 references/）"] += 1
        # 引用文件是否存在：`references/x.md`、scripts/…、[..](path)
        refs = set(re.findall(r"(?:`|\()((?:references|scripts|assets|templates|examples)/[\w./-]+)(?:`|\))", body))
        missing = [r for r in refs if os.path.normpath(os.path.join(d, r)) not in fset]
        if missing:
            problems["引用了不存在的文件"] += 1
            info["missing"] = missing[:3]
        sub = {x for x in ("references", "scripts", "assets") if any(f.startswith((d + "/" if d else "") + x + "/") for f in files)}
        info["sub"] = sub
        bodies.append(info["lines"])
        rows.append(info)

    print("## 1. SKILL.md 规范体检")
    if not skills:
        print("- 未发现 SKILL.md（若这是内容型仓库，见第 4/5 节）")
    else:
        dl = [len(v) for v in descs.values()]
        print(f"- 技能数 **{len(skills)}**；正文行数 中位 {statistics.median(bodies):.0f} / 最大 {max(bodies)}；description 长度 中位 {statistics.median(dl) if dl else 0:.0f}")
        print(f"- 带 references/ 的 {sum('references' in r['sub'] for r in rows)}、带 scripts/ 的 {sum('scripts' in r['sub'] for r in rows)}、带 assets/ 的 {sum('assets' in r['sub'] for r in rows)}")
        if problems:
            print("- 规范问题（数量 = 受影响的技能数）：")
            for k, v in problems.most_common():
                print(f"  - {k}: {v}/{len(skills)}")
        else:
            print("- 规范问题：未发现")
        bad = [r for r in rows if r.get("missing")][:3]
        for r in bad:
            print(f"  - 例：{r['path']} 引用缺失文件 {r['missing']}")
    print()

    # ================= 2. 插件/市场清单 =================
    manifests = [f for f in files if re.search(r"(^|/)(plugin|marketplace)\.json$", f.lower())]
    print("## 2. 插件 / 市场清单")
    if not manifests:
        print("- 未发现 plugin.json / marketplace.json")
    mk_plugins = set()
    disk_plugins = set()
    for m in manifests:
        t = read(root, m)
        try:
            j = json.loads(t)
        except Exception as e:
            print(f"- 🔴 {m}: JSON 无效（{str(e)[:60]}）")
            continue
        base = os.path.dirname(os.path.dirname(m)) if "/." in m or m.startswith(".") else os.path.dirname(m)
        if os.path.basename(m).lower() == "marketplace.json":
            pl = j.get("plugins", [])
            print(f"- {m}: 市场清单，声明 {len(pl)} 个插件；owner={bool(j.get('owner'))}；version={j.get('version', j.get('metadata', {}).get('version', '无'))}")
            for p in pl:
                src = p.get("source")
                src = src if isinstance(src, str) else (src or {}).get("path", "")
                if isinstance(src, str) and src.startswith("./"):
                    mk_plugins.add(os.path.normpath(src))
                    if not any(f.startswith(os.path.normpath(src) + "/") for f in files):
                        print(f"  - 🔴 声明的插件路径不存在: {src}")
        else:
            keys = [k for k in ("name", "version", "description", "license", "author", "keywords", "skills", "commands", "agents", "hooks", "mcpServers") if k in j]
            print(f"- {m}: 插件清单，字段 {keys}")
            for k in ("skills", "commands", "agents"):
                v = j.get(k)
                for pth in ([v] if isinstance(v, str) else (v or [])):
                    if isinstance(pth, str) and pth.startswith("./"):
                        full = os.path.normpath(os.path.join(base, pth))
                        if not any(f == full or f.startswith(full + "/") for f in files):
                            print(f"  - 🔴 {k} 声明的路径不存在: {pth}")
            if j.get("hooks") or j.get("mcpServers"):
                print("  - 🟡 声明了 hooks/mcpServers：会在用户机器上执行命令/启动进程，必须人工审阅")
    # 清单 vs 磁盘
    for f in manifests:
        if f.endswith(".claude-plugin/plugin.json") and f.count("/") >= 2:
            disk_plugins.add(f.split("/")[0])
    if mk_plugins and disk_plugins:
        mk_names = {p.lstrip("./") for p in mk_plugins}
        only_disk = sorted(disk_plugins - mk_names)
        only_mk = sorted(mk_names - disk_plugins - {""})
        if only_disk:
            print(f"- 🟡 磁盘上有 plugin.json 但市场清单未声明: {only_disk}")
        if only_mk:
            print(f"- 🟡 市场清单声明但磁盘上无 plugin.json: {only_mk}")
    platforms = sorted({m.split("/")[0] for m in files if re.match(r"^\.(claude|cursor|copilot|codex|gemini|agents)[-\w]*/", m)})
    print(f"- 多平台适配目录: {platforms or '无'}")
    print()

    # ================= 3. commands / agents =================
    defs = [f for f in files if re.search(r"(^|/)(commands|agents)/[^/]+\.md$", f)]
    print("## 3. commands / agents 定义")
    if not defs:
        print("- 无")
    else:
        nofm = nodesc = wide = 0
        for f in defs:
            fm, _ = frontmatter(read(root, f))
            if fm is None:
                nofm += 1
            elif not fm.get("description"):
                nodesc += 1
            if fm and "allowed-tools" in fm and WIDE_TOOLS.search(f"allowed-tools: {fm['allowed-tools']}"):
                wide += 1
        print(f"- 共 {len(defs)} 个；缺 frontmatter {nofm}、缺 description {nodesc}、allowed-tools 过宽 {wide}")
    print()

    # ================= 4. Markdown 相对链接 =================
    md = [f for f in files if f.lower().endswith((".md", ".mdx"))]
    broken, total_links, ext_links = [], 0, Counter()
    for f in md:
        t = read(root, f)
        t = re.sub(r"```.*?```", "", t, flags=re.S)
        for m in re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)", t):
            tgt = m.group(1)
            if tgt.startswith(("http://", "https://")):
                host = re.sub(r"^https?://([^/]+).*", r"\1", tgt)
                ext_links[host] += 1
                continue
            if tgt.startswith(("#", "mailto:", "tel:", "data:")):
                continue
            if PLACEHOLDER_LINK.match(tgt) or f.startswith((".github/", "docs/superpowers/")) and PLACEHOLDER_LINK.search(tgt):
                continue  # 模板/占位符链接（…、path/to/x、relative/path.md、<url>）不算失效
            total_links += 1
            path = tgt.split("#")[0].split("?")[0]
            if not path:
                continue
            full = os.path.normpath(os.path.join(os.path.dirname(f), path)) if not path.startswith("/") else path.lstrip("/")
            if full not in fset and not any(x.startswith(full + "/") for x in files):
                broken.append((f, tgt))
    print("## 4. Markdown 链接")
    print(f"- Markdown 文件 {len(md)} 个；相对链接 {total_links} 个，**失效 {len(broken)} 个**；外链域名 Top: {ext_links.most_common(6)}")
    for f, t in broken[:5]:
        print(f"  - {f} → {t}")
    print()

    # ================= 5. 重复与相似 =================
    print("## 5. 重复与相似")
    ks = list(descs.items())[:400]
    sims = []
    ws = {k: words(v) for k, v in ks}
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            sc = jaccard(ws[ks[i][0]], ws[ks[j][0]])
            if sc >= 0.6:
                sims.append((round(sc, 2), ks[i][0], ks[j][0]))
    sims.sort(reverse=True)
    names = Counter(os.path.basename(os.path.dirname(s)) for s in skills)
    dup_names = {k: v for k, v in names.items() if v > 1}
    print(f"- description 高度相似(≥0.6) {len(sims)} 对；同名技能目录 {dup_names or '无'}")
    for sc, a, b in sims[:3]:
        print(f"  - {sc}: {a} ≈ {b}")
    print()

    # ================= 6. 风险扫描 =================
    print("## 6. 风险扫描（静态线索，需人工复核；误报常见）")
    scan_files = [f for f in files if f.lower().endswith((".md", ".mdx", ".sh", ".ps1", ".py", ".js", ".mjs", ".ts", ".json", ".yml", ".yaml"))
                  and "node_modules" not in f and "/tests/" not in f and not f.startswith("tests/")]
    danger, inj = Counter(), []
    danger_ex = {}
    for f in scan_files[:3000]:
        t = read(root, f, 300_000)
        for rx, name in DANGER:
            if rx.search(t):
                danger[name] += 1
                danger_ex.setdefault(name, f)
        if f.lower().endswith((".md", ".mdx", ".txt")):
            for rx, name in INJECTION:
                m = rx.search(t)
                if m:
                    inj.append((f, name, m.group(0)[:60].replace("\n", " ")))
    if not danger and not inj:
        print("- 未命中")
    for k, v in danger.most_common():
        print(f"- 🟡 {k}: {v} 个文件，例 {danger_ex[k]}")
    for f, n, ex in inj[:6]:
        print(f"- 🟡 疑似提示注入措辞（{n}）: {f}：「{ex}」→ 需看上下文，教学/安全文档里常见")
    skill_scripts = [f for f in files if re.search(r"/(skills?|commands|agents)/.*/scripts/", f) or re.search(r"(^|/)skills?/[^/]+/scripts/", f)]
    if skill_scripts:
        net = [f for f in skill_scripts if re.search(r"requests\.|urllib|fetch\(|curl |wget |http\.client|axios|socket\.", read(root, f))]
        sp = [f for f in skill_scripts if re.search(r"subprocess|child_process|os\.system|exec\(", read(root, f))]
        print(f"- 技能自带脚本 {len(skill_scripts)} 个；含联网调用 {len(net)} 个、含执行子进程 {len(sp)} 个（这些脚本会在用户机器上运行）")
    hooks = [f for f in files if re.search(r"(^|/)hooks?(\.json|/)", f)]
    if hooks:
        print(f"- 🟡 含 hooks 文件 {hooks[:3]}：hooks 会自动执行命令，必须逐条审阅")
    installers = [f for f in files if os.path.basename(f) in ("install.sh", "install.ps1", "install.bat")]
    if installers:
        print(f"- 🟡 安装脚本 {installers}：用户常被引导 `curl | sh`，先读再评价，**不要执行**")
    print()

    # ================= 7. 自带校验 =================
    print("## 7. 自带校验与测试")
    val = [f for f in files if re.search(r"(validate|lint|check|verify)[\w-]*\.(py|js|mjs|sh)$", f.lower())]
    tests = [f for f in files if re.search(r"(^|/)(tests?|__tests__)/", f.lower())]
    wf = [f for f in files if f.startswith(".github/workflows/")]
    wf_txt = " ".join(read(root, f) for f in wf).lower()
    print(f"- 校验脚本: {val[:4] or '无'}；tests 目录文件 {len(tests)} 个；CI workflows {len(wf)} 个")
    if wf:
        print(f"- CI 是否调用校验/测试: {'是' if re.search(r'validate|pytest|npm test|vitest|jest|check', wf_txt) else '未见'}")
    print("\n> 以上均为线索。抽读 3 个代表性 SKILL.md 的正文质量（指令是否具体、有无示例/边界、有无与同类技能的明确分工）后再下判断。")


if __name__ == "__main__":
    main()
