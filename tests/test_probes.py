#!/usr/bin/env python3
"""探针脚本自动化测试（T01）：夹具驱动的集成测试 + 纯函数单测。

运行：python -m unittest discover -s tests -v
夹具由 tools/make_fixtures.py 在临时目录生成；Windows 无符号链接特权时
symlink 样本自动 skip。全部只用标准库，Python 3.8+。
"""
import os
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
        """中文目录/文件名不被 git 转义漏检，失效链接精确计数。"""
        repo = self.fx["chinese_paths"]
        _, cls_out = run_probe("classify_repo", repo)
        self.assertIn("content-collection", cls_out)
        self.assertIn("agent-skill-plugin", cls_out)
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


if __name__ == "__main__":
    unittest.main()
