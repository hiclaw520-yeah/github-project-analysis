#!/usr/bin/env python3
"""一键打包分发 zip（跨平台，逻辑唯一入口）。

打包内容 = HEAD 提交：git archive 只含已跟踪文件，天然不含 .git/，
也不含未提交 / 未跟踪的文件（有改动先 commit 再打包）。
用法：python scripts/package.py（Windows 也可双击 package.cmd，Unix 也可 ./package.sh）
"""
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/ 的上一级
PREFIX = "github-project-analysis"


def sh(*cmd):
    """跑一条 git 命令，返回 (是否成功, stdout)；git 不存在也按失败处理。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError:
        return False, ""
    return r.returncode == 0, r.stdout or ""


def main():
    os.chdir(ROOT)

    ok, _ = sh("git", "rev-parse", "--git-dir")
    if not ok:
        print("打包失败：未找到 git，或本目录不是 git 仓库。")
        return 1

    # 有未提交改动时提醒（zip 里只有最后一次 commit 的内容）
    ok, st = sh("git", "status", "--porcelain")
    if ok and st.strip():
        print(f"[警告] 当前有 {len(st.splitlines())} 处未提交/未跟踪的改动，不会进入 zip；本次打包的是最后一次 commit。")

    # 从 SKILL.md 的 metadata 读版本号作为文件名后缀（读不到就不带后缀）
    ver = ""
    try:
        m = re.search(r'^\s*version:\s*"?([^"\s]+)"?', open("SKILL.md", encoding="utf-8").read(), re.M)
        if m:
            ver = m.group(1)
    except OSError:
        pass

    os.makedirs("dist", exist_ok=True)
    out = os.path.join("dist", f"{PREFIX}-v{ver}.zip" if ver else f"{PREFIX}.zip")
    ok, _ = sh("git", "archive", "--format=zip", f"--prefix={PREFIX}/", "-o", out, "HEAD")
    if not ok:
        print("打包失败：git archive 出错。")
        return 1

    print(f"\n打包完成: {out}")
    print(f"zip 顶层为 {PREFIX}/ 目录，不含 .git/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
