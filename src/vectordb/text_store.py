"""product_text_db —— 文本向量库（Chroma + 百炼 text-embedding-v3）"""
from typing import List

from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.config import CHROMA_PERSIST_DIR, RETRIEVER_K
from src.embeddings.dashscope_emb import DashScopeEmbeddings

COLLECTION_NAME = "products_text"


def build_text_store(
    persist_dir: str = CHROMA_PERSIST_DIR,
) -> Chroma:
    """构建文本向量库实例"""
    embeddings = DashScopeEmbeddings()
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=persist_dir,
    )


def _build_text_documents(products: List[dict]) -> List[Document]:
    """
    构建文本 Document 列表。
    每个商品产生 3 条 Document（description / image_summary / summary）。
    """
    docs = []
    for i, p in enumerate(products):
        for field in ("description", "image_summary", "summary"):
            content = p.get(field, "")
            if not content:
                continue
            docs.append(Document(
                page_content=content,
                metadata={
                    "product_id": i,
                    "field": field,
                    "type": p.get("type", ""),
                    "name": p.get("name", ""),
                    "tags": ", ".join(p.get("tags", [])),
                },
                id=f"product_{i}_{field}",
            ))
    return docs


def ingest_texts(
    products: List[dict],
    persist_dir: str = CHROMA_PERSIST_DIR,
):
    """
    将商品文本写入 Chroma。
    每个商品 3 条 Document（~600 条）。
    """
    embeddings = DashScopeEmbeddings()
    docs = _build_text_documents(products)

    db = Chroma.from_documents(
        documents=docs,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=persist_dir,
    )
    print(f"文本向量库写入完成: {len(docs)} 条 → {COLLECTION_NAME}")
    return db


def load_text_store(persist_dir: str = CHROMA_PERSIST_DIR) -> Chroma:
    """加载已有文本向量库"""
    return build_text_store(persist_dir)


def text_retriever(db: Chroma, k: int = RETRIEVER_K):
    """文本向量库检索器"""
    return db.as_retriever(search_kwargs={"k": k})
