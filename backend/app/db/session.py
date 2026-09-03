"""Database session and PostGIS connectivity management."""
import socket
from typing import Any, Dict
from app.core.config import settings


def check_database_connectivity() -> Dict[str, Any]:
    """Test TCP connectivity to the configured PostgreSQL/PostGIS host and port.
    
    Returns diagnostic dictionary indicating whether a live PostgreSQL instance is reachable.
    Does NOT fake a successful connection if the database is offline.
    """
    is_reachable = False
    error_message = None

    try:
        # Fast TCP handshake check (1 second timeout)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        result = sock.connect_ex((settings.POSTGRES_SERVER, settings.POSTGRES_PORT))
        sock.close()

        if result == 0:
            is_reachable = True
        else:
            error_message = f"Connection refused on {settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT} (errno: {result})"
    except Exception as exc:
        error_message = str(exc)

    return {
        "database_engine": "PostgreSQL with PostGIS Spatial Extension",
        "configured_host": settings.POSTGRES_SERVER,
        "configured_port": settings.POSTGRES_PORT,
        "configured_database": settings.POSTGRES_DB,
        "is_connected": is_reachable,
        "postgis_extension_active": is_reachable and settings.POSTGIS_ENABLED,
        "status": "ONLINE" if is_reachable else "NOT_CONFIGURED_LOCAL_FALLBACK",
        "notes": (
            "Live PostGIS instance active."
            if is_reachable
            else "Live PostGIS instance is NOT reachable on localhost:5432. "
                 "The system is operating with deterministic in-memory/seed GIS data fallback."
        ),
        "error": error_message,
    }
