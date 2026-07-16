"""商品关系类型枚举"""
from enum import Enum


class RelationType(Enum):
    """图数据库中的边关系类型"""
    搭配 = "搭配"            # LLM 抽取 / Polyvore 数据集
    可替代 = "可替代"        # Amazon also_viewed
    常一起买 = "常一起买"    # Amazon also_bought
    同款 = "同款"            # 向量相似度 > 0.95 的不同平台同款
    同品牌 = "同品牌"
    同风格 = "同风格"
    同品类 = "同品类"
    被对比 = "被对比"        # 什么值得买评测文章
