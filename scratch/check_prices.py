import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))

from database import get_db_connection

def inspect_prices():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, price, attributes FROM items LIMIT 10;")
            rows = cur.fetchall()
            print("Muestra de precios reales en la tabla 'items':")
            for row in rows:
                print(f"ID: {row['id']} | Nombre: {row['name']} | Price col: {row.get('price')} | Attrs: {row.get('attributes')}")
    finally:
        conn.close()

if __name__ == "__main__":
    inspect_prices()
