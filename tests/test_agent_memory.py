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

    def test_decisions_include_initial_records(self):
        content = (MEMORY_DIR / "DECISIONS.md").read_text(encoding="utf-8")
        for decision_id in ("DEC-001", "DEC-002", "DEC-003", "DEC-004"):
            with self.subTest(decision_id=decision_id):
                self.assertIn(decision_id, content)

    def test_project_state_records_current_constraints(self):
        content = (MEMORY_DIR / "PROJECT_STATE.md").read_text(encoding="utf-8")
        for expected_text in ("Chroma", "Neo4j", "尚未形成正式前端目录"):
            with self.subTest(expected_text=expected_text):
                self.assertIn(expected_text, content)


if __name__ == "__main__":
    unittest.main()
