"""End-to-End Flood Response Pipeline Endpoint (T-018).

Connects flood extent vector boundaries to GIS spatial impact, response gaps,
and multi-criteria resource optimization.
All synthetic resources and disaster statistics are labeled DEMO DATA per agent.md.
"""
from fastapi import APIRouter, status

from app.schemas.flood import (
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONGeometry,
)
from app.schemas.flood_response import (
    FloodResponseAnalyzeRequest,
    FloodResponseAnalyzeResponse,
    ZoneBaselineProfile,
)
from app.schemas.gis import BuildingFootprint
from app.schemas.optimization import (
    OptimizationConstraint,
    OptimizationGoal,
    ResourceQuantity,
)
from app.services.flood_response_service import FloodResponseService

router = APIRouter(prefix="/flood-response", tags=["End-to-End Flood Response Pipeline"])


@router.post(
    "/analyze",
    response_model=FloodResponseAnalyzeResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute End-to-End Flood Response Workflow",
    description=(
        "Executes the complete operational pipeline: Ingests detected flood extent vector geometry, "
        "calculates spatial intersection across municipal zones and critical infrastructure, transforms "
        "impact metrics into dynamic emergency response gaps, and runs multi-criteria optimization to "
        "dispatch available stockpile resources efficiently."
    ),
)
def analyze_flood_response_and_optimize(
    request: FloodResponseAnalyzeRequest,
) -> FloodResponseAnalyzeResponse:
    """Run end-to-end flood spatial assessment and resource dispatch optimization."""
    return FloodResponseService.analyze_and_optimize(request)


@router.get(
    "/sample-payload",
    response_model=FloodResponseAnalyzeRequest,
    summary="Get Reference Flood Response Request [DEMO DATA]",
    description=(
        "Returns an end-to-end Ahmedabad flood response scenario with Sabarmati Riverfront "
        "and Maninagar zones, critical facility footprints, and available depot stockpiles."
    ),
)
def get_sample_flood_response_payload() -> FloodResponseAnalyzeRequest:
    """Return a reference end-to-end flood response request with synthetic DEMO DATA."""
    # Synthetic flood corridor over Sabarmati Riverfront (lon 72.56-72.58, lat 23.02-23.05)
    flood_fc = GeoJSONFeatureCollection(
        features=[
            GeoJSONFeature(
                geometry=GeoJSONGeometry(
                    type="Polygon",
                    coordinates=[
                        [
                            [72.565, 23.020],
                            [72.580, 23.020],
                            [72.580, 23.050],
                            [72.565, 23.050],
                            [72.565, 23.020],
                        ]
                    ],
                ),
                properties={"source": "Sentinel-2 NDWI Detected Extent", "label": "DEMO DATA"},
            )
        ]
    )

    # Zone 1: Sabarmati Riverfront (partially inundated)
    zone_1 = ZoneBaselineProfile(
        zone_id="ZONE-AHM-WEST-01",
        zone_name="Ahmedabad West / Sabarmati Riverfront [DEMO DATA]",
        total_area_sq_km=8.5,
        population=145000,
        geometry=GeoJSONGeometry(
            type="Polygon",
            coordinates=[
                [
                    [72.550, 23.010],
                    [72.590, 23.010],
                    [72.590, 23.060],
                    [72.550, 23.060],
                    [72.550, 23.010],
                ]
            ],
        ),
        baseline_demand=ResourceQuantity(
            ambulances=15,
            rescue_boats=8,
            food_packets=3000,
            medical_kits=500,
            personnel=60,
        ),
        local_capacity=ResourceQuantity(
            ambulances=3,
            rescue_boats=1,
            food_packets=500,
            medical_kits=100,
            personnel=10,
        ),
        base_priority=8,
    )

    # Zone 2: Maninagar (unaffected by riverfront flood)
    zone_2 = ZoneBaselineProfile(
        zone_id="ZONE-AHM-EAST-02",
        zone_name="Ahmedabad East / Maninagar [DEMO DATA]",
        total_area_sq_km=6.2,
        population=110000,
        geometry=GeoJSONGeometry(
            type="Polygon",
            coordinates=[
                [
                    [72.600, 22.980],
                    [72.640, 22.980],
                    [72.640, 23.010],
                    [72.600, 23.010],
                    [72.600, 22.980],
                ]
            ],
        ),
        baseline_demand=ResourceQuantity(
            ambulances=5,
            rescue_boats=0,
            food_packets=1000,
            medical_kits=200,
            personnel=20,
        ),
        local_capacity=ResourceQuantity(
            ambulances=2,
            rescue_boats=0,
            food_packets=300,
            medical_kits=50,
            personnel=5,
        ),
        base_priority=4,
    )

    # Buildings
    bldg_1 = BuildingFootprint(
        building_id="BLDG-CLINIC-01",
        name="Sabarmati Emergency Medical Post [DEMO DATA]",
        building_type="hospital",
        zone_id="ZONE-AHM-WEST-01",
        geometry=GeoJSONGeometry(type="Point", coordinates=[72.572, 23.035]),
    )

    return FloodResponseAnalyzeRequest(
        incident_id="INC-E2E-FLOOD-AHMEDABAD",
        flood_extent=flood_fc,
        zones=[zone_1, zone_2],
        buildings=[bldg_1],
        available_resources=ResourceQuantity(
            ambulances=15,
            rescue_boats=8,
            food_packets=4000,
            medical_kits=600,
            personnel=70,
        ),
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        constraints=OptimizationConstraint(reserve_margin_pct=10.0),
        only_allocate_to_affected=True,
    )
