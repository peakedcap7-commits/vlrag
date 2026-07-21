from io import BytesIO
from pathlib import Path

import torch
import torch.nn.functional as functional
from PIL import Image
from transformers import ChineseCLIPModel, ChineseCLIPProcessor

from src.config import CHINESE_CLIP_EMBEDDING_DIM, CHINESE_CLIP_MODEL


MODEL_NAME = CHINESE_CLIP_MODEL
EMBEDDING_DIM = CHINESE_CLIP_EMBEDDING_DIM


def _detect_device():
    """按 CUDA、MPS、CPU 顺序选择运行设备。"""
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class ChineseCLIPEmbeddings:
    """Chinese-CLIP 文本与图片嵌入适配器。"""

    def __init__(self, model_name=MODEL_NAME, device=None):
        self.device = device or _detect_device()
        self.processor = ChineseCLIPProcessor.from_pretrained(model_name)
        self.model = ChineseCLIPModel.from_pretrained(model_name)
        self.model = self.model.to(self.device)
        self.model.eval()

    def _move_inputs(self, inputs):
        return {
            name: value.to(self.device)
            for name, value in inputs.items()
        }

    def _to_vector(self, features):
        features = functional.normalize(features, p=2, dim=-1)
        return features.squeeze(0).detach().cpu().tolist()

    def embed_query(self, text):
        """将中文查询编码为 512 维归一化向量。"""
        inputs = self.processor(
            text=[text], return_tensors="pt", padding=True
        )
        with torch.no_grad():
            features = self.model.get_text_features(
                **self._move_inputs(inputs)
            )
        return self._to_vector(features)

    def embed_image(self, image):
        """将图片字节或本地路径编码为 512 维归一化向量。"""
        if isinstance(image, (bytes, bytearray)):
            source = BytesIO(image)
        else:
            source = Path(image)
        with Image.open(source) as opened_image:
            rgb_image = opened_image.convert("RGB")
        inputs = self.processor(images=rgb_image, return_tensors="pt")
        with torch.no_grad():
            features = self.model.get_image_features(
                **self._move_inputs(inputs)
            )
        return self._to_vector(features)
