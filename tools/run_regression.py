#!/usr/bin/env python3
"""回归比对器（T01 配套）：改动前后各跑一遍探针，逐脚本比对输出。

用法：
    python tools/run_regression.py baseline <repo>   # 改动前存基线
    python tools/run_regression.py compare  <repo>   # 改动后比对，0 差异返回 0

基线存 tests/.baseline/<repo名>/<脚本名>.out（gitignore，不提交——样本仓库
内容会随时间变化，基线只对"改动前后的近距离对比"有效）。有差异时精确指出
哪个仓库、哪个脚本的输出变了。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
BASELINE = os.path.join(ROOT, "tests", ".baseline")
PROBES = ("local_probe", "arch_probe", "content_probe", "classify_repo")


def run_probe(name, repo):
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, name + ".py"), repo],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300)
    return r.stdout


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("baseline", "compare"):
        sys.exit(__doc__)
    mode, repo = sys.argv[1], os.path.abspath(sys.argv[2])
    if not os.path.isdir(repo):
        sys.exit("仓库目录不存在: %s" % repo)
    tag = os.path.basename(repo.rstrip("/\\"))
    outdir = os.path.join(BASELINE, tag)

    if mode == "baseline":
        os.makedirs(outdir, exist_ok=True)
        for name in PROBES:
            with open(os.path.join(outdir, name + ".out"), "w",
                      encoding="utf-8", newline="\n") as f:
                f.write(run_probe(name, repo))
        print("基线已存: %s" % outdir)
        return 0

    # compare
    if not os.path.isdir(outdir):
        sys.exit("没有基线，先执行: python tools/run_regression.py baseline %s" % repo)
    diff_total = 0
    for name in PROBES:
        base_p = os.path.join(outdir, name + ".out")
        if not os.path.exists(base_p):
            print("%-14s 基线缺失" % name)
            diff_total += 1
            continue
        with open(base_p, encoding="utf-8") as f:
            base = f.read()
        now = run_probe(name, repo)
        if base == now:
            print("%-14s 一致" % name)
        else:
            b, n = base.splitlines(), now.splitlines()
            changed = sum(1 for i in range(max(len(b), len(n)))
                          if i >= len(b) or i >= len(n) or b[i] != n[i])
            print("%-14s 差异 %d 行（首处: 第 %d 行）"
                  % (name, changed,
                     next((i + 1 for i in range(max(len(b), len(n)))
                           if i >= len(b) or i >= len(n) or b[i] != n[i]), 0)))
            diff_total += 1
    print("仓库 [%s]: %d 个脚本输出有差异" % (tag, diff_total))
    return 1 if diff_total else 0


if __name__ == "__main__":
    sys.exit(main())
