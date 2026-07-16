"""product_image_db —— 图片向量库（Chroma + OpenCLIP），存路径不存图片"""
from typing import List

from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.config import CHROMA_PERSIST_DIR, RETRIEVER_K
from src.embeddings.openclip import OpenCLIPEmbeddings

COLLECTION_NAME = "products_image"


def build_image_store(
    persist_dir: str = CHROMA_PERSIST_DIR,
) -> Chroma:
    """构建图片向量库实例"""
    embeddings = OpenCLIPEmbeddings()
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=persist_dir,
    )


def ingest_images(
    products: List[dict],
    persist_dir: str = CHROMA_PERSIST_DIR,
):
    """
    将商品图片路径写入 Chroma。
    每条 Document：
    - page_content: 图片文件路径（如 data/raw/images/product_0.jpg）
    - metadata: product_id, type, name
    - id: product_{index}

    嵌入时 OpenCLIPEmbeddings.embed_documents 自动检测路径 → 从磁盘读图编码。
    """
    embeddings = OpenCLIPEmbeddings()
    docs = []
    for i, p in enumerate(products):
        image_path = p.get("image_path", "")
        if not image_path:
            continue
        docs.append(Document(
            page_content=image_path,
            metadata={
                "product_id": i,
                "type": p.get("type", ""),
                "name": p.get("name", ""),
                "tags": ", ".join(p.get("tags", [])),
            },
            id=f"product_{i}",
        ))

    db = Chroma.from_documents(
        documents=docs,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=persist_dir,
    )
    print(f"图片向量库写入完成: {len(docs)} 条 → {COLLECTION_NAME}")
    return db


def load_image_store(persist_dir: str = CHROMA_PERSIST_DIR) -> Chroma:
    """加载已有图片向量库"""
    return build_image_store(persist_dir)


def image_retriever(db: Chroma, k: int = RETRIEVER_K):
    """图片向量库检索器"""
    return db.as_retriever(search_kwargs={"k": k})
