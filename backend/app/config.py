"""Configuration.

Deployment settings come from the environment. Operational settings the team
fills in from the browser -- Africa's Talking credentials, the voice number, the
phone to test against -- live in the database instead, so that the site can be
handed to someone with no shell access and still be made to place a real call.
See app.settings_store.
"""
import os
from typing import List


class Settings:
    def __init__(self) -> None:
        self.app_name = "Mabia AI"
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./mabia.db")
        # Render and other hosts still hand out the legacy postgres:// scheme,
        # which SQLAlchemy 2 no longer recognises.
        if self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace(
                "postgres://", "postgresql://", 1)
        # Fail loudly and usefully rather than with a bare ModuleNotFoundError
        # three frames deep in SQLAlchemy.
        if self.database_url.startswith("postgresql"):
            try:
                import psycopg2  # noqa: F401
            except ImportError:  # pragma: no cover
                raise RuntimeError(
                    "DATABASE_URL points at Postgres but psycopg2 is not "
                    "installed. Add psycopg2-binary to backend/requirements.txt, "
                    "or unset DATABASE_URL to fall back to SQLite.")
        self.jwt_secret = os.getenv("JWT_SECRET", "dev-secret-change-me")
        self.jwt_algorithm = "HS256"
        self.jwt_ttl_hours = int(os.getenv("JWT_TTL_HOURS", "12"))
        self.public_base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
        self.cors_origins: List[str] = [
            o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()
        ]
        self.seed_on_start = os.getenv("SEED_ON_START", "1") == "1"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
