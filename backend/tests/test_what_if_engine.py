"""Comprehensive Test Suite for T-015 What-If Simulation Engine.

Tests all required simulation capabilities:
1. Baseline scenario with no changes (identity test)
2. Additional resources improve fulfillment
3. Reduced resources increase shortage
4. Increased zone demand changes allocation & unmet need
5. Changed local capacity alters central response gap
6. Multiple scenario changes executed concurrently
7. Base input immutability (original input data is never mutated)
8. Preservation of all T-014 optimization invariants
9. API endpoint integration via FastAPI TestClient
All synthetic resources are labeled DEMO/TEST DATA per agent.md.
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
from app.schemas.what_if import (
    ScenarioChanges,
    WhatIfSimulateRequest,
    ZoneModifier,
)
from app.services.what_if_service import WhatIfSimulationService

client = TestClient(app)


# -----------------------------------------------------------------------------
# Fixture helpers
# -----------------------------------------------------------------------------
def make_base_zones():
    return [
        ZoneDemand(
            zone_id="ZONE-TEST-01",
            zone_name="Zone Alpha [DEMO/TEST DATA]",
            priority=8,
            severity_score=8.0,
            demand=ResourceQuantity(ambulances=10, rescue_boats=4, food_packets=1000),
            local_capacity=ResourceQuantity(ambulances=2, rescue_boats=1, food_packets=200),
        ),
        ZoneDemand(
            zone_id="ZONE-TEST-02",
            zone_name="Zone Beta [DEMO/TEST DATA]",
            priority=5,
            severity_score=5.0,
            demand=ResourceQuantity(ambulances=8, rescue_boats=2, food_packets=800),
            local_capacity=ResourceQuantity(ambulances=0, rescue_boats=0, food_packets=0),
        ),
    ]


# -----------------------------------------------------------------------------
# Test 1: Baseline scenario with no changes
# -----------------------------------------------------------------------------
def test_what_if_baseline_no_changes():
    """Verify simulation with empty changes produces identical baseline and simulated results."""
    request = WhatIfSimulateRequest(
        incident_id="INC-WHATIF-NO-CHANGE",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        base_available_resources=ResourceQuantity(ambulances=15, rescue_boats=5, food_packets=1500),
        base_zones=make_base_zones(),
        changes=ScenarioChanges(description="Zero modification test [DEMO/TEST DATA]"),
    )

    response = client.post("/api/v1/what-if/simulate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    assert data["incident_id"] == "INC-WHATIF-NO-CHANGE"
    assert data["is_demo_data"] is True
    assert data["summary"]["verdict"] == "NEUTRAL"
    assert data["summary"]["fulfillment_rate_change"] == 0.0
    assert data["baseline"]["overall_fulfillment_rate"] == data["simulated"]["overall_fulfillment_rate"]
    assert len(data["summary"]["improved_zones"]) == 0
    assert len(data["summary"]["degraded_zones"]) == 0
    assert len(data["summary"]["unchanged_zones"]) == 2

    for comp in data["zone_comparisons"]:
        assert comp["status_impact"] == "UNCHANGED"
        assert comp["fulfillment_delta"] == 0.0
        assert comp["allocation_delta"]["ambulances"] == 0


# -----------------------------------------------------------------------------
# Test 2: Additional resources improve fulfillment
# -----------------------------------------------------------------------------
def test_what_if_additional_resources_improve_fulfillment():
    """Verify that deploying additional reserve stockpile improves zone fulfillment rate."""
    # Net demand: Alpha needs (10 - 2 = 8 ambulances), Beta needs 8 ambulances. Total = 16.
    # Base available: only 8 ambulances (creates shortage: 50% fulfilled).
    request = WhatIfSimulateRequest(
        incident_id="INC-WHATIF-MORE-RES",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        base_available_resources=ResourceQuantity(ambulances=8),
        base_zones=make_base_zones(),
        changes=ScenarioChanges(
            description="Deploy 8 additional reserve ambulances [DEMO/TEST DATA]",
            available_resource_deltas={"ambulances": 8},  # 8 -> 16
        ),
    )

    response = client.post("/api/v1/what-if/simulate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    assert data["summary"]["verdict"] == "IMPROVED"
    assert data["summary"]["fulfillment_rate_change"] > 0
    assert data["simulated"]["overall_fulfillment_rate"] > data["baseline"]["overall_fulfillment_rate"]

    # Beta was starved in baseline (got 0 ambulances because Alpha took all 8)
    beta_comp = next(z for z in data["zone_comparisons"] if z["zone_id"] == "ZONE-TEST-02")
    assert beta_comp["baseline_allocated"]["ambulances"] == 0
    assert beta_comp["simulated_allocated"]["ambulances"] == 8
    assert beta_comp["status_impact"] == "IMPROVED"
    assert "ZONE-TEST-02" in data["summary"]["improved_zones"]


# -----------------------------------------------------------------------------
# Test 3: Reduced resources increase shortage
# -----------------------------------------------------------------------------
def test_what_if_reduced_resources_increase_shortage():
    """Verify that depot loss/reduction degrades fulfillment and increases unmet need."""
    request = WhatIfSimulateRequest(
        incident_id="INC-WHATIF-LESS-RES",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        base_available_resources=ResourceQuantity(ambulances=16),  # Enough for 100% baseline
        base_zones=make_base_zones(),
        changes=ScenarioChanges(
            description="Depot power failure: lose 10 ambulances [DEMO/TEST DATA]",
            available_resource_deltas={"ambulances": -10},  # 16 -> 6
        ),
    )

    response = client.post("/api/v1/what-if/simulate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    assert data["summary"]["verdict"] == "DEGRADED"
    assert data["summary"]["fulfillment_rate_change"] < 0
    assert data["simulated"]["overall_fulfillment_rate"] < data["baseline"]["overall_fulfillment_rate"]

    # Unmet need increased
    assert data["simulated"]["total_remaining_unmet"]["ambulances"] > data["baseline"]["total_remaining_unmet"]["ambulances"]
    assert len(data["summary"]["degraded_zones"]) > 0


# -----------------------------------------------------------------------------
# Test 4: Increased zone demand changes result
# -----------------------------------------------------------------------------
def test_what_if_increased_zone_demand():
    """Verify that a localized demand surge increases net response gap and alters allocations."""
    request = WhatIfSimulateRequest(
        incident_id="INC-WHATIF-SURGE",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        base_available_resources=ResourceQuantity(ambulances=16),
        base_zones=make_base_zones(),
        changes=ScenarioChanges(
            description="Flood breach triggers demand surge in Zone Beta [DEMO/TEST DATA]",
            zone_changes=[
                ZoneModifier(
                    zone_id="ZONE-TEST-02",
                    demand_deltas={"ambulances": 10},  # Demand increases from 8 to 18
                )
            ],
        ),
    )

    response = client.post("/api/v1/what-if/simulate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    beta_comp = next(z for z in data["zone_comparisons"] if z["zone_id"] == "ZONE-TEST-02")
    # In baseline, Beta requested 8; in simulation, Beta requested 18
    assert beta_comp["simulated_unmet"]["ambulances"] > beta_comp["baseline_unmet"]["ambulances"]
    assert data["simulated"]["total_requested"]["ambulances"] == 26  # 8 (Alpha) + 18 (Beta)


# -----------------------------------------------------------------------------
# Test 5: Changed local capacity changes central response gap
# -----------------------------------------------------------------------------
def test_what_if_changed_local_capacity():
    """Verify that loss of local clinic capacity increases central dispatch demand."""
    # Alpha has gross demand = 10, local_capacity = 2 (net gap = 8)
    request = WhatIfSimulateRequest(
        incident_id="INC-WHATIF-LOCAL-CAP",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        base_available_resources=ResourceQuantity(ambulances=20),
        base_zones=make_base_zones(),
        changes=ScenarioChanges(
            description="Zone Alpha clinic submerged: local capacity drops to 0 [DEMO/TEST DATA]",
            zone_changes=[
                ZoneModifier(
                    zone_id="ZONE-TEST-01",
                    local_capacity_override=ResourceQuantity(ambulances=0, rescue_boats=0, food_packets=0),
                )
            ],
        ),
    )

    response = client.post("/api/v1/what-if/simulate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    alpha_base = next(z for z in data["baseline"]["allocations"] if z["zone_id"] == "ZONE-TEST-01")
    alpha_sim = next(z for z in data["simulated"]["allocations"] if z["zone_id"] == "ZONE-TEST-01")

    # Baseline net requested was 10 - 2 = 8
    assert alpha_base["requested"]["ambulances"] == 8
    # Simulated net requested is 10 - 0 = 10
    assert alpha_sim["requested"]["ambulances"] == 10
    # Central allocation must increase to cover the loss of local capacity
    assert alpha_sim["allocated"]["ambulances"] == 10


# -----------------------------------------------------------------------------
# Test 6: Multiple scenario changes executed concurrently
# -----------------------------------------------------------------------------
def test_what_if_multiple_concurrent_changes():
    """Verify multi-variable scenario: adjust stockpile, change multiple zone priorities and demands."""
    request = WhatIfSimulateRequest(
        incident_id="INC-WHATIF-MULTI",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        base_available_resources=ResourceQuantity(ambulances=10, rescue_boats=3),
        base_zones=make_base_zones(),
        changes=ScenarioChanges(
            description="Multi-factor scenario: reinforce boats, shift Beta priority to 10 [DEMO/TEST DATA]",
            available_resource_deltas={"ambulances": 5, "rescue_boats": 4},
            zone_changes=[
                ZoneModifier(
                    zone_id="ZONE-TEST-02",
                    priority_override=10,
                    severity_override=9.5,
                ),
                ZoneModifier(
                    zone_id="ZONE-TEST-01",
                    priority_override=4,
                    demand_deltas={"food_packets": 500},
                ),
            ],
        ),
    )

    response = client.post("/api/v1/what-if/simulate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    assert data["simulated"]["total_available"]["ambulances"] == 15
    assert data["simulated"]["total_available"]["rescue_boats"] == 7

    # In simulation, Zone Beta is now priority 10 (higher than Alpha's overridden 4)
    beta_sim = next(z for z in data["simulated"]["allocations"] if z["zone_id"] == "ZONE-TEST-02")
    assert beta_sim["priority"] == 10
    assert beta_sim["severity_score"] == 9.5
    assert beta_sim["effective_weight"] > 10.0


# -----------------------------------------------------------------------------
# Test 7: Base input data immutability
# -----------------------------------------------------------------------------
def test_what_if_base_input_remains_unchanged():
    """Verify that WhatIfSimulationService never mutates the original request or model objects."""
    base_available = ResourceQuantity(ambulances=10, rescue_boats=4)
    base_zones = make_base_zones()

    # Create deep copies of initial state for comparison
    orig_available_dict = copy.deepcopy(base_available.to_dict())
    orig_zone0_demand_dict = copy.deepcopy(base_zones[0].demand.to_dict())
    orig_zone0_priority = base_zones[0].priority

    request = WhatIfSimulateRequest(
        incident_id="INC-WHATIF-IMMUTABLE",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        base_available_resources=base_available,
        base_zones=base_zones,
        changes=ScenarioChanges(
            description="Mutate test [DEMO/TEST DATA]",
            available_resource_deltas={"ambulances": 50},
            zone_changes=[
                ZoneModifier(
                    zone_id="ZONE-TEST-01",
                    priority_override=1,
                    demand_deltas={"ambulances": 100},
                )
            ],
        ),
    )

    # Execute simulation directly via service
    result = WhatIfSimulationService.simulate(request)
    assert result is not None

    # Assert original Python objects in request and base_zones are completely untouched
    assert base_available.to_dict() == orig_available_dict
    assert base_zones[0].demand.to_dict() == orig_zone0_demand_dict
    assert base_zones[0].priority == orig_zone0_priority
    assert request.base_available_resources.to_dict() == orig_available_dict
    assert request.base_zones[0].demand.to_dict() == orig_zone0_demand_dict


# -----------------------------------------------------------------------------
# Test 8: T-014 optimization invariants remain valid in simulation
# -----------------------------------------------------------------------------
def test_what_if_preserves_t014_invariants():
    """Verify simulated allocations strictly adhere to capacity and demand constraints."""
    request = WhatIfSimulateRequest(
        incident_id="INC-WHATIF-INVARIANTS",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        base_available_resources=ResourceQuantity(ambulances=10, rescue_boats=5),
        base_zones=make_base_zones(),
        changes=ScenarioChanges(
            description="Aggressive change test [DEMO/TEST DATA]",
            available_resource_deltas={"ambulances": 20, "rescue_boats": -2},
            zone_changes=[
                ZoneModifier(
                    zone_id="ZONE-TEST-01",
                    demand_deltas={"ambulances": 30},
                )
            ],
        ),
    )

    response = client.post("/api/v1/what-if/simulate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    sim = data["simulated"]

    # Invariant 1: Allocated <= Available
    for r_type, alloc_val in sim["total_allocated"].items():
        if r_type != "extra":
            avail_val = sim["total_available"].get(r_type, 0)
            assert alloc_val <= avail_val, f"Allocated {alloc_val} exceeds available {avail_val} for {r_type}"

    # Invariant 2: Allocated <= Requested for each zone
    for zone in sim["allocations"]:
        for r_type, alloc_val in zone["allocated"].items():
            if r_type != "extra":
                req_val = zone["requested"].get(r_type, 0)
                assert alloc_val <= req_val, f"Zone {zone['zone_id']} allocated {alloc_val} exceeds requested {req_val} for {r_type}"

    # Invariant 3: Remaining stockpile = available - total allocated
    for r_type, rem_val in sim["remaining_stockpile"].items():
        if r_type != "extra":
            avail = sim["total_available"].get(r_type, 0)
            tot_alloc = sim["total_allocated"].get(r_type, 0)
            assert rem_val == max(0, avail - tot_alloc)

    # Invariant 4: No negative values
    for zone in sim["allocations"]:
        for r_type, alloc_val in zone["allocated"].items():
            if r_type != "extra":
                assert alloc_val >= 0
        for r_type, unmet_val in zone["remaining_unmet_need"].items():
            if r_type != "extra":
                assert unmet_val >= 0


# -----------------------------------------------------------------------------
# Test 9: Sample payload endpoint & end-to-end execution
# -----------------------------------------------------------------------------
def test_what_if_sample_payload_endpoint():
    """Verify sample payload endpoint returns valid request that simulates successfully."""
    sample_resp = client.get("/api/v1/what-if/sample-payload")
    assert sample_resp.status_code == 200
    sample_data = sample_resp.json()

    assert "incident_id" in sample_data
    assert "base_available_resources" in sample_data
    assert "base_zones" in sample_data
    assert "changes" in sample_data

    # Post sample payload directly to simulate endpoint
    sim_resp = client.post("/api/v1/what-if/simulate", json=sample_data)
    assert sim_resp.status_code == 200
    sim_result = sim_resp.json()

    assert sim_result["incident_id"] == sample_data["incident_id"]
    assert "baseline" in sim_result
    assert "simulated" in sim_result
    assert "summary" in sim_result
    assert sim_result["summary"]["verdict"] in ("IMPROVED", "DEGRADED", "NEUTRAL")
