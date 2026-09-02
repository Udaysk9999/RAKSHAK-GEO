"""Comprehensive Test Suite for T-014 Resource Optimization Engine.

Tests all required scenarios:
1. Normal allocation
2. Resource shortage
3. Resource surplus
4. Multiple zones with different priorities
5. A zone receiving no allocation when no capacity remains
6. Local capacity and net response gap computation
7. Reserve margin constraint enforcement
8. Balanced allocation objective
All synthetic data is labeled DEMO/TEST DATA per agent.md.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.optimization import (
    OptimizationConstraint,
    OptimizationGoal,
    ResourceOptimizationRequest,
    ResourceQuantity,
    ZoneDemand,
)
from app.services.optimization_service import ResourceOptimizationService

client = TestClient(app)


# -----------------------------------------------------------------------------
# Scenario 1: Normal Allocation
# -----------------------------------------------------------------------------
def test_normal_allocation():
    """Verify normal allocation scenario where resources partially satisfy multiple zones cleanly."""
    request = ResourceOptimizationRequest(
        incident_id="INC-TEST-NORMAL-001",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        available_resources=ResourceQuantity(
            ambulances=15,
            rescue_boats=5,
            food_packets=2000,
            medical_kits=400,
            personnel=50,
        ),
        zones=[
            ZoneDemand(
                zone_id="ZONE-TEST-01",
                zone_name="Zone Alpha [DEMO/TEST DATA]",
                priority=8,
                severity_score=7.5,
                demand=ResourceQuantity(
                    ambulances=10,
                    rescue_boats=3,
                    food_packets=1200,
                    medical_kits=250,
                    personnel=30,
                ),
            ),
            ZoneDemand(
                zone_id="ZONE-TEST-02",
                zone_name="Zone Beta [DEMO/TEST DATA]",
                priority=5,
                severity_score=5.0,
                demand=ResourceQuantity(
                    ambulances=8,
                    rescue_boats=4,
                    food_packets=1000,
                    medical_kits=200,
                    personnel=25,
                ),
            ),
        ],
    )

    response = client.post("/api/v1/optimization/allocate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    assert data["incident_id"] == "INC-TEST-NORMAL-001"
    assert data["is_demo_data"] is True
    # Capacity constraint: total allocated cannot exceed available
    assert data["total_allocated"]["ambulances"] <= 15
    assert data["total_allocated"]["rescue_boats"] <= 5
    assert data["remaining_stockpile"]["ambulances"] >= 0
    assert data["remaining_stockpile"]["rescue_boats"] >= 0

    # Zone Alpha (higher priority 8) should get all 10 requested ambulances
    alpha = next(z for z in data["allocations"] if z["zone_id"] == "ZONE-TEST-01")
    assert alpha["allocated"]["ambulances"] == 10
    assert alpha["remaining_unmet_need"]["ambulances"] == 0

    # Zone Beta (lower priority 5) gets remaining 5 ambulances (out of 8 requested)
    beta = next(z for z in data["allocations"] if z["zone_id"] == "ZONE-TEST-02")
    assert beta["allocated"]["ambulances"] == 5
    assert beta["remaining_unmet_need"]["ambulances"] == 3
    assert beta["allocation_status"] == "PARTIALLY_ALLOCATED"


# -----------------------------------------------------------------------------
# Scenario 2: Resource Shortage
# -----------------------------------------------------------------------------
def test_resource_shortage():
    """Verify system handles severe shortage without exceeding available stockpile."""
    request = ResourceOptimizationRequest(
        incident_id="INC-TEST-SHORTAGE-002",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        available_resources=ResourceQuantity(
            ambulances=5,
            rescue_boats=2,
            food_packets=500,
            medical_kits=100,
            personnel=10,
        ),
        zones=[
            ZoneDemand(
                zone_id="ZONE-CRITICAL-01",
                zone_name="Critical Flood Zone [DEMO/TEST DATA]",
                priority=9,
                severity_score=9.0,
                demand=ResourceQuantity(
                    ambulances=20,
                    rescue_boats=10,
                    food_packets=2500,
                    medical_kits=500,
                    personnel=50,
                ),
            ),
            ZoneDemand(
                zone_id="ZONE-MODERATE-02",
                zone_name="Moderate Impact Zone [DEMO/TEST DATA]",
                priority=4,
                severity_score=4.0,
                demand=ResourceQuantity(
                    ambulances=15,
                    rescue_boats=5,
                    food_packets=1500,
                    medical_kits=300,
                    personnel=30,
                ),
            ),
        ],
    )

    response = client.post("/api/v1/optimization/allocate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "FEASIBLE_SHORTAGE"
    assert data["overall_fulfillment_rate"] < 1.0
    assert data["total_allocated"]["ambulances"] == 5
    assert data["total_allocated"]["rescue_boats"] == 2
    assert data["remaining_stockpile"]["ambulances"] == 0
    assert data["remaining_stockpile"]["rescue_boats"] == 0

    # Bottlenecks identified
    assert "ambulances" in data["summary"]["bottleneck_resources"]
    assert "rescue_boats" in data["summary"]["bottleneck_resources"]

    # Critical zone gets all 5 ambulances, moderate zone gets 0
    crit = next(z for z in data["allocations"] if z["zone_id"] == "ZONE-CRITICAL-01")
    mod = next(z for z in data["allocations"] if z["zone_id"] == "ZONE-MODERATE-02")
    assert crit["allocated"]["ambulances"] == 5
    assert mod["allocated"]["ambulances"] == 0
    assert mod["allocation_status"] == "UNALLOCATED"


# -----------------------------------------------------------------------------
# Scenario 3: Resource Surplus
# -----------------------------------------------------------------------------
def test_resource_surplus():
    """Verify surplus scenario: 100% fulfillment without over-allocating to any zone."""
    request = ResourceOptimizationRequest(
        incident_id="INC-TEST-SURPLUS-003",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        available_resources=ResourceQuantity(
            ambulances=50,
            rescue_boats=20,
            food_packets=10000,
            medical_kits=2000,
            personnel=200,
        ),
        zones=[
            ZoneDemand(
                zone_id="ZONE-SURPLUS-01",
                zone_name="Zone One [DEMO/TEST DATA]",
                priority=7,
                severity_score=6.0,
                demand=ResourceQuantity(
                    ambulances=8,
                    rescue_boats=2,
                    food_packets=1000,
                    medical_kits=200,
                    personnel=20,
                ),
            ),
            ZoneDemand(
                zone_id="ZONE-SURPLUS-02",
                zone_name="Zone Two [DEMO/TEST DATA]",
                priority=4,
                severity_score=3.5,
                demand=ResourceQuantity(
                    ambulances=5,
                    rescue_boats=1,
                    food_packets=500,
                    medical_kits=100,
                    personnel=10,
                ),
            ),
        ],
    )

    response = client.post("/api/v1/optimization/allocate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "OPTIMAL"
    assert data["overall_fulfillment_rate"] == 1.0

    # Never allocate more than requested
    assert data["total_allocated"]["ambulances"] == 13  # 8 + 5
    assert data["total_allocated"]["rescue_boats"] == 3  # 2 + 1
    # Remaining stockpile matches exactly available - total_allocated
    assert data["remaining_stockpile"]["ambulances"] == 37  # 50 - 13
    assert data["remaining_stockpile"]["rescue_boats"] == 17  # 20 - 3

    for zone_alloc in data["allocations"]:
        assert zone_alloc["allocation_status"] == "FULLY_ALLOCATED"
        assert zone_alloc["fulfillment_rate"] == 1.0
        assert zone_alloc["remaining_unmet_need"]["ambulances"] == 0
        assert zone_alloc["remaining_unmet_need"]["rescue_boats"] == 0


# -----------------------------------------------------------------------------
# Scenario 4: Multiple Zones with Different Priorities
# -----------------------------------------------------------------------------
def test_multiple_zones_with_different_priorities():
    """Verify strict priority ordering: Tier 1 (High) > Tier 2 (Medium) > Tier 3 (Low)."""
    request = ResourceOptimizationRequest(
        incident_id="INC-TEST-PRIORITY-004",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        available_resources=ResourceQuantity(ambulances=10),
        zones=[
            ZoneDemand(
                zone_id="ZONE-TIER-3",
                zone_name="Low Priority Zone [DEMO/TEST DATA]",
                priority=2,
                severity_score=2.0,
                demand=ResourceQuantity(ambulances=10),
            ),
            ZoneDemand(
                zone_id="ZONE-TIER-1",
                zone_name="High Priority Zone [DEMO/TEST DATA]",
                priority=10,
                severity_score=9.5,
                demand=ResourceQuantity(ambulances=10),
            ),
            ZoneDemand(
                zone_id="ZONE-TIER-2",
                zone_name="Medium Priority Zone [DEMO/TEST DATA]",
                priority=6,
                severity_score=6.0,
                demand=ResourceQuantity(ambulances=10),
            ),
        ],
    )

    response = client.post("/api/v1/optimization/allocate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    allocs = {z["zone_id"]: z for z in data["allocations"]}

    # Tier 1 must get 10 ambulances (100%)
    assert allocs["ZONE-TIER-1"]["allocated"]["ambulances"] == 10
    assert allocs["ZONE-TIER-1"]["fulfillment_rate"] == 1.0
    assert allocs["ZONE-TIER-1"]["allocation_status"] == "FULLY_ALLOCATED"

    # Tier 2 and Tier 3 get 0 ambulances
    assert allocs["ZONE-TIER-2"]["allocated"]["ambulances"] == 0
    assert allocs["ZONE-TIER-2"]["allocation_status"] == "UNALLOCATED"

    assert allocs["ZONE-TIER-3"]["allocated"]["ambulances"] == 0
    assert allocs["ZONE-TIER-3"]["allocation_status"] == "UNALLOCATED"


# -----------------------------------------------------------------------------
# Scenario 5: A Zone Receiving No Allocation When No Capacity Remains
# -----------------------------------------------------------------------------
def test_zone_receiving_no_allocation_when_capacity_exhausted():
    """Verify that lower priority zone gets cleanly marked UNALLOCATED with full unmet need."""
    request = ResourceOptimizationRequest(
        incident_id="INC-TEST-EXHAUSTION-005",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        available_resources=ResourceQuantity(rescue_boats=4),
        zones=[
            ZoneDemand(
                zone_id="ZONE-DRAIN-01",
                zone_name="First Responder Zone [DEMO/TEST DATA]",
                priority=8,
                severity_score=8.0,
                demand=ResourceQuantity(rescue_boats=4),
            ),
            ZoneDemand(
                zone_id="ZONE-STARVED-02",
                zone_name="Exhausted Zone [DEMO/TEST DATA]",
                priority=3,
                severity_score=3.0,
                demand=ResourceQuantity(rescue_boats=6),
            ),
        ],
    )

    response = client.post("/api/v1/optimization/allocate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    starved = next(z for z in data["allocations"] if z["zone_id"] == "ZONE-STARVED-02")
    assert starved["allocated"]["rescue_boats"] == 0
    assert starved["remaining_unmet_need"]["rescue_boats"] == 6
    assert starved["fulfillment_rate"] == 0.0
    assert starved["allocation_status"] == "UNALLOCATED"
    assert "exhausted" in starved["status_note"].lower()
    assert data["summary"]["unallocated_zones"] == 1


# -----------------------------------------------------------------------------
# Scenario 6: Net Response Gap Calculation with Local Capacity
# -----------------------------------------------------------------------------
def test_local_capacity_net_gap():
    """Verify that net response gap = max(0, gross demand - local capacity)."""
    request = ResourceOptimizationRequest(
        incident_id="INC-TEST-NETGAP-006",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        available_resources=ResourceQuantity(ambulances=20),
        zones=[
            ZoneDemand(
                zone_id="ZONE-LOCAL-CAP",
                zone_name="Zone with On-site Units [DEMO/TEST DATA]",
                priority=7,
                demand=ResourceQuantity(ambulances=15),
                local_capacity=ResourceQuantity(ambulances=5),  # Net gap = 10
            )
        ],
    )

    response = client.post("/api/v1/optimization/allocate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    zone_alloc = data["allocations"][0]
    # Requested should reflect the net gap of 10
    assert zone_alloc["requested"]["ambulances"] == 10
    assert zone_alloc["allocated"]["ambulances"] == 10
    assert zone_alloc["remaining_unmet_need"]["ambulances"] == 0


# -----------------------------------------------------------------------------
# Scenario 7: Reserve Margin Constraint
# -----------------------------------------------------------------------------
def test_reserve_margin_constraint():
    """Verify that reserve_margin_percent leaves safety buffer in stockpile."""
    request = ResourceOptimizationRequest(
        incident_id="INC-TEST-RESERVE-007",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        available_resources=ResourceQuantity(food_packets=1000),
        constraints=OptimizationConstraint(reserve_margin_percent=20.0),  # Max usable = 800
        zones=[
            ZoneDemand(
                zone_id="ZONE-BIG-DEMAND",
                zone_name="Large Demand Zone [DEMO/TEST DATA]",
                priority=9,
                demand=ResourceQuantity(food_packets=1000),
            )
        ],
    )

    response = client.post("/api/v1/optimization/allocate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    # Out of 1000, only 80% (800) should be allocated due to 20% reserve
    assert data["total_allocated"]["food_packets"] == 800
    assert data["remaining_stockpile"]["food_packets"] == 200


# -----------------------------------------------------------------------------
# Scenario 8: Balanced Allocation Objective
# -----------------------------------------------------------------------------
def test_balanced_allocation_objective():
    """Verify balanced proportional allocation shares scarce resources across multiple zones."""
    request = ResourceOptimizationRequest(
        incident_id="INC-TEST-BALANCED-008",
        objective=OptimizationGoal.BALANCED_ALLOCATION,
        available_resources=ResourceQuantity(food_packets=1000),
        zones=[
            ZoneDemand(
                zone_id="ZONE-A",
                zone_name="Zone A [DEMO/TEST DATA]",
                priority=5,
                demand=ResourceQuantity(food_packets=1000),
            ),
            ZoneDemand(
                zone_id="ZONE-B",
                zone_name="Zone B [DEMO/TEST DATA]",
                priority=5,
                demand=ResourceQuantity(food_packets=1000),
            ),
        ],
    )

    response = client.post("/api/v1/optimization/allocate", json=request.model_dump())
    assert response.status_code == 200
    data = response.json()

    alloc_a = next(z for z in data["allocations"] if z["zone_id"] == "ZONE-A")
    alloc_b = next(z for z in data["allocations"] if z["zone_id"] == "ZONE-B")

    # In balanced allocation with equal priority and demand, 1000 packets should be shared ~500 each
    assert alloc_a["allocated"]["food_packets"] > 0
    assert alloc_b["allocated"]["food_packets"] > 0
    assert (
        alloc_a["allocated"]["food_packets"] + alloc_b["allocated"]["food_packets"]
        == 1000
    )


# -----------------------------------------------------------------------------
# Scenario 9: Convenience Alias Endpoint /optimize
# -----------------------------------------------------------------------------
def test_optimize_alias_endpoint():
    """Verify that /optimize acts as a transparent alias to /allocate."""
    sample = client.get("/api/v1/optimization/sample-payload").json()
    resp_alloc = client.post("/api/v1/optimization/allocate", json=sample)
    resp_opt = client.post("/api/v1/optimization/optimize", json=sample)

    assert resp_alloc.status_code == 200
    assert resp_opt.status_code == 200
    assert resp_alloc.json()["total_allocated"] == resp_opt.json()["total_allocated"]
