"""
Lightweight reusable CLIP service for GPU ranking and embedding.

- Loads the CLIP model once per process (singleton)
- Supports CUDA and Apple MPS; falls back to CPU
- Ranks candidate images (thumbnails) against product text descriptions
"""

from __future__ import annotations

import io
import threading
import logging
from typing import Dict, List, Optional, Tuple

import torch
from PIL import Image
import clip


_singleton_lock = threading.Lock()
_singleton_instance: Optional["CLIPService"] = None


class CLIPService:
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.device = self._select_device()
        self.model_name = (self.config.get('clip', {}) or {}).get('model', 'ViT-B/32')
        self.model, self.preprocess = clip.load(self.model_name, device=self.device)

        # Use fast dtypes where safe
        self.use_fp16 = self.device.type == 'cuda'
        if self.use_fp16:
            try:
                self.model = self.model.half()  # type: ignore[attr-defined]
                torch.backends.cuda.matmul.allow_tf32 = True  # type: ignore[attr-defined]
            except Exception:
                self.use_fp16 = False

        logging.getLogger(__name__).info(
            f"CLIPService initialized: model={self.model_name}, device={self.device.type}, fp16={self.use_fp16}"
        )

        self._text_cache: Dict[str, torch.Tensor] = {}

    def _select_device(self) -> torch.device:
        prefer = (self.config.get('clip', {}) or {}).get('device_preference', ["cuda", "mps"])  # type: ignore[assignment]
        if "cuda" in prefer and torch.cuda.is_available():
            return torch.device("cuda")
        if "mps" in prefer and getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")

    def _build_descriptions(self, product: Dict) -> List[str]:
        brand = product.get('Brand', '')
        title = product.get('Title', '')
        variant = product.get('Variant_Title', '') or product.get('Variant option', '') or ''

        descriptions: List[str] = []
        if brand or title:
            descriptions.append(f"A product photo of {brand} {title}")
        if brand and variant:
            descriptions.append(f"A package of {brand} {variant}")

        # Extract size (simple heuristic)
        import re
        size_match = re.search(r"(\d+(?:\.\d+)?)\s*(g|kg|ml|l|L)", f"{title} {variant}")
        if size_match:
            size = size_match.group(0)
            descriptions.append(f"A {size} pack of {brand} {title or variant}")

        if not descriptions:
            descriptions.append(title or brand or "product packshot")
        return descriptions

    def _encode_texts(self, descriptions: List[str]) -> torch.Tensor:
        cache_key = " || ".join(descriptions)
        if cache_key in self._text_cache:
            return self._text_cache[cache_key]

        with torch.no_grad():
            tokens = clip.tokenize(descriptions, truncate=True).to(self.device)
            text_features = self.model.encode_text(tokens)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)
        self._text_cache[cache_key] = text_features
        return text_features

    def _encode_images_from_bytes(self, images: List[bytes]) -> torch.Tensor:
        tensors = []
        for b in images:
            try:
                img = Image.open(io.BytesIO(b)).convert('RGB')
                tensor = self.preprocess(img).unsqueeze(0)
                tensors.append(tensor)
            except Exception:
                # Skip invalid image
                continue

        if not tensors:
            return torch.empty(0, 512, device=self.device)

        image_input = torch.cat(tensors, dim=0).to(self.device)
        if self.use_fp16:
            image_input = image_input.half()

        with torch.no_grad():
            image_features = self.model.encode_image(image_input)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        return image_features

    def rank_thumbnails(self, product: Dict, thumbnails: List[bytes]) -> List[int]:
        """
        Rank candidate thumbnails for a product. Returns indices (best first).
        """
        if not thumbnails:
            return []
        texts = self._build_descriptions(product)
        text_features = self._encode_texts(texts)
        image_features = self._encode_images_from_bytes(thumbnails)
        if image_features.numel() == 0:
            return []

        # cosine similarity in [-1,1]; convert to [0,1] then take max over texts
        sims = image_features @ text_features.T  # [N_images, N_texts]
        sims = (sims + 1.0) / 2.0
        max_per_image = sims.max(dim=1).values  # [N_images]

        sorted_indices = torch.argsort(max_per_image, descending=True).tolist()
        return sorted_indices


def get_clip_service(config: Optional[dict] = None) -> CLIPService:
    global _singleton_instance
    if _singleton_instance is not None:
        return _singleton_instance
    with _singleton_lock:
        if _singleton_instance is None:
            _singleton_instance = CLIPService(config)
        return _singleton_instance


