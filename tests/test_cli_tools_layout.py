import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOL_MODULES = (
    "cli_cnclip_index.py",
    "cli_polyvore_recommend.py",
    "cli_polyvore_retrieval.py",
    "cli_polyvore_text_index.py",
    "cli_polyvore_neo4j_import.py",
    "cli_polyvore_neo4j_chroma_index.py",
)


class CliToolsLayoutTest(unittest.TestCase):
    def test_开发工具只存在于_tools目录(self):
        for filename in TOOL_MODULES:
            self.assertTrue((PROJECT_ROOT / "tools" / filename).is_file())
            self.assertFalse((PROJECT_ROOT / "src" / filename).exists())

    def test_正式交互_cli_仍保留在_src(self):
        self.assertTrue((PROJECT_ROOT / "src" / "cli.py").is_file())

    def test_src_生产代码不依赖_tools(self):
        for path in (PROJECT_ROOT / "src").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported = [node.module or ""]
                else:
                    continue
                self.assertFalse(
                    any(name == "tools" or name.startswith("tools.") for name in imported),
                    f"生产模块不得依赖 tools：{path}",
                )

    def test_fastapi_启动链路不依赖_tools或_cli(self):
        app_path = PROJECT_ROOT / "src" / "api" / "app.py"
        source = app_path.read_text(encoding="utf-8")
        self.assertNotIn("tools", source)
        self.assertNotIn("cli_", source)
        self.assertIn("src.polyvore_recommend_service", source)


if __name__ == "__main__":
    unittest.main()
