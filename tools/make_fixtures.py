#!/usr/bin/env python3
"""离线测试夹具生成器：一次性生成探针脚本的全部攻击/边界样本仓库。

用法：python tools/make_fixtures.py <目标目录>
生成 9 类样本（每类一个子目录），供 tests/test_probes.py 断言：
  1. symlink_attack      SKILL.md 软链到仓库外的秘密文件（Windows 无特权时自动跳过并留标记）
  2. malicious_gitconfig .git/config 带恶意 fsmonitor（若被执行会留下 PWNED 标记文件）
  3. chinese_paths       中文目录/文件名 + 1 条失效相对链接
  4. env_files           .env（假密钥）、依赖 -r 展开（含仓库外越界引用）、锁文件、子目录 LICENSE
  5. bom_crlf_skill      带 BOM 与 CRLF 的 SKILL.md（1.1.4 修复的误判场景）
  6. dependency_cycles   硬环 a<->b 顶层互导 + 软环 c<->d 延迟导入
  7. src_layout          src/<pkg>/ 布局
  8. single_skill        根 SKILL.md 单技能仓库（1.1.5 修复的分类/name 误判场景）
  9. dev_skill_docs      仅带 .claude/skills/ 开发辅助技能的教程仓库（1.1.6 回归修复场景）
 10. team_handbook       极小团队手册 + 开发辅助技能：文档多于 SKILL.md，保底不生效（1.1.8 场景）
 11. multi_root_skills   根下 3 个 <name>/SKILL.md 技能目录（1.1.9 补缺口）
 12. root_skill_with_refs 根下 1 个技能目录 + references + 脚本（1.1.9 补缺口）
 13. tiny_root_skill     README + <name>/SKILL.md + 脚本的 3 文件极小仓库（1.1.8 回归锁）
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

    # 4. .env 文件 + 依赖展开 + 锁文件 + 子目录 LICENSE（不冒充根 LICENSE）
    #    requirements.txt 额外带两条仓库外越界引用：../ 相对越界与绝对路径（1.1.6 安全防护场景）
    env = os.path.join(out, "env_files")
    made["env_files"] = env
    outside_req = os.path.join(out, "_outside_reqs.txt")
    write(outside_req, "evil-outside-pkg==9.9.9\n")
    write(os.path.join(env, ".env"), "API_KEY=FAKE_KEY_NOT_REAL_123456\n")
    write(os.path.join(env, ".env.example"), "API_KEY=your-key-here\n")
    write(os.path.join(env, "requirements.txt"),
          "-r requirements-rt.txt\npytest\nrequests\n-r ../_outside_reqs.txt\n-r %s\n"
          % outside_req.replace("\\", "/"))
    write(os.path.join(env, "requirements-rt.txt"), "numpy==2.0.0\n")
    write(os.path.join(env, "package-lock.json"), "{}\n")
    write(os.path.join(env, "third_party", "lib", "LICENSE"), "MIT\n")
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

    # 8. 单技能仓库：根 SKILL.md（name 与仓库目录名故意不同）+ 文档占比超 65%
    #    修复前会被"文档占比"判成 content-collection，且 name 被拿去和克隆目录名比对
    ss = os.path.join(out, "single_skill")
    made["single_skill"] = ss
    write(os.path.join(ss, "SKILL.md"),
          skill("single-skill", "评估任意代码仓库的质量风险与学习价值并输出报告的测试技能夹具"))
    for g in ("guide", "faq", "tips", "notes"):
        write(os.path.join(ss, "references", "%s.md" % g), "# %s\n\n正文内容。\n" % g)
    write(os.path.join(ss, "scripts", "run.py"), "print('hi')\n")
    commit(ss)

    # 9. 仅带 .claude/skills/ 开发辅助技能的教程仓库：技能信号不得压制内容分类（1.1.6 回归修复）
    #    pyproject 用 PEP 621 表格写法声明 license（license = {text = "MIT"}），验证清单声明识别
    dv = os.path.join(out, "dev_skill_docs")
    made["dev_skill_docs"] = dv
    write(os.path.join(dv, ".claude", "skills", "release", "SKILL.md"),
          skill("release-helper", "仓库维护者的发布流程辅助技能（开发辅助夹具，不代表仓库类型）"))
    for i in (1, 2, 3, 4):
        write(os.path.join(dv, "chapters", "ch%d.md" % i), "# 第 %d 章\n\n教程正文内容。\n" % i)
    write(os.path.join(dv, "README.md"), "# 教程合集\n\n配套教程文档仓库。\n")
    write(os.path.join(dv, "pyproject.toml"),
          '[project]\nname = "tutorial-docs"\nversion = "0.1.0"\nlicense = {text = "MIT"}\n')
    commit(dv)

    # 10. 极小团队手册 + 开发辅助技能（1.1.8 修正场景）：
    #     文档多于 SKILL.md 时"SKILL.md 是本体"的保底不得生效，应判内容合集；
    #     pyproject 用 {file = "LICENSE"} 表格写法，验证 file 形式措辞（不把文件名当许可证名）
    tb = os.path.join(out, "team_handbook")
    made["team_handbook"] = tb
    write(os.path.join(tb, "README.md"), "# 团队手册\n\n新人入门与协作规范。\n")
    write(os.path.join(tb, "handbook", "basics.md"), "# 基础规范\n\n日常协作规则。\n")
    write(os.path.join(tb, "handbook", "advanced.md"), "# 进阶规范\n\n发布与值班流程。\n")
    write(os.path.join(tb, ".claude", "skills", "release", "SKILL.md"),
          skill("release-helper", "仓库维护者的发布流程辅助技能（开发辅助夹具，不代表仓库类型）"))
    write(os.path.join(tb, "pyproject.toml"),
          '[project]\nname = "team-handbook"\nversion = "0.1.0"\nlicense = {file = "LICENSE"}\n')
    commit(tb)

    # 11-13. 技能目录直接放仓库根下的三种布局（1.1.9 补缺口/锁回归）：
    #        根下首层非点目录的 <name>/SKILL.md 算技能强信号，压制"文档占比"内容信号
    mr = os.path.join(out, "multi_root_skills")
    made["multi_root_skills"] = mr
    for name in ("alpha", "beta", "gamma"):
        write(os.path.join(mr, name, "SKILL.md"),
              skill(name, "评估任意代码仓库的质量风险与学习价值并输出报告的测试技能夹具"))
        write(os.path.join(mr, name, "guide.md"), "# %s 指南\n\n正文内容。\n" % name)
    for g in ("r1", "r2", "r3", "r4"):
        write(os.path.join(mr, "references", "%s.md" % g), "# 参考材料\n\n正文内容。\n")
    for g in ("m1", "m2", "m3", "m4"):
        write(os.path.join(mr, "%s.md" % g), "# 散文标题 %s\n\n正文内容。\n" % g)
    write(os.path.join(mr, "README.md"), "# 技能合集\n\n多个技能的集合仓库。\n")
    write(os.path.join(mr, "scripts", "a.py"), "print('a')\n")
    write(os.path.join(mr, "scripts", "b.py"), "print('b')\n")
    commit(mr)

    rs = os.path.join(out, "root_skill_with_refs")
    made["root_skill_with_refs"] = rs
    write(os.path.join(rs, "alpha", "SKILL.md"),
          skill("alpha", "评估任意代码仓库的质量风险与学习价值并输出报告的测试技能夹具"))
    for g in ("r1", "r2", "r3", "r4"):
        write(os.path.join(rs, "references", "%s.md" % g), "# 参考材料\n\n正文内容。\n")
    write(os.path.join(rs, "README.md"), "# 单技能仓库\n\n附参考材料与脚本。\n")
    write(os.path.join(rs, "extra.md"), "# 补充说明\n\n正文内容。\n")
    write(os.path.join(rs, "scripts", "a.py"), "print('a')\n")
    write(os.path.join(rs, "scripts", "b.py"), "print('b')\n")
    commit(rs)

    ts = os.path.join(out, "tiny_root_skill")
    made["tiny_root_skill"] = ts
    write(os.path.join(ts, "README.md"), "# 极小技能仓库\n\n一个技能目录加一个脚本。\n")
    write(os.path.join(ts, "alpha", "SKILL.md"),
          skill("alpha", "评估任意代码仓库的质量风险与学习价值并输出报告的测试技能夹具"))
    write(os.path.join(ts, "run.py"), "print('hi')\n")
    commit(ts)

    return made


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    paths = build_all(sys.argv[1])
    for k, v in paths.items():
        print("- %s -> %s" % (k, v))
    print("夹具生成完毕（symlink 特权不足时该样本留 .fixture-skipped-symlink 标记）")
