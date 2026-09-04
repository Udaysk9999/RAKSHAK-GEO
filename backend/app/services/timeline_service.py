"""Future Response Gap Timeline Service for CITYSHIELD GIS (T-016).

Executes deterministic multi-horizon projections of disaster zone demands,
local capacity shifts, and net response gaps over configurable time steps.
Reuses the T-014 optimization engine when resource allocation is enabled.
Does NOT employ stochastic or machine learning methods.
All synthetic resources are labeled DEMO DATA per agent.md.
"""
import copy
from typing import Dict, List, Optional

from app.schemas.optimization import (
    OptimizationConstraint,
    OptimizationGoal,
    ResourceOptimizationRequest,
    ResourceQuantity,
    ZoneDemand,
)
from app.schemas.timeline import (
    FutureGapTimelineRequest,
    FutureGapTimelineResponse,
    HourlyGrowthRule,
    TimelinePoint,
    TimelineSummary,
    TimeStepProjection,
    ZoneGapPoint,
)
from app.services.optimization_service import ResourceOptimizationService


class FutureGapTimelineService:
    """Orchestrates deterministic future response gap timeline projections."""

    @classmethod
    def generate_timeline(cls, request: FutureGapTimelineRequest) -> FutureGapTimelineResponse:
        """Project disaster conditions and response gaps across requested future time points."""
        # 1. Ensure time horizons are non-negative and deterministically ordered
        time_offsets = sorted(list(set(request.time_horizons_hours)))
        if 0.0 not in time_offsets:
            time_offsets.insert(0, 0.0)

        # Map explicit time-step projections by time offset for direct lookup
        step_map: Dict[float, TimeStepProjection] = {
            step.time_offset_hours: step for step in request.step_projections
        }

        # 2. Iterate across each time horizon
        timeline_points: List[TimelinePoint] = []
        all_resource_keys = set(request.base_available_resources.to_dict().keys())
        for z in request.base_zones:
            all_resource_keys.update(z.demand.to_dict().keys())
            if z.local_capacity:
                all_resource_keys.update(z.local_capacity.to_dict().keys())

        all_resources_list = sorted(list(all_resource_keys))

        for t in time_offsets:
            is_base = (t == 0.0)
            label = step_map[t].label if (t in step_map and step_map[t].label) else (
                "T+0h Initial Baseline" if is_base else f"T+{t:g}h Projected State"
            )

            # A. Derive available stockpile at time t (without mutating base input)
            avail_at_t = cls._project_available_resources(
                base=copy.deepcopy(request.base_available_resources),
                time_hours=t,
                step=step_map.get(t),
            )

            # B. Derive zone demands and local capacities at time t
            projected_zones = cls._project_zones(
                base_zones=copy.deepcopy(request.base_zones),
                time_hours=t,
                step=step_map.get(t),
                hourly_rules=request.hourly_rules,
            )

            # C. Calculate zone-level response gaps: gap = max(0, demand - local_capacity)
            zone_gap_points: List[ZoneGapPoint] = []
            tot_demand_dict: Dict[str, int] = {k: 0 for k in all_resources_list}
            tot_cap_dict: Dict[str, int] = {k: 0 for k in all_resources_list}
            tot_gap_dict: Dict[str, int] = {k: 0 for k in all_resources_list}

            for p_zone in projected_zones:
                d_dict = p_zone.demand.to_dict()
                c_dict = p_zone.local_capacity.to_dict() if p_zone.local_capacity else {}
                g_dict: Dict[str, int] = {}

                for r in all_resources_list:
                    d_val = d_dict.get(r, 0)
                    c_val = c_dict.get(r, 0)
                    g_val = max(0, d_val - c_val)

                    g_dict[r] = g_val
                    tot_demand_dict[r] += d_val
                    tot_cap_dict[r] += c_val
                    tot_gap_dict[r] += g_val

                # Set net response gap on the zone object for optimization reuse
                p_zone.response_gap = ResourceQuantity.from_dict(g_dict)

                zone_gap_points.append(
                    ZoneGapPoint(
                        zone_id=p_zone.zone_id,
                        zone_name=p_zone.zone_name,
                        priority=p_zone.priority,
                        severity_score=p_zone.severity_score,
                        demand=p_zone.demand,
                        local_capacity=ResourceQuantity.from_dict(c_dict),
                        response_gap=ResourceQuantity.from_dict(g_dict),
                    )
                )

            # D. Optionally run T-014 optimization for this time point
            total_allocated: Optional[ResourceQuantity] = None
            total_unmet: Optional[ResourceQuantity] = None
            overall_rate: Optional[float] = None
            opt_status: Optional[str] = None

            if request.run_optimization:
                opt_req = ResourceOptimizationRequest(
                    incident_id=f"{request.incident_id}-T{t:g}H",
                    objective=request.objective,
                    available_resources=avail_at_t,
                    zones=projected_zones,
                    constraints=copy.deepcopy(request.constraints),
                )
                opt_res = ResourceOptimizationService.optimize_allocation(opt_req)

                total_allocated = opt_res.total_allocated
                total_unmet = opt_res.total_remaining_unmet
                overall_rate = opt_res.overall_fulfillment_rate
                opt_status = opt_res.status

                # Map optimization allocation outputs back to ZoneGapPoints
                res_zone_map = {az.zone_id: az for az in opt_res.allocations}
                for zgp in zone_gap_points:
                    if zgp.zone_id in res_zone_map:
                        matched = res_zone_map[zgp.zone_id]
                        zgp.allocated = matched.allocated
                        zgp.unmet_need = matched.remaining_unmet_need
                        zgp.fulfillment_rate = matched.fulfillment_rate

            timeline_points.append(
                TimelinePoint(
                    time_offset_hours=t,
                    label=label,
                    is_baseline=is_base,
                    total_demand=ResourceQuantity.from_dict(tot_demand_dict),
                    total_local_capacity=ResourceQuantity.from_dict(tot_cap_dict),
                    total_response_gap=ResourceQuantity.from_dict(tot_gap_dict),
                    available_resources=avail_at_t,
                    zone_gaps=zone_gap_points,
                    total_allocated=total_allocated,
                    total_unmet_demand=total_unmet,
                    overall_fulfillment_rate=overall_rate,
                    optimization_status=opt_status,
                )
            )

        # 3. Generate Timeline Executive Summary
        summary = cls._generate_summary(timeline_points)

        return FutureGapTimelineResponse(
            incident_id=request.incident_id,
            is_demo_data=True,
            projection_type="DETERMINISTIC_PLANNING_MODEL",
            timeline_points=timeline_points,
            summary=summary,
            message="Future Response Gap Timeline projected successfully using deterministic modeling.",
        )

    # -------------------------------------------------------------------------
    # Projection Computation Helpers
    # -------------------------------------------------------------------------

    @classmethod
    def _project_available_resources(
        cls,
        base: ResourceQuantity,
        time_hours: float,
        step: Optional[TimeStepProjection],
    ) -> ResourceQuantity:
        """Compute available depot resources at future time t."""
        if step is not None:
            if step.available_resource_override is not None:
                return step.available_resource_override
            if step.available_resource_deltas:
                r_dict = base.to_dict()
                for r_type, delta in step.available_resource_deltas.items():
                    r_dict[r_type] = max(0, r_dict.get(r_type, 0) + delta)
                return ResourceQuantity.from_dict(r_dict)
        return base

    @classmethod
    def _project_zones(
        cls,
        base_zones: List[ZoneDemand],
        time_hours: float,
        step: Optional[TimeStepProjection],
        hourly_rules: List[HourlyGrowthRule],
    ) -> List[ZoneDemand]:
        """Project each zone's demand and local capacity over time_hours."""
        # Index explicit step modifications if present
        mod_map = {m.zone_id: m for m in step.zone_modifications} if step else {}

        for zone in base_zones:
            d_dict = zone.demand.to_dict()
            c_dict = zone.local_capacity.to_dict() if zone.local_capacity else {}

            # 1. Apply continuous hourly rules
            for rule in hourly_rules:
                if rule.zone_id is not None and rule.zone_id != zone.zone_id:
                    continue

                # Additive linear demand growth: delta * hours
                if rule.hourly_demand_delta:
                    for r_type, rate in rule.hourly_demand_delta.items():
                        added = int(rate * time_hours)
                        d_dict[r_type] = max(0, d_dict.get(r_type, 0) + added)

                # Compounding multiplicative demand growth: demand * (multiplier ^ hours)
                if rule.hourly_demand_multiplier and time_hours > 0:
                    for r_type, mult in rule.hourly_demand_multiplier.items():
                        if mult > 0:
                            scaled = int(d_dict.get(r_type, 0) * (mult ** time_hours))
                            d_dict[r_type] = max(0, scaled)

                # Additive local capacity degradation or replenishment: rate * hours
                if rule.hourly_capacity_delta:
                    for r_type, cap_rate in rule.hourly_capacity_delta.items():
                        c_shift = int(cap_rate * time_hours)
                        c_dict[r_type] = max(0, c_dict.get(r_type, 0) + c_shift)

            # 2. Apply discrete step overrides / deltas if defined for this specific hour
            if zone.zone_id in mod_map:
                mod = mod_map[zone.zone_id]

                if mod.priority_override is not None:
                    zone.priority = mod.priority_override
                if mod.severity_override is not None:
                    zone.severity_score = mod.severity_override

                if mod.demand_override is not None:
                    d_dict = mod.demand_override.to_dict()
                elif mod.demand_deltas:
                    for r_type, d_delta in mod.demand_deltas.items():
                        d_dict[r_type] = max(0, d_dict.get(r_type, 0) + d_delta)

                if mod.local_capacity_override is not None:
                    c_dict = mod.local_capacity_override.to_dict()
                elif mod.local_capacity_deltas:
                    for r_type, c_delta in mod.local_capacity_deltas.items():
                        c_dict[r_type] = max(0, c_dict.get(r_type, 0) + c_delta)

            zone.demand = ResourceQuantity.from_dict(d_dict)
            zone.local_capacity = ResourceQuantity.from_dict(c_dict)

        return base_zones

    @classmethod
    def _generate_summary(cls, points: List[TimelinePoint]) -> TimelineSummary:
        """Summarize response gap growth, peak hour, and critical resource deficits."""
        base_point = points[0]
        final_point = points[-1]

        base_sum = sum(base_point.total_response_gap.to_dict().values())
        final_sum = sum(final_point.total_response_gap.to_dict().values())

        peak_hours = base_point.time_offset_hours
        peak_sum = base_sum

        for pt in points:
            pt_sum = sum(pt.total_response_gap.to_dict().values())
            if pt_sum > peak_sum:
                peak_sum = pt_sum
                peak_hours = pt.time_offset_hours

        # Detect trend
        if final_sum > base_sum:
            trend = "EXPANDING"
        elif final_sum < base_sum:
            trend = "CONTRACTING"
        else:
            trend = "STABLE"

        # Identify bottleneck resources whose gap expanded the most
        base_gaps = base_point.total_response_gap.to_dict()
        final_gaps = final_point.total_response_gap.to_dict()
        bottlenecks = [
            r for r, val in final_gaps.items()
            if val > base_gaps.get(r, 0)
        ]

        if trend == "EXPANDING":
            narrative = (
                f"Projected response gap is EXPANDING: total unmet gap grows from {base_sum} units at T+0h "
                f"to {final_sum} units by T+{final_point.time_offset_hours:g}h (peaking at T+{peak_hours:g}h with {peak_sum} units). "
                f"Key resource shortages: {', '.join(bottlenecks) if bottlenecks else 'general demand growth'}."
            )
        elif trend == "CONTRACTING":
            narrative = (
                f"Projected response gap is CONTRACTING: total unmet gap declines from {base_sum} units at T+0h "
                f"to {final_sum} units by T+{final_point.time_offset_hours:g}h as emergency capacities stabilize."
            )
        else:
            narrative = (
                f"Projected response gap remains STABLE at {base_sum} total units across all evaluated time horizons."
            )

        return TimelineSummary(
            baseline_gap_units=base_sum,
            final_gap_units=final_sum,
            peak_gap_hours=peak_hours,
            peak_gap_units=peak_sum,
            gap_trend=trend,
            critical_bottleneck_resources=bottlenecks,
            summary_narrative=narrative,
        )


# Future Response-Gap Timeline Service Foundation (Step 6)
from app.services.response_gap_timeline_service import (  # noqa: E402
    FutureResponseGapTimelineService,
)
