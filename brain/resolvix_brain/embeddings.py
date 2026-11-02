"""Embedding back-ends.

Primary: ``intfloat/multilingual-e5-small`` through fastembed (CPU, ONNX). fastembed 0.9 does not list this
model among its built-ins, so it is registered as a custom model (mean pooling, normalised, ``onnx/model.onnx``).
E5 needs the literal prefixes ``query: `` / ``passage: ``; we add them here and nowhere else.

Fallback (documented, flagged ``degraded``): a deterministic hashing character-n-gram embedder. It needs no
download and is what the unit tests use. Its cosine is mapped into the E5-like range (0.7 + 0.3 * cos) so the same
FAQ thresholds apply, but it only matches lexically similar text; production must use fastembed.
"""
from __future__ import annotations

import logging
import zlib
from pathlib import Path
from typing import Protocol

import numpy as np

from .settings import BrainSettings
from .text import tokens

log = logging.getLogger("resolvix_brain.embed")


class Embedder(Protocol):
    name: str
    degraded: bool

    def embed_queries(self, texts: list[str]) -> np.ndarray: ...
    def embed_passages(self, texts: list[str]) -> np.ndarray: ...
    def to_score(self, cosine: np.ndarray) -> np.ndarray: ...


class FastEmbedder:
    degraded = False

    def __init__(self, model: str, cache_dir: str):
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType

        self.name = model
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        try:
            TextEmbedding.add_custom_model(
                model=model, pooling=PoolingType.MEAN, normalization=True, sources=ModelSource(hf=model),
                dim=384, model_file="onnx/model.onnx", description="multilingual e5 small (custom registration)",
                license="mit", size_in_gb=0.47,
            )
        except ValueError:
            pass  # already registered (second Brain in the same process)
        self._model = TextEmbedding(model_name=model, cache_dir=cache_dir)

    def _embed(self, texts: list[str], prefix: str) -> np.ndarray:
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        v = np.asarray(list(self._model.embed([prefix + t for t in texts])), dtype=np.float32)
        n = np.linalg.norm(v, axis=1, keepdims=True)
        return v / np.maximum(n, 1e-9)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts, "query: ")

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts, "passage: ")

    def to_score(self, cosine: np.ndarray) -> np.ndarray:
        return cosine


class LexicalEmbedder:
    """Hashing TF embedder over word unigrams and character trigrams. Deterministic and offline."""

    name = "lexical-hash-1024"
    degraded = True
    DIM = 1024

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.DIM, dtype=np.float32)
        for tok in tokens(text):
            v[zlib.crc32(("w:" + tok).encode()) % self.DIM] += 2.0
            padded = f"^{tok}$"
            for i in range(len(padded) - 2):
                v[zlib.crc32(("c:" + padded[i : i + 3]).encode()) % self.DIM] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.DIM), dtype=np.float32)

    embed_passages = embed_queries

    def to_score(self, cosine: np.ndarray) -> np.ndarray:
        return 0.7 + 0.3 * cosine


def create_embedder(settings: BrainSettings) -> Embedder:
    """fastembed if requested and loadable, otherwise the lexical fallback (``degraded=True``, logged)."""
    if settings.embed_mode == "lexical":
        return LexicalEmbedder()
    try:
        return FastEmbedder(settings.embed_model, settings.embed_cache_dir)
    except Exception as exc:  # download/offline/ONNX problems
        log.error("fastembed unavailable (%s: %s); using degraded lexical embedder", type(exc).__name__, exc)
        return LexicalEmbedder()
