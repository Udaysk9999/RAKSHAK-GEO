"""Pydantic schemas for T-018 End-to-End Flood Response Pipeline.

Orchestrates the complete flow:
Flood Extent (NDWI/Satellite) -> GIS Spatial Impact -> Response Gap -> Resource Optimization.
All synthetic resources and disaster statistics are labeled DEMO DATA per agent.md.
"""
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator

from app.schemas.flood import (
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONGeometry,
)
from app.schemas.gis import (
    BuildingFootprint,
    GISImpactSummary,
    ImpactLevel,
    WardZoneGeometry,
)
from app.schemas.optimization import (
    OptimizationConstraint,
    OptimizationGoal,
    ResourceQuantity,
    ZoneDemand,
)


class ZoneBaselineProfile(BaseModel):
    """Input demographic, geographic, and facility baseline for a municipal zone."""
    zone_id: str = Field(..., description="Unique zone identifier (e.g. ZONE-AHM-01)")
    zone_name: str = Field(..., description="Administrative zone name")
    geometry: GeoJSONGeometry = Field(
        ..., description="Zone boundary polygon (GeoJSON Polygon or MultiPolygon)"
    )
    total_area_sq_km: Optional[float] = Field(
        default=None, ge=0.0, description="Total zone surface area in sq km"
    )
    population: Optional[int] = Field(
        default=None, ge=0, description="Estimated residential population [DEMO DATA]"
    )
    baseline_demand: Optional[ResourceQuantity] = Field(
        default=None,
        description="Gross resource demand prior to or under disaster conditions [DEMO DATA]",
    )
    local_capacity: Optional[ResourceQuantity] = Field(
        default=None,
        description="Local on-site capacity (clinics, boats, emergency supplies) [DEMO DATA]",
    )
    base_priority: int = Field(
        default=5, ge=1, le=10, description="Base zone priority ranking [1..10]"
    )


class FloodResponseAnalyzeRequest(BaseModel):
    """End-to-end request orchestrating flood extent analysis through resource optimization."""
    incident_id: str = Field(default="INC-E2E-FLOOD-001", description="Incident reference identifier")
    flood_extent: Union[GeoJSONFeatureCollection, GeoJSONFeature, GeoJSONGeometry] = Field(
        ...,
        description="Detected flood extent vector layer from satellite/NDWI analysis",
    )
    zones: List[ZoneBaselineProfile] = Field(
        ...,
        description="Municipal zones with geographic boundaries and baseline resource profiles",
    )
    buildings: List[BuildingFootprint] = Field(
        default_factory=list,
        description="Optional building and critical infrastructure footprints",
    )
    available_resources: ResourceQuantity = Field(
        ...,
        description="Central depot emergency resource stockpile available for dispatch",
    )
    objective: OptimizationGoal = Field(
        default=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        description="Resource allocation objective function",
    )
    constraints: Optional[OptimizationConstraint] = Field(
        default_factory=OptimizationConstraint,
        description="Dispatch constraints such as reserve margin buffers",
    )
    only_allocate_to_affected: bool = Field(
        default=True,
        description="If True, only zones with verified flood impact (LOW/MODERATE/HIGH/CRITICAL) receive allocations",
    )

    @field_validator("zones")
    @classmethod
    def validate_zones_non_empty(cls, v: List[ZoneBaselineProfile]) -> List[ZoneBaselineProfile]:
        """Ensure at least one zone is provided."""
        if not v:
            raise ValueError("zones list must contain at least one ZoneBaselineProfile.")
        return v


class IntegratedZoneResponse(BaseModel):
    """Comprehensive end-to-end impact and resource allocation profile for a zone."""
    zone_id: str
    zone_name: str
    impact_level: ImpactLevel
    flood_affected_area_sq_km: float
    flood_affected_percentage: float
    affected_building_count: int
    total_building_count: int
    priority: int = Field(ge=1, le=10)
    severity_score: float = Field(ge=0.0, le=10.0)
    gross_demand: ResourceQuantity
    local_capacity: ResourceQuantity
    net_response_gap: ResourceQuantity
    allocated_resources: ResourceQuantity
    remaining_unmet_need: ResourceQuantity
    fulfillment_rate: float = Field(ge=0.0, le=1.0)
    allocation_status: str


class FloodResponseAnalyzeResponse(BaseModel):
    """Complete end-to-end response output for municipal emergency command."""
    incident_id: str
    is_demo_data: bool = Field(default=True, description="Flags synthetic data as DEMO DATA")
    flood_impact_summary: GISImpactSummary
    zones: List[IntegratedZoneResponse]
    total_available_resources: ResourceQuantity
    total_allocated: ResourceQuantity
    total_remaining_unmet_need: ResourceQuantity
    overall_fulfillment_rate: float = Field(ge=0.0, le=1.0)
    overall_status: str = Field(description="OPTIMAL | PARTIAL | CRITICAL_SHORTAGE | NO_IMPACT")
    narrative_summary: str
    message: str = Field(
        default="End-to-end flood response analysis and resource optimization executed successfully."
    )
