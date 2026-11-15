import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")

from recommender import RecommenderEngine  # noqa: E402

engine = RecommenderEngine()


def _items(*prices, score=2.0):
    return [{"id": i, "price": p, "_score": score} for i, p in enumerate(prices, start=1)]


def test_rerank_prefers_higher_price_with_equal_score():
    result = engine._apply_price_reranking(_items(10.0, 100.0, 55.0), alpha=0.2)
    assert [i["id"] for i in result] == [2, 3, 1]
    assert abs(result[0]["_score"] - 2.4) < 1e-9


def test_rerank_uses_catalog_bounds_when_given():
    # Contra el catálogo (0-1000), 100 es barato: el boost es chico.
    result = engine._apply_price_reranking(_items(100.0), alpha=0.2, price_bounds=(0.0, 1000.0))
    assert abs(result[0]["_score"] - 2.0 * (1 + 0.2 * 0.1)) < 1e-9


def test_rerank_clamps_prices_outside_bounds():
    result = engine._apply_price_reranking(_items(5000.0), alpha=0.2, price_bounds=(0.0, 1000.0))
    assert abs(result[0]["_score"] - 2.4) < 1e-9


def test_rerank_empty_list():
    assert engine._apply_price_reranking([]) == []


def test_rerank_does_not_mix_strategies():
    # Cada estrategia se reordena por separado, el orden entre estrategias lo da la cascada.
    collab = engine._apply_price_reranking(_items(10.0, score=3.0))
    popular = engine._apply_price_reranking(_items(500.0, score=60.0))
    assert collab[0]["_score"] < popular[0]["_score"]  # escalas distintas, por eso no se ordenan juntas
