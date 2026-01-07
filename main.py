import json
from fastapi import FastAPI, HTTPException, Query, Path
# Asegúrate de tener schemas.py con estas clases definidas
from schemas import User, UserCreate, ItemArray, PreferenceInput, Error
from recommender import RecommenderEngine
from database import get_db_connection

app = FastAPI(title="Sistema Recomendador - Ciencia de Datos 2025", version="1.0.0")

# Instanciamos el motor una sola vez. 
# El motor ya contiene la lógica de conexión y limpieza de datos.
engine = RecommenderEngine()

# --- 1. ENDPOINT CREAR USUARIO ---
@app.post("/user", response_model=User, responses={400: {"model": Error}}, tags=["Usuarios"])
def create_user(user: UserCreate):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Lógica de Negocio: Priorizar preferred_genres explícito
            # Si viene en el objeto principal, lo usamos. Si no, miramos en atributos.
            genres_list = user.preferred_genres
            if genres_list is None:
                 genres_list = (user.attributes or {}).get('preferred_genres', [])
            
            # Limpieza: Sacar preferred_genres de attributes para no duplicar data en la DB
            attrs = dict(user.attributes or {})
            attrs.pop('preferred_genres', None)
            
            # Serialización para PostgreSQL (JSONB)
            json_genres = json.dumps(genres_list)
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
            
            # Retornamos el objeto User completo cumpliendo el Schema
            return User(
                id=new_id, 
                username=user.username, 
                attributes=attrs, 
                preferred_genres=genres_list
            )
            
    except Exception as e:
        conn.rollback()
        error_msg = str(e)
        if "unique constraint" in error_msg.lower():
            raise HTTPException(status_code=400, detail={"code": "DUPLICATE_USER", "message": "El nombre de usuario ya existe."})
        raise HTTPException(status_code=400, detail={"code": "DB_ERROR", "message": error_msg})
    finally:
        conn.close()

# --- 2. ENDPOINT OBTENER USUARIO ---
@app.get("/user/{userId}", response_model=User, responses={404: {"model": Error}}, tags=["Usuarios"])
def get_user(userId: int = Path(..., description="ID del usuario")):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, preferred_genres, attributes FROM users WHERE id = %s", (userId,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "User not found"})
            
            # Postgres devuelve JSONB parseado automáticamente como dict o list gracias a psycopg2
            return User(
                id=row['id'], 
                username=row['username'], 
                attributes=row['attributes'], 
                preferred_genres=row['preferred_genres']
            )
    finally:
        conn.close()

# --- 3. ENDPOINT RECOMENDAR (Aquí está la gran mejora) ---
@app.get("/user/{userId}/recommend", response_model=ItemArray, responses={404: {"model": Error}}, tags=["Recomendaciones"])
def recommend(
    userId: int = Path(..., description="ID del usuario"), 
    n: int = Query(..., description="Numero de items a recomendar")
):
    try:
        # DELEGACIÓN TOTAL: El engine ya nos devuelve una lista de diccionarios limpios
        # que coinciden perfectamente con el esquema Item de Pydantic.
        results = engine.get_recommendations(userId, n)
        
        return ItemArray(items=results)
        
    except Exception as e:
        # Loguear el error real en consola para el desarrollador
        print(f"Error en endpoint recommend: {e}")
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": "Error generando recomendaciones"})

# --- 4. ENDPOINT PREFERENCIAS ---
@app.post("/preference", tags=["Preferencias"])
def add_preference(pref: PreferenceInput):
    conn = get_db_connection()
    try:
        value = 10 if pref.interactionType == 'PURCHASE' else 1
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO preferences (user_id, item_id, interaction_type, value) VALUES (%s, %s, %s, %s)",
                (pref.userId, pref.itemId, pref.interactionType, value)
            )
            conn.commit()
            return {"message": "Preferencia registrada exitosamente"}
    except Exception as e:
        conn.rollback()
        # Verificar si es error de llave foránea (Usuario o Item no existen)
        msg = str(e)
        if "foreign key" in msg.lower():
             raise HTTPException(status_code=404, detail={"code": "INVALID_REF", "message": "Usuario o Item no existen."})
        raise HTTPException(status_code=400, detail={"code": "DB_ERROR", "message": msg})
    finally:
        conn.close()