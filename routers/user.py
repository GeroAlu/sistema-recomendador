import json
from fastapi import APIRouter, HTTPException, Path
from schemas import User, UserCreate, Error
from database import get_db_connection

router = APIRouter(tags=["Usuarios"])

@router.post("/user", response_model=User, responses={400: {"model": Error}})
def create_user(user: UserCreate):
    dbConnection = get_db_connection()
    try:
        with dbConnection.cursor() as cur:
            genres_list = user.preferred_genres
            if genres_list is None:
                 genres_list = (user.attributes or {}).get('preferred_genres', [])
            
            attrs = dict(user.attributes or {})
            attrs.pop('preferred_genres', None)
            
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
            dbConnection.commit()
            
            return User(
                id=new_id, 
                username=user.username, 
                attributes=attrs, 
                preferred_genres=genres_list
            )
            
    except Exception as e:
        dbConnection.rollback()
        error_msg = str(e)
        if "unique constraint" in error_msg.lower():
            raise HTTPException(status_code=400, detail={"code": "DUPLICATE_USER", "message": "El nombre de usuario ya existe."})
        raise HTTPException(status_code=400, detail={"code": "DB_ERROR", "message": error_msg})
    finally:
        dbConnection.close()

@router.get("/user/{userId}", response_model=User, responses={404: {"model": Error}})
def get_user(userId: int = Path(..., description="ID del usuario")):
    dbConnection = get_db_connection()
    try:
        with dbConnection.cursor() as cur:
            cur.execute("SELECT id, username, preferred_genres, attributes FROM users WHERE id = %s", (userId,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "User not found"})
            
            return User(
                id=row['id'], 
                username=row['username'], 
                attributes=row['attributes'], 
                preferred_genres=row['preferred_genres']
            )
    finally:
        dbConnection.close()
