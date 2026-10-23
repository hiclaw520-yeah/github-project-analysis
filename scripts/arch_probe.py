#!/usr/bin/env python3
"""
arch_probe.py — 从已克隆的仓库里提取"架构画像"，供写架构/核心/亮点章节用。

用法:
    python arch_probe.py /tmp/repo [--depth 3]

输出 Markdown，包含:
  1. 目录规模图（各目录源码行数）
  2. 入口点（server.py / main / Dockerfile CMD / compose / console_scripts）
  3. 技术栈（依赖文件关键词命中）
  4. Python 内部模块依赖图（Mermaid + 边权重），自动标出"反向/循环"依赖
  5. 运行形态线索（HTTP 路由数、ORM 模型数、定时任务数、外部域名）
  6. 变更热点（最近提交里被改最多的文件）

只依赖标准库 + git。所有结果是线索，不是结论：要回到代码里验证。
"""
import ast
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

SKIP = {".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__", ".next",
        "vendor", "target", "site-packages", "coverage", ".pytest_cache", ".mypy_cache"}
TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(_test|\.test|\.spec)\.|(^|/)test_")
CODE_EXT = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt", ".vue")

STACK_KEYS = {
    "Web 后端": ["fastapi", "flask", "django", "express", "koa", "nestjs", "hono", "fastify", "gin-gonic", "echo", "actix-web", "axum", "spring-boot", "rails", "laravel"],
    "前端/UI": ["react", "vue", "svelte", "solid-js", "next", "nuxt", "astro", "angular", "vite", "tailwindcss", "shadcn", "zustand", "redux", "recharts", "echarts", "d3", "cytoscape", "three", "xyflow", "reactflow"],
    "桌面/移动": ["electron", "tauri", "react-native", "flutter", "capacitor"],
    "ORM/DB/存储": ["sqlalchemy", "alembic", "sqlmodel", "prisma", "typeorm", "drizzle", "gorm", "psycopg", "asyncpg", "sqlite", "better-sqlite3", "redis", "mongodb", "clickhouse", "duckdb", "postgres"],
    "任务/调度/队列": ["apscheduler", "celery", "rq", "dramatiq", "arq", "bullmq", "node-cron", "temporal", "airflow", "prefect", "kafka", "rabbitmq"],
    "LLM/Agent": ["openai", "anthropic", "langchain", "langgraph", "llama-index", "litellm", "ollama", "crewai", "autogen", "ai-sdk", "vercel/ai", "transformers", "torch"],
    "MCP/插件协议": ["@modelcontextprotocol/sdk", "fastmcp", "mcp"],
    "代码分析/解析": ["tree-sitter", "web-tree-sitter", "babel", "acorn", "esprima", "ts-morph", "typescript", "libclang", "ghidra", "capstone", "frida"],
    "数据科学": ["pandas", "numpy", "scipy", "scikit-learn", "polars", "matplotlib"],
    "领域数据/量化库": ["akshare", "tushare", "efinance", "baostock", "yfinance", "ccxt", "qlib", "vnpy", "backtrader", "ta-lib", "pandas-ta"],
    "抓取/浏览器": ["playwright", "puppeteer", "selenium", "beautifulsoup4", "scrapy", "cheerio"],
    "网络/HTTP": ["httpx", "requests", "aiohttp", "axios", "got", "undici", "node-fetch"],
    "Schema/校验": ["pydantic", "zod", "ajv", "joi", "jsonschema", "valibot"],
    "可观测": ["opentelemetry", "sentry", "prometheus", "loguru", "structlog", "pino", "winston"],
    "通知/IM": ["apprise", "telegram", "dingtalk", "feishu", "lark", "wecom", "slack", "discord", "bark", "nodemailer", "smtplib"],
    "构建/Monorepo": ["pnpm", "turbo", "nx", "lerna", "esbuild", "tsup", "webpack", "rollup", "bun", "uv", "poetry", "napi-rs", "node-gyp", "cmake"],
    "测试/质量": ["pytest", "vitest", "jest", "mocha", "playwright", "mypy", "ruff", "eslint", "oxlint", "biome", "prettier", "knip", "jscpd", "husky"],
}


def sh(cmd, cwd):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60).stdout
    except Exception:
        return ""


def walk(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP]
        for fn in fns:
            p = os.path.join(dp, fn)
            yield os.path.relpath(p, root).replace(os.sep, "/"), p  # 统一正斜杠（Windows 兼容）


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


def read(p, limit=1_500_000):
    try:
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
    depth = 3
    if "--depth" in sys.argv:
        try:
            depth = int(sys.argv[sys.argv.index("--depth") + 1])
        except (IndexError, ValueError):
            pass
    files = list(walk(root))
    print(f"# 架构画像: {os.path.basename(root)}\n")

    # ---- 1. 目录规模 ----
    loc_by_dir = Counter()
    for rel, p in files:
        if not rel.endswith(CODE_EXT) or TEST_RE.search(rel.lower()):
            continue
        n = read(p).count("\n") + 1
        parts = rel.split("/")[:-1]
        key = "/".join(parts[:2]) if parts else "(根目录)"
        loc_by_dir[key] += n
    print("## 1. 目录规模（源码行，不含测试，取前 2 级目录）")
    for k, v in loc_by_dir.most_common(15):
        print(f"- `{k}`: {v}")
    print()

    # ---- 2. 入口点 ----
    print("## 2. 入口点与运行形态")
    names = {"server.py", "main.py", "app.py", "manage.py", "webui.py", "cli.py", "__main__.py", "index.js", "index.ts", "index.mjs",
             "main.ts", "main.js", "server.ts", "server.js", "cli.ts", "cli.js", "main.go", "main.rs", "lib.rs", "Program.cs", "Main.java"}
    entries = [rel for rel, _ in files if os.path.basename(rel) in names and rel.count("/") <= 3]
    print(f"- 疑似入口文件: {entries[:12]}")
    for rel, p in files:
        b = os.path.basename(rel).lower()
        if b == "dockerfile" and rel.count("/") <= 1:
            cmd = re.findall(r"^(?:CMD|ENTRYPOINT)\s+(.+)$", read(p), re.M)
            print(f"- {rel} 启动命令: {cmd[-2:]}")
        if b in ("docker-compose.yml", "docker-compose.yaml", "compose.yml") and rel.count("/") <= 1:
            svcs = re.findall(r"^  ([a-zA-Z0-9_-]+):\s*$", read(p), re.M)
            print(f"- {rel} 服务: {svcs[:10]}")
        if b == "pyproject.toml" and rel.count("/") <= 2:
            sc = re.findall(r"\[project\.scripts\]\n((?:.+\n)+?)(?:\n|\[)", read(p))
            if sc:
                print(f"- {rel} console_scripts: {sc[0].strip()[:200]}")
        if b == "package.json" and rel.count("/") <= 1:
            try:
                j = json.loads(read(p))
                print(f"- {rel} scripts: {list(j.get('scripts', {}))[:10]}")
            except Exception:
                pass
    subpk = [rel for rel, _ in files if rel.endswith("pyproject.toml") and rel.count("/") >= 1]
    if subpk:
        print(f"- 内部子包（独立 pyproject）: {[os.path.dirname(x) for x in subpk][:10]}")
    print()

    # ---- 3. 技术栈 ----
    dep_text = ""
    for rel, p in files:
        b = os.path.basename(rel).lower()
        if (b.startswith("requirements") and b.endswith(".txt")) or b in ("pyproject.toml", "package.json", "go.mod", "cargo.toml", "pom.xml", "build.gradle"):
            dep_text += "\n" + read(p).lower()
    print("## 3. 技术栈（依赖文件关键词命中）")
    for cat, keys in STACK_KEYS.items():
        hit = [k for k in keys if re.search(r"(^|[\"'\s/@\-_])" + re.escape(k) + r"([\"'\s=<>~!\[,^@\-_/.]|$)", dep_text)]
        if hit:
            print(f"- {cat}: {hit}")
    print()

    # ---- 4. 内部模块依赖图（Python / JS·TS / Go）----
    # 区分"硬依赖"（模块顶层导入）与"软依赖"（函数内延迟导入 / TYPE_CHECKING / import type）。
    edges, hard_edges, nodes_loc, lang_used = Counter(), Counter(), Counter(), []
    py = [(rel, p) for rel, p in files if rel.endswith(".py") and not TEST_RE.search(rel.lower())]
    _fs = {rel for rel, _ in files}
    # src 布局（src/<pkg>/__init__.py 且 src 本身不是包）：去掉前导 "src/"
    strip_src = ("src/__init__.py" not in _fs) and any(f.startswith("src/") and f.endswith("/__init__.py") and f.count("/") == 2 for f in _fs)
    if strip_src:
        py = [(rel[4:] if rel.startswith("src/") else rel, p) for rel, p in py]
    # 图里排除示例/文档/基准目录（它们通常是"使用方"）
    py = [(rel, p) for rel, p in py if not re.search(r"(^|/)(examples?|docs?|benchmarks?|demos?)/", rel)]
    tops = Counter(rel.split("/")[0] for rel, _ in py)
    pkg_roots = {t for t, n in tops.items() if n >= 5 and t not in ("scripts", "tests", "docs", "examples")}

    def is_typecheck(test):
        return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or \
               (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")

    def collect_imports(tree):
        out = []

        def rec(n, soft):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                out.append((n, soft))
                return
            for ch in ast.iter_child_nodes(n):
                if isinstance(ch, ast.If) and is_typecheck(ch.test):
                    for b in ch.body:
                        rec(b, True)
                    for b in ch.orelse:
                        rec(b, soft)
                    continue
                rec(ch, soft or isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)))
        rec(tree, False)
        return out

    def py_graph(fine):
        e, h, loc = Counter(), Counter(), Counter()

        def node(rel):
            if fine:  # 文件级：click/core.py -> click.core
                _m = rel[:-3].replace("/", ".")
                return _m[: -len(".__init__")] if _m.endswith(".__init__") else _m
            parts = rel.split("/")[:-1]
            return ".".join(parts[:depth]) if parts else "(root)"
        for rel, p in py:
            if rel.split("/")[0] not in pkg_roots:
                continue
            src_node = node(rel)
            text = read(p)
            loc[src_node] += text.count("\n") + 1
            try:
                tree = ast.parse(text)
            except Exception:
                continue
            for n, soft in collect_imports(tree):
                mods = []
                if isinstance(n, ast.Import):
                    mods = [a.name for a in n.names]
                elif n.level == 0 and n.module:
                    mods = [n.module] + ([f"{n.module}.{a.name}" for a in n.names] if fine else [])
                elif n.level > 0:  # 相对导入 → 绝对模块名
                    base = rel[:-3].split("/")
                    if base[-1] == "__init__":
                        base = base[:-1]
                    else:
                        base = base[:-1]
                    if n.level > 1:
                        base = base[: len(base) - (n.level - 1)]
                    mod = ".".join(base + ([n.module] if n.module else []))
                    mods = [mod] + ([f"{mod}.{a.name}" for a in n.names] if fine else [])
                for m in mods:
                    if m.split(".")[0] in pkg_roots:
                        dst = m if fine else ".".join(m.split(".")[:depth])
                        if dst != src_node:
                            e[(src_node, dst)] += 1
                            if not soft:
                                h[(src_node, dst)] += 1
        return e, h, loc

    if pkg_roots:
        lang_used.append("Python")
        edges, hard_edges, nodes_loc = py_graph(False)
        if len(nodes_loc) < 6 and sum(1 for rel, _ in py if rel.split("/")[0] in pkg_roots) >= 5:
            edges, hard_edges, nodes_loc = py_graph(True)
            lang_used[-1] = "Python(文件级粒度：目录级节点不足 6 个，自动细化)"

    # --- JS/TS：相对导入 + 工作区包名导入；import type 记为软依赖 ---
    JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte", ".astro")
    js = [(rel, p) for rel, p in files if rel.endswith(JS_EXT) and not rel.endswith(".d.ts") and not TEST_RE.search(rel.lower())]
    if len(js) >= 5:
        lang_used.append("JS/TS")
        fset = {rel for rel, _ in files}
        ws = {}
        for rel, p in files:
            if os.path.basename(rel) == "package.json":
                try:
                    nm = json.loads(read(p)).get("name")
                    if nm:
                        ws[nm] = os.path.dirname(rel)
                except Exception:
                    pass
        pkg_roots_js = sorted(set(ws.values()), key=len, reverse=True)

        def js_node(rel_dir):
            for pr in pkg_roots_js:
                if pr and (rel_dir == pr or rel_dir.startswith(pr + "/")):
                    parts = rel_dir.split("/")
                    return "/".join(parts[: len(pr.split("/")) + 2])
            parts = rel_dir.split("/") if rel_dir else []
            return "/".join(parts[:depth]) or "(root)"

        imp_re = re.compile(r"""(?:from|import)\s*\(?\s*['"]([^'"\n]+)['"]|require\(\s*['"]([^'"\n]+)['"]\s*\)""")
        for rel, p in js:
            text = read(p)
            src_node = js_node(os.path.dirname(rel))
            nodes_loc[src_node] += text.count("\n") + 1
            for m in imp_re.finditer(text):
                spec = m.group(1) or m.group(2)
                if not spec:
                    continue
                ls = text.rfind("\n", 0, m.start()) + 1
                soft = bool(re.match(r"\s*(import|export)\s+type\b", text[ls:m.end()])) or "import(" in text[max(0, m.start() - 8):m.start() + 8]
                if spec.startswith("."):
                    tgt = os.path.normpath(os.path.join(os.path.dirname(rel), spec)).replace("\\", "/")
                    tdir = tgt if any(f.startswith(tgt + "/") for f in fset) else os.path.dirname(tgt)
                    dst = js_node(tdir)
                else:
                    dst = None
                    for nm, pr in ws.items():
                        if spec == nm or spec.startswith(nm + "/"):
                            dst = js_node(pr + "/" + (spec[len(nm) + 1:].rsplit("/", 1)[0] if "/" in spec[len(nm) + 1:] else "src"))
                            break
                if dst and dst != src_node:
                    edges[(src_node, dst)] += 1
                    if not soft:
                        hard_edges[(src_node, dst)] += 1

    # --- Go：module 内 import（全部视为硬依赖）---
    gomods = [(rel, read(p)) for rel, p in files if os.path.basename(rel) == "go.mod"]
    if gomods:
        mod_path = (re.search(r"^module\s+(\S+)", gomods[0][1], re.M) or [None, None])[1]
        gof = [(rel, p) for rel, p in files if rel.endswith(".go") and not rel.endswith("_test.go")]
        if mod_path and len(gof) >= 5:
            lang_used.append("Go")
            for rel, p in gof:
                text = read(p)
                src_node = "/".join(os.path.dirname(rel).split("/")[:depth]) or "(root)"
                nodes_loc[src_node] += text.count("\n") + 1
                for imp in re.findall(r'"(' + re.escape(mod_path) + r'[^"]*)"', text):
                    dst = "/".join(imp[len(mod_path):].strip("/").split("/")[:depth]) or "(root)"
                    if dst != src_node:
                        edges[(src_node, dst)] += 1
                        hard_edges[(src_node, dst)] += 1

    print(f"## 4. 内部模块依赖图（已解析: {lang_used or '无'}；节点粒度 {depth} 级）")
    if edges:
        known = set(nodes_loc)
        keep = lambda b: b in known or any(k.startswith(b) for k in known)
        edges = Counter({(a, b): w for (a, b), w in edges.items() if keep(b)})
        hard_edges = Counter({(a, b): w for (a, b), w in hard_edges.items() if keep(b)})
        ids = {}

        def nid(x):
            return ids.setdefault(x, f"n{len(ids)}")
        print("```mermaid\ngraph LR")
        for (a, b), w in edges.most_common(40):
            soft_only = (a, b) not in hard_edges
            print(f'  {nid(a)}["{a}"] {"-.->" if soft_only else "-->"}|{w}| {nid(b)}["{b}"]')
        print("```")

        def is_parent_child(a, b):
            return (a == "(root)" or b == "(root)" or a.startswith(b + "/") or b.startswith(a + "/")
                    or a.startswith(b + ".") or b.startswith(a + "."))

        def mutual_of(E):
            return sorted({tuple(sorted((a, b))) for (a, b) in E if (b, a) in E})
        m_all = [m for m in mutual_of(edges) if not is_parent_child(*m)]
        m_hard = [m for m in mutual_of(hard_edges) if not is_parent_child(*m)]
        m_soft = [m for m in m_all if m not in set(m_hard)]
        pc = len(mutual_of(edges)) - len(m_all)
        print(f"- 节点 {len(known)}、边 {len(edges)}（其中仅靠延迟/类型导入的软边 {len(edges) - len(hard_edges)}；图中虚线）")
        print(f"- **硬环（模块顶层互相导入）{len(m_hard)} 对**: {m_hard[:8]}")
        print(f"- **靠延迟导入 / TYPE_CHECKING / import type 掩盖的环 {len(m_soft)} 对**: {m_soft[:8]}"
              + ("  ← 运行时被绕开，但设计上仍是双向耦合（常见于类型互引或为打破导入顺序所做的权宜处理）" if m_soft else ""))
        if pc:
            print(f"  （另有 {pc} 对是父子目录互引，如 src ↔ src/x，不算环，已排除）")
        fan_in, fan_out = Counter(), Counter()
        for (a, b), w in edges.items():
            fan_in[b] += 1
            fan_out[a] += 1
        print(f"- 被依赖最多的模块（核心/枢纽候选）: {fan_in.most_common(6)}")
        print(f"- 依赖他人最多的模块（可能是'上帝模块'/编排层）: {fan_out.most_common(6)}")
        print("- 注意：JS/TS 的路径别名（@/、tsconfig paths）未解析会漏边；动态导入/反射/插件注册不在图里；Go 全部按硬依赖计")
    else:
        print("- 未能提取：语言暂不支持（Rust/Java/C# 等），或仓库以内容/配置为主，或包结构特殊。请手动读入口文件梳理，并在报告里写明'依赖图未自动生成'。")
    print()

    # ---- 5. 运行形态线索 ----
    routes = models = jobs = 0
    hosts = Counter()
    for rel, p in files:
        if not rel.endswith((".py", ".ts", ".tsx", ".js", ".go")) or TEST_RE.search(rel.lower()):
            continue
        t = read(p)
        routes += len(re.findall(r"@(?:\w+\.)?(?:get|post|put|delete|patch)\(\s*[\"']/", t))
        routes += len(re.findall(r"\b(?:app|router)\.(?:get|post|put|delete|patch)\(\s*[\"']/", t))
        models += len(re.findall(r"^class \w+\((?:\w*Base|db\.Model|SQLModel)[^)]*\)", t, re.M))
        jobs += len(re.findall(r"add_job\(|@(?:\w+\.)?scheduled|schedule\.every|cron\s*=", t))
        if not rel.startswith(("docs/", "frontend/public")):
            for h in re.findall(r"https?://([a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-z]{2,})", t):
                if not re.search(r"(w3\.org|github\.com|githubusercontent|example\.|localhost|opentelemetry|python\.org|npmjs|shields\.io|googleapis\.com/css|fonts\.|schema\.|json-schema|apache\.org|mozilla|stackoverflow|readthedocs|wikipedia)", h):
                    hosts[h] += 1
    print("## 5. 运行形态线索")
    print(f"- HTTP 路由装饰器约 {routes} 个；ORM 模型类约 {models} 个；定时任务注册约 {jobs} 处")
    print(f"- 代码里出现最多的外部域名（数据源/第三方依赖线索）: {hosts.most_common(15)}")
    print()

    # ---- 6. 变更热点 ----
    log = sh(GIT_SAFE + ["log", "-n", "400", "--name-only", "--format="], root)
    cnt_all = Counter(l for l in log.splitlines() if l.strip() and not l.endswith((".md", ".lock", ".json", ".yml", ".yaml", ".txt", ".png", ".svg")))
    gone = sum(n for f, n in cnt_all.items() if not os.path.exists(os.path.join(root, f)))
    cnt = Counter({f: n for f, n in cnt_all.items() if os.path.exists(os.path.join(root, f))})
    print("## 6. 变更热点（最近 ≤400 次提交中被改最多、且【当前仍存在】的文件）")
    print(f"- 已被删除/迁移的历史路径累计 {gone} 次改动已排除（若占比很高，说明发生过大重构）")
    for f, n in cnt.most_common(10):
        print(f"- {n} 次 `{f}`")
    # ---- 7. 最长的函数与类（Python ast，精确测量）----
    longest_fn, longest_cls = [], []
    for rel, p in py:
        text = read(p)
        try:
            tree = ast.parse(text)
        except Exception:
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and getattr(n, "end_lineno", None):
                longest_fn.append((n.end_lineno - n.lineno + 1, f"{rel}:{n.name}"))
            elif isinstance(n, ast.ClassDef) and getattr(n, "end_lineno", None):
                longest_cls.append((n.end_lineno - n.lineno + 1, f"{rel}:{n.name}"))
    big_files = []
    for rel, p in files:
        if rel.endswith(CODE_EXT) and not TEST_RE.search(rel.lower()) and not rel.endswith(".d.ts"):
            big_files.append((read(p).count("\n") + 1, rel))
    big_files.sort(reverse=True)
    if not longest_fn:
        print("\n## 7. 最大的源码文件（非 Python 无法精确测量函数长度，改看文件体量）")
        print(f"- 最大 6 个: {big_files[:6]}；>1000 行的文件 {sum(1 for n, _ in big_files if n > 1000)} 个（共 {len(big_files)} 个源码文件）")
    if longest_fn:
        longest_fn.sort(reverse=True); longest_cls.sort(reverse=True)
        over100 = sum(1 for n, _ in longest_fn if n > 100)
        print("\n## 7. 最长的函数与类（Python，ast 精确测量，不含测试）")
        print(f"- 函数总数 {len(longest_fn)}；>100 行的函数 {over100} 个（{over100 * 100 // max(len(longest_fn), 1)}%）")
        print(f"- 最长 6 个函数: {longest_fn[:6]}")
        print(f"- 最长 4 个类（>1000 行基本是'上帝类'）: {longest_cls[:4]}")
        non_py = [(n, rel) for n, rel in big_files if not rel.endswith(".py")]
        if non_py:
            # 混合语言仓库：TS/Go 等没有函数级数据，明确标注并列出最大的非 Python 文件作替代线索
            print(f"- 注意：函数级测量仅覆盖 Python；非 Python 源码 {len(non_py)} 个文件（最大 {non_py[:3]}）无函数数据，"
                  "请结合文件体量与抽样阅读评估")
    print("\n> 热点 = 需求集中地，也是缺陷集中地；同时是大文件的，是最该先读/最该怀疑的文件。")
    print("> 以上全部是线索，不是结论：请沿一条端到端主链路读代码验证（见 references/architecture-core.md）。")


if __name__ == "__main__":
    main()
