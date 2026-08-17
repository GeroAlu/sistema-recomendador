import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))

from schemas import InteractionType, INTERACTION_WEIGHTS, PreferenceInput
from recommender import RecommenderEngine
from config import Settings

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

def test_price_reranking():
    print("Testing price re-ranking formula...")
    engine = RecommenderEngine()
    
    items = [
        {"id": 1, "name": "Cheap Book", "price": 10.0, "_score": 2.0},
        {"id": 2, "name": "Expensive Book", "price": 100.0, "_score": 2.0},
        {"id": 3, "name": "Mid-priced Book", "price": 55.0, "_score": 2.0},
    ]
    
    reranked = engine._apply_price_reranking(items, alpha=0.2)
    
    assert reranked[0]["id"] == 2, f"Expensive book should be ranked first, got {reranked[0]['id']}"
    assert reranked[1]["id"] == 3, f"Mid book should be ranked second, got {reranked[1]['id']}"
    assert reranked[2]["id"] == 1, f"Cheap book should be ranked third, got {reranked[2]['id']}"
    
    assert abs(reranked[0]["_score"] - 2.4) < 1e-5
    assert abs(reranked[1]["_score"] - 2.2) < 1e-5
    assert abs(reranked[2]["_score"] - 2.0) < 1e-5
    
    print("[OK] Price re-ranking formula verified successfully!")

def test_settings_validation():
    print("Testing settings fail-fast validation...")
    s = Settings(DB_HOST="", DB_NAME="", DB_USER="", DB_PASSWORD="")
    try:
        s.validate_connection_params()
        assert False, "Should have raised ValueError for missing DB params"
    except ValueError as e:
        print(f"[OK] Settings fail-fast validation verified: {e}")

if __name__ == "__main__":
    test_interaction_weights()
    test_preference_schema_validation()
    test_price_reranking()
    test_settings_validation()
    print("\nALL RECOMMENDER UNIT TESTS PASSED SUCCESSFULLY!")
