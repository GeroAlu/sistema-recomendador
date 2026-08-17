from fastapi import APIRouter, HTTPException, BackgroundTasks
from schemas import PreferenceInput, Error, INTERACTION_WEIGHTS
from database import get_db_connection
from recommender import RecommenderEngine

router = APIRouter(tags=["Preferencias"])
engine = RecommenderEngine()

def _recompute_similarities_task():
    try:
        conn = get_db_connection()
        engine.compute_and_store_similarities(conn)
        conn.close()
    except Exception as e:
        pass

@router.post("/preference", responses={400: {"model": Error}, 404: {"model": Error}})
def add_preference(pref: PreferenceInput, background_tasks: BackgroundTasks):
    dbConnection = get_db_connection()
    try:
        interaction_key = pref.interactionType
        weight = INTERACTION_WEIGHTS.get(interaction_key)
        if weight is None:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_INTERACTION", "message": f"Tipo de interacción inválido: {pref.interactionType}"}
            )

        interaction_str = interaction_key.value if hasattr(interaction_key, 'value') else str(interaction_key)

        with dbConnection.cursor() as cur:
            cur.execute(
                "INSERT INTO preferences (user_id, item_id, interaction_type, value) VALUES (%s, %s, %s, %s)",
                (pref.userId, pref.itemId, interaction_str, weight)
            )
            dbConnection.commit()

        background_tasks.add_task(_recompute_similarities_task)

        return {"message": "Preferencia registrada exitosamente"}
    except HTTPException:
        dbConnection.rollback()
        raise
    except Exception as e:
        dbConnection.rollback()
        msg = str(e)
        if "foreign key" in msg.lower():
            raise HTTPException(status_code=404, detail={"code": "INVALID_REF", "message": "Usuario o Item no existen."})
        raise HTTPException(status_code=400, detail={"code": "DB_ERROR", "message": msg})
    finally:
        dbConnection.close()
