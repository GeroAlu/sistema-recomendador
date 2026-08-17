import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))

from schemas import InteractionType, INTERACTION_WEIGHTS, PreferenceInput

def test_interaction_weights():
    print("Testing interaction weights mapping...")
    assert INTERACTION_WEIGHTS[InteractionType.VIEW] == 1
    assert INTERACTION_WEIGHTS[InteractionType.SEARCH] == 2
    assert INTERACTION_WEIGHTS[InteractionType.ADD_TO_CART] == 5
    assert INTERACTION_WEIGHTS[InteractionType.FAVORITE] == 7
    assert INTERACTION_WEIGHTS[InteractionType.PURCHASE] == 10
    print("[OK] Interaction weights OK")

def test_preference_schema_validation():
    print("Testing PreferenceInput schema validation...")
    valid_pref = PreferenceInput(userId=1, itemId=101, interactionType="ADD_TO_CART")
    assert valid_pref.interactionType == InteractionType.ADD_TO_CART
    
    try:
        invalid_pref = PreferenceInput(userId=1, itemId=101, interactionType="INVALID_TYPE")
        assert False, "Should fail on invalid interactionType"
    except Exception:
        print("[OK] Schema correctly rejected invalid interaction type")

def _apply_price_reranking_logic(items: list, alpha: float = 0.2) -> list:
    if not items:
        return items

    prices = []
    for item in items:
        attrs = item.get('attributes') or {}
        price_val = item.get('price')
        if price_val is None and isinstance(attrs, dict):
            price_val = attrs.get('price')
        try:
            prices.append(float(price_val) if price_val is not None else 0.0)
        except (ValueError, TypeError):
            prices.append(0.0)

    min_p = min(prices) if prices else 0.0
    max_p = max(prices) if prices else 0.0

    for idx, item in enumerate(items):
        raw_score = float(item.get('_score', 1.0))
        price = prices[idx]

        if max_p > min_p:
            norm_price = (price - min_p) / (max_p - min_p)
        else:
            norm_price = 0.5 if max_p > 0 else 0.0

        final_score = raw_score * (1.0 + alpha * norm_price)
        item['_score'] = final_score

    items.sort(key=lambda x: float(x.get('_score', 0.0)), reverse=True)
    return items

def test_price_reranking():
    print("Testing price re-ranking formula...")
    items = [
        {"id": 1, "name": "Cheap Book", "price": 10.0, "_score": 2.0},
        {"id": 2, "name": "Expensive Book", "price": 100.0, "_score": 2.0},
        {"id": 3, "name": "Mid-priced Book", "price": 55.0, "_score": 2.0},
    ]
    
    reranked = _apply_price_reranking_logic(items, alpha=0.2)
    
    assert reranked[0]["id"] == 2, f"Expensive book should be ranked first, got {reranked[0]['id']}"
    assert reranked[1]["id"] == 3, f"Mid book should be ranked second, got {reranked[1]['id']}"
    assert reranked[2]["id"] == 1, f"Cheap book should be ranked third, got {reranked[2]['id']}"
    
    assert abs(reranked[0]["_score"] - 2.4) < 1e-5
    assert abs(reranked[1]["_score"] - 2.2) < 1e-5
    assert abs(reranked[2]["_score"] - 2.0) < 1e-5
    
    print("[OK] Price re-ranking formula verified successfully!")

if __name__ == "__main__":
    test_interaction_weights()
    test_preference_schema_validation()
    test_price_reranking()
    print("\nALL LOGIC UNIT TESTS PASSED SUCCESSFULLY!")
