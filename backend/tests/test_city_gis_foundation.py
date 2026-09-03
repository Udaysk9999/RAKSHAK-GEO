"""Test suite for PostGIS + City GIS Data Foundation.

Covers:
1. Configuration & schema validity
2. Ward geometry model
3. Building geometry model
4. Point/Line/Polygon geometry handling
5. City/Dataset metadata
6. Repository/service compatibility (GISFloodImpactService & FloodResponseService)
7. DEMO/TEST seed loading
8. Data access API endpoints (/api/v1/city-data/*)
All synthetic disaster resources and geometries are labeled DEMO DATA per agent.md.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import check_database_connectivity
from app.main import app
from app.schemas.city_gis import (
    CityMetadata,
    DatasetSource,
    GeometryType,
    HospitalFacility,
    RoadSegment,
    ShelterFacility,
)
from app.schemas.flood import GeoJSONGeometry
from app.schemas.flood_response import FloodResponseAnalyzeRequest, ZoneBaselineProfile
from app.schemas.gis import BuildingFootprint, FloodImpactRequest, WardZoneGeometry
from app.schemas.optimization import OptimizationGoal, ResourceQuantity
from app.services.city_gis_repository import CityGISRepository
from app.services.flood_response_service import FloodResponseService
from app.services.gis_service import GISFloodImpactService

client = TestClient(app)


# -----------------------------------------------------------------------------
# 1. Configuration & Schema Validity
# -----------------------------------------------------------------------------
def test_database_configuration_and_connectivity_status():
    """Verify database configuration settings and connectivity diagnostics."""
    assert hasattr(settings, "POSTGRES_SERVER")
    assert hasattr(settings, "POSTGRES_PORT")
    assert hasattr(settings, "POSTGRES_DB")
    assert hasattr(settings, "DATABASE_URL")
    assert "postgresql://" in settings.DATABASE_URL

    status = check_database_connectivity()
    assert "database_engine" in status
    assert "is_connected" in status
    assert isinstance(status["is_connected"], bool)
    assert "status" in status
    assert "notes" in status


# -----------------------------------------------------------------------------
# 2. Ward Geometry Model
# -----------------------------------------------------------------------------
def test_ward_geometry_model():
    """Verify WardZoneGeometry model validation and polygon coordinates."""
    ward = WardZoneGeometry(
        zone_id="ZONE-TEST-01",
        zone_name="Test Ward [DEMO DATA]",
        total_area_sq_km=5.25,
        population=50000,
        geometry=GeoJSONGeometry(
            type="Polygon",
            coordinates=[
                [
                    [72.50, 23.00],
                    [72.60, 23.00],
                    [72.60, 23.10],
                    [72.50, 23.10],
                    [72.50, 23.00],
                ]
            ],
        ),
    )
    assert ward.zone_id == "ZONE-TEST-01"
    assert ward.geometry.type == "Polygon"
    assert len(ward.geometry.coordinates[0]) == 5


# -----------------------------------------------------------------------------
# 3. Building Geometry Model
# -----------------------------------------------------------------------------
def test_building_geometry_model():
    """Verify BuildingFootprint model with Point and Polygon coordinates."""
    # Point building
    bldg_pt = BuildingFootprint(
        building_id="BLDG-PT-01",
        name="Clinic Post [DEMO DATA]",
        building_type="hospital",
        geometry=GeoJSONGeometry(type="Point", coordinates=[72.55, 23.05]),
    )
    assert bldg_pt.geometry.type == "Point"
    assert bldg_pt.geometry.coordinates == [72.55, 23.05]

    # Polygon building
    bldg_poly = BuildingFootprint(
        building_id="BLDG-POLY-02",
        name="Civic Center [DEMO DATA]",
        building_type="civic",
        geometry=GeoJSONGeometry(
            type="Polygon",
            coordinates=[
                [
                    [72.551, 23.051],
                    [72.553, 23.051],
                    [72.553, 23.053],
                    [72.551, 23.053],
                    [72.551, 23.051],
                ]
            ],
        ),
    )
    assert bldg_poly.geometry.type == "Polygon"


# -----------------------------------------------------------------------------
# 4. Point, LineString, and Polygon Geometry Handling
# -----------------------------------------------------------------------------
def test_point_line_polygon_geometry_handling():
    """Verify typed models for Point (Hospital/Shelter), LineString (Road), and Polygon."""
    hosp = HospitalFacility(
        hospital_id="HOSP-T1",
        name="Trauma Center [DEMO DATA]",
        zone_id="ZONE-01",
        bed_capacity=80,
        geometry=GeoJSONGeometry(type="Point", coordinates=[72.56, 23.03]),
    )
    assert hosp.geometry.type == GeometryType.POINT.value

    shelter = ShelterFacility(
        shelter_id="SHELTER-T1",
        name="Relief Center [DEMO DATA]",
        zone_id="ZONE-01",
        occupancy_capacity=400,
        geometry=GeoJSONGeometry(type="Point", coordinates=[72.57, 23.04]),
    )
    assert shelter.geometry.type == GeometryType.POINT.value

    road = RoadSegment(
        road_id="ROAD-T1",
        name="Main Egress Highway [DEMO DATA]",
        is_evacuation_route=True,
        geometry=GeoJSONGeometry(
            type="LineString",
            coordinates=[[72.50, 23.00], [72.55, 23.05], [72.60, 23.10]],
        ),
    )
    assert road.geometry.type == GeometryType.LINESTRING.value
    assert road.is_evacuation_route is True


# -----------------------------------------------------------------------------
# 5. City and Dataset Metadata
# -----------------------------------------------------------------------------
def test_city_and_dataset_metadata():
    """Verify CityMetadata and DatasetSource models."""
    city = CityMetadata(
        city_id="AHMEDABAD",
        city_name="Ahmedabad [DEMO DATA]",
        state="Gujarat",
        country="India",
        crs="EPSG:4326",
        bounding_box=[72.50, 22.95, 72.68, 23.12],
    )
    assert city.city_id == "AHMEDABAD"
    assert city.crs == "EPSG:4326"

    src = DatasetSource(
        source_id="SRC-AMC-2026",
        name="Ahmedabad Municipal Boundary Layer",
        feature_count=64,
    )
    assert src.source_id == "SRC-AMC-2026"
    assert src.feature_count == 64


# -----------------------------------------------------------------------------
# 6. Repository Data Access & Seed Loading
# -----------------------------------------------------------------------------
def test_city_gis_repository_seed_loading():
    """Verify loading from data/city/test/ahmedabad_demo_city.json."""
    wards = CityGISRepository.get_ward_geometries()
    assert len(wards) >= 2
    assert all(isinstance(w, WardZoneGeometry) for w in wards)

    bldgs = CityGISRepository.get_building_footprints()
    assert len(bldgs) >= 2

    hosps = CityGISRepository.get_hospitals()
    assert len(hosps) >= 2
    assert all(h.bed_capacity > 0 for h in hosps)

    shelters = CityGISRepository.get_shelters()
    assert len(shelters) >= 2

    roads = CityGISRepository.get_roads()
    assert len(roads) >= 2

    pop_map = CityGISRepository.get_population()
    assert len(pop_map) >= 2
    assert all(p > 0 for p in pop_map.values())

    res = CityGISRepository.get_resources()
    assert isinstance(res, ResourceQuantity)
    assert res.ambulances > 0


# -----------------------------------------------------------------------------
# 7. Compatibility with GISFloodImpactService
# -----------------------------------------------------------------------------
def test_compatibility_with_gis_impact_service():
    """Verify repository wards feed directly into GISFloodImpactService without transformation."""
    wards = CityGISRepository.get_ward_geometries()
    bldgs = CityGISRepository.get_building_footprints()

    flood_poly = GeoJSONGeometry(
        type="Polygon",
        coordinates=[
            [
                [72.56, 23.02],
                [72.58, 23.02],
                [72.58, 23.05],
                [72.56, 23.05],
                [72.56, 23.02],
            ]
        ],
    )

    gis_req = FloodImpactRequest(
        incident_id="INC-COMPAT-TEST",
        flood_extent=flood_poly,
        zones=wards,
        buildings=bldgs,
    )

    gis_res = GISFloodImpactService.assess_impact(gis_req)
    assert gis_res.summary.total_zones_analyzed == len(wards)
    assert len(gis_res.zone_impacts) == len(wards)


# -----------------------------------------------------------------------------
# 8. Compatibility with FloodResponseService
# -----------------------------------------------------------------------------
def test_compatibility_with_flood_response_pipeline():
    """Verify repository data feeds into end-to-end flood response orchestrator."""
    wards = CityGISRepository.get_ward_geometries()
    bldgs = CityGISRepository.get_building_footprints()
    avail = CityGISRepository.get_resources()

    # Convert repository wards to ZoneBaselineProfiles
    profiles = [
        ZoneBaselineProfile(
            zone_id=w.zone_id,
            zone_name=w.zone_name,
            geometry=w.geometry,
            total_area_sq_km=w.total_area_sq_km,
            population=w.population,
            base_priority=6,
        )
        for w in wards
    ]

    flood_poly = GeoJSONGeometry(
        type="Polygon",
        coordinates=[
            [
                [72.56, 23.02],
                [72.58, 23.02],
                [72.58, 23.05],
                [72.56, 23.05],
                [72.56, 23.02],
            ]
        ],
    )

    e2e_req = FloodResponseAnalyzeRequest(
        incident_id="INC-COMPAT-E2E",
        flood_extent=flood_poly,
        zones=profiles,
        buildings=bldgs,
        available_resources=avail,
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
    )

    e2e_res = FloodResponseService.analyze_and_optimize(e2e_req)
    assert e2e_res.incident_id == "INC-COMPAT-E2E"
    assert len(e2e_res.zones) == len(wards)
    assert e2e_res.total_allocated.ambulances >= 0


# -----------------------------------------------------------------------------
# 9. City Data API Endpoints
# -----------------------------------------------------------------------------
def test_city_data_endpoints():
    """Verify all /api/v1/city-data/* endpoints return HTTP 200 with typed models."""
    routes = [
        ("/api/v1/city-data/status", 200),
        ("/api/v1/city-data/summary", 200),
        ("/api/v1/city-data/wards", 200),
        ("/api/v1/city-data/buildings", 200),
        ("/api/v1/city-data/hospitals", 200),
        ("/api/v1/city-data/shelters", 200),
        ("/api/v1/city-data/roads", 200),
        ("/api/v1/city-data/population", 200),
        ("/api/v1/city-data/resources", 200),
    ]

    for path, expected_status in routes:
        resp = client.get(path)
        assert resp.status_code == expected_status, f"Failed route {path}"
        data = resp.json()
        assert data is not None
