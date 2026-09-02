"""Spatial GIS Intelligence and Flood Impact Assessment Service (T-017).

Connects flood extent vector boundaries with municipal ward/zone boundaries and
building footprints to determine spatial inundation, affected areas, and deterministic
impact levels without external geospatial library dependencies.
All synthetic geometry and disaster statistics are labeled DEMO DATA per agent.md.
"""
import copy
import math
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from app.schemas.flood import (
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONGeometry,
)
from app.schemas.gis import (
    BuildingFootprint,
    BuildingImpactDetail,
    FloodImpactRequest,
    FloodImpactResponse,
    GISImpactSummary,
    ImpactLevel,
    WardZoneGeometry,
    ZoneImpactResult,
)


class GISFloodImpactService:
    """Service evaluating spatial intersections between flood extents, wards, and buildings."""

    @classmethod
    def assess_impact(cls, request: FloodImpactRequest) -> FloodImpactResponse:
        """Perform spatial intersection and classify impact across zones and buildings."""
        # 1. Guarantee input immutability
        zones_copy = copy.deepcopy(request.zones)
        buildings_copy = copy.deepcopy(request.buildings)

        # 2. Parse flood extent exterior rings
        flood_polygons = cls._extract_polygon_rings(request.flood_extent)

        # 3. Process each building footprint
        building_impacts_by_zone: Dict[str, List[BuildingImpactDetail]] = {
            z.zone_id: [] for z in zones_copy
        }
        unassigned_buildings: List[BuildingImpactDetail] = []
        total_affected_buildings = 0

        for bldg in buildings_copy:
            is_affected = cls._is_building_flooded(bldg, flood_polygons)
            if is_affected:
                total_affected_buildings += 1

            detail = BuildingImpactDetail(
                building_id=bldg.building_id,
                name=bldg.name,
                building_type=bldg.building_type,
                zone_id=bldg.zone_id,
                is_affected=is_affected,
                inundation_status="AFFECTED" if is_affected else "UNAFFECTED",
            )

            # Assign building to appropriate zone
            target_zid = bldg.zone_id
            if not target_zid:
                # Spatial lookup: determine which zone contains this building
                target_zid = cls._find_containing_zone(bldg, zones_copy)
                detail.zone_id = target_zid

            if target_zid and target_zid in building_impacts_by_zone:
                building_impacts_by_zone[target_zid].append(detail)
            else:
                unassigned_buildings.append(detail)

        # 4. Process each ward/zone
        zone_results: List[ZoneImpactResult] = []
        total_flooded_area_all_zones = 0.0
        affected_zones_count = 0
        highest_impact_level = ImpactLevel.UNAFFECTED
        highest_impact_zone: Optional[str] = None
        severity_rank = {
            ImpactLevel.UNAFFECTED: 0,
            ImpactLevel.LOW: 1,
            ImpactLevel.MODERATE: 2,
            ImpactLevel.HIGH: 3,
            ImpactLevel.CRITICAL: 4,
        }

        for zone in zones_copy:
            ward_polygons = cls._extract_polygon_rings(zone.geometry)

            # Calculate total zone area (in sq km)
            geom_area = cls._calculate_total_area(ward_polygons)
            total_zone_area = zone.total_area_sq_km if (zone.total_area_sq_km and zone.total_area_sq_km > 0) else geom_area
            total_zone_area = max(0.0001, total_zone_area)

            # Calculate intersection area between ward and flood extent
            flooded_area = cls._calculate_intersection_area(ward_polygons, flood_polygons)
            # Area cannot exceed total zone area
            flooded_area = min(total_zone_area, flooded_area)
            total_flooded_area_all_zones += flooded_area

            # Percentage calculation
            affected_pct = round((flooded_area / total_zone_area) * 100.0, 2)
            affected_pct = min(100.0, max(0.0, affected_pct))

            # Building metrics for this zone
            zone_bldgs = building_impacts_by_zone.get(zone.zone_id, [])
            affected_bldgs = [b for b in zone_bldgs if b.is_affected]
            affected_bldg_count = len(affected_bldgs)
            total_bldg_count = len(zone_bldgs)

            # Deterministic impact classification
            impact_level = cls._classify_impact_level(affected_pct, affected_bldg_count)

            if impact_level != ImpactLevel.UNAFFECTED:
                affected_zones_count += 1

            if severity_rank[impact_level] > severity_rank[highest_impact_level]:
                highest_impact_level = impact_level
                highest_impact_zone = zone.zone_name

            zone_results.append(
                ZoneImpactResult(
                    zone_id=zone.zone_id,
                    zone_name=zone.zone_name,
                    total_area_sq_km=round(total_zone_area, 4),
                    flood_affected_area_sq_km=round(flooded_area, 4),
                    flood_affected_percentage=affected_pct,
                    affected_building_count=affected_bldg_count,
                    total_building_count=total_bldg_count,
                    impact_level=impact_level,
                    affected_buildings=affected_bldgs,
                )
            )

        # 5. Build Executive Summary
        if affected_zones_count == 0:
            narrative = (
                f"Flood assessment complete: No municipal zones or evaluated buildings intersect the detected "
                f"flood extent. Overall status: {ImpactLevel.UNAFFECTED.value}."
            )
        else:
            narrative = (
                f"Spatial flood impact detected across {affected_zones_count} of {len(zones_copy)} analyzed zones, "
                f"encompassing {round(total_flooded_area_all_zones, 2)} sq km and {total_affected_buildings} "
                f"inundated structures. Peak impact observed in '{highest_impact_zone}' with severity tier {highest_impact_level.value}."
            )

        summary = GISImpactSummary(
            total_zones_analyzed=len(zones_copy),
            affected_zones_count=affected_zones_count,
            total_flood_area_sq_km=round(total_flooded_area_all_zones, 4),
            total_buildings_analyzed=len(buildings_copy),
            total_buildings_affected=total_affected_buildings,
            highest_impact_zone=highest_impact_zone,
            highest_impact_level=highest_impact_level,
            summary_narrative=narrative,
        )

        return FloodImpactResponse(
            incident_id=request.incident_id,
            is_demo_data=True,
            zone_impacts=zone_results,
            summary=summary,
            message="Spatial flood impact layer calculated deterministically using geometric vector intersection.",
        )

    # -------------------------------------------------------------------------
    # Spatial Geometric Calculations
    # -------------------------------------------------------------------------

    @classmethod
    def _extract_polygon_rings(
        cls,
        geom_or_collection: Union[GeoJSONFeatureCollection, GeoJSONFeature, GeoJSONGeometry, Dict[str, Any]],
    ) -> List[List[List[float]]]:
        """Extract all exterior polygon rings as lists of [lon, lat] coordinates."""
        rings: List[List[List[float]]] = []

        if isinstance(geom_or_collection, GeoJSONFeatureCollection):
            for feature in geom_or_collection.features:
                rings.extend(cls._extract_from_geometry(feature.geometry))
        elif isinstance(geom_or_collection, GeoJSONFeature):
            rings.extend(cls._extract_from_geometry(geom_or_collection.geometry))
        elif isinstance(geom_or_collection, GeoJSONGeometry):
            rings.extend(cls._extract_from_geometry(geom_or_collection))
        elif isinstance(geom_or_collection, dict):
            g_type = geom_or_collection.get("type", "")
            if g_type == "FeatureCollection":
                for f in geom_or_collection.get("features", []):
                    rings.extend(cls._extract_from_dict_geom(f.get("geometry", {})))
            elif g_type == "Feature":
                rings.extend(cls._extract_from_dict_geom(geom_or_collection.get("geometry", {})))
            else:
                rings.extend(cls._extract_from_dict_geom(geom_or_collection))

        return rings

    @classmethod
    def _extract_from_geometry(cls, geom: GeoJSONGeometry) -> List[List[List[float]]]:
        """Extract exterior rings from GeoJSONGeometry."""
        g_type = geom.type.lower()
        coords = geom.coordinates
        rings: List[List[List[float]]] = []

        if g_type == "polygon":
            if coords and len(coords) > 0:
                rings.append(coords[0])  # Exterior ring
        elif g_type == "multipolygon":
            for poly in coords:
                if poly and len(poly) > 0:
                    rings.append(poly[0])  # Exterior ring of each polygon
        return rings

    @classmethod
    def _extract_from_dict_geom(cls, geom_dict: Dict[str, Any]) -> List[List[List[float]]]:
        """Extract exterior rings from raw geometry dict."""
        g_type = geom_dict.get("type", "").lower()
        coords = geom_dict.get("coordinates", [])
        rings: List[List[List[float]]] = []

        if g_type == "polygon":
            if coords and len(coords) > 0:
                rings.append(coords[0])
        elif g_type == "multipolygon":
            for poly in coords:
                if poly and len(poly) > 0:
                    rings.append(poly[0])
        return rings

    @classmethod
    def _ring_bbox(cls, ring: List[List[float]]) -> Tuple[float, float, float, float]:
        """Return (min_x, min_y, max_x, max_y) for a coordinate ring."""
        xs = [c[0] for c in ring]
        ys = [c[1] for c in ring]
        return (min(xs), min(ys), max(xs), max(ys))

    @classmethod
    def _ring_area_sq_km(cls, ring: List[List[float]]) -> float:
        """Calculate polygon area in square kilometers using Shoelace formula."""
        if len(ring) < 3:
            return 0.0

        n = len(ring)
        avg_lat = sum(c[1] for c in ring) / n
        # Geodetic conversion: 1 deg lat ~ 111.32 km; 1 deg lon ~ 111.32 * cos(lat) km
        lat_km = 111.32
        lon_km = 111.32 * max(0.01, math.cos(math.radians(avg_lat)))

        area = 0.0
        for i in range(n):
            x1 = ring[i][0] * lon_km
            y1 = ring[i][1] * lat_km
            x2 = ring[(i + 1) % n][0] * lon_km
            y2 = ring[(i + 1) % n][1] * lat_km
            area += (x1 * y2) - (x2 * y1)

        return abs(area) / 2.0

    @classmethod
    def _calculate_total_area(cls, rings: List[List[List[float]]]) -> float:
        """Sum area in sq km across multiple polygon rings."""
        return sum(cls._ring_area_sq_km(r) for r in rings)

    @classmethod
    def _pip_grid(cls, ring: List[List[float]], xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        """Vectorized point-in-polygon ray casting over a 2D meshgrid."""
        x = xs.flatten()
        y = ys.flatten()
        inside = np.zeros(x.shape, dtype=bool)
        n = len(ring)

        for i in range(n):
            x1, y1 = ring[i][:2]
            x2, y2 = ring[(i + 1) % n][:2]
            # Jordan curve theorem condition
            cond = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1)
            inside ^= cond

        return inside.reshape(xs.shape)

    @classmethod
    def _calculate_intersection_area(
        cls,
        ward_rings: List[List[List[float]]],
        flood_rings: List[List[List[float]]],
    ) -> float:
        """Calculate intersection area between ward polygons and flood extent polygons in sq km."""
        if not ward_rings or not flood_rings:
            return 0.0

        total_intersected_sq_km = 0.0

        for w_ring in ward_rings:
            w_min_x, w_min_y, w_max_x, w_max_y = cls._ring_bbox(w_ring)
            w_area = cls._ring_area_sq_km(w_ring)
            if w_area <= 0:
                continue

            for f_ring in flood_rings:
                f_min_x, f_min_y, f_max_x, f_max_y = cls._ring_bbox(f_ring)

                # Check bounding box overlap
                overlap_min_x = max(w_min_x, f_min_x)
                overlap_max_x = min(w_max_x, f_max_x)
                overlap_min_y = max(w_min_y, f_min_y)
                overlap_max_y = min(w_max_y, f_max_y)

                # No bounding box overlap -> zero intersection
                if overlap_min_x >= overlap_max_x or overlap_min_y >= overlap_max_y:
                    continue

                # Check if ward is fully enclosed by flood polygon
                # If all 4 bbox corners of ward are inside flood polygon, 100% intersection
                w_corners = [
                    (w_min_x, w_min_y), (w_max_x, w_min_y),
                    (w_max_x, w_max_y), (w_min_x, w_max_y),
                ]
                all_corners_in_flood = all(cls._point_in_polygon(cx, cy, f_ring) for cx, cy in w_corners)
                all_ward_pts_in_flood = all(cls._point_in_polygon(c[0], c[1], f_ring) for c in w_ring)

                if all_corners_in_flood and all_ward_pts_in_flood:
                    total_intersected_sq_km += w_area
                    continue

                # Discretize overlapping region using midpoint Riemann integration grid
                res = 60  # 60x60 = 3600 sampling points per overlapping polygon pair
                dx = (overlap_max_x - overlap_min_x) / res
                dy = (overlap_max_y - overlap_min_y) / res

                xc = np.linspace(overlap_min_x + dx / 2, overlap_max_x - dx / 2, res)
                yc = np.linspace(overlap_min_y + dy / 2, overlap_max_y - dy / 2, res)
                xs, ys = np.meshgrid(xc, yc)

                in_ward = cls._pip_grid(w_ring, xs, ys)
                in_flood = cls._pip_grid(f_ring, xs, ys)

                # Overlap fraction of grid
                overlap_cells = np.sum(in_ward & in_flood)
                if overlap_cells == 0:
                    continue

                # Convert overlap coordinate area to sq km
                avg_lat = (overlap_min_y + overlap_max_y) / 2.0
                lat_km = 111.32
                lon_km = 111.32 * max(0.01, math.cos(math.radians(avg_lat)))

                cell_area_sq_km = (dx * lon_km) * (dy * lat_km)
                intersect_area = overlap_cells * cell_area_sq_km
                total_intersected_sq_km += intersect_area

        return total_intersected_sq_km

    @classmethod
    def _point_in_polygon(cls, x: float, y: float, ring: List[List[float]]) -> bool:
        """Scalar ray-casting test to determine if point (x, y) is inside a polygon ring."""
        inside = False
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i][:2]
            x2, y2 = ring[(i + 1) % n][:2]
            if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1):
                inside = not inside
        return inside

    @classmethod
    def _is_building_flooded(
        cls,
        building: BuildingFootprint,
        flood_rings: List[List[List[float]]],
    ) -> bool:
        """Check if building point or polygon footprint intersects any flood extent ring."""
        g_type = building.geometry.type.lower()
        coords = building.geometry.coordinates

        if g_type == "point":
            if len(coords) >= 2:
                bx, by = coords[0], coords[1]
                return any(cls._point_in_polygon(bx, by, f_ring) for f_ring in flood_rings)
        else:
            # Polygon building footprint: check centroid and vertices
            b_rings = cls._extract_from_geometry(building.geometry)
            for b_ring in b_rings:
                # Check centroid
                cx = sum(c[0] for c in b_ring) / len(b_ring)
                cy = sum(c[1] for c in b_ring) / len(b_ring)
                if any(cls._point_in_polygon(cx, cy, f_ring) for f_ring in flood_rings):
                    return True
                # Check any vertex
                for c in b_ring:
                    if any(cls._point_in_polygon(c[0], c[1], f_ring) for f_ring in flood_rings):
                        return True
        return False

    @classmethod
    def _find_containing_zone(
        cls,
        building: BuildingFootprint,
        zones: List[WardZoneGeometry],
    ) -> Optional[str]:
        """Find the zone_id of the ward enclosing this building."""
        g_type = building.geometry.type.lower()
        coords = building.geometry.coordinates

        if g_type == "point":
            bx, by = coords[0], coords[1]
        else:
            b_rings = cls._extract_from_geometry(building.geometry)
            if not b_rings or not b_rings[0]:
                return None
            bx = sum(c[0] for c in b_rings[0]) / len(b_rings[0])
            by = sum(c[1] for c in b_rings[0]) / len(b_rings[0])

        for zone in zones:
            w_rings = cls._extract_polygon_rings(zone.geometry)
            if any(cls._point_in_polygon(bx, by, w_ring) for w_ring in w_rings):
                return zone.zone_id
        return None

    @classmethod
    def _classify_impact_level(cls, percentage: float, affected_buildings: int) -> ImpactLevel:
        """Deterministic severity classification rules based on flooded percentage."""
        if percentage <= 0.0001:
            if affected_buildings > 0:
                return ImpactLevel.LOW
            return ImpactLevel.UNAFFECTED
        elif percentage <= 10.0:
            return ImpactLevel.LOW
        elif percentage <= 30.0:
            return ImpactLevel.MODERATE
        elif percentage <= 60.0:
            return ImpactLevel.HIGH
        else:
            return ImpactLevel.CRITICAL
