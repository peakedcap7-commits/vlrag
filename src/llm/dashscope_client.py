"""百炼 DashScope SDK 封装 —— 多模态调用 & 纯文本对话（同步+异步）"""
import asyncio
import base64
from io import BytesIO
from typing import Optional

import dashscope
from dashscope import MultiModalConversation
from langchain_openai import ChatOpenAI
from PIL import Image

from src.config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_URL,
    QWEN_VL_MAX,
    QWEN_MAX,
)

# 设置全局 API Key
dashscope.api_key = DASHSCOPE_API_KEY


def _b64_encode(image: Image.Image, fmt: str = "JPEG") -> str:
    """PIL Image 转 base64 字符串"""
    buffered = BytesIO()
    image.save(buffered, format=fmt)
    return base64.b64encode(buffered.getvalue()).decode()


# === 同步 API（单次调用用） ===

def describe_image(
    image: Image.Image,
    prompt: str = "请用中文详细描述这件时尚单品的款式、颜色、材质和风格",
    model: str = QWEN_VL_MAX,
) -> str:
    """多模态图片理解 —— DashScope 原生 SDK"""
    img_b64 = _b64_encode(image)
    messages = [{
        "role": "user",
        "content": [
            {"image": f"data:image/jpeg;base64,{img_b64}"},
            {"text": prompt},
        ],
    }]
    resp = MultiModalConversation.call(model=model, messages=messages)
    return resp.output.choices[0].message.content[0]["text"]


def describe_image_b64(
    img_b64: str,
    prompt: str = "请用中文详细描述这件时尚单品的款式、颜色、材质和风格",
    model: str = QWEN_VL_MAX,
) -> str:
    """多模态图片理解 —— 接受已编码的 base64 字符串"""
    messages = [{
        "role": "user",
        "content": [
            {"image": f"data:image/jpeg;base64,{img_b64}"},
            {"text": prompt},
        ],
    }]
    resp = MultiModalConversation.call(model=model, messages=messages)
    return resp.output.choices[0].message.content[0]["text"]


def build_chat_llm(
    model: str = QWEN_MAX,
    temperature: float = 0.7,
) -> ChatOpenAI:
    """纯文本对话 LLM —— OpenAI 兼容模式"""
    return ChatOpenAI(
        model=model,
        base_url=DASHSCOPE_BASE_URL,
        api_key=DASHSCOPE_API_KEY,
        temperature=temperature,
    )


# === 异步 API（批量并发用） ===

async def describe_image_async(
    image: Image.Image,
    prompt: str = "请用中文详细描述这件时尚单品的款式、颜色、材质和风格",
    model: str = QWEN_VL_MAX,
) -> str:
    """异步版图片理解 —— 在线程池中执行同步 API"""
    return await asyncio.to_thread(describe_image, image, prompt, model)


async def chat_async(
    llm: ChatOpenAI,
    prompt: str,
) -> str:
    """异步版 Chat —— 在线程池中执行同步 API"""
    resp = await asyncio.to_thread(llm.invoke, prompt)
    return resp.content.strip()
