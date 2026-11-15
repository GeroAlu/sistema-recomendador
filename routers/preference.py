import logging
import threading
from fastapi import APIRouter, HTTPException, BackgroundTasks
from schemas import PreferenceInput, Error, INTERACTION_WEIGHTS, InteractionType
from database import get_db_connection
from recommender import engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Preferencias"])

# Solo las señales fuertes justifican recalcular la matriz de similitudes. VIEW y SEARCH
# ocurren constantemente mientras se navega y dispararían un recálculo completo por cada uno.
SIMILARITY_REFRESH_EVENTS = {
    InteractionType.ADD_TO_CART,
    InteractionType.FAVORITE,
    InteractionType.PURCHASE,
}

# Evita recálculos simultáneos dentro de este proceso: si ya hay uno en curso, se omite
# (el siguiente evento fuerte lo vuelve a disparar). No protege entre varios workers.
_recompute_lock = threading.Lock()


def _recompute_similarities_task():
    """Recalcula las similitudes entre usuarios en segundo plano."""
    if not _recompute_lock.acquire(blocking=False):
        logger.info("Ya hay un recálculo de similitudes en curso, se omite este.")
        return
    try:
        _run_recompute()
    finally:
        _recompute_lock.release()


def _run_recompute():
    try:
        conn = get_db_connection()
    except Exception as e:
        logger.error(f"No se pudo conectar para recalcular similitudes: {e}")
        return
    try:
        engine.compute_and_store_similarities(conn)
    finally:
        conn.close()


@router.post("/preference", responses={400: {"model": Error}, 404: {"model": Error}})
def add_preference(pref: PreferenceInput, background_tasks: BackgroundTasks):
    dbConnection = get_db_connection()
    try:
        # pydantic ya valida que interactionType sea un InteractionType, siempre tiene peso.
        weight = INTERACTION_WEIGHTS[pref.interactionType]

        with dbConnection.cursor() as cur:
            cur.execute(
                "INSERT INTO preferences (user_id, item_id, interaction_type, value) VALUES (%s, %s, %s, %s)",
                (pref.userId, pref.itemId, pref.interactionType.value, weight)
            )
            dbConnection.commit()

        # las señales fuertes cambian la matriz: se recalcula sin bloquear la respuesta.
        if pref.interactionType in SIMILARITY_REFRESH_EVENTS:
            background_tasks.add_task(_recompute_similarities_task)

        return {"message": "Preferencia registrada exitosamente"}
    except Exception as e:
        dbConnection.rollback()
        msg = str(e)
        if "foreign key" in msg.lower():
            raise HTTPException(status_code=404, detail={"code": "INVALID_REF", "message": "Usuario o Item no existen."})
        raise HTTPException(status_code=400, detail={"code": "DB_ERROR", "message": msg})
    finally:
        dbConnection.close()
