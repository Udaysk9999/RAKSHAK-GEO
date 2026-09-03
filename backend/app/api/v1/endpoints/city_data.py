"""City GIS Data Access Endpoints (PostGIS-ready foundation).

Exposes typed data access endpoints for municipal spatial datasets:
wards, buildings, hospitals, shelters, roads, demographics, and depot resources.
Reports PostGIS connectivity status and falls back deterministically to seed fixtures.
All synthetic resources and geometries are labeled DEMO DATA per agent.md.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query, status

from app.db.session import check_database_connectivity
from app.schemas.city_gis import (
    CityGISInventorySummary,
    HospitalFacility,
    RoadSegment,
    ShelterFacility,
)
from app.schemas.gis import BuildingFootprint, WardZoneGeometry
from app.schemas.optimization import ResourceQuantity
from app.services.city_gis_repository import CityGISRepository

router = APIRouter(prefix="/city-data", tags=["City GIS Data Foundation"])


@router.get(
    "/status",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Check PostGIS Spatial Database Status",
    description="Reports connectivity status to PostgreSQL/PostGIS and whether fallback mode is active.",
)
def get_database_status() -> Dict[str, Any]:
    """Return database engine status and PostGIS connectivity diagnostics."""
    return check_database_connectivity()


@router.get(
    "/summary",
    response_model=CityGISInventorySummary,
    status_code=status.HTTP_200_OK,
    summary="Get City GIS Layer Inventory Summary [DEMO DATA]",
    description="Returns aggregate counts and metadata across wards, buildings, hospitals, shelters, roads, and population.",
)
def get_inventory_summary(
    city_id: str = Query("AHMEDABAD", description="Target city identifier"),
) -> CityGISInventorySummary:
    """Return an executive summary of indexed city spatial layers."""
    return CityGISRepository.get_inventory_summary(city_id=city_id)


@router.get(
    "/wards",
    response_model=List[WardZoneGeometry],
    status_code=status.HTTP_200_OK,
    summary="Get Municipal Ward/Zone Geometries [DEMO DATA]",
    description="Retrieves administrative ward polygons compatible with GIS impact and optimization services.",
)
def get_wards(
    city_id: Optional[str] = Query("AHMEDABAD", description="Filter by city identifier"),
) -> List[WardZoneGeometry]:
    """Retrieve municipal ward boundary geometries."""
    return CityGISRepository.get_ward_geometries(city_id=city_id)


@router.get(
    "/buildings",
    response_model=List[BuildingFootprint],
    status_code=status.HTTP_200_OK,
    summary="Get Building Footprints [DEMO DATA]",
    description="Retrieves structure footprints and critical facility geometries, optionally filtered by zone.",
)
def get_buildings(
    city_id: Optional[str] = Query("AHMEDABAD", description="Filter by city identifier"),
    zone_id: Optional[str] = Query(None, description="Optional zone ID filter"),
) -> List[BuildingFootprint]:
    """Retrieve building and infrastructure footprints."""
    return CityGISRepository.get_building_footprints(city_id=city_id, zone_id=zone_id)


@router.get(
    "/hospitals",
    response_model=List[HospitalFacility],
    status_code=status.HTTP_200_OK,
    summary="Get Emergency Medical Facilities [DEMO DATA]",
    description="Retrieves hospitals, trauma centers, and medical posts with bed capacities.",
)
def get_hospitals(
    city_id: Optional[str] = Query("AHMEDABAD", description="Filter by city identifier"),
    zone_id: Optional[str] = Query(None, description="Optional zone ID filter"),
) -> List[HospitalFacility]:
    """Retrieve hospital facilities."""
    return CityGISRepository.get_hospitals(city_id=city_id, zone_id=zone_id)


@router.get(
    "/shelters",
    response_model=List[ShelterFacility],
    status_code=status.HTTP_200_OK,
    summary="Get Designated Evacuation Shelters [DEMO DATA]",
    description="Retrieves disaster relief camps and emergency shelters with occupancy capacities.",
)
def get_shelters(
    city_id: Optional[str] = Query("AHMEDABAD", description="Filter by city identifier"),
    zone_id: Optional[str] = Query(None, description="Optional zone ID filter"),
) -> List[ShelterFacility]:
    """Retrieve evacuation shelter facilities."""
    return CityGISRepository.get_shelters(city_id=city_id, zone_id=zone_id)


@router.get(
    "/roads",
    response_model=List[RoadSegment],
    status_code=status.HTTP_200_OK,
    summary="Get Road Network and Evacuation Routes [DEMO DATA]",
    description="Retrieves road network segments with geometry and evacuation corridor designations.",
)
def get_roads(
    city_id: Optional[str] = Query("AHMEDABAD", description="Filter by city identifier"),
    zone_id: Optional[str] = Query(None, description="Optional zone ID filter"),
    evacuation_only: bool = Query(False, description="Filter for designated emergency evacuation corridors only"),
) -> List[RoadSegment]:
    """Retrieve road network links."""
    return CityGISRepository.get_roads(city_id=city_id, zone_id=zone_id, evacuation_only=evacuation_only)


@router.get(
    "/population",
    response_model=Dict[str, int],
    status_code=status.HTTP_200_OK,
    summary="Get Ward Population Demographics [DEMO DATA]",
    description="Retrieves ward-level resident population counts.",
)
def get_population(
    city_id: Optional[str] = Query("AHMEDABAD", description="Filter by city identifier"),
) -> Dict[str, int]:
    """Retrieve zone population mapping."""
    return CityGISRepository.get_population(city_id=city_id)


@router.get(
    "/resources",
    response_model=ResourceQuantity,
    status_code=status.HTTP_200_OK,
    summary="Get Central Emergency Depot Stockpiles [DEMO DATA]",
    description="Retrieves total available emergency stockpile quantities across municipal depots.",
)
def get_resources(
    city_id: Optional[str] = Query("AHMEDABAD", description="Filter by city identifier"),
) -> ResourceQuantity:
    """Retrieve depot resource quantities."""
    return CityGISRepository.get_resources(city_id=city_id)
