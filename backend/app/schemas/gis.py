"""Pydantic schemas for T-017 Flood Impact & GIS Zone Intelligence.

Defines spatial data models for administrative wards/zones, building footprints,
and deterministic flood impact evaluation.
All synthetic geometry and disaster numbers are labeled DEMO DATA per agent.md.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator

from app.schemas.flood import (
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONGeometry,
)


class ImpactLevel(str, Enum):
    """Deterministic spatial flood impact severity tiers."""
    UNAFFECTED = "UNAFFECTED"  # 0.0% flooded and 0 affected critical facilities
    LOW = "LOW"                # > 0.0% to <= 10.0% area flooded
    MODERATE = "MODERATE"      # > 10.0% to <= 30.0% area flooded
    HIGH = "HIGH"              # > 30.0% to <= 60.0% area flooded
    CRITICAL = "CRITICAL"      # > 60.0% area flooded


class BuildingFootprint(BaseModel):
    """Building or critical infrastructure footprint representation."""
    building_id: str = Field(..., description="Unique building or facility identifier")
    name: Optional[str] = Field(None, description="Descriptive name (e.g. Civil Hospital, Community Center)")
    building_type: Optional[str] = Field(
        default="general",
        description="Facility type (e.g., hospital, school, shelter, residential, commercial)",
    )
    zone_id: Optional[str] = Field(None, description="ID of the administrative ward/zone containing this building")
    geometry: GeoJSONGeometry = Field(
        ...,
        description="GeoJSON geometry of the building (Point or Polygon)",
    )


class WardZoneGeometry(BaseModel):
    """Administrative zone or ward geographic boundary."""
    zone_id: str = Field(..., description="Unique zone identifier (e.g., ZONE-AHM-01)")
    zone_name: str = Field(..., description="Human-readable zone name (e.g., Sabarmati Riverfront)")
    total_area_sq_km: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Total geographical area in sq km. If omitted or 0, calculated geometrically.",
    )
    geometry: GeoJSONGeometry = Field(
        ...,
        description="GeoJSON Polygon or MultiPolygon representing the ward boundary",
    )
    population: Optional[int] = Field(
        default=None, ge=0, description="Estimated population residing in the zone [DEMO DATA]"
    )


class BuildingImpactDetail(BaseModel):
    """Inundation status and classification for an individual building."""
    building_id: str
    name: Optional[str] = None
    building_type: Optional[str] = None
    zone_id: Optional[str] = None
    is_affected: bool = Field(description="True if building footprint intersects flood extent")
    inundation_status: str = Field(
        description="AFFECTED | UNAFFECTED (Never labeled 'destroyed' per protocol)"
    )


class ZoneImpactResult(BaseModel):
    """Granular flood impact metrics for an individual administrative zone."""
    zone_id: str
    zone_name: str
    total_area_sq_km: float = Field(ge=0.0, description="Total zone surface area in sq km")
    flood_affected_area_sq_km: float = Field(
        ge=0.0, description="Intersected flooded area in sq km"
    )
    flood_affected_percentage: float = Field(
        ge=0.0, le=100.0, description="Percentage of zone area affected by flood extent [0..100]"
    )
    affected_building_count: int = Field(
        default=0, ge=0, description="Number of buildings/facilities intersecting flood extent"
    )
    total_building_count: int = Field(
        default=0, ge=0, description="Total buildings/facilities evaluated in this zone"
    )
    impact_level: ImpactLevel = Field(
        description="Deterministic severity rating: UNAFFECTED, LOW, MODERATE, HIGH, CRITICAL"
    )
    affected_buildings: List[BuildingImpactDetail] = Field(
        default_factory=list,
        description="List of specific buildings located inside or intersecting the flood extent",
    )


class GISImpactSummary(BaseModel):
    """Executive summary of city-wide spatial flood impact."""
    total_zones_analyzed: int
    affected_zones_count: int
    total_flood_area_sq_km: float
    total_buildings_analyzed: int
    total_buildings_affected: int
    highest_impact_zone: Optional[str] = None
    highest_impact_level: ImpactLevel = ImpactLevel.UNAFFECTED
    summary_narrative: str = Field(
        description="Deterministic factual summary of spatial flood impact across zones"
    )


class FloodImpactRequest(BaseModel):
    """Request payload for spatial flood impact assessment across zones and buildings."""
    incident_id: str = Field(default="INC-FLOOD-GIS-001", description="Incident reference identifier")
    flood_extent: Union[GeoJSONFeatureCollection, GeoJSONFeature, GeoJSONGeometry] = Field(
        ...,
        description="Detected flood extent vector layer (FeatureCollection, Feature, or Geometry)",
    )
    zones: List[WardZoneGeometry] = Field(
        ...,
        description="List of city administrative ward/zone boundaries to analyze",
    )
    buildings: List[BuildingFootprint] = Field(
        default_factory=list,
        description="Optional list of building or critical facility footprints to intersect",
    )

    @field_validator("zones")
    @classmethod
    def validate_zones_non_empty(cls, v: List[WardZoneGeometry]) -> List[WardZoneGeometry]:
        """Ensure at least one zone is provided."""
        if not v:
            raise ValueError("zones list must contain at least one WardZoneGeometry.")
        return v


class FloodImpactResponse(BaseModel):
    """Response payload containing spatial zone-level and building-level flood impacts."""
    incident_id: str
    is_demo_data: bool = Field(default=True, description="Explicitly flags synthetic GIS data as DEMO DATA")
    zone_impacts: List[ZoneImpactResult]
    summary: GISImpactSummary
    message: str = Field(
        default="Spatial flood impact analysis completed successfully."
    )
