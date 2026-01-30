import logging
from fastapi import FastAPI
from schemas import Error
from routers.user import router as user_router
from routers.preference import router as preference_router
from routers.recommendation import router as recommendation_router

# logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Sistema Recomendador - Ciencia de Datos 2025", version="1.0.0")

# routers
app.include_router(user_router)
app.include_router(preference_router)
app.include_router(recommendation_router)

@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "message": "Sistema Recomendador corriendo, navega a la ruta /docs."}