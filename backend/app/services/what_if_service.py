"""What-If Simulation Service for CITYSHIELD GIS (T-015).

Reuses the existing T-014 deterministic optimization engine to simulate disaster scenarios
(stockpile changes, localized demand surges, infrastructure damage, and priority shifts)
without mutating original baseline data. Computes granular before-and-after comparative metrics.
All synthetic resources are explicitly labeled DEMO DATA.
"""
import copy
from typing import Dict, List

from app.schemas.optimization import (
    ResourceOptimizationRequest,
    ResourceOptimizationResponse,
    ResourceQuantity,
    ZoneDemand,
)
from app.schemas.what_if import (
    ResourceDelta,
    ResourceSignedQuantity,
    ScenarioChanges,
    SimulationSummary,
    WhatIfSimulateRequest,
    WhatIfSimulateResponse,
    ZoneAllocationComparison,
)
from app.services.optimization_service import ResourceOptimizationService


class WhatIfSimulationService:
    """Orchestrates What-If scenario parameter adjustments and baseline comparison."""

    @classmethod
    def simulate(cls, request: WhatIfSimulateRequest) -> WhatIfSimulateResponse:
        """Execute What-If simulation by running baseline, applying changes, and comparing."""
        # 1. Guarantee baseline data immutability by deep-copying inputs
        base_available = copy.deepcopy(request.base_available_resources)
        base_zones = copy.deepcopy(request.base_zones)
        base_constraints = copy.deepcopy(request.constraints)

        # 2. Run T-014 optimization on the baseline scenario
        baseline_request = ResourceOptimizationRequest(
            incident_id=f"{request.incident_id}-BASE",
            objective=request.objective,
            available_resources=base_available,
            zones=base_zones,
            constraints=base_constraints,
        )
        baseline_result = ResourceOptimizationService.optimize_allocation(baseline_request)

        # 3. Deterministically apply scenario modifications to a fresh clone
        sim_available = cls._apply_available_changes(
            copy.deepcopy(request.base_available_resources), request.changes
        )
        sim_zones = cls._apply_zone_changes(
            copy.deepcopy(request.base_zones), request.changes
        )
        sim_objective = request.changes.objective_override or request.objective

        # 4. Run T-014 optimization on the simulated scenario
        simulated_request = ResourceOptimizationRequest(
            incident_id=f"{request.incident_id}-SIM",
            objective=sim_objective,
            available_resources=sim_available,
            zones=sim_zones,
            constraints=base_constraints,
        )
        simulated_result = ResourceOptimizationService.optimize_allocation(simulated_request)

        # 5. Build zone-by-zone and resource-by-resource comparative analysis
        comparisons, summary = cls._build_comparison(
            baseline_result=baseline_result,
            simulated_result=simulated_result,
            changes=request.changes,
        )

        return WhatIfSimulateResponse(
            incident_id=request.incident_id,
            is_demo_data=True,
            scenario_description=request.changes.description or "What-If Emergency Simulation",
            baseline=baseline_result,
            simulated=simulated_result,
            zone_comparisons=comparisons,
            summary=summary,
            message="What-If simulation completed successfully via T-014 optimization engine.",
        )

    # -------------------------------------------------------------------------
    # Scenario Modification Helpers
    # -------------------------------------------------------------------------

    @classmethod
    def _apply_available_changes(
        cls, base: ResourceQuantity, changes: ScenarioChanges
    ) -> ResourceQuantity:
        """Apply deltas or override to available depot stockpile."""
        if changes.available_resource_override is not None:
            return changes.available_resource_override

        if not changes.available_resource_deltas:
            return base

        res_dict = base.to_dict()
        for r_type, delta in changes.available_resource_deltas.items():
            current_val = res_dict.get(r_type, 0)
            res_dict[r_type] = max(0, current_val + delta)
        return ResourceQuantity.from_dict(res_dict)

    @classmethod
    def _apply_zone_changes(
        cls, base_zones: List[ZoneDemand], changes: ScenarioChanges
    ) -> List[ZoneDemand]:
        """Apply localized zone modifications (demand surge, facility loss, priority)."""
        if not changes.zone_changes:
            return base_zones

        mod_map = {m.zone_id: m for m in changes.zone_changes}

        for zone in base_zones:
            if zone.zone_id not in mod_map:
                continue

            mod = mod_map[zone.zone_id]

            # Priority and Severity updates
            if mod.priority_override is not None:
                zone.priority = mod.priority_override
            if mod.severity_override is not None:
                zone.severity_score = mod.severity_override

            # Demand updates
            if mod.demand_override is not None:
                zone.demand = mod.demand_override
            elif mod.demand_deltas:
                d_dict = zone.demand.to_dict()
                for r_type, delta in mod.demand_deltas.items():
                    d_dict[r_type] = max(0, d_dict.get(r_type, 0) + delta)
                zone.demand = ResourceQuantity.from_dict(d_dict)

            # Local Capacity updates
            if mod.local_capacity_override is not None:
                zone.local_capacity = mod.local_capacity_override
            elif mod.local_capacity_deltas:
                c_dict = zone.local_capacity.to_dict() if zone.local_capacity else {}
                for r_type, delta in mod.local_capacity_deltas.items():
                    c_dict[r_type] = max(0, c_dict.get(r_type, 0) + delta)
                zone.local_capacity = ResourceQuantity.from_dict(c_dict)

            # Invalidate precomputed response gap so it is recalculated from new demand & capacity
            zone.response_gap = None

        return base_zones

    # -------------------------------------------------------------------------
    # Comparative Diffing Helpers
    # -------------------------------------------------------------------------

    @classmethod
    def _build_comparison(
        cls,
        baseline_result: ResourceOptimizationResponse,
        simulated_result: ResourceOptimizationResponse,
        changes: ScenarioChanges,
    ) -> tuple[List[ZoneAllocationComparison], SimulationSummary]:
        """Compute detailed delta breakdown between baseline and simulated outcomes."""
        base_zone_map = {z.zone_id: z for z in baseline_result.allocations}
        sim_zone_map = {z.zone_id: z for z in simulated_result.allocations}

        all_zone_ids = list(base_zone_map.keys())
        for zid in sim_zone_map.keys():
            if zid not in all_zone_ids:
                all_zone_ids.append(zid)

        comparisons: List[ZoneAllocationComparison] = []
        improved_zones: List[str] = []
        degraded_zones: List[str] = []
        unchanged_zones: List[str] = []

        # Discover all resource types present in baseline or simulation
        all_res_types = list(baseline_result.total_available.to_dict().keys())
        for r in simulated_result.total_available.to_dict().keys():
            if r not in all_res_types:
                all_res_types.append(r)

        for zid in all_zone_ids:
            b_alloc = base_zone_map.get(zid)
            s_alloc = sim_zone_map.get(zid)

            z_name = s_alloc.zone_name if s_alloc else (b_alloc.zone_name if b_alloc else zid)
            b_rate = b_alloc.fulfillment_rate if b_alloc else 0.0
            s_rate = s_alloc.fulfillment_rate if s_alloc else 0.0
            rate_delta = round(s_rate - b_rate, 4)

            b_alloc_dict = b_alloc.allocated.to_dict() if b_alloc else {r: 0 for r in all_res_types}
            s_alloc_dict = s_alloc.allocated.to_dict() if s_alloc else {r: 0 for r in all_res_types}

            b_unmet_dict = b_alloc.remaining_unmet_need.to_dict() if b_alloc else {r: 0 for r in all_res_types}
            s_unmet_dict = s_alloc.remaining_unmet_need.to_dict() if s_alloc else {r: 0 for r in all_res_types}

            alloc_diff: Dict[str, int] = {}
            unmet_diff: Dict[str, int] = {}
            res_deltas: Dict[str, ResourceDelta] = {}

            for r in all_res_types:
                b_val = b_alloc_dict.get(r, 0)
                s_val = s_alloc_dict.get(r, 0)
                a_delta = s_val - b_val
                alloc_diff[r] = a_delta

                b_u = b_unmet_dict.get(r, 0)
                s_u = s_unmet_dict.get(r, 0)
                u_delta = s_u - b_u
                unmet_diff[r] = u_delta

                res_deltas[r] = ResourceDelta(
                    resource_type=r,
                    baseline=b_val,
                    simulated=s_val,
                    delta=a_delta,
                )

            if rate_delta > 0.0001:
                status_impact = "IMPROVED"
                improved_zones.append(zid)
            elif rate_delta < -0.0001:
                status_impact = "DEGRADED"
                degraded_zones.append(zid)
            else:
                status_impact = "UNCHANGED"
                unchanged_zones.append(zid)

            comparisons.append(
                ZoneAllocationComparison(
                    zone_id=zid,
                    zone_name=z_name,
                    baseline_allocated=ResourceQuantity.from_dict(b_alloc_dict),
                    simulated_allocated=ResourceQuantity.from_dict(s_alloc_dict),
                    allocation_delta=ResourceSignedQuantity.from_dict(alloc_diff),
                    baseline_unmet=ResourceQuantity.from_dict(b_unmet_dict),
                    simulated_unmet=ResourceQuantity.from_dict(s_unmet_dict),
                    unmet_delta=ResourceSignedQuantity.from_dict(unmet_diff),
                    baseline_fulfillment_rate=round(b_rate, 4),
                    simulated_fulfillment_rate=round(s_rate, 4),
                    fulfillment_delta=rate_delta,
                    resource_deltas=res_deltas,
                    status_impact=status_impact,
                )
            )

        # Global metrics
        overall_b_rate = baseline_result.overall_fulfillment_rate
        overall_s_rate = simulated_result.overall_fulfillment_rate
        rate_change = round(overall_s_rate - overall_b_rate, 4)

        b_tot_alloc = baseline_result.total_allocated.to_dict()
        s_tot_alloc = simulated_result.total_allocated.to_dict()
        alloc_change = {r: s_tot_alloc.get(r, 0) - b_tot_alloc.get(r, 0) for r in all_res_types}

        b_tot_unmet = baseline_result.total_remaining_unmet.to_dict()
        s_tot_unmet = simulated_result.total_remaining_unmet.to_dict()
        unmet_change = {r: s_tot_unmet.get(r, 0) - b_tot_unmet.get(r, 0) for r in all_res_types}

        if rate_change > 0.0001:
            verdict = "IMPROVED"
            narrative = (
                f"Scenario '{changes.description}' improved overall response fulfillment from "
                f"{round(overall_b_rate * 100, 1)}% to {round(overall_s_rate * 100, 1)}% "
                f"(+{round(rate_change * 100, 1)}%). {len(improved_zones)} zone(s) gained increased coverage."
            )
        elif rate_change < -0.0001:
            verdict = "DEGRADED"
            narrative = (
                f"Scenario '{changes.description}' degraded overall response fulfillment from "
                f"{round(overall_b_rate * 100, 1)}% to {round(overall_s_rate * 100, 1)}% "
                f"({round(rate_change * 100, 1)}%). {len(degraded_zones)} zone(s) experienced increased unmet demand."
            )
        else:
            verdict = "NEUTRAL"
            narrative = (
                f"Scenario '{changes.description}' maintained equal overall fulfillment at "
                f"{round(overall_s_rate * 100, 1)}%. Allocation shifts remained neutral across evaluated zones."
            )

        summary = SimulationSummary(
            baseline_fulfillment_rate=round(overall_b_rate, 4),
            simulated_fulfillment_rate=round(overall_s_rate, 4),
            fulfillment_rate_change=rate_change,
            baseline_total_unmet=baseline_result.total_remaining_unmet,
            simulated_total_unmet=simulated_result.total_remaining_unmet,
            unmet_demand_change=unmet_change,
            allocated_resources_change=alloc_change,
            improved_zones=improved_zones,
            degraded_zones=degraded_zones,
            unchanged_zones=unchanged_zones,
            verdict=verdict,
            summary_narrative=narrative,
        )

        return comparisons, summary
