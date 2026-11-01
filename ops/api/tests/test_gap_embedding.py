"""Embedding clustering strategy (mocked HTTP only) and the fallback without a key."""
import logging

import httpx
import pytest
import respx

from resolvix_ops.config import Settings
from resolvix_ops.gaps.cluster import KeywordClusterStrategy, get_strategy
from resolvix_ops.gaps.embedding import EmbeddingClusterStrategy, cosine

URL = "https://embeddings.example.test/v1/embeddings"


def vec_for(text: str):
    # tiny fake model: fee-ish texts point one way, bus-ish texts another
    return [1.0, 0.1, 0.0] if "fee" in text or "payment" in text else [0.0, 0.2, 1.0]


@pytest.fixture
def api():
    with respx.mock(assert_all_mocked=True) as router:
        def handler(request):
            import json
            text = json.loads(request.content)["input"]
            return httpx.Response(200, json={"data": [{"embedding": vec_for(text)}]})
        router.post(URL).mock(side_effect=handler)
        yield router


def make():
    return EmbeddingClusterStrategy("k", URL, "m")


def test_cosine():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([0, 0], [1, 1]) == 0.0


def test_paraphrases_with_different_keywords_share_a_cluster(api):
    s = make()
    k1, l1 = s.assign("when is the fee deadline", "accounts")
    k2, l2 = s.assign("payment last date kya hai", "accounts")
    assert k1 == k2 and l1 == l2
    k3, _ = s.assign("bus timing for hostel", "accounts")
    assert k3 != k1


def test_other_department_does_not_merge(api):
    s = make()
    k1, _ = s.assign("fee deadline", "accounts")
    k2, _ = s.assign("fee payment date", "hostel")
    assert k1 != k2


def test_embedding_failure_degrades_to_keywords(caplog):
    with respx.mock(assert_all_mocked=True) as router:
        router.post(URL).mock(return_value=httpx.Response(500))
        caplog.set_level(logging.WARNING)
        s = make()
        assert s.assign("fee deadline", "accounts") == KeywordClusterStrategy().assign("fee deadline", "accounts")
    assert "embedding failed" in caplog.text


def test_without_key_get_strategy_falls_back_to_keywords(caplog):
    settings = Settings(_env_file=None, service_key="x", session_secret="s" * 32, gap_cluster_strategy="embedding")
    caplog.set_level(logging.WARNING)
    assert isinstance(get_strategy("embedding", settings), KeywordClusterStrategy)
    assert "EMBEDDING_API_KEY" in caplog.text


def test_with_key_get_strategy_returns_a_shared_embedding_instance():
    settings = Settings(_env_file=None, service_key="x", session_secret="s" * 32, embedding_api_key="k",
                        embedding_api_url=URL, gap_cluster_strategy="embedding")
    a, b = get_strategy("embedding", settings), get_strategy("embedding", settings)
    assert isinstance(a, EmbeddingClusterStrategy) and a is b
