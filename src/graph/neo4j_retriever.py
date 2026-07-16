"""Neo4j 图检索器 —— TODO: 二期实现"""
from src.graph.base import GraphRetriever, ProductNode


class Neo4jRetriever(GraphRetriever):
    """
    Neo4j 图数据库检索器。
    TODO: 接入 Neo4j 后实现以下方法。
    Schema 参考:
        (:Product)-[:搭配 {confidence, source}]->(:Product)
        (:Product)-[:常一起买 {weight, source}]->(:Product)
        (:Product)-[:属于品牌]->(:Brand)
        (:Product)-[:属于品类]->(:Category)-[:父类]->(:Category)
        (:Product)-[:属于风格]->(:Style)
    """
    def retrieve_by_product(self, product_ids, relations=None, top_k=5):
        raise NotImplementedError("Neo4j 检索器尚未实现，请使用 DummyGraphRetriever")

    def retrieve_by_category(self, category, top_k=5):
        raise NotImplementedError("Neo4j 检索器尚未实现，请使用 DummyGraphRetriever")

    def retrieve_by_style(self, style, top_k=5):
        raise NotImplementedError("Neo4j 检索器尚未实现，请使用 DummyGraphRetriever")
