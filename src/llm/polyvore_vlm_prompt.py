from langchain_core.prompts import ChatPromptTemplate


POLYVORE_VLM_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是专业的时尚商品视觉分析助手。metadata 仅用于辅助，"
            "冲突以图片可见内容为准。禁止编造品牌，禁止编造价格，"
            "禁止编造性别，禁止编造人群，禁止编造不可见材质，"
            "禁止编造防水，禁止编造防风，禁止编造透气，"
            "禁止编造保暖，禁止编造速干，禁止编造抗皱。",
        ),
        (
            "human",
            """请分析图片，并结合以下 metadata：
item_id: {item_id}
url_name: {url_name}
semantic_category: {semantic_category}
category_name: {category_name}
bucket: {bucket}
object_key: {object_key}

只返回符合以下 schema 的 JSON，不要返回其他文字：
{{
  "item_id": "{item_id}",
  "category": "商品大类",
  "sub_category": "商品细分类",
  "colors": ["颜色"],
  "material": "",
  "style": ["风格"],
  "details": ["可见细节"],
  "scene": ["适用场景"],
  "retrieval_text": "中文商品检索描述",
  "confidence": 0.0,
  "uncertain_fields": ["material"]
}}

material 必须固定为空字符串，uncertain_fields 必须包含 material。
retrieval_text 使用中文自然语言，用于中文向量检索；retrieval_text 禁止包含材质成分断言。""",
        ),
    ]
)


def build_polyvore_vlm_prompt(metadata):
    """注入商品元数据并生成 VLM 提示词。"""
    return POLYVORE_VLM_PROMPT.format(**metadata)
