"""Resource Optimization API Endpoints (T-014).

Provides endpoints to determine feasible, priority-weighted emergency resource allocations
across disaster zones while strictly respecting capacity constraints.
All synthetic resources are explicitly labeled DEMO DATA.
"""
from fastapi import APIRouter, status
from app.schemas.optimization import (
    OptimizationGoal,
    OptimizationStatusResponse,
    ResourceOptimizationRequest,
    ResourceOptimizationResponse,
    ResourceQuantity,
    ZoneDemand,
)
from app.services.optimization_service import ResourceOptimizationService

router = APIRouter(prefix="/optimization", tags=["Resource Optimization"])


@router.get(
    "/status",
    response_model=OptimizationStatusResponse,
    summary="Get Resource Optimization Engine status",
    description="Check the operational readiness, algorithm configuration, and supported objectives of the T-014 engine.",
)
def get_optimization_status() -> OptimizationStatusResponse:
    """Check engine status and capability."""
    return ResourceOptimizationService.get_status()


@router.post(
    "/allocate",
    response_model=ResourceOptimizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Optimize Resource Allocation (Primary T-014 API)",
    description=(
        "Executes deterministic multi-criteria optimization to allocate available emergency resources "
        "across affected disaster zones. Prioritizes zones with greater response gaps and higher severity/priority, "
        "strictly enforces capacity limits, and returns granular per-zone allocations and unmet gaps."
    ),
)
def allocate_resources(request: ResourceOptimizationRequest) -> ResourceOptimizationResponse:
    """Execute resource allocation optimization."""
    return ResourceOptimizationService.optimize_allocation(request)


@router.post(
    "/optimize",
    response_model=ResourceOptimizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Optimize Resource Allocation (Alias)",
    description="Convenience alias endpoint identical to /allocate.",
)
def optimize_resources_alias(request: ResourceOptimizationRequest) -> ResourceOptimizationResponse:
    """Alias for /allocate."""
    return ResourceOptimizationService.optimize_allocation(request)


@router.get(
    "/sample-payload",
    response_model=ResourceOptimizationRequest,
    summary="Get sample optimization payload [DEMO DATA]",
    description=(
        "Returns a complete reference request payload for Ahmedabad flood disaster zones "
        "including zone priorities, severity scores, gross demand, local capacities, and available depot stockpiles."
    ),
)
def get_sample_payload() -> ResourceOptimizationRequest:
    """Return sample request data for client testing and inspection."""
    return ResourceOptimizationRequest(
        incident_id="INC-AHM-FLOOD-2026-001",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        available_resources=ResourceQuantity(
            ambulances=20,
            rescue_boats=8,
            food_packets=4000,
            medical_kits=800,
            personnel=100,
        ),
        zones=[
            ZoneDemand(
                zone_id="ZONE-AHM-WEST-01",
                zone_name="Ahmedabad West / Sabarmati Riverfront [DEMO DATA]",
                priority=9,
                severity_score=8.5,
                population_at_risk=15000,
                demand=ResourceQuantity(
                    ambulances=15,
                    rescue_boats=6,
                    food_packets=3000,
                    medical_kits=600,
                    personnel=60,
                ),
                local_capacity=ResourceQuantity(
                    ambulances=3,
                    rescue_boats=1,
                    food_packets=500,
                    medical_kits=100,
                    personnel=10,
                ),
            ),
            ZoneDemand(
                zone_id="ZONE-AHM-EAST-02",
                zone_name="Ahmedabad East / Maninagar [DEMO DATA]",
                priority=6,
                severity_score=6.2,
                population_at_risk=8000,
                demand=ResourceQuantity(
                    ambulances=10,
                    rescue_boats=4,
                    food_packets=2000,
                    medical_kits=400,
                    personnel=40,
                ),
                local_capacity=ResourceQuantity(
                    ambulances=2,
                    rescue_boats=0,
                    food_packets=200,
                    medical_kits=50,
                    personnel=5,
                ),
            ),
            ZoneDemand(
                zone_id="ZONE-AHM-NORTH-03",
                zone_name="Ahmedabad North / Chandkheda [DEMO DATA]",
                priority=3,
                severity_score=3.8,
                population_at_risk=4000,
                demand=ResourceQuantity(
                    ambulances=5,
                    rescue_boats=2,
                    food_packets=1000,
                    medical_kits=200,
                    personnel=20,
                ),
                local_capacity=ResourceQuantity(
                    ambulances=1,
                    rescue_boats=0,
                    food_packets=100,
                    medical_kits=20,
                    personnel=5,
                ),
            ),
        ],
    )
