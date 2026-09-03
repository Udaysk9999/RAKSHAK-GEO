"""GIS Zone Intelligence and Flood Impact Endpoints (T-017).

Provides spatial intersection between flood extent layers and administrative city wards / building footprints.
All synthetic geometry and disaster statistics are labeled DEMO DATA per agent.md.
"""
from fastapi import APIRouter, status

from app.schemas.flood import (
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONGeometry,
)
from app.schemas.gis import (
    BuildingFootprint,
    FloodImpactRequest,
    FloodImpactResponse,
    WardZoneGeometry,
)
from app.services.gis_service import GISFloodImpactService

router = APIRouter(prefix="/gis", tags=["GIS Zone Intelligence & Flood Impact"])


@router.post(
    "/impact",
    response_model=FloodImpactResponse,
    status_code=status.HTTP_200_OK,
    summary="Assess Spatial Flood Impact on Zones and Buildings",
    description=(
        "Performs 2D vector spatial intersection between a detected flood extent boundary and municipal "
        "ward/zone polygons. Computes affected flooded area, percentage area submerged, and identifies "
        "inundated building/facility footprints. Classifies severity deterministically into UNAFFECTED, "
        "LOW, MODERATE, HIGH, or CRITICAL."
    ),
)
def assess_spatial_flood_impact(request: FloodImpactRequest) -> FloodImpactResponse:
    """Assess spatial flood impact across city zones and buildings."""
    return GISFloodImpactService.assess_impact(request)


@router.get(
    "/sample-payload",
    response_model=FloodImpactRequest,
    summary="Get Sample Flood Impact Assessment Request [DEMO DATA]",
    description=(
        "Returns a reference Ahmedabad flood assessment scenario with Sabarmati Riverfront "
        "and Maninagar East ward polygons, critical hospital/shelter footprints, and a river corridor flood extent."
    ),
)
def get_sample_gis_impact_payload() -> FloodImpactRequest:
    """Return a reference spatial impact assessment request with synthetic DEMO DATA."""
    # Synthetic flood corridor over Sabarmati (approx lon 72.56-72.58, lat 23.02-23.05)
    flood_poly = GeoJSONGeometry(
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
    )
    flood_fc = GeoJSONFeatureCollection(
        features=[
            GeoJSONFeature(
                geometry=flood_poly,
                properties={"source": "Sentinel-2 NDWI Flood Extent", "label": "DEMO DATA"},
            )
        ]
    )

    # Ward 1: Sabarmati Riverfront (intersects flood extent partially)
    ward_1 = WardZoneGeometry(
        zone_id="ZONE-AHM-WEST-01",
        zone_name="Ahmedabad West / Sabarmati Riverfront [DEMO DATA]",
        total_area_sq_km=8.5,
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
        population=145000,
    )

    # Ward 2: Maninagar East (outside the flood corridor)
    ward_2 = WardZoneGeometry(
        zone_id="ZONE-AHM-EAST-02",
        zone_name="Ahmedabad East / Maninagar [DEMO DATA]",
        total_area_sq_km=6.2,
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
        population=110000,
    )

    # Buildings: 1 flooded hospital, 1 unflooded shelter
    bldg_1 = BuildingFootprint(
        building_id="BLDG-HOSP-01",
        name="Sabarmati Emergency Clinic [DEMO DATA]",
        building_type="hospital",
        zone_id="ZONE-AHM-WEST-01",
        geometry=GeoJSONGeometry(
            type="Point",
            coordinates=[72.572, 23.035],  # Inside flood polygon
        ),
    )
    bldg_2 = BuildingFootprint(
        building_id="BLDG-SHELTER-02",
        name="Maninagar Community Relief Shelter [DEMO DATA]",
        building_type="shelter",
        zone_id="ZONE-AHM-EAST-02",
        geometry=GeoJSONGeometry(
            type="Point",
            coordinates=[72.615, 22.995],  # Outside flood polygon
        ),
    )

    return FloodImpactRequest(
        incident_id="INC-AHM-FLOOD-GIS-DEMO",
        flood_extent=flood_fc,
        zones=[ward_1, ward_2],
        buildings=[bldg_1, bldg_2],
    )
