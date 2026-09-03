"""Future Response Gap Timeline API Endpoints (T-016).

Provides deterministic planning projections of response gaps over future time horizons.
All synthetic resources are labeled DEMO DATA per agent.md.
"""
from fastapi import APIRouter, status

from app.schemas.optimization import (
    OptimizationGoal,
    ResourceQuantity,
    ZoneDemand,
)
from app.schemas.timeline import (
    FutureGapTimelineRequest,
    FutureGapTimelineResponse,
    HourlyGrowthRule,
    TimeStepProjection,
)
from app.schemas.what_if import ZoneModifier
from app.services.timeline_service import FutureGapTimelineService

router = APIRouter(prefix="/future-gap", tags=["Future Response Gap Timeline"])


@router.post(
    "/timeline",
    response_model=FutureGapTimelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Project Future Response Gap Timeline",
    description=(
        "Executes deterministic multi-horizon projections of disaster conditions across configurable "
        "time points (e.g. 0h, 6h, 12h, 18h, 24h). Evaluates demand growth, local capacity decay, "
        "and resulting net response gaps (max(0, demand - local capacity)). Reuses T-014 optimization "
        "to calculate projected unmet needs and fulfillment rates when enabled."
    ),
)
def project_future_gap_timeline(request: FutureGapTimelineRequest) -> FutureGapTimelineResponse:
    """Project future response gap timeline deterministically."""
    return FutureGapTimelineService.generate_timeline(request)


@router.get(
    "/sample-payload",
    response_model=FutureGapTimelineRequest,
    summary="Get Sample Future Gap Timeline Request [DEMO DATA]",
    description=(
        "Returns a reference 24-hour flood progression request for Ahmedabad disaster zones. "
        "Models steady hourly demand growth (+50 food packets/hr) and capacity decay in Zone Alpha, "
        "with an emergency reinforcement at T+12h (+5 ambulances, +2 boats)."
    ),
)
def get_sample_timeline_payload() -> FutureGapTimelineRequest:
    """Return a reference Future Response Gap Timeline request with synthetic DEMO DATA."""
    return FutureGapTimelineRequest(
        incident_id="INC-AHM-TIMELINE-24H",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        base_available_resources=ResourceQuantity(
            ambulances=15,
            rescue_boats=6,
            food_packets=3000,
            medical_kits=600,
            personnel=80,
        ),
        base_zones=[
            ZoneDemand(
                zone_id="ZONE-AHM-WEST-01",
                zone_name="Ahmedabad West / Sabarmati Riverfront [DEMO DATA]",
                priority=9,
                severity_score=8.5,
                demand=ResourceQuantity(
                    ambulances=12,
                    rescue_boats=5,
                    food_packets=2000,
                    medical_kits=400,
                    personnel=50,
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
                severity_score=6.0,
                demand=ResourceQuantity(
                    ambulances=8,
                    rescue_boats=3,
                    food_packets=1500,
                    medical_kits=300,
                    personnel=30,
                ),
                local_capacity=ResourceQuantity(
                    ambulances=2,
                    rescue_boats=0,
                    food_packets=200,
                    medical_kits=50,
                    personnel=5,
                ),
            ),
        ],
        time_horizons_hours=[0.0, 6.0, 12.0, 18.0, 24.0],
        hourly_rules=[
            HourlyGrowthRule(
                zone_id="ZONE-AHM-WEST-01",
                hourly_demand_delta={"food_packets": 50, "medical_kits": 10},
                hourly_capacity_delta={"ambulances": -1},  # Clinic access degraded over time
            ),
            HourlyGrowthRule(
                zone_id="ZONE-AHM-EAST-02",
                hourly_demand_delta={"food_packets": 30},
            ),
        ],
        step_projections=[
            TimeStepProjection(
                time_offset_hours=12.0,
                label="T+12h State Reserve Stockpile Mobilization [DEMO DATA]",
                available_resource_deltas={"ambulances": 6, "rescue_boats": 3},
            )
        ],
        run_optimization=True,
    )
