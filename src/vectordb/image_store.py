"""Chinese-CLIP 图片向量库只读加载入口。"""

from langchain_chroma import Chroma

from src.config import CHROMA_PERSIST_DIR

COLLECTION_NAME = "products_image_cnclip_v1"


def build_image_store(
    persist_dir: str = CHROMA_PERSIST_DIR,
) -> Chroma:
    """加载显式向量写入的 Chinese-CLIP collection。"""
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=None,
        persist_directory=persist_dir,
    )


def load_image_store(persist_dir: str = CHROMA_PERSIST_DIR) -> Chroma:
    """加载已有 Chinese-CLIP 图片向量库。"""
    return build_image_store(persist_dir)
