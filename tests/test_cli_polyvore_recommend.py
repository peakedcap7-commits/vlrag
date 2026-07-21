import ast
import importlib
import sys
import unittest
from pathlib import Path


# 让本文件既可以 `python -m unittest` 运行，也可以直接 `python tests/...` 运行
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def import_required(module_name):
    """把待实现模块缺失报告为预期的契约失败。"""
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise AssertionError(f"缺少待实现模块：{module_name}") from exc


def _read_cli_ast():
    """读取 cli_polyvore_recommend.py 源码并解析为 AST。"""
    project_root = Path(__file__).resolve().parents[1]
    cli_path = project_root / "src" / "cli_polyvore_recommend.py"
    return ast.parse(cli_path.read_text(encoding="utf-8"))


def _find_main_function(tree):
    """在模块顶层定位 main 函数定义。"""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("cli_polyvore_recommend.py 未找到 main 函数定义")


def _collect_add_argument_calls(function_node):
    """收集 main 内所有 add_argument 调用，以第一个位置参数(如 --sample)为键。"""
    calls = {}
    for node in ast.walk(function_node):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # 形如 parser.add_argument("--flag", ...)
        if not (isinstance(func, ast.Attribute) and func.attr == "add_argument"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            calls[first.value] = node
    return calls


def _extract_default_keyword(call_node, flag_name):
    """从 add_argument 调用中提取 default 关键字参数节点。"""
    for kw in call_node.keywords:
        if kw.arg == "default":
            return kw.value
    raise AssertionError(f"{flag_name} 未显式提供 default 关键字参数")


class CliPolyvoreRecommendDefaultsTest(unittest.TestCase):
    """回归保护：--sample 与 --enriched 的默认值必须来自 PolyvoreRecommendConfig 实例字段。"""

    def test_defaults_变量必须由_PolyvoreRecommendConfig_实例化(self):
        """防止有人把 defaults 改成其它来源而默认值恰好相等。"""
        tree = _read_cli_ast()
        main_func = _find_main_function(tree)

        for node in main_func.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not (isinstance(target, ast.Name) and target.id == "defaults"):
                    continue
                call = node.value
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "PolyvoreRecommendConfig"
                ):
                    return
        raise AssertionError("main 内未找到 defaults = PolyvoreRecommendConfig() 赋值")

    def test_sample_默认值必须引用_defaults_sample_path(self):
        """--sample 的 default 必须是 defaults.sample_path 属性引用。"""
        tree = _read_cli_ast()
        main_func = _find_main_function(tree)
        calls = _collect_add_argument_calls(main_func)

        self.assertIn("--sample", calls, "main 内未找到 --sample 参数定义")
        default_value = _extract_default_keyword(calls["--sample"], "--sample")

        # 必须是属性访问节点，不得是字面量常量或其它表达式
        self.assertIsInstance(
            default_value,
            ast.Attribute,
            "--sample 的 default 必须引用 defaults.sample_path，不得使用独立字面量常量",
        )
        self.assertIsInstance(
            default_value.value,
            ast.Name,
            "--sample 的 default 必须引用名为 defaults 的变量",
        )
        self.assertEqual(default_value.value.id, "defaults")
        self.assertEqual(default_value.attr, "sample_path")

    def test_enriched_默认值必须引用_defaults_enriched_path(self):
        """--enriched 的 default 必须是 defaults.enriched_path 属性引用。"""
        tree = _read_cli_ast()
        main_func = _find_main_function(tree)
        calls = _collect_add_argument_calls(main_func)

        self.assertIn("--enriched", calls, "main 内未找到 --enriched 参数定义")
        default_value = _extract_default_keyword(calls["--enriched"], "--enriched")

        self.assertIsInstance(
            default_value,
            ast.Attribute,
            "--enriched 的 default 必须引用 defaults.enriched_path，不得使用独立字面量常量",
        )
        self.assertIsInstance(
            default_value.value,
            ast.Name,
            "--enriched 的 default 必须引用名为 defaults 的变量",
        )
        self.assertEqual(default_value.value.id, "defaults")
        self.assertEqual(default_value.attr, "enriched_path")

    def test_运行时_默认路径字段与_PolyvoreRecommendConfig_一致(self):
        """补足静态断言：验证 PolyvoreRecommendConfig 实际承载期望路径。"""
        service_module = import_required("src.polyvore_recommend_service")
        config = service_module.PolyvoreRecommendConfig()

        self.assertEqual(
            config.sample_path,
            Path("data/processed/polyvore_items_sample.jsonl"),
        )
        self.assertEqual(
            config.enriched_path,
            Path("data/processed/polyvore_items_enriched_sample.jsonl"),
        )


if __name__ == "__main__":
    unittest.main()
