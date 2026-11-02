import logging
from fastapi import APIRouter, HTTPException, Path, Query
from schemas import ItemArray, Error
from database import get_db_connection
from recommender import RecommenderEngine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Recomendaciones"])
engine = RecommenderEngine()

@router.get("/user/{userId}/recommend", response_model=ItemArray, responses={404: {"model": Error}})
def recommend(
    userId: int = Path(..., description="ID del usuario"), 
    n: int = Query(..., description="Numero de items a recomendar")
):
    # Validar que el usuario exista en la base de datos (OpenAPI 404 requirement)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE id = %s", (userId,))
            if not cur.fetchone():
                raise HTTPException(
                    status_code=404, 
                    detail={"code": "NOT_FOUND", "message": f"Usuario con ID {userId} no encontrado."}
                )
    finally:
        conn.close()

    try:
        results = engine.get_recommendations(userId, n)
        return ItemArray(items=results)
    except Exception as e:
        logger.error(f"Error en endpoint recommend: {e}")
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": "Error generando recomendaciones"})

