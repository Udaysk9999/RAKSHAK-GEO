"""Comprehensive Test Suite for T-016 Future Response Gap Timeline Engine.

Tests all 12 required conditions:
1. Baseline at time 0 is correct
2. No-change timeline remains stable
3. Increasing demand increases future response gap
4. Decreasing local capacity increases future response gap
5. Resource changes over time are reflected correctly
6. Multiple zones evaluated and tracked independently
7. Multiple resource types evaluated simultaneously
8. Timeline ordering is deterministic regardless of input order
9. Base input data is never mutated
10. T-014 optimization invariants are preserved at all time steps
11. Invalid timeline input (negative hours, empty zones) is rejected
12. API endpoint contract works end-to-end with FastAPI TestClient
All synthetic disaster resources are labeled DEMO/TEST DATA per agent.md.
"""
import copy
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.optimization import (
    OptimizationGoal,
    ResourceQuantity,
    ZoneDemand,
)
from app.schemas.timeline import (
    FutureGapTimelineRequest,
    HourlyGrowthRule,
    TimeStepProjection,
)
from app.services.timeline_service import FutureGapTimelineService

client = TestClient(app)


def make_test_zones():
    return [
        ZoneDemand(
            zone_id="ZONE-AHM-01",
            zone_name="Sabarmati Riverfront [DEMO/TEST DATA]",
            priority=9,
            severity_score=8.5,
            demand=ResourceQuantity(ambulances=15, rescue_boats=6, food_packets=2000),
            local_capacity=ResourceQuantity(ambulances=3, rescue_boats=1, food_packets=400),
        ),
        ZoneDemand(
            zone_id="ZONE-AHM-02",
            zone_name="Maninagar East [DEMO/TEST DATA]",
            priority=6,
            severity_score=6.0,
            demand=ResourceQuantity(ambulances=10, rescue_boats=3, food_packets=1200),
            local_capacity=ResourceQuantity(ambulances=2, rescue_boats=0, food_packets=200),
        ),
    ]


# -----------------------------------------------------------------------------
# Test 1: Baseline at time 0 is correct
# -----------------------------------------------------------------------------
def test_timeline_baseline_time_zero_correct():
    """Verify that T+0h accurately reproduces initial demand, local capacity, and net response gap."""
    request = FutureGapTimelineRequest(
        incident_id="INC-TEST-T0",
        base_available_resources=ResourceQuantity(ambulances=20, rescue_boats=8, food_packets=3000),
        base_zones=make_test_zones(),
        time_horizons_hours=[0.0, 6.0, 12.0],
        run_optimization=True,
    )

    response = client.post("/api/v1/future-gap/timeline", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    t0_point = data["timeline_points"][0]
    assert t0_point["time_offset_hours"] == 0.0
    assert t0_point["is_baseline"] is True

    # Total demand at T+0: 15 + 10 = 25 ambulances; 6 + 3 = 9 boats; 2000 + 1200 = 3200 food
    assert t0_point["total_demand"]["ambulances"] == 25
    assert t0_point["total_demand"]["rescue_boats"] == 9
    assert t0_point["total_demand"]["food_packets"] == 3200

    # Total local capacity at T+0: 3 + 2 = 5 ambulances; 1 + 0 = 1 boat; 400 + 200 = 600 food
    assert t0_point["total_local_capacity"]["ambulances"] == 5
    assert t0_point["total_local_capacity"]["rescue_boats"] == 1

    # Total response gap at T+0: max(0, 25 - 5) = 20 ambulances; 9 - 1 = 8 boats
    assert t0_point["total_response_gap"]["ambulances"] == 20
    assert t0_point["total_response_gap"]["rescue_boats"] == 8


# -----------------------------------------------------------------------------
# Test 2: No-change timeline remains stable
# -----------------------------------------------------------------------------
def test_timeline_no_change_remains_stable():
    """Verify that without growth rules or step shifts, timeline values remain constant across all horizons."""
    request = FutureGapTimelineRequest(
        incident_id="INC-TEST-STABLE",
        base_available_resources=ResourceQuantity(ambulances=20),
        base_zones=make_test_zones(),
        time_horizons_hours=[0.0, 6.0, 12.0, 18.0, 24.0],
        hourly_rules=[],
        step_projections=[],
    )

    response = client.post("/api/v1/future-gap/timeline", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    assert data["summary"]["gap_trend"] == "STABLE"
    assert data["summary"]["baseline_gap_units"] == data["summary"]["final_gap_units"]

    # All time horizons must have identical total response gap
    initial_gap = data["timeline_points"][0]["total_response_gap"]
    for pt in data["timeline_points"]:
        assert pt["total_response_gap"] == initial_gap


# -----------------------------------------------------------------------------
# Test 3: Increasing demand increases future response gap
# -----------------------------------------------------------------------------
def test_timeline_increasing_demand_increases_future_gap():
    """Verify that hourly demand growth expands the net response gap monotonically."""
    request = FutureGapTimelineRequest(
        incident_id="INC-TEST-DEMAND-GROWTH",
        base_available_resources=ResourceQuantity(ambulances=20),
        base_zones=make_test_zones(),
        time_horizons_hours=[0.0, 6.0, 12.0],
        hourly_rules=[
            HourlyGrowthRule(
                hourly_demand_delta={"ambulances": 5},  # Global growth: +5 ambulances/hour per zone
            )
        ],
    )

    response = client.post("/api/v1/future-gap/timeline", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    assert data["summary"]["gap_trend"] == "EXPANDING"
    assert data["summary"]["final_gap_units"] > data["summary"]["baseline_gap_units"]

    pts = data["timeline_points"]
    assert pts[0]["total_response_gap"]["ambulances"] < pts[1]["total_response_gap"]["ambulances"]
    assert pts[1]["total_response_gap"]["ambulances"] < pts[2]["total_response_gap"]["ambulances"]


# -----------------------------------------------------------------------------
# Test 4: Decreasing local capacity increases future response gap
# -----------------------------------------------------------------------------
def test_timeline_decreasing_capacity_increases_gap():
    """Verify that progressive local infrastructure decay expands the response gap."""
    # Zone 1 has local capacity of 3 ambulances
    request = FutureGapTimelineRequest(
        incident_id="INC-TEST-CAPACITY-DECAY",
        base_available_resources=ResourceQuantity(ambulances=20),
        base_zones=[
            ZoneDemand(
                zone_id="ZONE-DECAY",
                zone_name="Submerged Zone [DEMO/TEST DATA]",
                priority=8,
                severity_score=7.0,
                demand=ResourceQuantity(ambulances=10),
                local_capacity=ResourceQuantity(ambulances=6),  # Initial gap = 4
            )
        ],
        time_horizons_hours=[0.0, 3.0],
        hourly_rules=[
            HourlyGrowthRule(
                zone_id="ZONE-DECAY",
                hourly_capacity_delta={"ambulances": -2},  # Drops 2 ambulances per hour
            )
        ],
    )

    response = client.post("/api/v1/future-gap/timeline", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    pts = data["timeline_points"]
    # At T+0h: demand=10, capacity=6 -> gap=4
    assert pts[0]["total_response_gap"]["ambulances"] == 4
    # At T+3h: capacity = 6 - (2 * 3) = 0 -> gap = 10 - 0 = 10
    assert pts[1]["total_local_capacity"]["ambulances"] == 0
    assert pts[1]["total_response_gap"]["ambulances"] == 10


# -----------------------------------------------------------------------------
# Test 5: Resource changes over time are reflected correctly
# -----------------------------------------------------------------------------
def test_timeline_resource_changes_reflected():
    """Verify that a time step projection modifies available stockpile capacity at that specific horizon."""
    request = FutureGapTimelineRequest(
        incident_id="INC-TEST-STOCKPILE-SHIFT",
        base_available_resources=ResourceQuantity(ambulances=10),
        base_zones=make_test_zones(),
        time_horizons_hours=[0.0, 6.0, 12.0],
        step_projections=[
            TimeStepProjection(
                time_offset_hours=12.0,
                label="State Reserve Mobilization [DEMO/TEST DATA]",
                available_resource_deltas={"ambulances": 15},  # 10 -> 25 at T+12h
            )
        ],
    )

    response = client.post("/api/v1/future-gap/timeline", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    pts = data["timeline_points"]
    assert pts[0]["available_resources"]["ambulances"] == 10
    assert pts[1]["available_resources"]["ambulances"] == 10
    assert pts[2]["available_resources"]["ambulances"] == 25
    assert "Mobilization" in pts[2]["label"]


# -----------------------------------------------------------------------------
# Test 6: Multiple zones evaluated and tracked independently
# -----------------------------------------------------------------------------
def test_timeline_multiple_zones():
    """Verify that multiple zones with heterogeneous growth rates project accurate individual gaps."""
    request = FutureGapTimelineRequest(
        incident_id="INC-TEST-MULTI-ZONE",
        base_available_resources=ResourceQuantity(food_packets=10000),
        base_zones=make_test_zones(),
        time_horizons_hours=[0.0, 10.0],
        hourly_rules=[
            HourlyGrowthRule(
                zone_id="ZONE-AHM-01",
                hourly_demand_delta={"food_packets": 100},  # Zone 1 grows fast
            ),
            HourlyGrowthRule(
                zone_id="ZONE-AHM-02",
                hourly_demand_delta={"food_packets": 10},   # Zone 2 grows slow
            ),
        ],
    )

    response = client.post("/api/v1/future-gap/timeline", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    pt_10h = data["timeline_points"][1]
    z1 = next(z for z in pt_10h["zone_gaps"] if z["zone_id"] == "ZONE-AHM-01")
    z2 = next(z for z in pt_10h["zone_gaps"] if z["zone_id"] == "ZONE-AHM-02")

    # Zone 1: base demand 2000 + (100 * 10) = 3000. Local capacity = 400. Gap = 2600
    assert z1["demand"]["food_packets"] == 3000
    assert z1["response_gap"]["food_packets"] == 2600

    # Zone 2: base demand 1200 + (10 * 10) = 1300. Local capacity = 200. Gap = 1100
    assert z2["demand"]["food_packets"] == 1300
    assert z2["response_gap"]["food_packets"] == 1100


# -----------------------------------------------------------------------------
# Test 7: Multiple resource types evaluated simultaneously
# -----------------------------------------------------------------------------
def test_timeline_multiple_resource_types():
    """Verify all resource dimensions (ambulances, boats, food, medical, personnel) are projected concurrently."""
    request = FutureGapTimelineRequest(
        incident_id="INC-TEST-MULTI-RESOURCE",
        base_available_resources=ResourceQuantity(
            ambulances=20, rescue_boats=10, food_packets=5000, medical_kits=1000, personnel=100
        ),
        base_zones=make_test_zones(),
        time_horizons_hours=[0.0, 6.0],
        hourly_rules=[
            HourlyGrowthRule(
                hourly_demand_delta={
                    "ambulances": 2,
                    "rescue_boats": 1,
                    "food_packets": 50,
                    "medical_kits": 10,
                    "personnel": 5,
                }
            )
        ],
    )

    response = client.post("/api/v1/future-gap/timeline", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    pt = data["timeline_points"][1]
    for r in ["ambulances", "rescue_boats", "food_packets", "medical_kits"]:
        assert pt["total_demand"][r] > data["timeline_points"][0]["total_demand"][r]
        assert pt["total_response_gap"][r] > data["timeline_points"][0]["total_response_gap"][r]


# -----------------------------------------------------------------------------
# Test 8: Timeline ordering is deterministic regardless of input order
# -----------------------------------------------------------------------------
def test_timeline_ordering_deterministic():
    """Verify input horizons passed in random order are sorted deterministically in chronological order."""
    request = FutureGapTimelineRequest(
        incident_id="INC-TEST-ORDERING",
        base_available_resources=ResourceQuantity(ambulances=20),
        base_zones=make_test_zones(),
        time_horizons_hours=[24.0, 6.0, 18.0, 0.0, 12.0],  # Out of order
    )

    response = client.post("/api/v1/future-gap/timeline", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    extracted_offsets = [pt["time_offset_hours"] for pt in data["timeline_points"]]
    assert extracted_offsets == [0.0, 6.0, 12.0, 18.0, 24.0]


# -----------------------------------------------------------------------------
# Test 9: Base input data is never mutated
# -----------------------------------------------------------------------------
def test_timeline_base_input_not_mutated():
    """Verify that FutureGapTimelineService never alters the original base objects."""
    base_avail = ResourceQuantity(ambulances=15, rescue_boats=5)
    base_zones = make_test_zones()

    orig_avail_dict = copy.deepcopy(base_avail.to_dict())
    orig_z0_demand = copy.deepcopy(base_zones[0].demand.to_dict())
    orig_z0_cap = copy.deepcopy(base_zones[0].local_capacity.to_dict())

    request = FutureGapTimelineRequest(
        incident_id="INC-TEST-IMMUTABLE",
        base_available_resources=base_avail,
        base_zones=base_zones,
        time_horizons_hours=[0.0, 12.0, 24.0],
        hourly_rules=[
            HourlyGrowthRule(hourly_demand_delta={"ambulances": 50})
        ],
    )

    # Invoke service directly
    result = FutureGapTimelineService.generate_timeline(request)
    assert result is not None

    # Assert original models remain strictly unchanged
    assert base_avail.to_dict() == orig_avail_dict
    assert base_zones[0].demand.to_dict() == orig_z0_demand
    assert base_zones[0].local_capacity.to_dict() == orig_z0_cap
    assert request.base_available_resources.to_dict() == orig_avail_dict


# -----------------------------------------------------------------------------
# Test 10: T-014 optimization invariants are preserved at all time steps
# -----------------------------------------------------------------------------
def test_timeline_preserves_t014_invariants():
    """Verify that allocation <= capacity, allocation <= gap, and no negative numbers at every horizon."""
    request = FutureGapTimelineRequest(
        incident_id="INC-TEST-INVARIANTS",
        base_available_resources=ResourceQuantity(ambulances=15, rescue_boats=4),
        base_zones=make_test_zones(),
        time_horizons_hours=[0.0, 6.0, 12.0],
        hourly_rules=[
            HourlyGrowthRule(hourly_demand_delta={"ambulances": 10})
        ],
        run_optimization=True,
    )

    response = client.post("/api/v1/future-gap/timeline", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    for pt in data["timeline_points"]:
        avail = pt["available_resources"]
        tot_alloc = pt["total_allocated"]
        assert tot_alloc is not None

        # Capacity ceiling invariant
        for r in ["ambulances", "rescue_boats"]:
            assert tot_alloc[r] <= avail[r]

        # Demand ceiling invariant for each zone
        for zg in pt["zone_gaps"]:
            assert zg["allocated"] is not None
            assert zg["response_gap"] is not None
            for r in ["ambulances", "rescue_boats"]:
                assert zg["allocated"][r] <= zg["response_gap"][r]
                assert zg["unmet_need"][r] >= 0
                assert zg["allocated"][r] >= 0


# -----------------------------------------------------------------------------
# Test 11: Invalid timeline input is rejected appropriately
# -----------------------------------------------------------------------------
def test_timeline_invalid_input_rejected():
    """Verify that negative time horizons or empty zones are rejected with HTTP 422."""
    # Negative time horizon
    bad_payload_1 = {
        "incident_id": "BAD-HOURS",
        "base_available_resources": {"ambulances": 10},
        "base_zones": [z.model_dump() for z in make_test_zones()],
        "time_horizons_hours": [-5.0, 10.0],
    }
    resp1 = client.post("/api/v1/future-gap/timeline", json=bad_payload_1)
    assert resp1.status_code == 422

    # Empty base zones
    bad_payload_2 = {
        "incident_id": "EMPTY-ZONES",
        "base_available_resources": {"ambulances": 10},
        "base_zones": [],
        "time_horizons_hours": [0.0, 6.0],
    }
    resp2 = client.post("/api/v1/future-gap/timeline", json=bad_payload_2)
    assert resp2.status_code == 422


# -----------------------------------------------------------------------------
# Test 12: API endpoint contract & sample payload execution
# -----------------------------------------------------------------------------
def test_timeline_sample_payload_and_api_contract():
    """Verify /future-gap/sample-payload returns valid model that executes successfully via POST."""
    sample_resp = client.get("/api/v1/future-gap/sample-payload")
    assert sample_resp.status_code == 200
    sample_data = sample_resp.json()

    assert "incident_id" in sample_data
    assert "time_horizons_hours" in sample_data
    assert "hourly_rules" in sample_data

    # Post sample payload directly to endpoint
    post_resp = client.post("/api/v1/future-gap/timeline", json=sample_data)
    assert post_resp.status_code == 200
    result = post_resp.json()

    assert result["incident_id"] == sample_data["incident_id"]
    assert len(result["timeline_points"]) == len(sample_data["time_horizons_hours"])
    assert result["summary"]["gap_trend"] in ("EXPANDING", "CONTRACTING", "STABLE")
    assert "DETERMINISTIC" in result["projection_type"]
