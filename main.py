import json
from fastapi import FastAPI, HTTPException, Query, Path
from schemas import User, UserCreate, ItemArray, PreferenceInput, Error
from recommender import RecommenderEngine
from database import get_db_connection

app = FastAPI(title="Sistema Recomendador - Ciencia de Datos 2025", version="1.0.0")
engine = RecommenderEngine()

@app.post("/user", response_model=User, responses={400: {"model": Error}})
def create_user(user: UserCreate):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Prefer the explicit top-level `preferred_genres`; fall back to attributes if missing
        genres_list = user.preferred_genres if user.preferred_genres is not None else (user.attributes or {}).get('preferred_genres', [])
        if genres_list is None:
            genres_list = []
        json_genres = json.dumps(genres_list)
        # Avoid duplicating preferred_genres inside attributes column
        attrs = dict(user.attributes or {})
        attrs.pop('preferred_genres', None)
        json_attrs = json.dumps(attrs)
        
        cur.execute(
            """
            INSERT INTO users (username, preferred_genres, attributes) 
            VALUES (%s, %s, %s) 
            RETURNING id
            """,
            (user.username, json_genres, json_attrs)
        )
        new_id = cur.fetchone()['id']
        conn.commit()
        
        response_user = User(id=new_id, username=user.username, attributes=attrs, preferred_genres=genres_list)
        return response_user
    except Exception as e:
        conn.rollback()
        error_msg = str(e)
        if "unique constraint" in error_msg.lower():
            raise HTTPException(status_code=400, detail={"code": "DUPLICATE_USER", "message": "El nombre de usuario ya existe."})
        raise HTTPException(status_code=400, detail={"code": "DB_ERROR", "message": error_msg})
    finally:
        conn.close()

@app.get("/user/{userId}", response_model=User, responses={404: {"model": Error}})
def get_user(userId: int = Path(..., description="ID del usuario")):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, username, preferred_genres, attributes FROM users WHERE id = %s", (userId,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "User not found"})
        return User(id=row['id'], username=row['username'], attributes=row['attributes'], preferred_genres=row['preferred_genres'])
    finally:
        conn.close()

@app.get("/user/{userId}/recommend", response_model=ItemArray, responses={404: {"model": Error}})
def recommend(userId: int = Path(..., description="ID del usuario"), n: int = Query(..., description="numero de items a recomendar")):
    try:
        results = engine.get_recommendations(userId, n)
        # Sanitize results: ensure every item has an integer 'id' and proper fields
        sanitized = []
        for it in (results or []):
            if not isinstance(it, dict):
                continue
            # try common id fields
            iid = it.get('id') if 'id' in it else it.get('item_id')
            # try inside attributes
            if iid is None and isinstance(it.get('attributes'), dict):
                iid = it['attributes'].get('id') if 'id' in it['attributes'] else None
            # try case-insensitive key search
            if iid is None:
                for k, v in it.items():
                    if k.lower() in ('id', 'item_id'):
                        iid = v
                        break
            if iid is None:
                # skip items without id
                logger = __import__('logging').getLogger(__name__)
                logger.warning("Skipping item without id: %s", it)
                continue
            try:
                iid = int(iid)
            except Exception:
                logger = __import__('logging').getLogger(__name__)
                logger.warning("Skipping item with non-integer id: %s", it)
                continue
            # normalize attributes
            attr = it.get('attributes', {})
            if isinstance(attr, str):
                try:
                    attr = json.loads(attr.replace("'", '"'))
                except Exception:
                    attr = {}
            sanitized.append({'id': iid, 'name': it.get('name'), 'genre': it.get('genre'), 'attributes': attr})
        return ItemArray(items=sanitized)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": str(e)})

@app.post("/preference")
def add_preference(pref: PreferenceInput):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO preferences (user_id, item_id, interaction_type, value) VALUES (%s, %s, %s, %s)",
            (pref.userId, pref.itemId, pref.interactionType, pref.value)
        )
        conn.commit()
        return {"message": "Preferencia registrada exitosamente"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail={"code": "DB_ERROR", "message": str(e)})
    finally:
        conn.close()
