from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "AGENTS.md"


class AgentPolicyTest(unittest.TestCase):
    def test_policy_exists_with_required_sections(self) -> None:
        self.assertTrue(POLICY_PATH.is_file(), f"缺少项目规则文档：{POLICY_PATH}")
        content = POLICY_PATH.read_text(encoding="utf-8")

        required_sections = (
            "## 主 Agent",
            "## 角色调度",
            "## 分级审批",
            "## 共享记忆",
            "## 文件所有权",
            "## Git 与 Worktree",
            "## 完成定义",
        )
        for section in required_sections:
            with self.subTest(section=section):
                self.assertIn(section, content)

    def test_policy_contains_all_roles_and_development_guidelines(self) -> None:
        content = POLICY_PATH.read_text(encoding="utf-8")

        for role in (
            "architect",
            "backend",
            "frontend",
            "database",
            "tester",
            "reviewer",
            "acceptance",
            "karpathy-guidelines",
        ):
            with self.subTest(role=role):
                self.assertIn(role, content)

    def test_policy_contains_high_risk_gates(self) -> None:
        content = POLICY_PATH.read_text(encoding="utf-8")

        for phrase in ("新增顶级目录", "修改字段类型", "删除数据", "生产部署"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, content)


if __name__ == "__main__":
    unittest.main()
