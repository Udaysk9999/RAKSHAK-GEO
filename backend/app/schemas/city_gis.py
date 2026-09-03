"""City GIS spatial data models and PostGIS schema definitions.

Defines typed Pydantic models for core municipal spatial layers:
1. City & Dataset Metadata
2. Wards / Administrative Zones (Polygon/MultiPolygon)
3. Buildings & Critical Facilities (Point/Polygon)
4. Hospitals & Trauma Centers (Point/Polygon)
5. Evacuation Shelters & Relief Camps (Point/Polygon)
6. Road Network & Access Routes (LineString/MultiLineString)
7. Population Demographics (Ward/Block-level)
8. Emergency Stockpile Resources (Depots)
All synthetic entities are explicitly labeled DEMO DATA per agent.md.
"""
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.schemas.flood import GeoJSONGeometry
from app.schemas.gis import BuildingFootprint, WardZoneGeometry
from app.schemas.optimization import ResourceQuantity


class GeometryType(str, Enum):
    """Supported PostGIS geometry representation types."""
    POINT = "Point"
    POLYGON = "Polygon"
    MULTIPOLYGON = "MultiPolygon"
    LINESTRING = "LineString"
    MULTILINESTRING = "MultiLineString"


class DatasetSource(BaseModel):
    """Provenance and lineage metadata for an ingested city GIS layer."""
    source_id: str = Field(..., description="Unique source identifier (e.g. SRC-OSM-AHM)")
    name: str = Field(..., description="Data provider name (e.g. OpenStreetMap, Ahmedabad Municipal Corp)")
    license: Optional[str] = Field("ODbL / Open Data", description="Data license terms")
    acquisition_date: Optional[str] = Field(None, description="Date of dataset capture or download (ISO 8601)")
    version: str = Field("1.0.0", description="Dataset revision or release version")
    feature_count: int = Field(default=0, ge=0, description="Number of spatial features in layer")


class CityMetadata(BaseModel):
    """Metadata describing a municipal boundary and its spatial reference."""
    city_id: str = Field(default="AHMEDABAD", description="Standard city identifier (e.g. AHMEDABAD, SURAT, MUMBAI)")
    city_name: str = Field(default="Ahmedabad", description="Human-readable city name")
    state: str = Field(default="Gujarat", description="State or province")
    country: str = Field(default="India", description="Country name")
    crs: str = Field(default="EPSG:4326", description="Spatial coordinate reference system (WGS84)")
    bounding_box: Optional[List[float]] = Field(
        default=None, description="[min_lon, min_lat, max_lon, max_lat]"
    )
    total_population: Optional[int] = Field(default=None, ge=0)
    total_area_sq_km: Optional[float] = Field(default=None, ge=0.0)


class RoadSegment(BaseModel):
    """Road network link or evacuation access corridor."""
    road_id: str = Field(..., description="Unique road segment identifier (e.g. ROAD-SABARMATI-EXPR)")
    name: Optional[str] = Field(None, description="Street or corridor name (e.g. Ashram Road)")
    road_type: str = Field(default="primary", description="Classification: motorway, trunk, primary, secondary, tertiary, residential")
    city_id: str = Field(default="AHMEDABAD", description="City identifier")
    zone_id: Optional[str] = Field(None, description="Traversed administrative zone ID")
    lanes: Optional[int] = Field(default=2, ge=1, description="Number of traffic lanes")
    length_km: Optional[float] = Field(default=None, ge=0.0, description="Segment length in kilometers")
    is_evacuation_route: bool = Field(default=False, description="Designated emergency egress corridor")
    geometry: GeoJSONGeometry = Field(..., description="LineString or MultiLineString coordinate sequence")


class HospitalFacility(BaseModel):
    """Emergency medical center, clinic, or trauma care facility."""
    hospital_id: str = Field(..., description="Unique hospital identifier (e.g. HOSP-CIVIL-01)")
    name: str = Field(..., description="Facility name (e.g. Ahmedabad Civil Hospital)")
    city_id: str = Field(default="AHMEDABAD", description="City identifier")
    zone_id: str = Field(..., description="Administrative zone containing the facility")
    bed_capacity: int = Field(default=50, ge=0, description="Inpatient hospital bed capacity")
    icu_beds: int = Field(default=10, ge=0, description="Intensive care unit beds")
    has_emergency_ward: bool = Field(default=True, description="24/7 trauma emergency department availability")
    geometry: GeoJSONGeometry = Field(..., description="Point or Polygon footprint")


class ShelterFacility(BaseModel):
    """Designated disaster relief camp or evacuation shelter."""
    shelter_id: str = Field(..., description="Unique shelter identifier (e.g. SHELTER-COMMUNITY-01)")
    name: str = Field(..., description="Shelter name (e.g. Sabarmati Municipal High School Relief Camp)")
    city_id: str = Field(default="AHMEDABAD", description="City identifier")
    zone_id: str = Field(..., description="Administrative zone containing the shelter")
    occupancy_capacity: int = Field(default=500, ge=0, description="Maximum evacuee shelter capacity")
    has_generator: bool = Field(default=True, description="Backup power generator on-site")
    potable_water_liters: int = Field(default=5000, ge=0, description="On-site drinking water storage in liters")
    geometry: GeoJSONGeometry = Field(..., description="Point or Polygon footprint")


class PopulationDemographic(BaseModel):
    """Granular census/demographic profile for an administrative zone."""
    zone_id: str = Field(..., description="Associated zone identifier")
    city_id: str = Field(default="AHMEDABAD")
    total_population: int = Field(..., ge=0, description="Total resident population")
    elderly_count: Optional[int] = Field(default=0, ge=0, description="Vulnerable elderly residents (>65 yrs)")
    children_count: Optional[int] = Field(default=0, ge=0, description="Vulnerable children (<10 yrs)")
    household_count: Optional[int] = Field(default=0, ge=0, description="Number of residential households")
    density_per_sq_km: Optional[float] = Field(default=None, ge=0.0)


class CityGISInventorySummary(BaseModel):
    """Executive inventory of city spatial assets loaded in the platform."""
    city: CityMetadata
    wards_count: int
    buildings_count: int
    hospitals_count: int
    shelters_count: int
    roads_count: int
    total_population_indexed: int
    database_status: Dict[str, Any]
    is_demo_data: bool = Field(default=True)
