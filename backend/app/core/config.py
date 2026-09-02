"""Application configuration settings."""
import os
from pydantic import BaseModel


class Settings(BaseModel):
    """Application settings and environment variables."""
    PROJECT_NAME: str = "CITYSHIELD GIS - RAKSHAK-GEO"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    DEMO_MODE: bool = True
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")


settings = Settings()
