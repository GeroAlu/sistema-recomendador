import sys
import os
import logging
from fastapi import FastAPI
from schemas import Error
from database import get_db_connection
from routers.user import router as user_router
from routers.preference import router as preference_router
from routers.recommendation import router as recommendation_router

# logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# revisar si esta el archivo de variables de entorno antes de prender la app.
if not os.path.exists(".env"):
    logger.error("No se encontró el archivo .env. Creá uno copiando .env.example")
    sys.exit(1)

app = FastAPI(title="Sistema Recomendador - Ciencia de Datos 2025", version="1.0.0")

@app.on_event("startup")
def startup_check_db():
    try:
        conn = get_db_connection()
        conn.close()
        logger.info("Conexión a la base de datos exitosa.")
    except Exception as e:
        logger.error(f"No se pudo conectar a la base de datos: {e}")
        sys.exit(1)

# routers
app.include_router(user_router)
app.include_router(preference_router)
app.include_router(recommendation_router)

@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "message": "Sistema Recomendador corriendo, navega a la ruta /docs."}