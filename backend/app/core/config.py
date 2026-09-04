import os
from typing import Optional
from pydantic import BaseModel, Field


def _load_env_file():
    """Load key-value pairs from .env into os.environ if present without external dependencies."""
    for env_path in [".env", "../.env"]:
        if os.path.isfile(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass


_load_env_file()


class Settings(BaseModel):
    """Application settings and environment variables."""
    PROJECT_NAME: str = "CITYSHIELD GIS - RAKSHAK-GEO"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    DEMO_MODE: bool = True
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    # PostgreSQL / PostGIS Database Configuration
    POSTGRES_SERVER: str = os.getenv("POSTGRES_SERVER", "localhost")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "postgres")
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "cityshield_gis")
    POSTGIS_ENABLED: bool = os.getenv("POSTGIS_ENABLED", "false").lower() in ("true", "1", "yes")

    # LLM Copilot Configuration (T-020)
    OPENROUTER_API_KEY: Optional[str] = os.getenv("OPENROUTER_API_KEY", None)
    COPILOT_MODEL: Optional[str] = os.getenv("COPILOT_MODEL", None)
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    COPILOT_TIMEOUT_SECONDS: float = float(os.getenv("COPILOT_TIMEOUT_SECONDS", "15.0"))

    @property
    def DATABASE_URL(self) -> str:
        """Construct PostgreSQL connection URI."""
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()
