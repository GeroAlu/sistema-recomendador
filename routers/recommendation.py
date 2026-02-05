from fastapi import APIRouter, HTTPException, Path, Query
from schemas import ItemArray, Error
from recommender import RecommenderEngine

router = APIRouter(tags=["Recomendaciones"])
engine = RecommenderEngine()

# --- ENDPOINT RECOMENDAR ---
@router.get("/user/{userId}/recommend", response_model=ItemArray, responses={404: {"model": Error}})
def recommend(
    userId: int = Path(..., description="ID del usuario"), 
    n: int = Query(..., description="Numero de items a recomendar")
):
    try:
        # DELEGACIÓN TOTAL: El engine ya nos devuelve una lista de diccionarios limpios
        results = engine.get_recommendations(userId, n)
        return ItemArray(items=results)
        
    except Exception as e:
        print(f"Error en endpoint recommend: {e}")
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": "Error generando recomendaciones"})
