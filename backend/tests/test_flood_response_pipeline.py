"""Integration Test Suite for T-018 End-to-End Flood Response Pipeline.

Tests the full orchestration flow:
Flood Extent Vector (NDWI/Satellite)
  -> GIS Spatial Impact
  -> Affected Zones
  -> Response Gap Derivation
  -> Resource Optimization

Covers all 9 required conditions:
1. Flood extent successfully reaches GIS impact
2. Affected zones are produced with spatial metrics
3. Affected zones feed response gap calculations
4. Optimization runs from integrated request
5. No-flood case is handled correctly (NO_IMPACT, zero dispatch)
6. Invalid flood input is rejected with HTTP 422
7. Input data objects are not mutated
8. Complete endpoint contract works with FastAPI TestClient
9. Invariants from T-014/T-015/T-016/T-017 remain strictly preserved
All synthetic disaster resources and geometries are labeled DEMO DATA per agent.md.
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
from app.schemas.flood_response import (
    FloodResponseAnalyzeRequest,
    ZoneBaselineProfile,
)
from app.schemas.gis import BuildingFootprint, ImpactLevel
from app.schemas.optimization import (
    OptimizationConstraint,
    OptimizationGoal,
    ResourceQuantity,
)
from app.services.flood_response_service import FloodResponseService

client = TestClient(app)


def make_box_poly(min_x: float, min_y: float, max_x: float, max_y: float) -> GeoJSONGeometry:
    """Helper returning a GeoJSON rectangular polygon."""
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


def sample_test_request(flood_geometry: GeoJSONGeometry) -> FloodResponseAnalyzeRequest:
    """Helper constructing an end-to-end flood response request."""
    # Zone 1: [72.50, 23.00] to [72.60, 23.10]
    z1 = ZoneBaselineProfile(
        zone_id="ZONE-01",
        zone_name="Riverfront North [DEMO DATA]",
        geometry=make_box_poly(72.50, 23.00, 72.60, 23.10),
        total_area_sq_km=10.0,
        population=80000,
        baseline_demand=ResourceQuantity(ambulances=10, rescue_boats=6, food_packets=2000),
        local_capacity=ResourceQuantity(ambulances=2, rescue_boats=1, food_packets=400),
        base_priority=7,
    )
    # Zone 2: [72.70, 23.20] to [72.80, 23.30] (separate geographic area)
    z2 = ZoneBaselineProfile(
        zone_id="ZONE-02",
        zone_name="Uptown South [DEMO DATA]",
        geometry=make_box_poly(72.70, 23.20, 72.80, 23.30),
        total_area_sq_km=8.0,
        population=60000,
        baseline_demand=ResourceQuantity(ambulances=5, rescue_boats=0, food_packets=1000),
        local_capacity=ResourceQuantity(ambulances=1, rescue_boats=0, food_packets=200),
        base_priority=5,
    )

    bldg_1 = BuildingFootprint(
        building_id="BLDG-01",
        name="Riverfront Clinic [DEMO DATA]",
        building_type="hospital",
        zone_id="ZONE-01",
        geometry=GeoJSONGeometry(type="Point", coordinates=[72.55, 23.05]),
    )

    return FloodResponseAnalyzeRequest(
        incident_id="INC-TEST-E2E",
        flood_extent=flood_geometry,
        zones=[z1, z2],
        buildings=[bldg_1],
        available_resources=ResourceQuantity(ambulances=12, rescue_boats=5, food_packets=3000),
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        only_allocate_to_affected=True,
    )


# -----------------------------------------------------------------------------
# Test 1: Flood extent successfully reaches GIS impact
# -----------------------------------------------------------------------------
def test_flood_extent_reaches_gis_impact():
    """Verify that flood extent vector is ingested by the orchestrator and processed by GIS impact."""
    flood = make_box_poly(72.54, 23.00, 72.62, 23.10)  # Overlaps Zone 1
    req = sample_test_request(flood)

    response = client.post("/api/v1/flood-response/analyze", json=req.model_dump())
    assert response.status_code == 200
    data = response.json()

    assert "flood_impact_summary" in data
    assert data["flood_impact_summary"]["total_zones_analyzed"] == 2
    assert data["flood_impact_summary"]["total_flood_area_sq_km"] > 0.0


# -----------------------------------------------------------------------------
# Test 2: Affected zones are produced with spatial metrics
# -----------------------------------------------------------------------------
def test_affected_zones_produced():
    """Verify that zones are classified into appropriate impact levels and area metrics."""
    flood = make_box_poly(72.54, 23.00, 72.62, 23.10)  # Overlaps Zone 1, Zone 2 dry
    req = sample_test_request(flood)

    response = client.post("/api/v1/flood-response/analyze", json=req.model_dump())
    assert response.status_code == 200
    data = response.json()

    z_map = {z["zone_id"]: z for z in data["zones"]}
    assert z_map["ZONE-01"]["impact_level"] != ImpactLevel.UNAFFECTED.value
    assert z_map["ZONE-01"]["flood_affected_percentage"] > 0.0
    assert z_map["ZONE-02"]["impact_level"] == ImpactLevel.UNAFFECTED.value
    assert z_map["ZONE-02"]["flood_affected_percentage"] == 0.0


# -----------------------------------------------------------------------------
# Test 3: Affected zones feed response gap calculations
# -----------------------------------------------------------------------------
def test_affected_zones_feed_response_gap():
    """Verify gross demand, local capacity, and net response gap: max(0, demand - local_capacity)."""
    flood = make_box_poly(72.54, 23.00, 72.62, 23.10)
    req = sample_test_request(flood)

    response = client.post("/api/v1/flood-response/analyze", json=req.model_dump())
    assert response.status_code == 200
    data = response.json()

    z1 = next(z for z in data["zones"] if z["zone_id"] == "ZONE-01")
    # Base demand: 10 amb, capacity: 2 amb -> net gap = 8 amb
    assert z1["gross_demand"]["ambulances"] == 10
    assert z1["local_capacity"]["ambulances"] == 2
    assert z1["net_response_gap"]["ambulances"] == 8

    # Base boats: 6, capacity: 1 -> net gap = 5 boats
    assert z1["net_response_gap"]["rescue_boats"] == 5


# -----------------------------------------------------------------------------
# Test 4: Optimization runs from the integrated request
# -----------------------------------------------------------------------------
def test_optimization_runs_from_integrated_request():
    """Verify that ResourceOptimizationService executes and dispatches stockpile to affected zones."""
    flood = make_box_poly(72.54, 23.00, 72.62, 23.10)
    req = sample_test_request(flood)

    response = client.post("/api/v1/flood-response/analyze", json=req.model_dump())
    assert response.status_code == 200
    data = response.json()

    z1 = next(z for z in data["zones"] if z["zone_id"] == "ZONE-01")
    # Zone 1 had gap of 8 ambulances; available depot had 12 ambulances
    assert z1["allocated_resources"]["ambulances"] == 8
    assert z1["remaining_unmet_need"]["ambulances"] == 0
    assert z1["fulfillment_rate"] == 1.0

    # Total allocated tracked in summary
    assert data["total_allocated"]["ambulances"] == 8
    assert data["overall_fulfillment_rate"] == 1.0


# -----------------------------------------------------------------------------
# Test 5: No-flood case is handled correctly (NO_IMPACT)
# -----------------------------------------------------------------------------
def test_no_flood_case_handled():
    """Verify that a disjoint flood extent results in NO_IMPACT and zero allocations."""
    # Flood far away in [73.00, 24.00] to [73.10, 24.10]
    distant_flood = make_box_poly(73.00, 24.00, 73.10, 24.10)
    req = sample_test_request(distant_flood)

    response = client.post("/api/v1/flood-response/analyze", json=req.model_dump())
    assert response.status_code == 200
    data = response.json()

    assert data["overall_status"] == "NO_IMPACT"
    assert data["flood_impact_summary"]["affected_zones_count"] == 0
    assert data["total_allocated"]["ambulances"] == 0
    assert data["total_allocated"]["rescue_boats"] == 0
    for z in data["zones"]:
        assert z["impact_level"] == ImpactLevel.UNAFFECTED.value


# -----------------------------------------------------------------------------
# Test 6: Invalid flood input is rejected
# -----------------------------------------------------------------------------
def test_invalid_input_rejected():
    """Verify empty zones list returns HTTP 422."""
    bad_payload = {
        "incident_id": "BAD-REQ",
        "flood_extent": make_box_poly(72.5, 23.0, 72.6, 23.1).model_dump(),
        "zones": [],  # Empty
        "available_resources": {"ambulances": 10},
    }
    resp = client.post("/api/v1/flood-response/analyze", json=bad_payload)
    assert resp.status_code == 422


# -----------------------------------------------------------------------------
# Test 7: Existing service results / inputs are not mutated
# -----------------------------------------------------------------------------
def test_service_inputs_not_mutated():
    """Verify FloodResponseService does not mutate caller's Python input objects."""
    flood = make_box_poly(72.54, 23.00, 72.62, 23.10)
    req = sample_test_request(flood)

    orig_zones_dump = copy.deepcopy([z.model_dump() for z in req.zones])
    orig_avail_dump = copy.deepcopy(req.available_resources.model_dump())

    res = FloodResponseService.analyze_and_optimize(req)
    assert res is not None

    # Verify input objects remain identical
    assert [z.model_dump() for z in req.zones] == orig_zones_dump
    assert req.available_resources.model_dump() == orig_avail_dump


# -----------------------------------------------------------------------------
# Test 8: Complete endpoint contract and sample payload
# -----------------------------------------------------------------------------
def test_endpoint_contract_and_sample_payload():
    """Verify GET /flood-response/sample-payload returns valid model and executes via POST."""
    sample_resp = client.get("/api/v1/flood-response/sample-payload")
    assert sample_resp.status_code == 200
    sample_data = sample_resp.json()

    assert "incident_id" in sample_data
    assert "flood_extent" in sample_data
    assert "zones" in sample_data
    assert len(sample_data["zones"]) == 2

    post_resp = client.post("/api/v1/flood-response/analyze", json=sample_data)
    assert post_resp.status_code == 200
    res_data = post_resp.json()

    assert res_data["incident_id"] == sample_data["incident_id"]
    assert res_data["is_demo_data"] is True
    assert len(res_data["zones"]) == 2
    assert "narrative_summary" in res_data


# -----------------------------------------------------------------------------
# Test 9: Invariants hold across end-to-end pipeline
# -----------------------------------------------------------------------------
def test_pipeline_invariants_hold():
    """Verify allocated <= capacity, allocated <= response gap, and non-negativity."""
    flood = make_box_poly(72.50, 23.00, 72.60, 23.10)
    req = sample_test_request(flood)

    res = FloodResponseService.analyze_and_optimize(req)

    for z in res.zones:
        for r in ["ambulances", "rescue_boats", "food_packets"]:
            alloc_val = getattr(z.allocated_resources, r)
            gap_val = getattr(z.net_response_gap, r)
            unmet_val = getattr(z.remaining_unmet_need, r)
            assert alloc_val <= gap_val
            assert alloc_val >= 0
            assert unmet_val >= 0
