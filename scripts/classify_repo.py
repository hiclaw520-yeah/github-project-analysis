#!/usr/bin/env python3
"""
classify_repo.py — 判断一个已克隆仓库属于哪种"项目类型"，决定后续用哪套评估方法。

用法:
    python classify_repo.py /tmp/repo [--json]

输出:
  1. 类型得分与证据（可多类型混合，如"带代码的插件 + 应用"）
  2. 规模档位 / monorepo / 子模块 / 原生代码等形态标记
  3. 领域线索（用于路由到 references/domains/ 里的补充清单）
  4. 建议启用/忽略的分析脚本

类型清单（与 references/archetypes/ 一一对应）:
  app-service        可运行的应用 / 服务 / Web / 桌面
  library-framework  被他人依赖的库 / SDK / 框架
  cli-devtool        命令行 / 开发者工具 / 编辑器扩展
  agent-skill-plugin Agent 技能包 / 插件 / MCP 服务 / 提示词与指令集
  content-collection 文档 / 教程 / awesome 列表 / 课程 / 数据集 / 模板文本
  research-model     论文实现 / 模型训练 / 评测基准 / Notebook
  template-config    脚手架 / starter / 基础设施即代码 / dotfiles
  script-tool        小型脚本 / 个人工具 / 单用途自动化（规模标记，常与其他类型叠加）

注意：这是启发式，只给线索与证据；最终类型要读完 README 后由你确认，混合型要并列写出。
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
from collections import Counter

CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".c", ".cc",
            ".cpp", ".h", ".hpp", ".rb", ".php", ".cs", ".swift", ".vue", ".svelte", ".astro", ".sh", ".ps1",
            ".lua", ".dart", ".scala", ".zig"}
DOC_EXT = {".md", ".mdx", ".rst", ".txt", ".adoc"}
NATIVE_EXT = {".c", ".cc", ".cpp", ".h", ".hpp", ".rs", ".swift", ".zig", ".go", ".m", ".mm"}
SKIP = {".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__", "target", "vendor"}


def list_files(root):
    try:
        out = subprocess.run(GIT_SAFE + ["ls-files"], cwd=root, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60).stdout
        files = [l for l in out.splitlines() if l.strip()]
        if files:
            return files
    except Exception:
        pass
    files = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP]
        for f in fns:
            files.append(os.path.relpath(os.path.join(dp, f), root).replace(os.sep, "/"))
    return files


# 所有 git 调用都走这个包装：命令行 -c 优先级高于仓库自带的 .git/config，
# 避免被评估仓库通过 core.fsmonitor / core.sshCommand / hooksPath 等配置在本机执行命令。
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


def read(root, rel, limit=400_000):
    try:
        p = os.path.join(root, rel)
        if not inside_repo(p) or os.path.getsize(p) > limit:
            return ""
        return open(p, encoding="utf-8", errors="ignore").read()
    except Exception:
        return ""


def main():
    if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]):
        sys.exit(__doc__)
    root = os.path.abspath(sys.argv[1])
    _CFG["root_real"] = os.path.realpath(root)
    files = list_files(root)
    low = [f.lower() for f in files]
    ext = Counter(os.path.splitext(f)[1].lower() for f in files)
    n = len(files)
    code_files = [f for f in files if os.path.splitext(f)[1].lower() in CODE_EXT]
    doc_files = [f for f in files if os.path.splitext(f)[1].lower() in DOC_EXT]
    code_n, doc_n = len(code_files), len(doc_files)

    def has(pred):
        return any(pred(p) for p in low)

    def count(pred):
        return sum(1 for p in low if pred(p))

    # 汇总依赖文件文本（根与二级目录），用于关键词判断
    dep_text = ""
    pkg_jsons = []
    NOISE_DIR = re.compile(r"(^|/)(examples?|docs?|tests?|fixtures?|samples?|demos?|benchmarks?|e2e|playground|website|homepage)/")
    for rel, l in zip(files, low):
        b = os.path.basename(l)
        if NOISE_DIR.search(l):
            continue  # 示例/文档/测试里的子项目清单不代表项目本体
        if rel.count("/") <= 3 and (b.startswith("requirements") and b.endswith(".txt") or b in (
                "pyproject.toml", "package.json", "go.mod", "cargo.toml", "pom.xml", "build.gradle", "gemfile", "composer.json")):
            t = read(root, rel).lower()
            dep_text += "\n" + t
            if b == "package.json":
                try:
                    pkg_jsons.append((rel, json.loads(t)))
                except Exception:
                    pass
    # 剔除"项目自身的名字"，避免 click 这类库因自己的 pyproject 里写着 click 而被判成'依赖 click 的 CLI'
    own = set()
    for rel, l in zip(files, low):
        if rel.count("/") <= 3 and os.path.basename(l) in ("pyproject.toml", "package.json", "cargo.toml", "setup.cfg") and not NOISE_DIR.search(l):
            t = read(root, rel)
            for m in re.finditer(r'(?m)^\s*"?name"?\s*[:=]\s*"([^"]+)"', t):
                own.add(m.group(1).lower())
    for nm in sorted(own, key=len, reverse=True):
        if len(nm) >= 3:
            dep_text = dep_text.replace(nm, " ")
    readme = ""
    for cand in ("README.md", "readme.md", "README.rst", "README"):
        if cand in files:
            readme = read(root, cand).lower()
            break

    def dep(*keys):
        return any(re.search(r"(^|[\"'\s/@\-_])" + re.escape(k) + r"([\"'\s=<>~!\[,^@\-_/.]|$)", dep_text) for k in keys)

    score, ev = Counter(), {}

    def add(t, pts, why):
        score[t] += pts
        ev.setdefault(t, []).append(why)

    # ---- agent-skill-plugin ----
    skill_md = count(lambda p: p.endswith("/skill.md") or p == "skill.md")
    # 根目录或 skills/<name>/ 布局的 SKILL.md 是技能包的强信号（克隆目录名任意，不影响）
    skill_md_root = count(lambda p: p == "skill.md" or re.match(r"^skills/[^/]+/skill\.md$", p))
    manifests = [f for f in files if re.search(r"(^|/)(\.claude-plugin|\.cursor-plugin|\.copilot-plugin|\.codex-plugin)/", f.lower())
                 or re.search(r"(^|/)(plugin|marketplace)\.json$", f.lower())]
    cmd_md = count(lambda p: re.search(r"(^|/)commands/[^/]+\.md$", p) is not None)
    agent_md = count(lambda p: re.search(r"(^|/)agents/[^/]+\.md$", p) is not None)
    mcp = dep("@modelcontextprotocol/sdk", "fastmcp", "mcp") or has(lambda p: os.path.basename(p) == "server.json") or "model context protocol" in readme[:3000]
    if skill_md_root:
        add("agent-skill-plugin", 4 if skill_md_root == 1 else 6,
            f"{skill_md_root} 个根/skills 布局 SKILL.md（技能包强信号）")
    elif skill_md:
        pts = min(6, 2 + skill_md // 5)
        if n <= 5:
            # 文件极少的仓库里 SKILL.md 就是本体（如中文路径下的单技能小仓库），
            # 技能信号给保底分，避免被"文档占比"反超（1.1.6）
            pts = max(pts, 4)
        add("agent-skill-plugin", pts, f"{skill_md} 个 SKILL.md")
    if manifests:
        add("agent-skill-plugin", 3, f"插件/市场清单 {len(manifests)} 个（如 {manifests[0]}）")
    if cmd_md or agent_md:
        add("agent-skill-plugin", 2, f"commands/{cmd_md} agents/{agent_md} 个 md 定义")
    if mcp:
        add("agent-skill-plugin", 3, "MCP 服务/SDK 线索")

    # ---- content-collection ----
    # 有根/skills 布局 SKILL.md 的仓库不因"文档占比高/精选词"判成内容合集——技能包本身就是
    # md 为主的仓库；但 .claude/skills/、.agents/skills/ 等开发辅助技能不算（1.1.6 回归修复）
    if n and doc_n / n > 0.65 and code_n < 15 and not skill_md_root:
        add("content-collection", 4, f"文档占比 {doc_n * 100 // n}%、代码文件仅 {code_n}")
    if re.search(r"awesome|curated list", readme[:1500]) and doc_n >= code_n and not skill_md_root:
        add("content-collection", 2, "README 呈现 awesome/curated list 特征")
    if has(lambda p: re.search(r"(^|/)(chapters?|lessons?|book|course|tutorial)s?/", p) is not None):
        add("content-collection", 2, "含 chapters/lessons/book/tutorial 目录")
    if skill_md >= 10 and code_n < 15:  # 技能包常常也是内容型
        add("content-collection", 1, "以 Markdown 内容为主")

    # ---- app-service ----
    docker = has(lambda p: os.path.basename(p) in ("dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml"))
    web_be = dep("fastapi", "flask", "django", "express", "koa", "nestjs", "gin-gonic", "actix-web", "axum", "spring-boot", "rails", "laravel", "hono", "fastify")
    web_fe = dep("react", "vue", "svelte", "next", "nuxt", "astro", "angular", "solid-js")
    desktop = dep("electron", "tauri", "@tauri-apps/api")
    if web_be:
        add("app-service", 3, "后端 Web 框架依赖")
    if web_fe and has(lambda p: p.endswith("index.html") or "/pages/" in p or "/app/" in p):
        add("app-service", 2, "前端应用框架 + 页面结构")
    if docker:
        add("app-service", 1, "有 Docker/Compose")
    if desktop:
        add("app-service", 3, "桌面应用框架")
    if has(lambda p: os.path.basename(p) in ("server.py", "app.py", "main.go", "manage.py")):
        add("app-service", 1, "存在服务入口文件")

    # ---- library-framework ----
    for rel, pj in pkg_jsons:
        if rel.count("/") == 0 and not pj.get("private") and any(k in pj for k in ("main", "exports", "module", "types")) and "bin" not in pj:
            add("library-framework", 3, "package.json 声明 main/exports 且非 private、无 bin")
    root_entry = has(lambda p: p in ("main.py", "run.py", "app.py", "server.py", "manage.py", "__main__.py"))
    if re.search(r"\[build-system\]", dep_text) and re.search(r"\[project\]", dep_text) and not web_be and not root_entry:
        add("library-framework", 2, "pyproject 定义可发布包且无服务入口")
    if re.search(r"^\[lib\]", dep_text, re.M):
        add("library-framework", 2, "Cargo [lib]")
    if re.search(r"\b(sdk|framework|library)\b", readme[:3000]):
        add("library-framework", 1, "README 自述为 SDK/框架/库")
    first_h = next((l for l in readme.splitlines() if l.lstrip().startswith("#")), "")
    if re.search(r"\b(sdk|framework|library|toolkit)\b", first_h):
        add("library-framework", 2, f"README 标题自称框架/库：{first_h.strip()[:60]}")
    pkg_dirs = {f.split("/")[0] for f in files if f.endswith("/__init__.py") and f.count("/") == 1}
    pkg_dirs |= {f.split("/")[1] for f in files if f.startswith("src/") and f.endswith("/__init__.py") and f.count("/") == 2}
    if pkg_dirs and re.search(r"\[project\]", dep_text) and not root_entry:
        add("library-framework", 1, f"可导入的 Python 包目录 {sorted(pkg_dirs)[:3]}")

    # ---- cli-devtool ----
    bin_pj = [rel for rel, pj in pkg_jsons if "bin" in pj]
    if bin_pj:
        add("cli-devtool", 3, f"package.json 含 bin（{bin_pj[0]}）")
    if re.search(r"\[project\.scripts\]|console_scripts|\[\[bin\]\]", dep_text):
        add("cli-devtool", 3, "声明命令行入口（scripts/bin）")
    if dep("click", "typer", "argparse", "commander", "yargs", "cobra", "clap", "oclif", "ink"):
        add("cli-devtool", 2, "命令行解析库依赖")
    if has(lambda p: p.startswith("cmd/") or p.startswith("bin/")):
        add("cli-devtool", 1, "cmd/ 或 bin/ 目录")
    if has(lambda p: os.path.basename(p) in ("install.sh", "install.ps1")):
        add("cli-devtool", 1, "提供安装脚本")

    # ---- research-model ----
    nb = ext.get(".ipynb", 0)
    ml = dep("torch", "tensorflow", "jax", "transformers", "scikit-learn", "xgboost", "lightgbm", "diffusers", "keras")
    if nb >= 3:
        add("research-model", 2, f"{nb} 个 Notebook")
    if ml:
        add("research-model", 2, "ML 框架依赖")
    if has(lambda p: os.path.basename(p) in ("train.py", "eval.py", "evaluate.py", "finetune.py")):
        add("research-model", 2, "训练/评测入口")
    if re.search(r"arxiv|paper|citation|bibtex|benchmark", readme[:3000]):
        add("research-model", 1, "README 含论文/引用/基准字样")

    # ---- template-config ----
    tf = ext.get(".tf", 0)
    if tf or has(lambda p: os.path.basename(p) in ("chart.yaml",)) or count(lambda p: p.startswith(("k8s/", "helm/", "ansible/"))) > 3:
        add("template-config", 3, "基础设施即代码（tf/helm/k8s/ansible）")
    if has(lambda p: os.path.basename(p) in ("cookiecutter.json", "copier.yml", "copier.yaml")) or re.search(r"\b(template|boilerplate|starter|scaffold)\b", readme[:600]):
        add("template-config", 2, "模板/脚手架/starter 特征")
    if has(lambda p: p.startswith((".bashrc", ".zshrc", ".vimrc", ".tmux.conf")) or "dotfiles" in p):
        add("template-config", 2, "dotfiles 特征")

    if root_entry and not web_be:
        add("app-service", 1, "根目录有可直接运行的入口文件（脚本式应用）")

    # ---- script-tool（规模标记）----
    tiny = 5 <= code_n <= 40  # 需要有一定量的代码才算'小型脚本项目'；纯内容仓库里零星的校验脚本不算
    if tiny:
        add("script-tool", 2, f"仅 {code_n} 个代码文件（小型项目）")

    # ---- 形态 ----
    monorepo = []
    for tag, pred in [("pnpm-workspace", lambda p: p == "pnpm-workspace.yaml"), ("lerna", lambda p: p == "lerna.json"),
                      ("turbo", lambda p: p == "turbo.json"), ("nx", lambda p: p == "nx.json"),
                      ("go.work", lambda p: p == "go.work"), ("npm/yarn workspaces", lambda p: False)]:
        if has(pred):
            monorepo.append(tag)
    if any("workspaces" in pj for _, pj in pkg_jsons):
        monorepo.append("package.json workspaces")
    if re.search(r"^\[workspace\]", dep_text, re.M):
        monorepo.append("cargo workspace")
    pkg_count = count(lambda p: os.path.basename(p) == "package.json")
    pyproj_count = count(lambda p: os.path.basename(p) == "pyproject.toml")
    native = {e: c for e, c in ext.items() if e in NATIVE_EXT and c >= 5}
    size = "tiny" if n < 40 else "small" if n < 200 else "medium" if n < 1000 else "large" if n < 3000 else "huge"
    flags = {
        "files": n, "size_class": size, "code_files": code_n, "doc_files": doc_n,
        "doc_share_pct": doc_n * 100 // max(n, 1),
        "monorepo_signals": monorepo, "package_json_count": pkg_count, "pyproject_count": pyproj_count,
        "submodules": has(lambda p: p == ".gitmodules"),
        "native_code_ext": native,
        "has_disclaimer_file": has(lambda p: "disclaimer" in os.path.basename(p)),
        "has_security_md": has(lambda p: os.path.basename(p) == "security.md"),
        "has_agent_config": has(lambda p: os.path.basename(p) in ("agents.md", "claude.md", ".cursorrules")),
        "multi_language_readmes": count(lambda p: re.search(r"readme[._-]?(zh|ja|ko|es|tr|ru|vi|el|fr|de|pt)", p) is not None),
    }

    # ---- 领域线索 ----
    text_for_domain = readme[:4000] + " " + dep_text[:6000]
    topics_hint = text_for_domain
    domains = {}
    dom_rules = {
        "quant-trading": r"akshare|tushare|baostock|efinance|yfinance|ccxt|backtest|回测|选股|量化|a-share|a股|trading|portfolio|k线|ohlc",
        "ai-agent-llm": r"\bllm\b|openai|anthropic|langchain|langgraph|mcp|agentic|claude|rag\b|embedding|multi-agent|prompt",
        "security-dual-use": r"reverse.?engineer|decompil|ghidra|ida pro|binary analysis|exploit|pentest|penetration|malware|jailbreak|crack|bypass|scrap|crawler|anti-?bot|fuzz|vulnerab|逆向|渗透|爬虫|破解",
        "data-science": r"pandas|numpy|polars|dataset|notebook|dashboard|visuali[sz]ation",
        "devops-infra": r"terraform|kubernetes|helm|ansible|docker|ci/cd|observability|prometheus",
        "web3-crypto": r"solidity|ethereum|wallet|defi|smart contract|web3|blockchain|nft",
        "education-content": r"tutorial|course|lesson|教程|课程|handbook|cheatsheet",
    }
    for d, pat in dom_rules.items():
        hits = re.findall(pat, text_for_domain, re.I)
        if len(hits) >= 2:
            domains[d] = len(hits)

    ranked = [(t, s) for t, s in score.most_common() if t != "script-tool"]
    if ranked:
        primary = ranked[0][0]
    elif score.get("script-tool"):
        primary = "script-tool"
    else:
        primary = "unknown（未命中任何类型，需读 README 判断）"
    secondary = [t for t, s in ranked[1:3] if s >= max(2, ranked[0][1] * 0.4)] if ranked else []

    # 建议
    advice = []
    KNOWN = {"app-service", "library-framework", "cli-devtool", "agent-skill-plugin", "content-collection",
             "research-model", "template-config", "script-tool"}
    hb = [t for t in [primary] + list(secondary) if t in KNOWN]
    if score.get("script-tool") and "script-tool" not in hb:
        hb.append("script-tool")
    if hb:
        advice.append("**先读类型手册**: " + "、".join(f"references/archetypes/{t}.md" for t in hb))
    else:
        advice.append("类型未识别：读完 README 后手动选择 references/archetypes/ 下最接近的手册（可多选）")
    if primary == "content-collection" or (primary == "agent-skill-plugin" and code_n < 20):
        advice += ["content_probe.py（内容/技能包体检，必跑）", "local_probe.py（提交与安全红旗）",
                   "arch_probe.py 对纯内容仓库意义不大，可跳过依赖图，改看信息架构"]
    else:
        advice += ["local_probe.py", "arch_probe.py"]
        if skill_md or manifests:
            advice.append("content_probe.py（含 SKILL.md/插件清单，需校验规范与一致性）")
    if size in ("large", "huge") or monorepo:
        advice.append("monorepo/大仓库：按包/子目录抽样，不要通读；依赖图看工作区包之间的关系")
    if "security-dual-use" in domains:
        advice.append("读 references/domains/security-dual-use.md（双重用途与滥用风险）")
    if "quant-trading" in domains:
        advice.append("读 references/domains/quant-trading.md")
    if "ai-agent-llm" in domains:
        advice.append("读 references/domains/ai-agent-llm.md")

    result = {"primary": primary, "secondary": secondary, "scores": dict(score), "evidence": ev,
              "flags": flags, "domains": domains, "advice": advice}
    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"# 项目类型识别: {os.path.basename(root)}\n")
    print(f"- **主类型**: `{primary}`；并列/次类型: {secondary or '无'}" + ("；**叠加标记: `script-tool`（小型项目，按相对规模设期望）**" if score.get("script-tool") and primary != "script-tool" else ""))
    print(f"- 规模档位: **{size}**（{n} 个文件；代码 {code_n}、文档 {doc_n}，文档占 {flags['doc_share_pct']}%）")
    print("## 类型得分与证据")
    for t, s in score.most_common():
        print(f"- {t}（{s} 分）: " + "；".join(ev[t]))
    print("## 形态标记")
    print(f"- monorepo 信号: {monorepo or '无'}（package.json {pkg_count} 个、pyproject {pyproj_count} 个）")
    print(f"- 子模块 .gitmodules: {flags['submodules']} · 原生/系统语言文件: {native or '无'}")
    print(f"- DISCLAIMER 文件: {flags['has_disclaimer_file']} · SECURITY.md: {flags['has_security_md']} · AGENTS/CLAUDE 配置: {flags['has_agent_config']} · 多语言 README: {flags['multi_language_readmes']} 个")
    print(f"## 领域线索（用于选读 references/domains/）\n- {domains or '无明显领域线索'}")
    print("## 建议的分析路径")
    for a in advice:
        print(f"- {a}")
    print("\n> 这是启发式结果：读完 README 后确认类型；混合型（如'带代码的插件'）要并列写出，并按各自适用的维度评估。")


if __name__ == "__main__":
    main()
