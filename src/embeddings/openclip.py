"""OpenCLIPEmbeddings —— 支持图片路径(磁盘) + base64(用户查询) 双模式"""
import base64
from io import BytesIO
from pathlib import Path
from typing import List

import torch
from PIL import Image

from src.config import CLIP_MODEL, CLIP_CHECKPOINT

# 图片文件扩展名
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _detect_device() -> str:
    """自动检测可用设备: CUDA > MPS > CPU"""
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _is_image_path(text: str) -> bool:
    """判断字符串是否为图片文件路径"""
    return Path(text).suffix.lower() in _IMAGE_EXTENSIONS


class OpenCLIPEmbeddings:
    """
    OpenCLIP 嵌入适配器。不继承 Pydantic/LangChain Embeddings 基类，
    避免 Pydantic v1/v2 兼容问题。直接提供 Chroma 需要的接口。

    embed_documents():
      - 传入图片路径 → 从磁盘加载图片 → 图片编码器 → 512维向量
      - 传入文本(中文) → qwen-turbo 翻译 → 文本编码器 → 512维向量

    embed_image_from_base64():
      - 用户上传图片(base64) → 图片编码器 → 512维向量（查询专用）
    """

    def __init__(
        self,
        model_name: str = CLIP_MODEL,
        checkpoint: str = CLIP_CHECKPOINT,
        device: str | None = None,
    ):
        self.model_name = model_name
        self.checkpoint = checkpoint
        self.device = device or _detect_device()
        self._model = None
        self._preprocess = None
        self._tokenizer = None
        self._lazy_load()

    def _lazy_load(self):
        """加载 OpenCLIP 模型，仅首次调用时执行"""
        if self._model is not None:
            return

        import open_clip

        self._model, self._preprocess, _ = (
            open_clip.create_model_and_transforms(
                self.model_name, pretrained=self.checkpoint
            )
        )
        self._tokenizer = open_clip.get_tokenizer(self.model_name)
        self._model = self._model.to(self.device)
        self._model.eval()

    def _pil_to_tensor(self, image: Image.Image):
        """PIL Image → 预处理 → tensor"""
        if image.mode != "RGB":
            image = image.convert("RGB")
        return self._preprocess(image).unsqueeze(0).to(self.device)

    # ---- 图片编码 ----

    def embed_image_from_path(self, image_path: str) -> List[float]:
        """从磁盘路径加载图片 → 向量"""
        self._lazy_load()
        image = Image.open(image_path).convert("RGB")
        tensor = self._pil_to_tensor(image)

        import open_clip

        with torch.no_grad():
            features = self._model.encode_image(tensor)
            features /= features.norm(dim=-1, keepdim=True)

        return features.cpu().numpy().flatten().tolist()

    def embed_image_from_base64(self, img_b64: str) -> List[float]:
        """用户上传 base64 图片 → 向量（查询用）"""
        self._lazy_load()
        img_data = base64.b64decode(img_b64)
        image = Image.open(BytesIO(img_data)).convert("RGB")
        tensor = self._pil_to_tensor(image)

        import open_clip

        with torch.no_grad():
            features = self._model.encode_image(tensor)
            features /= features.norm(dim=-1, keepdim=True)

        return features.cpu().numpy().flatten().tolist()

    def embed_images_from_paths(self, paths: List[str]) -> List[List[float]]:
        """批量磁盘图片路径 → 向量"""
        return [self.embed_image_from_path(p) for p in paths]

    # ---- 文本编码 ----

    def _encode_texts(self, texts: List[str]) -> List[List[float]]:
        """文本 → 向量，OpenCLIP 文本编码器"""
        self._lazy_load()

        import open_clip
        tokens = self._tokenizer(texts, context_length=77).to(self.device)
        with torch.no_grad():
            features = self._model.encode_text(tokens)
            features /= features.norm(dim=-1, keepdim=True)
        return features.cpu().numpy().tolist()

    # ---- Chroma 需要的接口 ----

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        自动分流：图片路径 → 图片编码器 / 文本 → 文本编码器。
        """
        image_paths = []
        image_indices = []
        text_parts = []
        text_indices = []

        for i, t in enumerate(texts):
            if _is_image_path(t):
                image_paths.append(t)
                image_indices.append(i)
            else:
                text_parts.append(t)
                text_indices.append(i)

        results = [None] * len(texts)

        if image_paths:
            for idx, path in zip(image_indices, image_paths):
                results[idx] = self.embed_image_from_path(path)

        if text_parts:
            text_vectors = self._encode_texts(text_parts)
            for idx, vec in zip(text_indices, text_vectors):
                results[idx] = vec

        return results

    def embed_query(self, text: str) -> List[float]:
        """单条查询 → 向量（文本）"""
        return self._encode_texts([text])[0]
