import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DB_HOST: Optional[str] = Field(default=None, validation_alias="DB_HOST")
    DB_PORT: int = Field(default=5432, validation_alias="DB_PORT")
    DB_NAME: Optional[str] = Field(default=None, validation_alias="DB_NAME")
    DB_USER: Optional[str] = Field(default=None, validation_alias="DB_USER")
    DB_PASSWORD: Optional[str] = Field(default=None, validation_alias="DB_PASSWORD")
    DB_SSLMODE: Optional[str] = Field(default="prefer", validation_alias="DB_SSLMODE")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def get_host(self) -> str:
        return self.DB_HOST or os.getenv("PGHOST", "")

    def get_database(self) -> str:
        return self.DB_NAME or os.getenv("PGDATABASE", "")

    def get_user(self) -> str:
        return self.DB_USER or os.getenv("PGUSER", "")

    def get_password(self) -> str:
        return self.DB_PASSWORD or os.getenv("PGPASSWORD", "")

    def get_port(self) -> int:
        port_val = os.getenv("PGPORT")
        if port_val and port_val.isdigit():
            return int(port_val)
        return self.DB_PORT

    def get_sslmode(self) -> str:
        return os.getenv("PGSSLMODE") or self.DB_SSLMODE or "prefer"

    def validate_connection_params(self):
        host = self.get_host()
        database = self.get_database()
        user = self.get_user()
        password = self.get_password()
        
        if not (host and database and user and password):
            missing = []
            if not host: missing.append("DB_HOST / PGHOST")
            if not database: missing.append("DB_NAME / PGDATABASE")
            if not user: missing.append("DB_USER / PGUSER")
            if not password: missing.append("DB_PASSWORD / PGPASSWORD")
            raise ValueError(f"Faltan variables de entorno requeridas para la base de datos: {', '.join(missing)}")

settings = Settings()
