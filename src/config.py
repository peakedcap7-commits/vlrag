# ShoppingQnA 多模态 RAG 购物助手 - 百炼平台版

import os
from dotenv import load_dotenv

load_dotenv()

# ===== 百炼 API 配置 =====
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# ===== 百炼模型名称 =====
QWEN_VL_MAX = "qwen-vl-max"              # 多模态视觉理解（替代 GPT-4o）
QWEN_MAX = "qwen-max"                    # 最强文本对话
QWEN_TURBO = "qwen-turbo"                # 轻量文本（替代 GPT-4o-mini）
TEXT_EMBEDDING_V3 = "text-embedding-v3"  # 文本嵌入（替代 Ada-002）

# ===== OpenCLIP 配置（本地，不变） =====
CLIP_MODEL = "ViT-B-32"
CLIP_CHECKPOINT = "metaclip_fullcc"

# ===== 检索配置 =====
RETRIEVER_K = 5
RERANK_TOP_K = 5
CHROMA_PERSIST_DIR = "./chroma_data"

# ===== 数据配置 =====
DATASET_NAME = "hahminlew/kream-product-blip-captions"
SAMPLE_SIZE = 200
BATCH_SIZE = 10
BATCH_INTERVAL = 0.6  # API 限流间隔（秒）

# ===== 评估配置 =====
EVAL_QUERY_COUNT = 20  # 人工标注测试查询数
HIT_RATE_TARGET = 0.6
MRR_TARGET = 0.4
