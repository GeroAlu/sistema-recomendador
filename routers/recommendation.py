import logging
from fastapi import APIRouter, HTTPException, Path, Query
from schemas import ItemArray, Error
from config import settings
from database import get_db_connection
from recommender import engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Recomendaciones"])


@router.get("/user/{userId}/recommend", response_model=ItemArray, responses={404: {"model": Error}})
def recommend(
    userId: int = Path(..., description="ID del usuario"),
    n: int = Query(..., ge=1, le=settings.MAX_RECOMMENDATIONS, description="Numero de items a recomendar")
):
    # Una sola conexión para validar el usuario y generar las recomendaciones.
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE id = %s", (userId,))
            if not cur.fetchone():
                raise HTTPException(
                    status_code=404,
                    detail={"code": "NOT_FOUND", "message": f"Usuario con ID {userId} no encontrado."}
                )

        results = engine.get_recommendations(userId, n, dbConnection=conn)
        return ItemArray(items=results)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en endpoint recommend: {e}")
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": "Error generando recomendaciones"})
    finally:
        conn.close()
