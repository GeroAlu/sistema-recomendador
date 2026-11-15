import sys
import logging
from fastapi import FastAPI
from database import get_db_connection, init_db
from recommender import engine
from routers.user import router as user_router
from routers.preference import router as preference_router
from routers.recommendation import router as recommendation_router

# logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Sistema Recomendador - Ciencia de Datos 2025", version="1.0.0")

@app.on_event("startup")
def startup_check_db():
    try:
        init_db()
        logger.info("Conexión e inicialización de la base de datos exitosa.")
    except Exception as e:
        logger.error(f"No se pudo conectar a la base de datos o inicializar tablas: {e}")
        sys.exit(1)

    # Pobla user_similarities una vez al arrancar
    try:
        conn = get_db_connection()
        try:
            engine.compute_and_store_similarities(conn)
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"No se pudieron precalcular las similitudes al iniciar: {e}")

# routers
app.include_router(user_router)
app.include_router(preference_router)
app.include_router(recommendation_router)

@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "message": "Sistema Recomendador corriendo, navega a la ruta /docs."}
