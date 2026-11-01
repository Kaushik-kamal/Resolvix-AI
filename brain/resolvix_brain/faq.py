"""FAQ semantic cache: cosine similarity between the caller's question and the indexed question variants."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .embeddings import Embedder
from .kb.compiler import FaqItem


@dataclass(frozen=True)
class FaqMatch:
    entry_id: str
    score: float
    question: str


@dataclass
class FaqResult:
    top: list[FaqMatch]          # best match per entry, descending, up to k
    hit: FaqMatch | None         # score >= tau_hit
    hints: list[FaqMatch]        # tau_soft <= score < tau_hit (top 3), passed to the LLM

    @property
    def best(self) -> FaqMatch | None:
        return self.top[0] if self.top else None


class FaqIndex:
    def __init__(self, items: list[FaqItem], matrix: np.ndarray, embedder: Embedder):
        self.items = items
        self.matrix = matrix
        self.embedder = embedder

    @classmethod
    def build(cls, items: list[FaqItem], embedder: Embedder) -> "FaqIndex":
        mat = embedder.embed_passages([i.question for i in items]) if items else np.zeros((0, 1), dtype=np.float32)
        return cls(items, mat, embedder)

    def search_vec(self, qvec: np.ndarray, k: int = 3) -> list[FaqMatch]:
        if not self.items:
            return []
        scores = self.embedder.to_score(self.matrix @ qvec)
        best: dict[str, FaqMatch] = {}
        for idx in np.argsort(-scores)[: max(k * 4, 8)]:
            it = self.items[int(idx)]
            if it.entry_id not in best:
                best[it.entry_id] = FaqMatch(it.entry_id, float(scores[idx]), it.question)
        return sorted(best.values(), key=lambda m: -m.score)[:k]

    def lookup(self, qvec: np.ndarray, tau_hit: float, tau_soft: float) -> FaqResult:
        top = self.search_vec(qvec, k=3)
        hit = top[0] if top and top[0].score >= tau_hit else None
        hints = [m for m in top if tau_soft <= m.score < tau_hit] if not hit else []
        return FaqResult(top, hit, hints)
