from pathlib import Path

import numpy as np
import torch
from PIL import Image


class VisualUnavailableError(RuntimeError):
    pass


class LocalDinoV2Embedder:
    """Local-only DINOv2 adapter. It never downloads weights at runtime."""

    dimension = 384
    model_id = "facebook/dinov2_vits14"
    model_revision = "dinov2_vits14_pretrain"
    preprocess_version = "rgb-bicubic-224-imagenet-v1"

    def __init__(self, weights_path: Path | None = None) -> None:
        self.weights_path = weights_path
        self._model = None

    def embed(self, image_path: Path) -> np.ndarray:
        hub_root = Path(torch.hub.get_dir()) / "facebookresearch_dinov2_main"
        checkpoint = self.weights_path or (Path(torch.hub.get_dir()) / "checkpoints" / "dinov2_vits14_pretrain.pth")
        if not hub_root.is_dir() or not checkpoint.is_file():
            raise VisualUnavailableError("DINOv2本地仓库或权重未安装；视觉能力未就绪")
        if self._model is None:
            self._model = torch.hub.load(str(hub_root), "dinov2_vits14", source="local").eval()
        with Image.open(image_path) as source:
            return self.embed_image(source.convert("RGB"))

    def embed_image(self, image: Image.Image) -> np.ndarray:
        if self._model is None:
            hub_root = Path(torch.hub.get_dir()) / "facebookresearch_dinov2_main"
            checkpoint = self.weights_path or (Path(torch.hub.get_dir()) / "checkpoints" / "dinov2_vits14_pretrain.pth")
            if not hub_root.is_dir() or not checkpoint.is_file():
                raise VisualUnavailableError("DINOv2本地仓库或权重未安装；视觉能力未就绪")
            self._model = torch.hub.load(str(hub_root), "dinov2_vits14", source="local").eval()
        image = image.convert("RGB").resize((224, 224), Image.Resampling.BICUBIC)
        values = np.asarray(image, dtype=np.float32) / 255.0
        values = (values - np.array([0.485, 0.456, 0.406])) / np.array([0.229, 0.224, 0.225])
        tensor = torch.from_numpy(values.transpose(2, 0, 1)).float().unsqueeze(0)
        with torch.inference_mode():
            vector = self._model(tensor).cpu().numpy().reshape(-1).astype(np.float32)
        if vector.shape[0] != self.dimension:
            raise VisualUnavailableError("DINOv2输出维度异常，视觉能力未就绪")
        return vector / np.linalg.norm(vector)
