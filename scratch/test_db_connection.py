import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))

from database import get_db_connection, init_db
from recommender import RecommenderEngine

def test_db():
    print("Testing DB connection to Neon...")
    try:
        conn = get_db_connection()
        print("[OK] Connected to DB successfully!")
        conn.close()
        
        print("Initializing tables (user_similarities)...")
        init_db()
        print("[OK] Database initialized and table user_similarities verified!")

        print("Testing similarity computation & persistence on real DB...")
        conn = get_db_connection()
        engine = RecommenderEngine()
        engine.compute_and_store_similarities(conn)
        conn.close()
        print("[OK] compute_and_store_similarities executed successfully!")
        
        print("\nALL DATABASE TESTS & INITIALIZATION COMPLETED SUCCESSFULLY!")
    except Exception as e:
        print(f"[ERROR] Connection/Init failed: {e}")

if __name__ == "__main__":
    test_db()
