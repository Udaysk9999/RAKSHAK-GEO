"""Data models and schemas for T-014 Resource Optimization API.

All synthetic disaster resources are explicitly labeled DEMO DATA per agent.md guidelines.
"""
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class OptimizationGoal(str, Enum):
    """Primary objective function for resource allocation."""
    PRIORITIZE_CRITICAL_ZONES = "prioritize_critical_zones"
    BALANCED_ALLOCATION = "balanced_allocation"
    MAXIMIZE_COVERAGE = "maximize_coverage"
    MINIMIZE_RESPONSE_TIME = "minimize_response_time"


class ResourceQuantity(BaseModel):
    """Resource inventory counts by resource type."""
    ambulances: int = Field(default=0, ge=0, description="Emergency medical transport units")
    rescue_boats: int = Field(default=0, ge=0, description="Water rescue crafts")
    food_packets: int = Field(default=0, ge=0, description="Ration and nutrition supply packs")
    medical_kits: int = Field(default=0, ge=0, description="First aid and trauma care kits")
    personnel: int = Field(default=0, ge=0, description="Emergency response personnel count")
    extra: Dict[str, int] = Field(default_factory=dict, description="Additional custom resource items")

    def to_dict(self) -> Dict[str, int]:
        """Convert standard and extra resource counts to a unified dictionary."""
        base = {
            "ambulances": self.ambulances,
            "rescue_boats": self.rescue_boats,
            "food_packets": self.food_packets,
            "medical_kits": self.medical_kits,
            "personnel": self.personnel,
        }
        base.update(self.extra)
        return base

    @classmethod
    def from_dict(cls, data: Dict[str, int]) -> "ResourceQuantity":
        """Instantiate ResourceQuantity from a dictionary of resource counts."""
        standard_keys = {"ambulances", "rescue_boats", "food_packets", "medical_kits", "personnel"}
        standard_args = {k: data.get(k, 0) for k in standard_keys}
        extra_args = {k: v for k, v in data.items() if k not in standard_keys}
        return cls(**standard_args, extra=extra_args)


class ResourceItemAllocation(BaseModel):
    """Granular allocation metric for an individual resource type in a zone."""
    resource_type: str
    requested: int = Field(ge=0, description="Requested amount (need/response gap)")
    allocated: int = Field(ge=0, description="Allocated amount from available capacity")
    remaining_unmet: int = Field(ge=0, description="Unmet need remaining after allocation")
    fulfillment_rate: float = Field(ge=0.0, le=1.0, description="Ratio of allocated to requested")
    allocation_status: str = Field(description="FULLY_ALLOCATED | PARTIALLY_ALLOCATED | UNALLOCATED")


class ZoneDemand(BaseModel):
    """Need/demand assessment for a specific GIS disaster zone."""
    zone_id: str = Field(..., description="Unique zone identifier, e.g. 'ZONE-AHM-01'")
    zone_name: str = Field(..., description="Human-readable zone name")
    priority: int = Field(default=5, ge=1, le=10, description="Zone priority level (1=Low, 10=Highest)")
    severity_score: float = Field(default=1.0, ge=0.0, le=10.0, description="Disaster impact/severity score (0-10)")
    population_at_risk: int = Field(default=0, ge=0, description="Estimated affected population count")
    demand: ResourceQuantity = Field(..., description="Required resource quantities (gross need)")
    local_capacity: Optional[ResourceQuantity] = Field(
        default=None, description="Existing on-site resources already in this zone"
    )
    response_gap: Optional[ResourceQuantity] = Field(
        default=None, description="Net response gap (unmet need). If omitted, computed as max(0, demand - local_capacity)"
    )


class OptimizationConstraint(BaseModel):
    """Constraints governing resource dispatch and routing."""
    max_travel_time_minutes: Optional[float] = Field(default=60.0, ge=0.0)
    reserve_margin_percent: float = Field(default=0.0, ge=0.0, le=100.0, description="Reserve buffer percentage")


class ResourceOptimizationRequest(BaseModel):
    """Request payload for resource optimization allocation."""
    incident_id: str = Field(default="INC-DEMO-001", description="Incident reference identifier")
    objective: OptimizationGoal = Field(default=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES)
    available_resources: ResourceQuantity = Field(..., description="Total available stockpile across depots")
    zones: List[ZoneDemand] = Field(..., description="List of target disaster zones with unmet demand")
    constraints: Optional[OptimizationConstraint] = Field(default_factory=OptimizationConstraint)


class ZoneAllocationResult(BaseModel):
    """Allocation output for a specific zone."""
    zone_id: str
    zone_name: str
    priority: int = Field(description="Zone priority rating")
    severity_score: float = Field(description="Disaster severity score")
    effective_weight: float = Field(description="Calculated composite priority weight used in optimization")
    requested: ResourceQuantity = Field(description="Effective requested amount (response gap)")
    allocated: ResourceQuantity = Field(description="Amount allocated from stockpile")
    remaining_unmet_need: ResourceQuantity = Field(description="Remaining unmet need after allocation")
    fulfillment_rate: float = Field(ge=0.0, le=1.0, description="Overall fulfillment rate across resources")
    allocation_status: str = Field(description="FULLY_ALLOCATED | PARTIALLY_ALLOCATED | UNALLOCATED")
    resource_breakdown: Dict[str, ResourceItemAllocation] = Field(
        default_factory=dict, description="Detailed breakdown by resource item"
    )
    status_note: str = Field(default="Allocated deterministically [DEMO DATA]")


class OptimizationSummary(BaseModel):
    """Overall optimization execution summary."""
    total_zones: int
    fully_satisfied_zones: int
    partially_satisfied_zones: int
    unallocated_zones: int
    bottleneck_resources: List[str] = Field(
        default_factory=list, description="Resources where demand exceeded available capacity"
    )
    surplus_resources: List[str] = Field(
        default_factory=list, description="Resources with leftover capacity in stockpile"
    )
    overall_fulfillment_rate: float = Field(ge=0.0, le=1.0)


class ResourceOptimizationResponse(BaseModel):
    """Response payload returned by the optimization engine."""
    status: str = Field(default="OPTIMAL", description="Execution status: OPTIMAL | FEASIBLE_SHORTAGE | NO_CAPACITY")
    incident_id: str
    objective: OptimizationGoal
    is_demo_data: bool = Field(default=True, description="Explicitly flags synthetic resources as DEMO DATA")
    total_available: ResourceQuantity
    total_requested: ResourceQuantity
    total_allocated: ResourceQuantity
    remaining_stockpile: ResourceQuantity
    total_remaining_unmet: ResourceQuantity
    overall_fulfillment_rate: float = Field(ge=0.0, le=1.0)
    allocations: List[ZoneAllocationResult]
    summary: OptimizationSummary
    message: str = Field(default="Resource optimization executed successfully.")


class OptimizationStatusResponse(BaseModel):
    """Module health and capability inspection response."""
    module: str = "T-014 Resource Optimization Engine"
    version: str = "1.0.0"
    status: str = "operational"
    algorithm_implemented: bool = True
    supported_objectives: List[str] = [goal.value for goal in OptimizationGoal]
    message: str = "Deterministic resource optimization solver is fully operational."
