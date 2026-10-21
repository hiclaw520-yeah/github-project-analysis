#!/usr/bin/env python3
"""
gh_probe.py — 一条命令采集 GitHub 仓库的"体检数据"，输出 Markdown 摘要。

用法:
    python gh_probe.py https://github.com/owner/repo
    python gh_probe.py owner/repo --json        # 输出原始 JSON
    GITHUB_TOKEN=xxx python gh_probe.py owner/repo   # 提高限速(未认证 60 次/小时)

只依赖标准库。任何单项失败都不会中断，缺失项会标注"获取失败"。
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# 输出强制 UTF-8（replace 兜底）：中文 Windows 下输出被管道/重定向时，Python 会退回
# GBK 等本地编码，遇到 ✓ 等字符抛 UnicodeEncodeError 直接中断；统一 UTF-8 后任何编码环境都不崩。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from collections import Counter
from datetime import datetime, timedelta, timezone

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN")
NOW = datetime.now(timezone.utc)


def parse_repo(arg: str):
    m = re.search(r"github\.com[/:]([^/\s]+)/([^/\s#?]+)", arg)
    if m:
        owner, repo = m.group(1), m.group(2)
    else:
        parts = arg.strip("/").split("/")
        if len(parts) != 2:
            sys.exit("无法解析仓库，请传入 URL 或 owner/repo")
        owner, repo = parts
    return owner, re.sub(r"\.git$", "", repo)


def get(path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-project-review",
        **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return {"_error": "403 限速或无权限(设置 GITHUB_TOKEN 可缓解)"}
        return {"_error": f"HTTP {e.code}"}
    except Exception as e:  # 网络问题
        return {"_error": str(e)}


def ok(x):
    return not (isinstance(x, dict) and "_error" in x)


def days_ago(iso):
    if not iso:
        return None
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (NOW - d).days


def search_count(q):
    r = get("/search/issues", {"q": q, "per_page": 1})
    return r.get("total_count") if ok(r) else None


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    owner, repo = parse_repo(sys.argv[1])
    as_json = "--json" in sys.argv
    full = f"{owner}/{repo}"
    out = {"repo": full}

    info = get(f"/repos/{full}")
    if not ok(info):
        sys.exit(f"仓库信息获取失败: {info['_error']}")
    out["info"] = {
        "description": info.get("description"),
        "stars": info["stargazers_count"],
        "forks": info["forks_count"],
        "watchers": info.get("subscribers_count"),
        "open_issues_incl_pr": info["open_issues_count"],
        "license": (info.get("license") or {}).get("spdx_id"),
        "created_days_ago": days_ago(info["created_at"]),
        "pushed_days_ago": days_ago(info["pushed_at"]),
        "archived": info["archived"],
        "is_fork": info["fork"],
        "default_branch": info["default_branch"],
        "topics": info.get("topics", []),
        "size_kb": info["size"],
        "has_homepage": bool(info.get("homepage")),
        "owner_type": info["owner"]["type"],
    }
    branch = info["default_branch"]

    langs = get(f"/repos/{full}/languages")
    if ok(langs):
        total = sum(langs.values()) or 1
        out["languages"] = {k: round(v * 100 / total, 1) for k, v in langs.items()}

    # ---- 活跃度：最近 100 次提交 ----
    commits = get(f"/repos/{full}/commits", {"per_page": 100, "sha": branch})
    if ok(commits) and commits:
        dates = [c["commit"]["author"]["date"] for c in commits]
        authors = Counter(
            (c.get("author") or {}).get("login") or c["commit"]["author"]["name"]
            for c in commits
        )
        msgs = [c["commit"]["message"] for c in commits]
        conv = sum(bool(re.match(r"^(feat|fix|docs|refactor|test|chore|perf|ci|build|style)(\(.+\))?!?:", m)) for m in msgs)
        ai_trailer = sum(bool(re.search(r"co-authored-by:.*(claude|copilot|cursor|codex|gemini|openai|aider)", m, re.I)) for m in msgs)
        bots = sum(1 for a in authors if "bot" in a.lower())
        span_days = max((datetime.fromisoformat(dates[0].replace("Z", "+00:00")) -
                         datetime.fromisoformat(dates[-1].replace("Z", "+00:00"))).days, 1)
        out["commits_last100"] = {
            "latest_days_ago": days_ago(dates[0]),
            "oldest_of_100_days_ago": days_ago(dates[-1]),
            "span_days": span_days,
            "commits_per_week": round(len(dates) / span_days * 7, 1),
            "unique_authors": len(authors),
            "top_author_share_pct": round(authors.most_common(1)[0][1] * 100 / len(dates), 1),
            "conventional_commit_pct": round(conv * 100 / len(msgs)),
            "ai_coauthor_trailer_pct": round(ai_trailer * 100 / len(msgs)),
            "bot_authors": bots,
        }

    contribs = get(f"/repos/{full}/contributors", {"per_page": 100})
    if ok(contribs):
        out["contributors"] = {
            "count_up_to_100": len(contribs),
            "top3": [(c["login"], c["contributions"]) for c in contribs[:3]],
        }

    rels = get(f"/repos/{full}/releases", {"per_page": 5})
    if ok(rels):
        out["releases"] = [(r["tag_name"], days_ago(r["published_at"])) for r in rels]
    tags = get(f"/repos/{full}/tags", {"per_page": 5})
    if ok(tags):
        out["tags_sample"] = [t["name"] for t in tags]

    # ---- Issue / PR 健康度（Search API 限速 10/min，仅 5 次调用）----
    since = (NOW - timedelta(days=90)).strftime("%Y-%m-%d")
    out["issues_prs"] = {
        "issues_open": search_count(f"repo:{full} type:issue state:open"),
        "issues_closed": search_count(f"repo:{full} type:issue state:closed"),
        "prs_open": search_count(f"repo:{full} type:pr state:open"),
        "prs_merged": search_count(f"repo:{full} type:pr is:merged"),
        "prs_merged_last_90d": search_count(f"repo:{full} type:pr is:merged merged:>={since}"),
    }

    # ---- 目录树：工程化信号 ----
    tree = get(f"/repos/{full}/git/trees/{branch}", {"recursive": 1})
    if ok(tree):
        paths = [t["path"] for t in tree.get("tree", []) if t["type"] == "blob"]
        low = [p.lower() for p in paths]

        def has(pred):
            return any(pred(p) for p in low)

        code_ext = (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".c", ".cc", ".cpp", ".h", ".rb", ".php", ".cs", ".swift", ".vue")
        is_test = lambda p: bool(re.search(r"(^|/)(tests?|__tests__|spec)/|(_test|\.test|\.spec)\.|(^|/)test_", p))
        code_files = [p for p in low if p.endswith(code_ext)]
        test_files = [p for p in code_files if is_test(p)]
        out["tree"] = {
            "truncated": tree.get("truncated", False),
            "total_files": len(paths),
            "code_files": len(code_files),
            "test_files": len(test_files),
            "test_to_code_ratio": round(len(test_files) / max(len(code_files) - len(test_files), 1), 2),
            "ci_workflows": [p for p in paths if p.startswith(".github/workflows/")],
            "has_dockerfile": has(lambda p: p.endswith("dockerfile") or "docker-compose" in p),
            "has_license": has(lambda p: p.split("/")[-1].startswith("license")),
            "has_contributing": has(lambda p: "contributing" in p.split("/")[-1]),
            "has_security_md": has(lambda p: p.split("/")[-1] == "security.md"),
            "has_changelog": has(lambda p: "changelog" in p.split("/")[-1] or p.startswith("release")),
            "has_docs_dir": has(lambda p: p.startswith("docs/")),
            "has_architecture_doc": has(lambda p: "architecture" in p),
            "has_env_example": has(lambda p: p.endswith(".env.example")),
            "has_lockfile": has(lambda p: p.split("/")[-1] in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock", "cargo.lock", "go.sum", "pipfile.lock")),
            "has_type_or_lint_cfg": has(lambda p: p.split("/")[-1] in ("tsconfig.json", "mypy.ini", "pyproject.toml", ".eslintrc.json", ".eslintrc.js", "ruff.toml", ".golangci.yml")),
            "has_dependabot_or_renovate": has(lambda p: "dependabot" in p or "renovate" in p),
            "agent_files": [p for p in paths if re.search(r"(^|/)(agents?\.md|claude\.md|\.cursorrules|\.agents/|\.claude/|\.cursor/)", p.lower())][:8],
            "top_level": sorted({p.split("/")[0] for p in paths})[:40],
        }
        # 命中 TODO 过多等需 clone 后用 local_probe.py / arch_probe.py

    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    render(out)


def render(o):
    i = o["info"]
    print(f"# GitHub 体检数据: {o['repo']}\n")
    print(f"- 简介: {i['description']}")
    print(f"- Star {i['stars']} · Fork {i['forks']} · Watch {i['watchers']} · 协议 {i['license']} · 主题 {', '.join(i['topics'][:8])}")
    print(f"- 创建 {i['created_days_ago']} 天前 · 最近 push {i['pushed_days_ago']} 天前 · 归档={i['archived']} · 是 fork={i['is_fork']} · 账号类型 {i['owner_type']}")
    if i["stars"]:
        print(f"- Fork/Star 比 {i['forks'] / i['stars']:.2f}（通常 0.1~0.3；过低可能说明大家只收藏不使用）")
        if i["created_days_ago"]:
            print(f"- 日均涨星 {i['stars'] / max(i['created_days_ago'], 1):.1f}（需结合是否上过 Trending 判断）")
    if "languages" in o:
        print(f"- 语言占比: {o['languages']}")
    c = o.get("commits_last100")
    if c:
        print("\n## 活跃度与协作（最近 100 次提交）")
        print(f"- 最近提交 {c['latest_days_ago']} 天前；100 次提交跨度 {c['span_days']} 天（≈{c['commits_per_week']} 次/周）")
        print(f"- 提交者 {c['unique_authors']} 人（按 GitHub 登录名/作者名）；头号作者占比 {c['top_author_share_pct']}%（>85% 视为单人项目）。注意：同一个人常有多个账号/用户名，会被算成多人——**以 local_probe 的按邮箱统计为准**")
        print(f"- Conventional Commits 占比 {c['conventional_commit_pct']}%；AI 共同作者署名占比 {c['ai_coauthor_trailer_pct']}%；bot 账号 {c['bot_authors']} 个")
    if "contributors" in o:
        print(f"- 贡献者(最多取100): {o['contributors']['count_up_to_100']}；Top3: {o['contributors']['top3']}")
    if "releases" in o:
        print(f"- 最近 Release (tag, 天前): {o['releases']}；tags: {o.get('tags_sample')}")
    ip = o["issues_prs"]
    print("\n## Issue / PR 健康度")
    print(f"- Issue 开/关: {ip['issues_open']}/{ip['issues_closed']}；PR 开: {ip['prs_open']}；PR 累计合并 {ip['prs_merged']}，近90天合并 {ip['prs_merged_last_90d']}")
    t = o.get("tree")
    if t:
        print("\n## 工程化信号（目录树）")
        print(f"- 文件 {t['total_files']}（树被截断={t['truncated']}）；代码文件 {t['code_files']}；测试文件 {t['test_files']}；测试/源码文件比 {t['test_to_code_ratio']}")
        flags = {k: v for k, v in t.items() if k.startswith("has_")}
        print("- " + " · ".join(f"{k[4:]}={'✓' if v else '✗'}" for k, v in flags.items()))
        print(f"- CI workflows: {t['ci_workflows']}")
        print(f"- AI 协作配置文件: {t['agent_files']}")
        print(f"- 顶层目录/文件: {t['top_level']}")
    print("\n> 以上均为客观信号，不是结论。请继续按 SKILL.md 做代码抽样阅读与评分。")


if __name__ == "__main__":
    main()
