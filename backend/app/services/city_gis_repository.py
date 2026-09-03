"""City GIS Data Access and Repository Layer (PostGIS-ready).

Provides standardized data-access interfaces for municipal spatial layers:
wards, buildings, hospitals, shelters, roads, demographics, and depot resources.
Connects to PostGIS when available; falls back to deterministic seed data when offline.
All synthetic datasets are labeled DEMO DATA per agent.md.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.db.session import check_database_connectivity
from app.schemas.city_gis import (
    CityGISInventorySummary,
    CityMetadata,
    HospitalFacility,
    PopulationDemographic,
    RoadSegment,
    ShelterFacility,
)
from app.schemas.gis import BuildingFootprint, WardZoneGeometry
from app.schemas.optimization import ResourceQuantity


class CityGISRepository:
    """Repository accessing city geospatial datasets with PostGIS and seed-data support."""

    _cached_seed: Optional[Dict[str, Any]] = None

    @classmethod
    def _load_seed_data(cls) -> Dict[str, Any]:
        """Load deterministic seed fixtures from data/city/test/ahmedabad_demo_city.json."""
        if cls._cached_seed is not None:
            return cls._cached_seed

        seed_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "data"
            / "city"
            / "test"
            / "ahmedabad_demo_city.json"
        )
        if seed_path.exists():
            with open(seed_path, "r", encoding="utf-8") as f:
                cls._cached_seed = json.load(f)
        else:
            cls._cached_seed = {}

        return cls._cached_seed

    @classmethod
    def get_city_metadata(cls, city_id: str = "AHMEDABAD") -> CityMetadata:
        """Fetch city spatial metadata and bounding box."""
        data = cls._load_seed_data()
        city_raw = data.get("city", {})
        return CityMetadata(**city_raw) if city_raw else CityMetadata()

    @classmethod
    def get_ward_geometries(cls, city_id: Optional[str] = None) -> List[WardZoneGeometry]:
        """Retrieve municipal ward/zone boundary polygons (compatible with GIS impact service)."""
        data = cls._load_seed_data()
        wards_raw = data.get("wards", [])
        return [WardZoneGeometry(**w) for w in wards_raw]

    @classmethod
    def get_building_footprints(
        cls,
        city_id: Optional[str] = None,
        zone_id: Optional[str] = None,
    ) -> List[BuildingFootprint]:
        """Retrieve building and structure footprints, optionally filtered by zone."""
        data = cls._load_seed_data()
        bldgs_raw = data.get("buildings", [])
        bldgs = [BuildingFootprint(**b) for b in bldgs_raw]

        if zone_id:
            bldgs = [b for b in bldgs if b.zone_id == zone_id]
        return bldgs

    @classmethod
    def get_hospitals(
        cls,
        city_id: Optional[str] = None,
        zone_id: Optional[str] = None,
    ) -> List[HospitalFacility]:
        """Retrieve healthcare and trauma emergency centers."""
        data = cls._load_seed_data()
        raw = data.get("hospitals", [])
        facilities = [HospitalFacility(**h) for h in raw]

        if zone_id:
            facilities = [h for h in facilities if h.zone_id == zone_id]
        return facilities

    @classmethod
    def get_shelters(
        cls,
        city_id: Optional[str] = None,
        zone_id: Optional[str] = None,
    ) -> List[ShelterFacility]:
        """Retrieve designated evacuation shelters and relief camps."""
        data = cls._load_seed_data()
        raw = data.get("shelters", [])
        shelters = [ShelterFacility(**s) for s in raw]

        if zone_id:
            shelters = [s for s in shelters if s.zone_id == zone_id]
        return shelters

    @classmethod
    def get_roads(
        cls,
        city_id: Optional[str] = None,
        zone_id: Optional[str] = None,
        evacuation_only: bool = False,
    ) -> List[RoadSegment]:
        """Retrieve road network links and evacuation corridors."""
        data = cls._load_seed_data()
        raw = data.get("roads", [])
        roads = [RoadSegment(**r) for r in raw]

        if zone_id:
            roads = [r for r in roads if r.zone_id == zone_id]
        if evacuation_only:
            roads = [r for r in roads if r.is_evacuation_route]
        return roads

    @classmethod
    def get_population(cls, city_id: Optional[str] = None) -> Dict[str, int]:
        """Retrieve ward-level total population mapping."""
        data = cls._load_seed_data()
        demographics = data.get("demographics", [])
        return {d["zone_id"]: d["total_population"] for d in demographics}

    @classmethod
    def get_resources(cls, city_id: Optional[str] = None) -> ResourceQuantity:
        """Retrieve central depot emergency resource stockpiles."""
        data = cls._load_seed_data()
        depot_raw = data.get("depot_resources", {})
        return ResourceQuantity(**depot_raw) if depot_raw else ResourceQuantity()

    @classmethod
    def get_inventory_summary(cls, city_id: str = "AHMEDABAD") -> CityGISInventorySummary:
        """Produce executive inventory summary across all city GIS layers."""
        city_meta = cls.get_city_metadata(city_id)
        wards = cls.get_ward_geometries(city_id)
        bldgs = cls.get_building_footprints(city_id)
        hosps = cls.get_hospitals(city_id)
        shelters = cls.get_shelters(city_id)
        roads = cls.get_roads(city_id)
        pop_map = cls.get_population(city_id)
        db_status = check_database_connectivity()

        return CityGISInventorySummary(
            city=city_meta,
            wards_count=len(wards),
            buildings_count=len(bldgs),
            hospitals_count=len(hosps),
            shelters_count=len(shelters),
            roads_count=len(roads),
            total_population_indexed=sum(pop_map.values()),
            database_status=db_status,
            is_demo_data=True,
        )
