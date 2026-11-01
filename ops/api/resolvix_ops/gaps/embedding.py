"""Embedding-based gap clustering (PRD P1-04), behind the same ClusterStrategy interface.

Selected with GAP_CLUSTER_STRATEGY=embedding and needs a cloud embedding API (OpenAI-compatible `POST /embeddings`)
configured through EMBEDDING_API_KEY (+ EMBEDDING_API_URL, EMBEDDING_MODEL). Without a key get_strategy() falls back to
the keyword strategy with a warning (see BLOCKERS.md). It was only exercised with mocked HTTP.

How it works: a question is embedded; if its cosine similarity to the centroid of a cluster seen earlier in this process
(same department) is at least SIMILARITY_THRESHOLD it joins that cluster (same key and label), otherwise it starts a
cluster under the keyword key. Centroids live in memory, so after a restart paraphrases that only the embedding links
start new clusters again (the keyword keys keep the old ones continuous).
Any embedding error degrades to the keyword key for that question; a gap is never rejected because of it.
"""
import logging
import math
import threading

import httpx

from .cluster import ClusterStrategy, KeywordClusterStrategy, department_part

log = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.82
EMBED_TIMEOUT_S = 5.0


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class EmbeddingClusterStrategy(ClusterStrategy):
    name = "embedding"

    def __init__(self, api_key: str, api_url: str, model: str, threshold: float = SIMILARITY_THRESHOLD):
        self._api_key, self._api_url, self._model, self._threshold = api_key, api_url, model, threshold
        self._keywords = KeywordClusterStrategy()
        self._centroids: dict[str, tuple[str, str, list[float], int]] = {}  # key -> (dept, label, vector, n)
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings) -> "EmbeddingClusterStrategy | None":
        if not settings.embedding_api_key:
            return None
        return cls(settings.embedding_api_key, settings.embedding_api_url, settings.embedding_model)

    def embed(self, text: str) -> list[float]:
        r = httpx.post(self._api_url, json={"model": self._model, "input": text},
                       headers={"Authorization": f"Bearer {self._api_key}"}, timeout=EMBED_TIMEOUT_S)
        r.raise_for_status()
        return [float(x) for x in r.json()["data"][0]["embedding"]]

    def assign(self, question: str, department_guess: str | None) -> tuple[str, str]:
        key, label = self._keywords.assign(question, department_guess)
        dept = department_part(department_guess)
        try:
            vector = self.embed(question)
        except Exception as exc:  # never lose a gap because the embedding service is down
            log.warning("embedding failed (%s); using the keyword cluster", type(exc).__name__)
            return key, label
        with self._lock:
            best_key, best = None, self._threshold
            for ckey, (cdept, _clabel, centroid, _n) in self._centroids.items():
                if cdept != dept:
                    continue
                similarity = cosine(vector, centroid)
                if similarity >= best:
                    best_key, best = ckey, similarity
            if best_key is not None:
                cdept, clabel, centroid, n = self._centroids[best_key]
                merged = [(c * n + v) / (n + 1) for c, v in zip(centroid, vector)]
                self._centroids[best_key] = (cdept, clabel, merged, n + 1)
                return best_key, clabel
            self._centroids.setdefault(key, (dept, label, vector, 1))
            return key, label
