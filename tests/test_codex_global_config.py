from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".codex" / "config.toml"


class CodexGlobalConfigTest(unittest.TestCase):
    def test_agent_limits_are_safe(self) -> None:
        self.assertTrue(CONFIG_PATH.is_file(), f"缺少 Codex 全局配置：{CONFIG_PATH}")

        with CONFIG_PATH.open("rb") as config_file:
            config = tomllib.load(config_file)

        agents = config["agents"]
        self.assertEqual(agents["max_threads"], 4)
        self.assertEqual(agents["max_depth"], 1)
        self.assertIs(agents["interrupt_message"], True)


if __name__ == "__main__":
    unittest.main()
