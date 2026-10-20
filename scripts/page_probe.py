#!/usr/bin/env python3
"""
page_probe.py — 不耗 GitHub API 额度，直接解析仓库主页里嵌入的数据。

用法:
    python page_probe.py https://github.com/owner/repo [--json]

输出: star/fork/watch、协议、主题、简介、官网、release/tag 数、提交总数、创建时间、
      是否归档、默认分支、Issues/PR 计数（页面有则取）、采集时间。

为什么要有它:
  - 匿名 API 每小时仅 60 次，沙箱出口 IP 共享，经常 403；
  - web_fetch 会把整页导航文本塞进上下文，非常耗 token；
  - 页面内嵌 JSON 比抓文本稳定得多。
GitHub 改版后字段可能变化：任何字段取不到都写"未取到"，不要猜。
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone

UA = "Mozilla/5.0 (compatible; github-project-review)"


def parse_repo(arg):
    m = re.search(r"github\.com[/:]([^/\s]+)/([^/\s#?]+)", arg)
    if m:
        return m.group(1), re.sub(r"\.git$", "", m.group(2))
    parts = arg.strip("/").split("/")
    if len(parts) == 2:
        return parts[0], parts[1]
    sys.exit("无法解析仓库，请传入 URL 或 owner/repo")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "ignore"), r.headers.get("Date")


def grab_obj(h, key):
    """从 h 中取出 "key":{...} 的 JSON 对象（花括号配平）。"""
    i = h.find(f'"{key}":{{')
    if i < 0:
        return None
    j = h.find("{", i)
    depth, k = 0, j
    in_str = esc = False
    while k < len(h):
        c = h[k]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
        k += 1
    try:
        return json.loads(h[j:k + 1])
    except Exception:
        return None


def rx(h, pat, grp=1):
    m = re.search(pat, h, re.S)
    return m.group(grp) if m else None


def counter_after(h, label):
    """取导航里 label 后面的计数（Issues / Pull requests）。"""
    for m in re.finditer(r">\s*" + re.escape(label) + r"\s*<(.{0,700}?)</a>", h, re.S):
        seg = re.sub(r"\s+", " ", m.group(1))
        t = re.search(r'title="([\d,+]+)"', seg) or re.search(r'CounterLabel[^>]*>\s*([\d,.kK+]+)\s*<', seg)
        if t:
            return t.group(1)
    return None


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    owner, repo = parse_repo(sys.argv[1])
    url = f"https://github.com/{owner}/{repo}"
    try:
        h, date_hdr = fetch(url)
    except Exception as e:
        sys.exit(f"页面获取失败: {e}（可能是仓库不存在/私有/被限流）")

    about = grab_obj(h, "sidebarAboutData") or {}
    sec = about.get("sections") or {}
    rel = sec.get("releases") or {}
    lic = rx(h, r'"license":\{"spdxId":"([^"]*)"')
    out = {
        "repo": f"{owner}/{repo}",
        "url": url,
        "fetched_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "server_date_header": date_hdr,
        "description": about.get("description") or rx(h, r'<meta name="description" content="([^"]*)"'),
        "website": about.get("website"),
        "topics": [t.get("name") for t in about.get("topics", [])],
        "stars": about.get("stargazerCount"),
        "forks": about.get("forksCount"),
        "watchers": about.get("watcherCount"),
        "license": lic,
        "releases": rel.get("releaseCount"),
        "tags": rel.get("tagCount"),
        "has_packages": sec.get("packages"),
        "used_by_shown": sec.get("usedBy"),
        "sponsors_enabled": sec.get("sponsors"),
        "commit_count": rx(h, r'"commitCount":"?(\d+)"?'),
        "created_at": rx(h, r'"createdAt":"([^"]+)"'),
        "default_branch": rx(h, r'"defaultBranch":"([^"]+)"'),
        "archived": (rx(h, r'"isArchived":(true|false)') == "true") if rx(h, r'"isArchived":(true|false)') else None,
        "issues_open": counter_after(h, "Issues"),
        "prs_open": counter_after(h, "Pull requests"),
    }
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    def v(x):
        return "未取到" if x in (None, "", []) else x

    print(f"# 页面数据: {out['repo']}（采集 {out['fetched_at_utc']} UTC）")
    print(f"- 简介: {v(out['description'])}")
    print(f"- 官网: {v(out['website'])} · 主题: {', '.join(out['topics']) or '无'}")
    print(f"- Star {v(out['stars'])} · Fork {v(out['forks'])} · Watch {v(out['watchers'])} · 协议 {v(out['license'])}")
    if out["stars"] and out["forks"]:
        print(f"- Fork/Star 比 {out['forks'] / out['stars']:.2f}（解读前先看部署方式：若推荐 Fork 后跑 Actions，比值会虚高）")
    print(f"- 创建于 {v(out['created_at'])} · 提交总数 {v(out['commit_count'])} · 默认分支 {v(out['default_branch'])} · 归档 {v(out['archived'])}")
    if out["created_at"] and out["stars"]:
        try:
            d = (datetime.now(timezone.utc) - datetime.fromisoformat(out["created_at"].replace("Z", "+00:00"))).days
            print(f"- 项目年龄 {d} 天 · 日均涨星 {out['stars'] / max(d, 1):.1f}（需结合是否上过 Trending 判断）")
        except Exception:
            pass
    print(f"- Release {v(out['releases'])} · Tag {v(out['tags'])} · 开放 Issue {v(out['issues_open'])} · 开放 PR {v(out['prs_open'])}")
    print(f"- Packages 发布: {v(out['has_packages'])} · 赞助入口: {v(out['sponsors_enabled'])}")
    print("\n> 数据来自页面快照；若页面被缓存，star 数为下限。仓库页异常时可改用组织/用户主页或 gh_probe.py。")


if __name__ == "__main__":
    main()
