#!/usr/bin/env python3
"""探针脚本自动化测试（T01）：夹具驱动的集成测试 + 纯函数单测。

运行：python -m unittest discover -s tests -v
夹具由 tools/make_fixtures.py 在临时目录生成；Windows 无符号链接特权时
symlink 样本自动 skip。全部只用标准库，Python 3.8+。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import scripts.content_probe as cp  # noqa: E402
from tools.make_fixtures import build_all  # noqa: E402

SCRIPTS = os.path.join(ROOT, "scripts")
PROBES = ("local_probe", "arch_probe", "content_probe", "classify_repo")


def run_probe(name, repo):
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, name + ".py"), repo],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    return r.returncode, r.stdout


class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx_root = tempfile.mkdtemp(prefix="ghpr_fx_")
        cls.fx = build_all(cls.fx_root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.fx_root, ignore_errors=True)

    def test_symlink_secret_not_read(self):
        """仓库内软链指向外部秘密文件：探针绝不能把秘密读进输出。"""
        repo = self.fx["symlink_attack"]
        if os.path.exists(os.path.join(repo, ".fixture-skipped-symlink")):
            self.skipTest("当前系统无符号链接特权，夹具未生成")
        _, out = run_probe("content_probe", repo)
        self.assertNotIn("SECRET_CANARY", out)

    def test_malicious_gitconfig_suppressed(self):
        """恶意 .git/config（fsmonitor/hooksPath）不得被执行，提交历史照常采集。"""
        repo = self.fx["malicious_gitconfig"]
        code, out = run_probe("local_probe", repo)
        self.assertEqual(code, 0)
        self.assertIn("提交历史", out)
        self.assertFalse(os.path.exists(os.path.join(repo, "PWNED_MARKER_DO_NOT_WANT")),
                         "仓库自带 fsmonitor 被执行了——GIT_SAFE 防护失效！")

    def test_chinese_paths_detected(self):
        """中文目录/文件名不被 git 转义漏检；中文技能仓库主类型是技能包（1.1.5 修正）。"""
        repo = self.fx["chinese_paths"]
        _, cls_out = run_probe("classify_repo", repo)
        self.assertTrue(re.search(r"主类型\*\*:\s*`agent-skill-plugin`", cls_out),
                        "中文技能仓库被分错类:\n%s" % cls_out[:400])
        _, out = run_probe("content_probe", repo)
        self.assertIn("失效 1 个", out)

    def test_env_flagged_example_not(self):
        """.env 提交要标红旗；.env.example 不标。"""
        repo = self.fx["env_files"]
        _, out = run_probe("local_probe", repo)
        self.assertIn("仓库里提交了 .env 文件", out)
        self.assertNotIn("🔴 .env.example", out)
        self.assertIn(".env.example✓", out)

    def test_bom_and_crlf_frontmatter(self):
        """带 BOM 与 CRLF 的 SKILL.md 不应被误判为缺少 frontmatter（1.1.4）。"""
        _, out = run_probe("content_probe", self.fx["bom_crlf_skill"])
        self.assertNotIn("缺少 frontmatter", out)

    def test_dependency_cycles(self):
        """顶层互导记硬环 1 对；函数内延迟导回记软环 1 对。"""
        _, out = run_probe("arch_probe", self.fx["dependency_cycles"])
        self.assertIn("硬环（模块顶层互相导入）1 对", out)
        self.assertIn("掩盖的环 1 对", out)
        self.assertIn("pkg_a.core", out)
        self.assertIn("pkg_d.core", out)

    def test_src_layout_stripped(self):
        """src/<pkg>/ 布局的模块节点不带 src/ 前缀。"""
        _, out = run_probe("arch_probe", self.fx["src_layout"])
        self.assertIn("mypkg.core", out)
        self.assertNotIn("src/mypkg.core", out)

    def test_width_cjk_double(self):
        self.assertEqual(cp.width("abc"), 3)
        self.assertEqual(cp.width("ab中文"), 6)
        # 30 个汉字加权后恰好过 60 阈值；20 个汉字不过（1.1.4 修复：中文不再被误判）
        self.assertGreaterEqual(cp.width("评" * 30), 60)
        self.assertLess(cp.width("评" * 20), 60)

    def test_frontmatter_basics(self):
        fm, body = cp.frontmatter("---\nname: x\ndescription: >\n  多行\n---\n\n正文")
        self.assertEqual(fm.get("name"), "x")
        self.assertIn("多行", fm.get("description", ""))
        self.assertEqual(body.strip(), "正文")
        fm2, _ = cp.frontmatter("没有 frontmatter")
        self.assertIsNone(fm2)

    def test_single_skill_classified_as_skill(self):
        """根 SKILL.md 单技能仓库：主类型必须是技能包，不因文档占比高判成内容合集（1.1.5）。"""
        _, out = run_probe("classify_repo", self.fx["single_skill"])
        self.assertTrue(re.search(r"主类型\*\*:\s*`agent-skill-plugin`", out),
                        "单技能仓库被分错类:\n%s" % out[:500])

    def test_root_skill_name_no_dir_check(self):
        """根 SKILL.md 的 name 不与克隆目录名比对（1.1.5）。"""
        _, out = run_probe("content_probe", self.fx["single_skill"])
        self.assertNotIn("name 与目录名不一致", out)
        self.assertNotIn("缺少 frontmatter", out)

    def test_injection_word_boundary(self):
        """注入正则必须带词边界：README/category 等普通词不得误报（1.1.5）。"""
        for text in ("README and then copy .env", "see the category page", "check the blueprint"):
            self.assertFalse(any(p.search(text) for p, _ in cp.INJECTION), text)
        self.assertTrue(any(p.search("cat ~/.ssh/id_rsa") for p, _ in cp.INJECTION))

    def test_license_root_only_with_hint(self):
        """子目录 LICENSE 不冒充根许可证；检不出时提示人工核实而非判无（1.1.5）。"""
        _, out = run_probe("local_probe", self.fx["env_files"])
        self.assertIn("LICENSE✗", out)
        self.assertIn("需人工核实", out)

    def test_dep_expansion_and_lockfile(self):
        """-r 引用递归展开计入依赖数；锁文件单独报告（1.1.5）。"""
        _, out = run_probe("local_probe", self.fx["env_files"])
        self.assertIn("合计 3 个依赖", out)
        self.assertIn("锁文件: ✓ package-lock.json", out)

    def test_dev_skill_docs_still_content(self):
        """仅 .claude/skills/ 开发辅助技能的教程仓库仍判内容合集，不被技能信号压制（1.1.6 回归修复）。"""
        _, out = run_probe("classify_repo", self.fx["dev_skill_docs"])
        self.assertTrue(re.search(r"主类型\*\*:\s*`content-collection`", out),
                        "开发辅助技能误压制内容信号:\n%s" % out[:500])

    def test_dep_expansion_path_safety(self):
        """-r 引用不得越过仓库边界：../ 相对越界与绝对路径引用不读、不计入（1.1.6）。"""
        _, out = run_probe("local_probe", self.fx["env_files"])
        self.assertIn("合计 3 个依赖", out)  # 两条仓库外越界引用不计入
        self.assertNotIn("evil-outside-pkg", out)

    def test_lockfile_line_only_with_deps(self):
        """无依赖清单的仓库（纯技能包/纯文档）不再输出"锁文件 ✗"误导行（1.1.6）。"""
        _, out = run_probe("local_probe", self.fx["single_skill"])
        self.assertNotIn("锁文件", out)

    def test_pyproject_table_license(self):
        """PEP 621 表格写法 license = {text = "MIT"} 被识别为清单声明（1.1.6）。"""
        _, out = run_probe("local_probe", self.fx["dev_skill_docs"])
        self.assertIn("pyproject.toml 声明为 MIT", out)
        self.assertNotIn("清单也无声明", out)

    def test_team_handbook_still_content(self):
        """极小仓库带开发辅助技能且文档多于 SKILL.md 时判内容合集，技能保底不生效（1.1.8）。"""
        _, out = run_probe("classify_repo", self.fx["team_handbook"])
        self.assertTrue(re.search(r"主类型\*\*:\s*`content-collection`", out),
                        "开发辅助技能被保底分抬成主类型:\n%s" % out[:500])

    def test_pyproject_file_license(self):
        """pyproject 的 {file = "LICENSE"} 输出为"引用的许可证文件"，不把文件名当许可证名（1.1.8）。"""
        _, out = run_probe("local_probe", self.fx["team_handbook"])
        self.assertIn("引用的许可证文件 LICENSE", out)
        self.assertNotIn("声明为 LICENSE", out)


if __name__ == "__main__":
    unittest.main()
