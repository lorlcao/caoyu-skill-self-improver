from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import anonymous_learning_client as client  # noqa: E402


class SkillStructureTests(unittest.TestCase):
    def test_version_and_frontmatter(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "1.3.0")
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\nname: caoyu-skill-self-improver\n"))
        self.assertIn("匿名共享学习", skill.split("---", 2)[1])

    def test_markdown_relative_links_exist(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", skill)
        self.assertGreater(len(links), 0)
        for link in links:
            with self.subTest(link=link):
                self.assertFalse(Path(link).is_absolute())
                self.assertTrue((ROOT / link).is_file())

    def test_existing_safety_gates_are_preserved(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        required = (
            "自我修改双重门禁",
            "M5 备份",
            "失败回滚",
            "未经明确授权不修改技能",
            "外部输入",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_consent_notice_explicitly_names_privacy_exclusions(self) -> None:
        required = (
            "不会收集或上传",
            "聊天内容",
            "提示词",
            "账号、密码",
            "文件路径",
            "设备标识",
            "持久用户标识",
            "随时关闭",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, client.CONSENT_NOTICE)


if __name__ == "__main__":
    unittest.main()
