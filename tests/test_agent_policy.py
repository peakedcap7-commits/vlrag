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

    def test_policy_contains_critical_operating_rules(self) -> None:
        content = POLICY_PATH.read_text(encoding="utf-8")

        for phrase in (
            "主 Agent 是唯一调度入口",
            "主 Agent 同时最多调度三个专业 Agent",
            "专业 Agent 不得继续派生子 Agent",
            "必须先由 architect 评审，再由用户批准",
            "必须先由 database 评审，再由用户批准",
            "必须单独获得用户明确批准",
            "同一文件同一时间只能有一个写入所有者",
            "reviewer 和 acceptance 只读",
            "多个写密集任务仅在文件所有权清晰且使用独立 Worktree 时并行",
            "P0 和 P1 阻止合并",
            "未通过必要测试、审查和验收时不得宣布完成",
            "新增顶级目录",
            "修改字段类型",
            "删除数据",
            "生产部署",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, content)


if __name__ == "__main__":
    unittest.main()
