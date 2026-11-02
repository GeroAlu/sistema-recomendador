import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from config import settings

logger = logging.getLogger(__name__)

def get_db_connection():
    settings.validate_connection_params()
    
    conn = psycopg2.connect(
        host=settings.get_host(),
        database=settings.get_database(),
        user=settings.get_user(),
        password=settings.get_password(),
        port=settings.get_port(),
        sslmode=settings.get_sslmode(),
        cursor_factory=RealDictCursor
    )
    return conn

def init_db():
    """Inicializa tablas necesarias como user_similarities si no existen."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_similarities (
                    user_id_1 INT NOT NULL,
                    user_id_2 INT NOT NULL,
                    similarity_score DOUBLE PRECISION NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id_1, user_id_2)
                );
            """)
            conn.commit()
            logger.info("Tabla user_similarities verificada/creada exitosamente.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error al inicializar la base de datos: {e}")
        raise e
    finally:
        conn.close()