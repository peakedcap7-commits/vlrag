"""检索器数据模型 —— ItemWrapper"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ItemWrapper:
    """商品包装器，统一检索结果格式"""
    product_id: int | str
    name: str
    type: str
    description: str = ""
    image_summary: str = ""
    summary: str = ""
    tags: List[str] = field(default_factory=list)
    image_path: Optional[str] = None
    score: float = 0.0
    source: str = ""  # 检索来源: "image" / "text" / "hybrid"

    def to_context(self) -> str:
        """格式化为 Prompt 可用的上下文字符串"""
        return (
            f"[{self.product_id}] {self.name}\n"
            f"类型: {self.type}\n"
            f"描述: {self.description}\n"
            f"标签: {', '.join(self.tags)}\n"
            f"相似度: {self.score:.4f}"
        )


def fetch_products(
    product_ids: List[int | str],
    products: List[dict],
) -> List[ItemWrapper]:
    """按 item_id 或旧列表索引获取完整商品信息。"""
    products_by_item_id = {
        str(product["item_id"]): product
        for product in products
        if product.get("item_id") is not None
    }
    results = []
    for pid in product_ids:
        product = products_by_item_id.get(str(pid))
        if product is None and isinstance(pid, int) and 0 <= pid < len(products):
            product = products[pid]
        if product is None:
            continue
        product_id = product.get("item_id", pid)
        retrieval_text = product.get("retrieval_text", "")
        tags = product.get("tags") or [
            *product.get("colors", []),
            *product.get("style", []),
        ]
        results.append(ItemWrapper(
            product_id=str(product_id) if product.get("item_id") is not None else product_id,
            name=product.get("name") or retrieval_text,
            type=(
                product.get("type")
                or product.get("sub_category")
                or product.get("category", "")
            ),
            description=product.get("description") or retrieval_text,
            image_summary=product.get("image_summary", ""),
            summary=product.get("summary", ""),
            tags=tags,
            image_path=product.get("image_path"),
        ))
    return results
