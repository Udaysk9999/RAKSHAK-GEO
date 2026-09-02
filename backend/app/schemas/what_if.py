"""Data models and schemas for T-015 What-If Simulation Engine.

Allows emergency managers to simulate scenario changes (resource stockpile shifts,
demand surges, facility damage/capacity changes, priority reclassifications) and
compare baseline allocation against simulated allocation using the T-014 optimization engine.
All synthetic resources are labeled DEMO DATA per agent.md.
"""
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from app.schemas.optimization import (
    OptimizationConstraint,
    OptimizationGoal,
    ResourceOptimizationResponse,
    ResourceQuantity,
    ZoneDemand,
)


class ResourceSignedQuantity(BaseModel):
    """Signed resource quantity delta (supports positive, zero, or negative numbers)."""
    ambulances: int = Field(default=0, description="Change in emergency medical transport units")
    rescue_boats: int = Field(default=0, description="Change in water rescue crafts")
    food_packets: int = Field(default=0, description="Change in ration supply packs")
    medical_kits: int = Field(default=0, description="Change in trauma care kits")
    personnel: int = Field(default=0, description="Change in response personnel count")
    extra: Dict[str, int] = Field(default_factory=dict, description="Change in additional custom resource items")

    def to_dict(self) -> Dict[str, int]:
        """Convert standard and extra resource counts to a dictionary."""
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
    def from_dict(cls, data: Dict[str, int]) -> "ResourceSignedQuantity":
        """Instantiate ResourceSignedQuantity from a dictionary of signed counts."""
        standard_keys = {"ambulances", "rescue_boats", "food_packets", "medical_kits", "personnel"}
        standard_args = {k: data.get(k, 0) for k in standard_keys}
        extra_args = {k: v for k, v in data.items() if k not in standard_keys}
        return cls(**standard_args, extra=extra_args)


class ZoneModifier(BaseModel):
    """Explicit modifiers to apply to a specific disaster zone in simulation."""
    zone_id: str = Field(..., description="Target zone identifier to modify")
    demand_deltas: Optional[Dict[str, int]] = Field(
        default=None,
        description="Relative changes to gross demand (e.g. {'ambulances': 5, 'food_packets': -200})",
    )
    demand_override: Optional[ResourceQuantity] = Field(
        default=None,
        description="Exact replacement for zone demand if provided",
    )
    local_capacity_deltas: Optional[Dict[str, int]] = Field(
        default=None,
        description="Relative changes to local on-site capacity (e.g. {'ambulances': -2} if facility flooded)",
    )
    local_capacity_override: Optional[ResourceQuantity] = Field(
        default=None,
        description="Exact replacement for local capacity if provided",
    )
    priority_override: Optional[int] = Field(
        default=None, ge=1, le=10, description="Override zone priority rating [1..10]"
    )
    severity_override: Optional[float] = Field(
        default=None, ge=0.0, le=10.0, description="Override zone disaster severity score [0..10]"
    )


class ScenarioChanges(BaseModel):
    """Specification of deterministic parameter shifts for the What-If simulation."""
    description: Optional[str] = Field(
        default="Emergency parameter shift simulation",
        description="Human-readable scenario description",
    )
    available_resource_deltas: Optional[Dict[str, int]] = Field(
        default=None,
        description="Additions or subtractions to central stockpile (e.g. {'ambulances': 10, 'rescue_boats': -3})",
    )
    available_resource_override: Optional[ResourceQuantity] = Field(
        default=None,
        description="Exact replacement for total available stockpile",
    )
    zone_changes: List[ZoneModifier] = Field(
        default_factory=list,
        description="List of specific zone modifications to apply",
    )
    objective_override: Optional[OptimizationGoal] = Field(
        default=None,
        description="Optional change in allocation objective function",
    )


class WhatIfSimulateRequest(BaseModel):
    """Request payload for running a What-If disaster response simulation."""
    incident_id: str = Field(default="INC-WHATIF-001", description="Incident reference identifier")
    objective: OptimizationGoal = Field(
        default=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        description="Baseline objective function",
    )
    base_available_resources: ResourceQuantity = Field(
        ..., description="Baseline available resource capacity across depots"
    )
    base_zones: List[ZoneDemand] = Field(
        ..., description="Baseline target disaster zones with initial demand and capacity"
    )
    constraints: Optional[OptimizationConstraint] = Field(
        default_factory=OptimizationConstraint,
        description="Dispatch constraints (reserve margin, travel time)",
    )
    changes: ScenarioChanges = Field(
        default_factory=ScenarioChanges,
        description="Scenario parameter shifts to simulate",
    )


class ResourceDelta(BaseModel):
    """Detailed baseline vs simulated comparison for a single resource type."""
    resource_type: str
    baseline: int
    simulated: int
    delta: int = Field(description="simulated - baseline (positive = increase, negative = decrease)")


class ZoneAllocationComparison(BaseModel):
    """Zone-level comparative analysis between baseline and simulation."""
    zone_id: str
    zone_name: str
    baseline_allocated: ResourceQuantity
    simulated_allocated: ResourceQuantity
    allocation_delta: ResourceSignedQuantity = Field(
        description="simulated_allocated - baseline_allocated (can be negative)"
    )
    baseline_unmet: ResourceQuantity
    simulated_unmet: ResourceQuantity
    unmet_delta: ResourceSignedQuantity = Field(
        description="simulated_unmet - baseline_unmet (can be negative)"
    )
    baseline_fulfillment_rate: float
    simulated_fulfillment_rate: float
    fulfillment_delta: float = Field(description="simulated_rate - baseline_rate")
    resource_deltas: Dict[str, ResourceDelta] = Field(
        default_factory=dict, description="Detailed per-resource allocation deltas"
    )
    status_impact: str = Field(
        description="IMPROVED | DEGRADED | UNCHANGED"
    )


class SimulationSummary(BaseModel):
    """High-level summary of simulation impact."""
    baseline_fulfillment_rate: float
    simulated_fulfillment_rate: float
    fulfillment_rate_change: float = Field(description="simulated - baseline fulfillment rate")
    baseline_total_unmet: ResourceQuantity
    simulated_total_unmet: ResourceQuantity
    unmet_demand_change: Dict[str, int] = Field(description="Change in total unmet units per resource type")
    allocated_resources_change: Dict[str, int] = Field(description="Change in total allocated units per resource type")
    improved_zones: List[str] = Field(default_factory=list, description="Zone IDs with higher fulfillment")
    degraded_zones: List[str] = Field(default_factory=list, description="Zone IDs with lower fulfillment")
    unchanged_zones: List[str] = Field(default_factory=list, description="Zone IDs with equal fulfillment")
    verdict: str = Field(description="IMPROVED | DEGRADED | NEUTRAL")
    summary_narrative: str = Field(description="Deterministic descriptive summary of the scenario outcome")


class WhatIfSimulateResponse(BaseModel):
    """Complete comparative response payload returned by the What-If Simulator."""
    incident_id: str
    is_demo_data: bool = Field(default=True, description="Explicitly flags synthetic disaster data as DEMO DATA")
    scenario_description: str
    baseline: ResourceOptimizationResponse = Field(description="Full baseline optimization result")
    simulated: ResourceOptimizationResponse = Field(description="Full simulated optimization result")
    zone_comparisons: List[ZoneAllocationComparison] = Field(
        description="Per-zone comparative diffs between baseline and simulation"
    )
    summary: SimulationSummary = Field(description="Executive comparative metrics and narrative verdict")
    message: str = Field(default="What-If simulation executed successfully using T-014 optimization engine.")
