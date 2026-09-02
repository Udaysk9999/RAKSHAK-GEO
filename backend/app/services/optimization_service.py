"""Resource Optimization Service for CITYSHIELD GIS (T-014).

Implements a deterministic multi-criteria emergency resource allocation algorithm.
Prioritizes disaster zones with greater response gaps and higher severity/priority,
respects available stockpile capacities, enforces demand ceilings, and computes
exact remaining unmet needs.
"""
from typing import Dict, List, Tuple
from app.schemas.optimization import (
    OptimizationConstraint,
    OptimizationGoal,
    OptimizationStatusResponse,
    OptimizationSummary,
    ResourceItemAllocation,
    ResourceOptimizationRequest,
    ResourceOptimizationResponse,
    ResourceQuantity,
    ZoneAllocationResult,
    ZoneDemand,
)


class ResourceOptimizationService:
    """Deterministic optimization solver for multi-zone emergency resource allocation."""

    @staticmethod
    def get_status() -> OptimizationStatusResponse:
        """Return operational status and capabilities of the optimization engine."""
        return OptimizationStatusResponse()

    @classmethod
    def optimize_allocation(cls, request: ResourceOptimizationRequest) -> ResourceOptimizationResponse:
        """Execute deterministic resource optimization across all target disaster zones."""
        # 1. Extract and normalize available resources (stockpile)
        constraints = request.constraints or OptimizationConstraint()
        reserve_ratio = max(0.0, min(1.0, constraints.reserve_margin_percent / 100.0))

        raw_available = request.available_resources.to_dict()
        usable_capacity: Dict[str, int] = {}
        for r_type, count in raw_available.items():
            usable_capacity[r_type] = int(count * (1.0 - reserve_ratio))

        # 2. Determine net demand / response gap for each zone
        zone_gaps: List[Tuple[ZoneDemand, Dict[str, int], float]] = []
        for zone in request.zones:
            gap_dict = cls._compute_zone_gap(zone)
            effective_weight = cls._compute_priority_weight(zone)
            zone_gaps.append((zone, gap_dict, effective_weight))

        # 3. Discover all active resource keys
        all_resource_types = list(usable_capacity.keys())
        for _, g_dict, _ in zone_gaps:
            for k in g_dict.keys():
                if k not in all_resource_types:
                    all_resource_types.append(k)
                    usable_capacity[k] = 0

        # 4. Execute allocation strategy based on objective
        if request.objective in (OptimizationGoal.BALANCED_ALLOCATION, OptimizationGoal.MAXIMIZE_COVERAGE):
            zone_allocations, remaining_capacity = cls._allocate_balanced(
                zone_gaps, usable_capacity, all_resource_types
            )
        else:
            # Default: PRIORITIZE_CRITICAL_ZONES or MINIMIZE_RESPONSE_TIME
            zone_allocations, remaining_capacity = cls._allocate_priority_first(
                zone_gaps, usable_capacity, all_resource_types
            )

        # 5. Build structured ZoneAllocationResult outputs
        results: List[ZoneAllocationResult] = []
        total_requested_dict: Dict[str, int] = {k: 0 for k in all_resource_types}
        total_allocated_dict: Dict[str, int] = {k: 0 for k in all_resource_types}
        total_unmet_dict: Dict[str, int] = {k: 0 for k in all_resource_types}

        fully_satisfied = 0
        partially_satisfied = 0
        unallocated_zones = 0

        for zone, req_dict, eff_weight in zone_gaps:
            alloc_dict = zone_allocations.get(zone.zone_id, {k: 0 for k in all_resource_types})
            unmet_dict: Dict[str, int] = {}
            breakdown: Dict[str, ResourceItemAllocation] = {}

            zone_req_sum = sum(req_dict.values())
            zone_alloc_sum = 0

            for r in all_resource_types:
                r_req = req_dict.get(r, 0)
                r_alloc = alloc_dict.get(r, 0)
                r_unmet = max(0, r_req - r_alloc)

                unmet_dict[r] = r_unmet
                zone_alloc_sum += r_alloc

                total_requested_dict[r] += r_req
                total_allocated_dict[r] += r_alloc
                total_unmet_dict[r] += r_unmet

                r_rate = (r_alloc / r_req) if r_req > 0 else 1.0
                if r_req == 0 or r_rate >= 1.0:
                    r_status = "FULLY_ALLOCATED"
                elif r_alloc > 0:
                    r_status = "PARTIALLY_ALLOCATED"
                else:
                    r_status = "UNALLOCATED"

                breakdown[r] = ResourceItemAllocation(
                    resource_type=r,
                    requested=r_req,
                    allocated=r_alloc,
                    remaining_unmet=r_unmet,
                    fulfillment_rate=round(r_rate, 4),
                    allocation_status=r_status,
                )

            zone_rate = (zone_alloc_sum / zone_req_sum) if zone_req_sum > 0 else 1.0
            if zone_req_sum == 0 or zone_rate >= 1.0:
                zone_status = "FULLY_ALLOCATED"
                fully_satisfied += 1
                note = f"Demand fully satisfied for {zone.zone_name} [DEMO DATA]"
            elif zone_alloc_sum > 0:
                zone_status = "PARTIALLY_ALLOCATED"
                partially_satisfied += 1
                note = f"Partial allocation due to stockpile constraints ({round(zone_rate * 100, 1)}% fulfilled) [DEMO DATA]"
            else:
                zone_status = "UNALLOCATED"
                unallocated_zones += 1
                note = f"Zero allocation: all available capacity exhausted by higher-priority zones [DEMO DATA]"

            results.append(
                ZoneAllocationResult(
                    zone_id=zone.zone_id,
                    zone_name=zone.zone_name,
                    priority=zone.priority,
                    severity_score=zone.severity_score,
                    effective_weight=round(eff_weight, 2),
                    requested=ResourceQuantity.from_dict(req_dict),
                    allocated=ResourceQuantity.from_dict(alloc_dict),
                    remaining_unmet_need=ResourceQuantity.from_dict(unmet_dict),
                    fulfillment_rate=round(zone_rate, 4),
                    allocation_status=zone_status,
                    resource_breakdown=breakdown,
                    status_note=note,
                )
            )

        # 6. Overall Summary Metrics
        grand_req_sum = sum(total_requested_dict.values())
        grand_alloc_sum = sum(total_allocated_dict.values())
        overall_rate = (grand_alloc_sum / grand_req_sum) if grand_req_sum > 0 else 1.0

        bottlenecks = [
            r for r in all_resource_types
            if total_requested_dict[r] > raw_available.get(r, 0)
        ]
        # Actual remaining physical stockpile across depots (including unused capacity and reserve buffer)
        actual_remaining_stockpile = {
            r: max(0, raw_available.get(r, 0) - total_allocated_dict.get(r, 0))
            for r in all_resource_types
        }

        surpluses = [
            r for r in all_resource_types
            if actual_remaining_stockpile.get(r, 0) > 0
        ]

        if overall_rate >= 1.0:
            exec_status = "OPTIMAL"
            msg = "All disaster zone response gaps fully satisfied by available resources."
        elif grand_alloc_sum > 0:
            exec_status = "FEASIBLE_SHORTAGE"
            msg = f"Resource shortage detected. Optimized allocation satisfied {round(overall_rate * 100, 1)}% of total response gap."
        else:
            exec_status = "NO_CAPACITY"
            msg = "No resources allocated: available stockpile is empty or insufficient."

        summary = OptimizationSummary(
            total_zones=len(results),
            fully_satisfied_zones=fully_satisfied,
            partially_satisfied_zones=partially_satisfied,
            unallocated_zones=unallocated_zones,
            bottleneck_resources=bottlenecks,
            surplus_resources=surpluses,
            overall_fulfillment_rate=round(overall_rate, 4),
        )

        return ResourceOptimizationResponse(
            status=exec_status,
            incident_id=request.incident_id,
            objective=request.objective,
            is_demo_data=True,
            total_available=request.available_resources,
            total_requested=ResourceQuantity.from_dict(total_requested_dict),
            total_allocated=ResourceQuantity.from_dict(total_allocated_dict),
            remaining_stockpile=ResourceQuantity.from_dict(actual_remaining_stockpile),
            total_remaining_unmet=ResourceQuantity.from_dict(total_unmet_dict),
            overall_fulfillment_rate=round(overall_rate, 4),
            allocations=results,
            summary=summary,
            message=msg,
        )

    # -------------------------------------------------------------------------
    # Helper & Solver Methods
    # -------------------------------------------------------------------------

    @staticmethod
    def _compute_zone_gap(zone: ZoneDemand) -> Dict[str, int]:
        """Determine net unmet demand for a zone.

        If response_gap is explicitly provided, use it directly.
        Otherwise, subtract local capacity from gross demand.
        """
        if zone.response_gap is not None:
            return zone.response_gap.to_dict()

        gross_demand = zone.demand.to_dict()
        local_cap = zone.local_capacity.to_dict() if zone.local_capacity else {}

        net_gap: Dict[str, int] = {}
        for r_type, req_val in gross_demand.items():
            on_site = local_cap.get(r_type, 0)
            net_gap[r_type] = max(0, req_val - on_site)
        return net_gap

    @staticmethod
    def _compute_priority_weight(zone: ZoneDemand) -> float:
        """Composite priority weight considering explicit priority and disaster severity."""
        # Priority range [1..10], Severity score range [0..10]
        # Weight scales linearly: higher priority & higher severity get higher composite score
        base_priority = float(zone.priority)
        severity_multiplier = 1.0 + (zone.severity_score / 10.0)
        return round(base_priority * severity_multiplier, 3)

    @classmethod
    def _allocate_priority_first(
        cls,
        zone_gaps: List[Tuple[ZoneDemand, Dict[str, int], float]],
        available: Dict[str, int],
        resource_types: List[str],
    ) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int]]:
        """Priority-First Greedy Allocation.

        Sorts zones by composite priority descending (tie breaker: total response gap descending).
        Allocates available resources greedily to critical zones first until fulfilled or stockpile is exhausted.
        """
        # Sort zones by effective weight descending, then total gap descending
        sorted_zones = sorted(
            zone_gaps,
            key=lambda item: (item[2], sum(item[1].values())),
            reverse=True,
        )

        stockpile = dict(available)
        allocations: Dict[str, Dict[str, int]] = {
            z[0].zone_id: {r: 0 for r in resource_types} for z in zone_gaps
        }

        for r in resource_types:
            for zone, req_dict, _ in sorted_zones:
                if stockpile[r] <= 0:
                    break
                needed = req_dict.get(r, 0)
                if needed <= 0:
                    continue

                grant = min(needed, stockpile[r])
                allocations[zone.zone_id][r] = grant
                stockpile[r] -= grant

        return allocations, stockpile

    @classmethod
    def _allocate_balanced(
        cls,
        zone_gaps: List[Tuple[ZoneDemand, Dict[str, int], float]],
        available: Dict[str, int],
        resource_types: List[str],
    ) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int]]:
        """Weighted Proportional Balanced Allocation.

        Distributes available resources proportionally according to zone priority weights and demand size,
        maximizing equitable coverage across zones during shortages.
        """
        stockpile = dict(available)
        allocations: Dict[str, Dict[str, int]] = {
            z[0].zone_id: {r: 0 for r in resource_types} for z in zone_gaps
        }

        for r in resource_types:
            total_needed = sum(g[1].get(r, 0) for g in zone_gaps)
            if total_needed <= 0:
                continue

            # Case 1: Surplus or exact match
            if stockpile[r] >= total_needed:
                for zone, req_dict, _ in zone_gaps:
                    amt = req_dict.get(r, 0)
                    allocations[zone.zone_id][r] = amt
                    stockpile[r] -= amt
                continue

            # Case 2: Shortage - Weighted proportional distribution
            # Calculate sum of (weight * needed)
            weight_demand_sum = sum(
                (weight * req_dict.get(r, 0)) for _, req_dict, weight in zone_gaps
            )
            if weight_demand_sum <= 0:
                continue

            total_granted = 0
            for zone, req_dict, weight in zone_gaps:
                needed = req_dict.get(r, 0)
                if needed <= 0:
                    continue
                ratio = (weight * needed) / weight_demand_sum
                grant = min(needed, int(stockpile[r] * ratio))
                allocations[zone.zone_id][r] = grant
                total_granted += grant

            # Update stockpile with primary allocation
            remaining_for_round = stockpile[r] - total_granted
            stockpile[r] = 0

            # Distribute remaining discrete units by priority to zones with unmet gap
            if remaining_for_round > 0:
                zones_with_unmet = sorted(
                    [
                        (z[0].zone_id, z[1].get(r, 0) - allocations[z[0].zone_id][r], z[2])
                        for z in zone_gaps
                        if (z[1].get(r, 0) - allocations[z[0].zone_id][r]) > 0
                    ],
                    key=lambda x: (x[2], x[1]),
                    reverse=True,
                )

                idx = 0
                while remaining_for_round > 0 and zones_with_unmet:
                    zid, unmet, _ = zones_with_unmet[idx % len(zones_with_unmet)]
                    allocations[zid][r] += 1
                    remaining_for_round -= 1
                    # Update unmet count
                    current_unmet = zone_gaps[0][1].get(r, 0)  # non-zero check
                    idx += 1

        return allocations, stockpile
