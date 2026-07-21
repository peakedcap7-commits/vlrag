"""嵌入模型测试"""
import ast
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestDashScopeEmbeddings:
    """百炼 text-embedding-v3 测试"""

    def test_embed_query_dimension(self):
        """验证输出维度为 1024"""
        from src.embeddings.dashscope_emb import DashScopeEmbeddings

        emb = DashScopeEmbeddings()
        vector = emb.embed_query("黑色真皮机车夹克")
        assert len(vector) == 1024

    def test_embed_documents_batch(self):
        """验证批量嵌入"""
        from src.embeddings.dashscope_emb import DashScopeEmbeddings

        emb = DashScopeEmbeddings()
        texts = ["红色连衣裙", "蓝色牛仔裤", "白色运动鞋"]
        vectors = emb.embed_documents(texts)
        assert len(vectors) == 3
        assert all(len(v) == 1024 for v in vectors)


class TestOpenCLIP下线契约:
    """约束图片嵌入链路仅使用 Chinese-CLIP。"""

    def test_旧嵌入模块已删除(self):
        assert not (PROJECT_ROOT / "src/embeddings/openclip.py").exists()

    def test_源码有效标识不再引用旧实现(self):
        references = []
        for source_path in (PROJECT_ROOT / "src").rglob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Name, ast.Attribute)):
                    identifier = node.id if isinstance(node, ast.Name) else node.attr
                    if "openclip" in identifier.lower().replace("_", ""):
                        references.append(f"{source_path.relative_to(PROJECT_ROOT)}:{identifier}")
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    modules = [alias.name for alias in node.names]
                    if isinstance(node, ast.ImportFrom) and node.module:
                        modules.append(node.module)
                    for module in modules:
                        if "openclip" in module.lower().replace("_", ""):
                            references.append(
                                f"{source_path.relative_to(PROJECT_ROOT)}:{module}"
                            )

        assert references == [], f"仍存在旧实现引用：{references}"

    def test_图片主_collection_使用_cnclip_v1(self):
        store_path = PROJECT_ROOT / "src/vectordb/image_store.py"
        tree = ast.parse(store_path.read_text(encoding="utf-8"))
        collection_names = [
            node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "COLLECTION_NAME"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
        ]

        assert collection_names == ["products_image_cnclip_v1"]

    def test_图片库不再暴露旧自动嵌入入口(self):
        store_path = PROJECT_ROOT / "src/vectordb/image_store.py"
        tree = ast.parse(store_path.read_text(encoding="utf-8"))
        function_names = {
            node.name for node in tree.body if isinstance(node, ast.FunctionDef)
        }

        assert "ingest_images" not in function_names
        assert "image_retriever" not in function_names

    def test_项目依赖不再包含_open_clip_torch(self):
        pyproject = tomllib.loads(
            (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        dependencies = pyproject["project"]["dependencies"]

        assert not any(
            dependency.split("[")[0].split("=")[0].split(">")[0].strip().lower()
            == "open-clip-torch"
            for dependency in dependencies
        )
