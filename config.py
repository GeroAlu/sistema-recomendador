import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DB_HOST: Optional[str] = None
    DB_PORT: Optional[int] = None
    DB_NAME: Optional[str] = None
    DB_USER: Optional[str] = None
    DB_PASSWORD: Optional[str] = None
    DB_SSLMODE: Optional[str] = None

    PGHOST: Optional[str] = None
    PGPORT: Optional[int] = None
    PGDATABASE: Optional[str] = None
    PGUSER: Optional[str] = None
    PGPASSWORD: Optional[str] = None
    PGSSLMODE: Optional[str] = None

    # Parámetros del recomendador
    COLLAB_SMOOTHING: float = 1.0        
    RERANK_ALPHA: float = 0.2       
    MAX_RECOMMENDATIONS: int = 100

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def get_host(self) -> str:
        return self.DB_HOST or self.PGHOST or os.getenv("PGHOST", "")

    def get_database(self) -> str:
        return self.DB_NAME or self.PGDATABASE or os.getenv("PGDATABASE", "")

    def get_user(self) -> str:
        return self.DB_USER or self.PGUSER or os.getenv("PGUSER", "")

    def get_password(self) -> str:
        return self.DB_PASSWORD or self.PGPASSWORD or os.getenv("PGPASSWORD", "")

    def get_port(self) -> int:
        if self.DB_PORT:
            return self.DB_PORT
        if self.PGPORT:
            return self.PGPORT
        port_val = os.getenv("PGPORT")
        return int(port_val) if port_val and port_val.isdigit() else 5432

    def get_sslmode(self) -> str:
        return self.DB_SSLMODE or self.PGSSLMODE or os.getenv("PGSSLMODE") or "prefer"

    def validate_connection_params(self):
        required = {
            "DB_HOST / PGHOST": self.get_host(),
            "DB_NAME / PGDATABASE": self.get_database(),
            "DB_USER / PGUSER": self.get_user(),
            "DB_PASSWORD / PGPASSWORD": self.get_password(),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Faltan variables de entorno requeridas para la base de datos: {', '.join(missing)}")


settings = Settings()
