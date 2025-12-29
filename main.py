import json
from fastapi import FastAPI, HTTPException, Query, Path
from schemas import User, ItemArray, PreferenceInput, Error
from recommender import RecommenderEngine
from database import get_db_connection

app = FastAPI(title="Sistema Recomendador - Ciencia de Datos 2025", version="1.0.0")
engine = RecommenderEngine()

@app.post("/user", response_model=User, responses={400: {"model": Error}})
def create_user(user: User):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        genres_list = user.attributes.get('preferred_genres', [])
        json_genres = json.dumps(genres_list)
        json_attrs = json.dumps(user.attributes)
        
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
        
        user.id = new_id
        return user
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
        cur.execute("SELECT id, username, attributes FROM users WHERE id = %s", (userId,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "User not found"})
        return User(id=row['id'], username=row['username'], attributes=row['attributes'])
    finally:
        conn.close()

@app.get("/user/{userId}/recommend", response_model=ItemArray, responses={404: {"model": Error}})
def recommend(userId: int = Path(..., description="ID del usuario"), n: int = Query(..., description="numero de items a recomendar")):
    try:
        results = engine.get_recommendations(userId, n)
        return ItemArray(items=results)
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

