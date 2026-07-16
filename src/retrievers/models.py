"""检索器数据模型 —— ItemWrapper"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ItemWrapper:
    """商品包装器，统一检索结果格式"""
    product_id: int
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
    product_ids: List[int],
    products: List[dict],
) -> List[ItemWrapper]:
    """根据 product_id 列表获取完整商品信息"""
    results = []
    for pid in product_ids:
        if 0 <= pid < len(products):
            p = products[pid]
            results.append(ItemWrapper(
                product_id=pid,
                name=p.get("name", ""),
                type=p.get("type", ""),
                description=p.get("description", ""),
                image_summary=p.get("image_summary", ""),
                summary=p.get("summary", ""),
                tags=p.get("tags", []),
                image_path=p.get("image_path"),
            ))
    return results
