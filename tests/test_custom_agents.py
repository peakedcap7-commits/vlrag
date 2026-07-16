from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / ".codex" / "agents"
SKILL_PATH = "C:/Users/Administrator/.agents/skills/karpathy-guidelines/SKILL.md"
EXPECTED_SANDBOXES = {
    "architect": "workspace-write",
    "backend": "workspace-write",
    "frontend": "workspace-write",
    "database": "workspace-write",
    "tester": "workspace-write",
    "reviewer": "read-only",
    "acceptance": "read-only",
}


def load_agent(name: str) -> dict:
    with (AGENT_DIR / f"{name}.toml").open("rb") as config_file:
        return tomllib.load(config_file)


class CustomAgentsTest(unittest.TestCase):
    def test_agent_files_are_complete(self) -> None:
        actual_files = {path.stem for path in AGENT_DIR.glob("*.toml")}
        self.assertEqual(actual_files, set(EXPECTED_SANDBOXES))

    def test_agent_identity_and_instructions_are_present(self) -> None:
        for name in EXPECTED_SANDBOXES:
            with self.subTest(agent=name):
                config = load_agent(name)
                self.assertEqual(config["name"], name)
                self.assertTrue(config["description"].strip())
                self.assertTrue(config["developer_instructions"].strip())

    def test_agent_sandbox_modes_are_correct(self) -> None:
        for name, expected_sandbox in EXPECTED_SANDBOXES.items():
            with self.subTest(agent=name):
                self.assertEqual(load_agent(name)["sandbox_mode"], expected_sandbox)

    def test_backend_and_frontend_enable_karpathy_guidelines(self) -> None:
        self.assertTrue(Path(SKILL_PATH).is_file(), f"缺少开发规范：{SKILL_PATH}")

        for name in ("backend", "frontend"):
            with self.subTest(agent=name):
                config = load_agent(name)
                skill_configs = config["skills"]["config"]
                self.assertTrue(
                    any(
                        skill["path"] == SKILL_PATH and skill["enabled"] is True
                        for skill in skill_configs
                    )
                )
                self.assertIn("karpathy-guidelines", config["developer_instructions"])

    def test_read_only_agents_forbid_modifications(self) -> None:
        for name in ("reviewer", "acceptance"):
            with self.subTest(agent=name):
                self.assertIn("不得修改", load_agent(name)["developer_instructions"])


if __name__ == "__main__":
    unittest.main()
