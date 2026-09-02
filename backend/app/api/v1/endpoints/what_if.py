"""What-If Simulation API Endpoints (T-015).

Allows emergency coordinators to simulate disaster scenario changes and evaluate the impact
on resource fulfillment and unmet gaps against a baseline using the T-014 optimization engine.
All synthetic resources are explicitly labeled DEMO DATA.
"""
from fastapi import APIRouter, status
from app.schemas.optimization import (
    OptimizationGoal,
    ResourceQuantity,
    ZoneDemand,
)
from app.schemas.what_if import (
    ScenarioChanges,
    WhatIfSimulateRequest,
    WhatIfSimulateResponse,
    ZoneModifier,
)
from app.services.what_if_service import WhatIfSimulationService

router = APIRouter(prefix="/what-if", tags=["What-If Simulator"])


@router.post(
    "/simulate",
    response_model=WhatIfSimulateResponse,
    status_code=status.HTTP_200_OK,
    summary="Simulate What-If Disaster Response Scenario",
    description=(
        "Executes a comparative simulation: runs the baseline scenario through the T-014 optimization engine, "
        "applies deterministic scenario changes (stockpile fluctuations, demand surges, local clinic damage, priority shifts), "
        "recalculates response gaps, executes the simulated optimization, and returns granular before-and-after differences."
    ),
)
def simulate_scenario(request: WhatIfSimulateRequest) -> WhatIfSimulateResponse:
    """Execute What-If scenario simulation."""
    return WhatIfSimulationService.simulate(request)


@router.get(
    "/sample-payload",
    response_model=WhatIfSimulateRequest,
    summary="Get Sample What-If Simulation Request [DEMO DATA]",
    description=(
        "Returns a sample What-If simulation request modeling an emergency reinforcement: "
        "depots receive +10 additional ambulances and +5 rescue boats while Sabarmati Riverfront "
        "experiences an elevated flood severity score."
    ),
)
def get_sample_what_if_payload() -> WhatIfSimulateRequest:
    """Provide a reference What-If simulation request with synthetic DEMO DATA."""
    return WhatIfSimulateRequest(
        incident_id="INC-AHM-WHATIF-001",
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
        ],
        changes=ScenarioChanges(
            description="Reinforcement dispatch: deploy state reserve stockpile (+10 ambulances, +4 boats) to mitigate riverfront flooding [DEMO DATA]",
            available_resource_deltas={
                "ambulances": 10,
                "rescue_boats": 4,
            },
            zone_changes=[
                ZoneModifier(
                    zone_id="ZONE-AHM-WEST-01",
                    severity_override=9.5,
                    demand_deltas={"rescue_boats": 2},
                )
            ],
        ),
    )
