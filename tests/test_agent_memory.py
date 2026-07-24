import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MEMORY_DIR = ROOT / "docs" / "agent"
EXPECTED_FILES = {
    "PROJECT_STATE.md",
    "ARCHITECTURE.md",
    "DATABASE.md",
    "DECISIONS.md",
    "TASK_BOARD.md",
    "TASK_POLICY.md",
    "ACCEPTANCE.md",
}
METADATA_FIELDS = (
    "- 最后更新时间：",
    "- 对应提交：",
    "- 维护者：",
    "- 状态：",
)


class AgentMemoryTest(unittest.TestCase):
    def test_memory_files_are_complete(self):
        actual_files = {path.name for path in MEMORY_DIR.glob("*.md")}
        self.assertEqual(actual_files, EXPECTED_FILES)

    def test_each_memory_file_has_metadata(self):
        for filename in EXPECTED_FILES:
            content = (MEMORY_DIR / filename).read_text(encoding="utf-8")
            for field in METADATA_FIELDS:
                with self.subTest(filename=filename, field=field):
                    self.assertIn(field, content)

    def test_decisions_match_approved_records(self):
        content = (MEMORY_DIR / "DECISIONS.md").read_text(encoding="utf-8")
        decision_ids = set(re.findall(r"^##\s+(DEC-\d{3})\b", content, re.MULTILINE))
        self.assertEqual(
            decision_ids,
            {
                "DEC-001",
                "DEC-002",
                "DEC-003",
                "DEC-004",
                "DEC-005",
                "DEC-006",
                "DEC-007",
                "DEC-008",
            },
        )

    def test_memory_records_current_project_constraints(self):
        project_state = (MEMORY_DIR / "PROJECT_STATE.md").read_text(encoding="utf-8")
        architecture = (MEMORY_DIR / "ARCHITECTURE.md").read_text(encoding="utf-8")
        database = (MEMORY_DIR / "DATABASE.md").read_text(encoding="utf-8")

        self.assertIn("Chroma", project_state)
        self.assertIn("尚未形成正式前端目录", project_state)
        self.assertIn("232 条图切片", project_state)
        self.assertIn("neo4j_outfit_provider", architecture)
        self.assertIn("232 个 Item、40 个 Outfit、233 条关系", database)
        self.assertIn("M2", project_state)
        self.assertIn("M3", project_state)
        self.assertIn("M4 暂缓", project_state)

    def test_memory_records_completed_multi_agent_acceptance(self):
        project_state = (MEMORY_DIR / "PROJECT_STATE.md").read_text(encoding="utf-8")
        task_board = (MEMORY_DIR / "TASK_BOARD.md").read_text(encoding="utf-8")
        acceptance = (MEMORY_DIR / "ACCEPTANCE.md").read_text(encoding="utf-8")

        self.assertIn("Codex App 可见性验收：已完成", project_state)
        self.assertIn("当前阶段：已完成", task_board)
        self.assertNotIn("feat/multi-agent-setup", task_board)
        self.assertIn("019f6a96-c116-7041-8d52-14b79acf3720", acceptance)

    def test_architecture_records_current_dependency_exceptions(self):
        architecture = (MEMORY_DIR / "ARCHITECTURE.md").read_text(encoding="utf-8")

        for dependency in (
            "chatbot → llm",
            "chatbot → vectordb",
            "chatbot → Chroma",
            "retrievers → llm",
            "retrievers → embeddings",
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, architecture)
        self.assertIn("cli 与 chatbot.chain 共同承担对象组装", architecture)
        self.assertIn("chatbot.chain 与 retrievers 均直接依赖 Chroma", architecture)


if __name__ == "__main__":
    unittest.main()
