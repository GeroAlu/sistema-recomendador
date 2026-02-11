import json
import logging

logger = logging.getLogger(__name__)


def parse_json_safe(data):
    """Parsea JSON de forma segura."""
    if isinstance(data, dict): return data
    if isinstance(data, str):
        try: return json.loads(data)
        except:
            try: return json.loads(data.replace("'", '"'))
            except: return {}
    return {}


def map_item_to_schema(row):
    """Mapea una un item a la estructura esperada por el esquema Item."""
    attrs = parse_json_safe(row.get('attributes'))

# Agregar campos específicos al diccionario de atributos.
    if 'author' in row and row['author']:
        attrs['author'] = row['author']
    if 'price' in row and row['price']:
        try: attrs['price'] = float(row['price'])
        except: pass

    return {
        "id": int(row['id']),
        "name": str(row['name']),
        "genre": row.get('genre'),
        "attributes": attrs,
        "recommendation_source": row.get('_source', 'unknown'),
        "score": float(row.get('_score', 0.0))
    }


def add_unique_items(target_list, seen_set, new_items, limit):
    """Agrega items a la lista final respetando el límite y sin duplicados."""
    for item in new_items:
        if len(target_list) >= limit:
            break
        try: iid = int(item['id'])
        except: continue

        if iid not in seen_set:
            target_list.append(item)
            seen_set.add(iid)


def get_user_preferred_genres(dbConnection, user_id):
    """Obtiene géneros preferidos del usuario."""
    try:
        with dbConnection.cursor() as cur:
            cur.execute("SELECT preferred_genres FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if row and row['preferred_genres']:
                data = row['preferred_genres']
                # Manejar si Postgres devuelve lista o string JSON
                return data if isinstance(data, list) else json.loads(data) if isinstance(data, str) else []
    except Exception as e:
        logger.warning(f"Error leyendo géneros usuario {user_id}: {e}")
        return []
    return []
