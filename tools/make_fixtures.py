#!/usr/bin/env python3
"""离线测试夹具生成器：一次性生成探针脚本的全部攻击/边界样本仓库。

用法：python tools/make_fixtures.py <目标目录>
生成 7 类样本（每类一个子目录），供 tests/test_probes.py 断言：
  1. symlink_attack      SKILL.md 软链到仓库外的秘密文件（Windows 无特权时自动跳过并留标记）
  2. malicious_gitconfig .git/config 带恶意 fsmonitor（若被执行会留下 PWNED 标记文件）
  3. chinese_paths       中文目录/文件名 + 1 条失效相对链接
  4. env_files           提交了 .env（假密钥）与 .env.example
  5. bom_crlf_skill      带 BOM 与 CRLF 的 SKILL.md（1.1.4 修复的误判场景）
  6. dependency_cycles   硬环 a<->b 顶层互导 + 软环 c<->d 延迟导入
  7. src_layout          src/<pkg>/ 布局
"""
import os
import subprocess
import sys

GIT = ["git", "-c", "core.fsmonitor=false", "-c", "user.name=fixture",
       "-c", "user.email=fixture@example.com"]


def sh(*cmd, cwd):
    return subprocess.run(GIT + list(cmd), cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def write(path, text, encoding="utf-8"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(text)


def commit(root):
    sh("init", "-q", ".", cwd=root)
    sh("add", "-A", cwd=root)
    sh("commit", "-qm", "fixture", cwd=root)


def skill(name, desc, body="# 正文\n引用 [a](./missing.md)\n"):
    return "---\nname: %s\ndescription: %s\n---\n\n%s" % (name, desc, body)


def build_all(out):
    """生成全部夹具，返回 dict<名字, 路径>。"""
    os.makedirs(out, exist_ok=True)
    made = {}

    # 1. symlink 攻击：仓库内 SKILL.md 指向仓库外的"秘密文件"
    host = os.path.join(out, "symlink_attack")
    outside = os.path.join(out, "_outside_secret.txt")
    write(outside, "SECRET_CANARY_TOP_SECRET\n")
    made["symlink_attack"] = host
    write(os.path.join(host, "normal-skill", "SKILL.md"),
          skill("normal-skill", "评估任意代码仓库的质量风险与学习价值并输出报告的测试技能夹具"))
    link = os.path.join(host, "evil-skill", "SKILL.md")
    os.makedirs(os.path.dirname(link), exist_ok=True)
    try:
        os.symlink(outside, link)
    except OSError:
        # Windows 无符号链接特权：留标记，测试据此 skip（junction 需要目录，场景不适用）
        write(os.path.join(host, ".fixture-skipped-symlink"), "no symlink privilege\n")

    # 2. 恶意 .git/config：fsmonitor 被执行会留下标记文件（我们的 GIT_SAFE 必须压制它）
    mal = os.path.join(out, "malicious_gitconfig")
    made["malicious_gitconfig"] = mal
    write(os.path.join(mal, "ok-skill", "SKILL.md"),
          skill("ok-skill", "评估任意代码仓库的质量风险与学习价值并输出报告的测试技能夹具"))
    commit(mal)
    with open(os.path.join(mal, ".git", "config"), "a", encoding="utf-8") as f:
        f.write('\tfsmonitor = "echo PWNED > PWNED_MARKER_DO_NOT_WANT"\n')
        f.write("\thooksPath = .\n")

    # 3. 中文路径
    cn = os.path.join(out, "chinese_paths")
    made["chinese_paths"] = cn
    write(os.path.join(cn, "技能", "产品需求", "SKILL.md"),
          skill("cn-skill", "评估任意代码仓库的质量风险与学习价值并输出报告的测试技能夹具"))
    commit(cn)

    # 4. .env 文件
    env = os.path.join(out, "env_files")
    made["env_files"] = env
    write(os.path.join(env, ".env"), "API_KEY=FAKE_KEY_NOT_REAL_123456\n")
    write(os.path.join(env, ".env.example"), "API_KEY=your-key-here\n")
    write(os.path.join(env, "demo-skill", "SKILL.md"),
          skill("demo-skill", "评估任意代码仓库的质量风险与学习价值并输出报告的测试技能夹具"))
    commit(env)

    # 5. BOM / CRLF 技能
    bc = os.path.join(out, "bom_crlf_skill")
    made["bom_crlf_skill"] = bc
    body = skill("bom-skill", "评估任意代码仓库的质量风险与学习价值并输出报告的测试技能夹具")
    write(os.path.join(bc, "bom-skill", "SKILL.md"), body, encoding="utf-8-sig")
    write(os.path.join(bc, "crlf-skill", "SKILL.md"),
          skill("crlf-skill", "评估任意代码仓库的质量风险与学习价值并输出报告的测试技能夹具"),
          encoding="utf-8")
    with open(os.path.join(bc, "crlf-skill", "SKILL.md"), "rb") as f:
        raw = f.read().replace(b"\n", b"\r\n")
    with open(os.path.join(bc, "crlf-skill", "SKILL.md"), "wb") as f:
        f.write(raw)
    commit(bc)

    # 6. 依赖环：a<->b 顶层互导（硬环），c->d 顶层 + d 内部延迟导回 c（软环）
    # arch_probe 只统计 .py 数 >= 5 的顶层目录为包根，故每包补 filler 模块
    cy = os.path.join(out, "dependency_cycles")
    made["dependency_cycles"] = cy
    write(os.path.join(cy, "pkg_a", "__init__.py"), "")
    write(os.path.join(cy, "pkg_a", "core.py"), "import pkg_b.core\n\n\ndef run():\n    return 1\n")
    write(os.path.join(cy, "pkg_b", "__init__.py"), "")
    write(os.path.join(cy, "pkg_b", "core.py"), "import pkg_a.core\n\n\ndef run():\n    return 2\n")
    write(os.path.join(cy, "pkg_c", "__init__.py"), "")
    write(os.path.join(cy, "pkg_c", "core.py"), "import pkg_d.core\n\n\ndef run():\n    return 3\n")
    write(os.path.join(cy, "pkg_d", "__init__.py"), "")
    write(os.path.join(cy, "pkg_d", "core.py"),
          "def run():\n    import pkg_c.core\n    return 4\n")
    for pkg in ("pkg_a", "pkg_b", "pkg_c", "pkg_d"):
        for i in (1, 2, 3):
            write(os.path.join(cy, pkg, "m%d.py" % i), "VALUE = %d\n" % i)
    commit(cy)

    # 7. src 布局（同样需要 >=5 个 .py 才被视为包根）
    sl = os.path.join(out, "src_layout")
    made["src_layout"] = sl
    write(os.path.join(sl, "src", "mypkg", "__init__.py"), "")
    write(os.path.join(sl, "src", "mypkg", "core.py"), "from mypkg import util\n\n\ndef run():\n    return util.help()\n")
    write(os.path.join(sl, "src", "mypkg", "util.py"), "def help():\n    return 1\n")
    for i in (1, 2):
        write(os.path.join(sl, "src", "mypkg", "m%d.py" % i), "VALUE = %d\n" % i)
    commit(sl)

    return made


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    paths = build_all(sys.argv[1])
    for k, v in paths.items():
        print("- %s -> %s" % (k, v))
    print("夹具生成完毕（symlink 特权不足时该样本留 .fixture-skipped-symlink 标记）")
