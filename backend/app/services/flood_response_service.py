"""End-to-End Flood Response Pipeline Orchestration Service (T-018).

Connects flood detection output to GIS zone impact and resource optimization:
Flood Extent -> GIS Impact -> Response Gap -> Resource Optimization.
Reuses existing GISFloodImpactService and ResourceOptimizationService without duplication.
All synthetic resources and disaster statistics are labeled DEMO DATA per agent.md.
"""
import copy
from typing import Dict, List, Optional

from app.schemas.flood_response import (
    FloodResponseAnalyzeRequest,
    FloodResponseAnalyzeResponse,
    IntegratedZoneResponse,
    ZoneBaselineProfile,
)
from app.schemas.gis import (
    FloodImpactRequest,
    FloodImpactResponse,
    ImpactLevel,
    WardZoneGeometry,
    ZoneImpactResult,
)
from app.schemas.optimization import (
    ResourceOptimizationRequest,
    ResourceOptimizationResponse,
    ResourceQuantity,
    ZoneDemand,
)
from app.services.gis_service import GISFloodImpactService
from app.services.optimization_service import ResourceOptimizationService


class FloodResponseService:
    """Orchestration service uniting flood spatial analysis with emergency resource dispatch."""

    @classmethod
    def analyze_and_optimize(cls, request: FloodResponseAnalyzeRequest) -> FloodImpactResponse:
        """Execute end-to-end flood response: GIS spatial intersection -> need calculation -> resource optimization."""
        # 1. Guarantee original input immutability
        zones_copy = copy.deepcopy(request.zones)
        bldgs_copy = copy.deepcopy(request.buildings)
        avail_copy = copy.deepcopy(request.available_resources)

        # 2. Stage 1: Invoke existing GIS spatial impact service
        ward_geometries = [
            WardZoneGeometry(
                zone_id=z.zone_id,
                zone_name=z.zone_name,
                total_area_sq_km=z.total_area_sq_km,
                geometry=z.geometry,
                population=z.population,
            )
            for z in zones_copy
        ]

        gis_req = FloodImpactRequest(
            incident_id=f"{request.incident_id}-GIS",
            flood_extent=request.flood_extent,
            zones=ward_geometries,
            buildings=bldgs_copy,
        )
        gis_response = GISFloodImpactService.assess_impact(gis_req)

        # Map GIS impact results by zone_id
        gis_map: Dict[str, ZoneImpactResult] = {
            zr.zone_id: zr for zr in gis_response.zone_impacts
        }

        # 3. Stage 2: Transform spatial impact into emergency demand & response gaps
        zone_demands: List[ZoneDemand] = []
        zone_profiles_map: Dict[str, ZoneBaselineProfile] = {z.zone_id: z for z in zones_copy}

        for zone_input in zones_copy:
            zid = zone_input.zone_id
            gis_res = gis_map.get(zid)

            impact_level = gis_res.impact_level if gis_res else ImpactLevel.UNAFFECTED
            flood_pct = gis_res.flood_affected_percentage if gis_res else 0.0

            # Derive priority and severity score deterministically based on impact level
            priority, severity_score = cls._derive_priority_and_severity(
                impact_level=impact_level,
                base_priority=zone_input.base_priority,
                flood_pct=flood_pct,
            )

            # Determine gross demand
            demand_qty = cls._determine_gross_demand(
                zone_input=zone_input,
                impact_level=impact_level,
                flood_pct=flood_pct,
                only_allocate_to_affected=request.only_allocate_to_affected,
            )

            # Determine local capacity
            local_cap_qty = zone_input.local_capacity or ResourceQuantity()

            # Calculate net response gap: max(0, demand - local_capacity)
            gap_dict: Dict[str, int] = {}
            d_dict = demand_qty.to_dict()
            c_dict = local_cap_qty.to_dict()
            all_keys = set(d_dict.keys()).union(c_dict.keys())

            for k in all_keys:
                gap_dict[k] = max(0, d_dict.get(k, 0) - c_dict.get(k, 0))

            gap_qty = ResourceQuantity.from_dict(gap_dict)

            zone_demands.append(
                ZoneDemand(
                    zone_id=zid,
                    zone_name=zone_input.zone_name,
                    priority=priority,
                    severity_score=severity_score,
                    demand=demand_qty,
                    local_capacity=local_cap_qty,
                    response_gap=gap_qty,
                )
            )

        # 4. Stage 3: Invoke existing T-014 Resource Optimization service
        opt_req = ResourceOptimizationRequest(
            incident_id=f"{request.incident_id}-OPT",
            objective=request.objective,
            available_resources=avail_copy,
            zones=zone_demands,
            constraints=request.constraints,
        )
        opt_response = ResourceOptimizationService.optimize_allocation(opt_req)

        # Map optimization results by zone_id
        alloc_map = {az.zone_id: az for az in opt_response.allocations}

        # 5. Stage 4: Combine GIS impact and optimization dispatch outputs
        integrated_zones: List[IntegratedZoneResponse] = []

        for zd in zone_demands:
            zid = zd.zone_id
            gis_res = gis_map.get(zid)
            alloc_res = alloc_map.get(zid)

            allocated = alloc_res.allocated if alloc_res else ResourceQuantity()
            unmet = alloc_res.remaining_unmet_need if alloc_res else zd.response_gap
            fulfillment = alloc_res.fulfillment_rate if alloc_res else 0.0
            status_note = alloc_res.status_note if alloc_res else "UNPROCESSED"

            integrated_zones.append(
                IntegratedZoneResponse(
                    zone_id=zid,
                    zone_name=zd.zone_name,
                    impact_level=gis_res.impact_level if gis_res else ImpactLevel.UNAFFECTED,
                    flood_affected_area_sq_km=gis_res.flood_affected_area_sq_km if gis_res else 0.0,
                    flood_affected_percentage=gis_res.flood_affected_percentage if gis_res else 0.0,
                    affected_building_count=gis_res.affected_building_count if gis_res else 0,
                    total_building_count=gis_res.total_building_count if gis_res else 0,
                    priority=zd.priority,
                    severity_score=zd.severity_score,
                    gross_demand=zd.demand,
                    local_capacity=zd.local_capacity or ResourceQuantity(),
                    net_response_gap=zd.response_gap or ResourceQuantity(),
                    allocated_resources=allocated,
                    remaining_unmet_need=unmet,
                    fulfillment_rate=fulfillment,
                    allocation_status=status_note,
                )
            )

        # 6. Synthesize Executive Narrative
        overall_status = opt_response.status
        if gis_response.summary.affected_zones_count == 0:
            overall_status = "NO_IMPACT"
            narrative = (
                "End-to-End Flood Assessment complete: Detected flood extent does not intersect any "
                "monitored city wards. Zero emergency resources dispatched."
            )
        else:
            narrative = (
                f"Flood response workflow executed across {gis_response.summary.total_zones_analyzed} zones. "
                f"Satellite analysis identified {gis_response.summary.affected_zones_count} inundated zones "
                f"({gis_response.summary.total_flood_area_sq_km} sq km flooded, "
                f"{gis_response.summary.total_buildings_affected} structures affected). "
                f"Resource optimization achieved {round(opt_response.overall_fulfillment_rate * 100, 1)}% "
                f"overall demand fulfillment under '{request.objective.value}' objective (Status: {opt_response.status})."
            )

        return FloodResponseAnalyzeResponse(
            incident_id=request.incident_id,
            is_demo_data=True,
            flood_impact_summary=gis_response.summary,
            zones=integrated_zones,
            total_available_resources=opt_response.total_available,
            total_allocated=opt_response.total_allocated,
            total_remaining_unmet_need=opt_response.total_remaining_unmet,
            overall_fulfillment_rate=opt_response.overall_fulfillment_rate,
            overall_status=overall_status,
            narrative_summary=narrative,
            message="End-to-end flood detection, GIS impact, and resource optimization pipeline completed.",
        )

    # -------------------------------------------------------------------------
    # Helper Derivations
    # -------------------------------------------------------------------------

    @classmethod
    def _derive_priority_and_severity(
        cls,
        impact_level: ImpactLevel,
        base_priority: int,
        flood_pct: float,
    ) -> (int, float):
        """Deterministically derive zone priority and disaster severity score from flood tier."""
        if impact_level == ImpactLevel.CRITICAL:
            return 10, min(10.0, 8.5 + (flood_pct / 100.0) * 1.5)
        elif impact_level == ImpactLevel.HIGH:
            return max(8, base_priority), min(8.5, 6.5 + (flood_pct / 60.0) * 2.0)
        elif impact_level == ImpactLevel.MODERATE:
            return max(6, base_priority), min(6.5, 4.5 + (flood_pct / 30.0) * 2.0)
        elif impact_level == ImpactLevel.LOW:
            return max(4, base_priority), min(4.5, 2.0 + (flood_pct / 10.0) * 2.5)
        else:
            return 1, 0.0

    @classmethod
    def _determine_gross_demand(
        cls,
        zone_input: ZoneBaselineProfile,
        impact_level: ImpactLevel,
        flood_pct: float,
        only_allocate_to_affected: bool,
    ) -> ResourceQuantity:
        """Calculate zone gross emergency demand from baseline or demographic estimates."""
        # If zone is unaffected and emergency policy restricts dispatch strictly to flooded zones:
        if only_allocate_to_affected and impact_level == ImpactLevel.UNAFFECTED:
            return ResourceQuantity()

        # If explicit baseline demand is provided:
        if zone_input.baseline_demand is not None:
            return zone_input.baseline_demand

        # Demographic estimation if demand omitted [DEMO DATA]
        pop = zone_input.population or 50000
        impact_scale = max(0.05, flood_pct / 100.0)

        # Approximate need proportional to affected population
        est_ambulances = max(1, int((pop / 20000) * impact_scale * 10))
        est_boats = max(1, int((pop / 30000) * impact_scale * 8)) if flood_pct > 10.0 else 0
        est_food = max(100, int((pop / 10) * impact_scale * 50))
        est_medical = max(10, int((pop / 100) * impact_scale * 20))
        est_personnel = max(5, int((pop / 1000) * impact_scale * 15))

        return ResourceQuantity(
            ambulances=est_ambulances,
            rescue_boats=est_boats,
            food_packets=est_food,
            medical_kits=est_medical,
            personnel=est_personnel,
        )
