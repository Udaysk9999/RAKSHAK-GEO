"""Application configuration settings."""
import os
from pydantic import BaseModel, Field


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

    @property
    def DATABASE_URL(self) -> str:
        """Construct PostgreSQL connection URI."""
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()
