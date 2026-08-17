import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))

from database import get_db_connection

def check_records():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM user_similarities;")
            count = cur.fetchone()['cnt']
            print(f"Total de registros persistidos en 'user_similarities': {count}")
            
            cur.execute("SELECT * FROM user_similarities LIMIT 5;")
            rows = cur.fetchall()
            print("Muestra de registros en 'user_similarities':")
            for row in rows:
                print(dict(row))
    finally:
        conn.close()

if __name__ == "__main__":
    check_records()
