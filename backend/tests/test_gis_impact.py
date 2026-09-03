"""Comprehensive Test Suite for T-017 Flood Impact & GIS Zone Intelligence.

Covers all 9 required test conditions:
1. No flood intersection (0.0% area flooded, UNAFFECTED)
2. Partial ward intersection (proportional flooded area & percentage)
3. Full ward intersection (100.0% area flooded, CRITICAL)
4. Multiple wards evaluated concurrently with heterogeneous impact
5. Building intersection (correctly flags AFFECTED/UNAFFECTED, never 'destroyed')
6. Deterministic impact classification tiers (UNAFFECTED, LOW, MODERATE, HIGH, CRITICAL)
7. Invalid geometry/input handling (empty zones, malformed schemas rejected with 422)
8. API endpoint contract works end-to-end with FastAPI TestClient
9. Original input data is strictly not mutated
All synthetic disaster geometries are labeled TEST/DEMO DATA per agent.md.
"""
import copy
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.flood import (
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONGeometry,
)
from app.schemas.gis import (
    BuildingFootprint,
    FloodImpactRequest,
    ImpactLevel,
    WardZoneGeometry,
)
from app.services.gis_service import GISFloodImpactService

client = TestClient(app)


def make_box_geometry(min_x: float, min_y: float, max_x: float, max_y: float) -> GeoJSONGeometry:
    """Helper creating a rectangular GeoJSON Polygon."""
    return GeoJSONGeometry(
        type="Polygon",
        coordinates=[
            [
                [min_x, min_y],
                [max_x, min_y],
                [max_x, max_y],
                [min_x, max_y],
                [min_x, min_y],
            ]
        ],
    )


# -----------------------------------------------------------------------------
# Test 1: No flood intersection
# -----------------------------------------------------------------------------
def test_gis_no_flood_intersection():
    """Verify that a flood extent completely outside a ward results in 0% flooded and UNAFFECTED."""
    # Ward in [72.50, 23.00] to [72.55, 23.05]
    ward = WardZoneGeometry(
        zone_id="ZONE-01",
        zone_name="Dry Ward [TEST DATA]",
        total_area_sq_km=10.0,
        geometry=make_box_geometry(72.50, 23.00, 72.55, 23.05),
    )
    # Flood far away in [72.80, 23.30] to [72.85, 23.35]
    flood_fc = GeoJSONFeatureCollection(
        features=[
            GeoJSONFeature(
                geometry=make_box_geometry(72.80, 23.30, 72.85, 23.35),
                properties={"name": "Distant Flood"},
            )
        ]
    )

    request = FloodImpactRequest(
        incident_id="INC-NO-INTERSECT",
        flood_extent=flood_fc,
        zones=[ward],
    )

    response = client.post("/api/v1/gis/impact", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    z0 = data["zone_impacts"][0]
    assert z0["flood_affected_area_sq_km"] == 0.0
    assert z0["flood_affected_percentage"] == 0.0
    assert z0["impact_level"] == ImpactLevel.UNAFFECTED.value
    assert data["summary"]["affected_zones_count"] == 0
    assert data["summary"]["highest_impact_level"] == ImpactLevel.UNAFFECTED.value


# -----------------------------------------------------------------------------
# Test 2: Partial ward intersection
# -----------------------------------------------------------------------------
def test_gis_partial_ward_intersection():
    """Verify that a flood extent overlapping half the ward calculates ~50% flooded area."""
    # Ward: [72.50, 23.00] to [72.60, 23.10] (width 0.10, height 0.10)
    ward = WardZoneGeometry(
        zone_id="ZONE-PARTIAL",
        zone_name="Partial Flood Ward [TEST DATA]",
        geometry=make_box_geometry(72.50, 23.00, 72.60, 23.10),
    )
    # Flood: [72.55, 23.00] to [72.65, 23.10] (overlaps the eastern half: width 0.05, height 0.10)
    flood = make_box_geometry(72.55, 23.00, 72.65, 23.10)

    request = FloodImpactRequest(
        incident_id="INC-PARTIAL",
        flood_extent=flood,
        zones=[ward],
    )

    response = client.post("/api/v1/gis/impact", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    z0 = data["zone_impacts"][0]
    assert z0["flood_affected_area_sq_km"] > 0.0
    # Overlap is roughly 50% (allow tolerance for numerical Riemann integration)
    assert 45.0 <= z0["flood_affected_percentage"] <= 55.0
    # ~50% falls in HIGH impact tier (30% < pct <= 60%)
    assert z0["impact_level"] == ImpactLevel.HIGH.value


# -----------------------------------------------------------------------------
# Test 3: Full ward intersection
# -----------------------------------------------------------------------------
def test_gis_full_ward_intersection():
    """Verify that a flood extent completely enveloping a ward yields 100% flooded and CRITICAL."""
    # Ward: [72.52, 23.02] to [72.56, 23.06]
    ward = WardZoneGeometry(
        zone_id="ZONE-FULL",
        zone_name="Submerged Ward [TEST DATA]",
        total_area_sq_km=5.0,
        geometry=make_box_geometry(72.52, 23.02, 72.56, 23.06),
    )
    # Flood envelopes the ward: [72.50, 23.00] to [72.60, 23.10]
    flood = make_box_geometry(72.50, 23.00, 72.60, 23.10)

    request = FloodImpactRequest(
        incident_id="INC-FULL",
        flood_extent=flood,
        zones=[ward],
    )

    response = client.post("/api/v1/gis/impact", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    z0 = data["zone_impacts"][0]
    assert z0["flood_affected_percentage"] == 100.0
    assert z0["flood_affected_area_sq_km"] == z0["total_area_sq_km"]
    assert z0["impact_level"] == ImpactLevel.CRITICAL.value


# -----------------------------------------------------------------------------
# Test 4: Multiple wards evaluated concurrently
# -----------------------------------------------------------------------------
def test_gis_multiple_wards():
    """Verify multiple wards receive independent, accurate flood metrics."""
    # Zone 1: Dry (outside flood)
    w1 = WardZoneGeometry(
        zone_id="ZONE-W1",
        zone_name="Zone One [TEST DATA]",
        geometry=make_box_geometry(72.40, 23.00, 72.45, 23.05),
    )
    # Zone 2: Partially flooded
    w2 = WardZoneGeometry(
        zone_id="ZONE-W2",
        zone_name="Zone Two [TEST DATA]",
        geometry=make_box_geometry(72.50, 23.00, 72.60, 23.10),
    )
    # Zone 3: Fully flooded
    w3 = WardZoneGeometry(
        zone_id="ZONE-W3",
        zone_name="Zone Three [TEST DATA]",
        geometry=make_box_geometry(72.55, 23.02, 72.58, 23.05),
    )
    # Flood: [72.54, 23.00] to [72.62, 23.10]
    flood = make_box_geometry(72.54, 23.00, 72.62, 23.10)

    request = FloodImpactRequest(
        incident_id="INC-MULTI-ZONE",
        flood_extent=flood,
        zones=[w1, w2, w3],
    )

    response = client.post("/api/v1/gis/impact", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    assert len(data["zone_impacts"]) == 3
    res_map = {z["zone_id"]: z for z in data["zone_impacts"]}

    assert res_map["ZONE-W1"]["impact_level"] == ImpactLevel.UNAFFECTED.value
    assert res_map["ZONE-W1"]["flood_affected_percentage"] == 0.0

    assert res_map["ZONE-W2"]["flood_affected_percentage"] > 0.0
    assert res_map["ZONE-W2"]["impact_level"] in (ImpactLevel.LOW.value, ImpactLevel.MODERATE.value, ImpactLevel.HIGH.value)

    assert res_map["ZONE-W3"]["flood_affected_percentage"] == 100.0
    assert res_map["ZONE-W3"]["impact_level"] == ImpactLevel.CRITICAL.value

    assert data["summary"]["total_zones_analyzed"] == 3
    assert data["summary"]["affected_zones_count"] == 2


# -----------------------------------------------------------------------------
# Test 5: Building intersection where building data exists
# -----------------------------------------------------------------------------
def test_gis_building_intersection():
    """Verify buildings are identified as AFFECTED or UNAFFECTED, never labeled 'destroyed'."""
    ward = WardZoneGeometry(
        zone_id="ZONE-BLDG",
        zone_name="Civic District [TEST DATA]",
        geometry=make_box_geometry(72.50, 23.00, 72.60, 23.10),
    )
    # Flood is in eastern half [72.55, 23.00] to [72.60, 23.10]
    flood = make_box_geometry(72.55, 23.00, 72.60, 23.10)

    # Building 1: inside flooded area (lon 72.57, lat 23.05)
    b1 = BuildingFootprint(
        building_id="BLDG-01",
        name="District General Hospital [TEST DATA]",
        building_type="hospital",
        zone_id="ZONE-BLDG",
        geometry=GeoJSONGeometry(type="Point", coordinates=[72.57, 23.05]),
    )
    # Building 2: outside flooded area (lon 72.52, lat 23.05)
    b2 = BuildingFootprint(
        building_id="BLDG-02",
        name="Government Secondary School [TEST DATA]",
        building_type="school",
        zone_id="ZONE-BLDG",
        geometry=GeoJSONGeometry(type="Point", coordinates=[72.52, 23.05]),
    )

    request = FloodImpactRequest(
        incident_id="INC-BLDGS",
        flood_extent=flood,
        zones=[ward],
        buildings=[b1, b2],
    )

    response = client.post("/api/v1/gis/impact", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    z0 = data["zone_impacts"][0]
    assert z0["total_building_count"] == 2
    assert z0["affected_building_count"] == 1
    assert len(z0["affected_buildings"]) == 1

    aff_bldg = z0["affected_buildings"][0]
    assert aff_bldg["building_id"] == "BLDG-01"
    assert aff_bldg["is_affected"] is True
    assert aff_bldg["inundation_status"] == "AFFECTED"  # Terminology check: never 'destroyed'
    assert "destroyed" not in aff_bldg["inundation_status"].lower()


# -----------------------------------------------------------------------------
# Test 6: Deterministic impact classification tiers
# -----------------------------------------------------------------------------
def test_gis_deterministic_impact_classification():
    """Verify deterministic thresholds: UNAFFECTED (0%), LOW (<=10%), MODERATE (<=30%), HIGH (<=60%), CRITICAL (>60%)."""
    classify = GISFloodImpactService._classify_impact_level

    assert classify(0.0, 0) == ImpactLevel.UNAFFECTED
    assert classify(0.0, 1) == ImpactLevel.LOW  # Boundary facility hit
    assert classify(5.0, 0) == ImpactLevel.LOW
    assert classify(10.0, 0) == ImpactLevel.LOW
    assert classify(15.0, 0) == ImpactLevel.MODERATE
    assert classify(30.0, 0) == ImpactLevel.MODERATE
    assert classify(45.0, 0) == ImpactLevel.HIGH
    assert classify(60.0, 0) == ImpactLevel.HIGH
    assert classify(65.0, 0) == ImpactLevel.CRITICAL
    assert classify(100.0, 0) == ImpactLevel.CRITICAL


# -----------------------------------------------------------------------------
# Test 7: Invalid geometry / input handling
# -----------------------------------------------------------------------------
def test_gis_invalid_input_handling():
    """Verify empty zones list is rejected with HTTP 422."""
    bad_request = {
        "incident_id": "BAD-REQ",
        "flood_extent": {
            "type": "Polygon",
            "coordinates": [[[72.5, 23.0], [72.6, 23.0], [72.6, 23.1], [72.5, 23.1], [72.5, 23.0]]],
        },
        "zones": [],  # Invalid: empty zones
    }
    resp = client.post("/api/v1/gis/impact", json=bad_request)
    assert resp.status_code == 422


# -----------------------------------------------------------------------------
# Test 8: API endpoint contract and sample payload
# -----------------------------------------------------------------------------
def test_gis_api_contract_and_sample_payload():
    """Verify /gis/sample-payload returns valid model and executes successfully via POST /gis/impact."""
    get_resp = client.get("/api/v1/gis/sample-payload")
    assert get_resp.status_code == 200
    sample_data = get_resp.json()

    assert "incident_id" in sample_data
    assert "flood_extent" in sample_data
    assert "zones" in sample_data
    assert len(sample_data["zones"]) == 2

    post_resp = client.post("/api/v1/gis/impact", json=sample_data)
    assert post_resp.status_code == 200
    res_data = post_resp.json()

    assert res_data["incident_id"] == sample_data["incident_id"]
    assert res_data["is_demo_data"] is True
    assert len(res_data["zone_impacts"]) == 2
    assert "summary" in res_data
    assert res_data["summary"]["total_zones_analyzed"] == 2


# -----------------------------------------------------------------------------
# Test 9: Original input data is not mutated
# -----------------------------------------------------------------------------
def test_gis_original_input_not_mutated():
    """Verify GISFloodImpactService.assess_impact does not alter input objects in-place."""
    ward = WardZoneGeometry(
        zone_id="ZONE-IMMUTABLE",
        zone_name="Preserved Ward [TEST DATA]",
        total_area_sq_km=12.5,
        geometry=make_box_geometry(72.50, 23.00, 72.60, 23.10),
    )
    bldg = BuildingFootprint(
        building_id="BLDG-IMMUTABLE",
        geometry=GeoJSONGeometry(type="Point", coordinates=[72.55, 23.05]),
    )
    flood = make_box_geometry(72.52, 23.02, 72.58, 23.08)

    orig_ward_dict = copy.deepcopy(ward.model_dump())
    orig_bldg_dict = copy.deepcopy(bldg.model_dump())

    request = FloodImpactRequest(
        incident_id="INC-IMMUTABLE",
        flood_extent=flood,
        zones=[ward],
        buildings=[bldg],
    )

    # Call service directly
    result = GISFloodImpactService.assess_impact(request)
    assert result is not None

    # Check that original input objects are identical
    assert ward.model_dump() == orig_ward_dict
    assert bldg.model_dump() == orig_bldg_dict
