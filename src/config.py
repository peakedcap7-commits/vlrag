# ShoppingQnA 多模态 RAG 购物助手 - 百炼平台版

import os
from dotenv import load_dotenv

load_dotenv()


def _parse_bool_env(name, default="false"):
    """严格解析布尔环境变量。"""
    value = os.getenv(name, default).strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"{name} 必须为 true 或 false")


# ===== 百炼 API 配置 =====
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# ===== 百炼模型名称 =====
QWEN_VL_MAX = "qwen-vl-max"              # 多模态视觉理解（替代 GPT-4o）
QWEN_MAX = "qwen-max"                    # 最强文本对话
QWEN_TURBO = "qwen-turbo"                # 轻量文本（替代 GPT-4o-mini）
TEXT_EMBEDDING_V3 = "text-embedding-v3"  # 文本嵌入（替代 Ada-002）

# ===== Chinese-CLIP 配置（本地） =====
CHINESE_CLIP_MODEL = os.getenv(
    "CHINESE_CLIP_MODEL",
    "OFA-Sys/chinese-clip-vit-base-patch16",
)
CHINESE_CLIP_EMBEDDING_DIM = 512
ENABLE_MODEL_WARMUP = _parse_bool_env("ENABLE_MODEL_WARMUP")

# ===== 检索配置 =====
RETRIEVER_K = 5
RERANK_TOP_K = 5
CHROMA_PERSIST_DIR = "./chroma_data"

# ===== MinIO 配置 =====
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_SECURE = _parse_bool_env("MINIO_SECURE")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "shopping-qna")

# ===== Neo4j Outfit 图配置 =====
OUTFIT_PROVIDER = os.getenv("OUTFIT_PROVIDER", "neo4j").strip().lower()
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

# ===== 数据配置 =====
DATASET_NAME = "hahminlew/kream-product-blip-captions"
SAMPLE_SIZE = 200
BATCH_SIZE = 10
BATCH_INTERVAL = 0.6  # API 限流间隔（秒）

# ===== 评估配置 =====
EVAL_QUERY_COUNT = 20  # 人工标注测试查询数
HIT_RATE_TARGET = 0.6
MRR_TARGET = 0.4
