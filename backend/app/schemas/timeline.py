"""Data models and schemas for T-016 Future Response Gap Timeline.

Provides deterministic projections of how disaster zone demand, local capacity,
and net response gaps evolve over configurable future time points (e.g. 0h, 6h, 12h, 24h).
These are deterministic planning projections based on specified rules, NOT ML/AI forecasts.
All synthetic resources are labeled DEMO DATA per agent.md.
"""
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from app.schemas.optimization import (
    OptimizationConstraint,
    OptimizationGoal,
    ResourceQuantity,
    ZoneDemand,
)
from app.schemas.what_if import ZoneModifier


class HourlyGrowthRule(BaseModel):
    """Deterministic rate-based growth or decay rule applied over elapsed hours."""
    zone_id: Optional[str] = Field(
        default=None,
        description="Target zone identifier. If None, rule applies globally to all zones.",
    )
    hourly_demand_delta: Optional[Dict[str, int]] = Field(
        default=None,
        description="Linear additive demand growth per elapsed hour (e.g. {'food_packets': 50})",
    )
    hourly_capacity_delta: Optional[Dict[str, int]] = Field(
        default=None,
        description="Linear capacity degradation or replenishment per hour (e.g. {'ambulances': -1})",
    )
    hourly_demand_multiplier: Optional[Dict[str, float]] = Field(
        default=None,
        description="Hourly compound growth factor (e.g. {'ambulances': 1.05} for +5%/hour)",
    )


class TimeStepProjection(BaseModel):
    """Explicit deterministic state modifications applied at a specific time point."""
    time_offset_hours: float = Field(
        ge=0.0,
        description="Time offset in hours from baseline (must be >= 0.0)",
    )
    label: Optional[str] = Field(default=None, description="Descriptive label for this time point")
    available_resource_deltas: Optional[Dict[str, int]] = Field(
        default=None,
        description="Stockpile capacity changes effective at this time step",
    )
    available_resource_override: Optional[ResourceQuantity] = Field(
        default=None,
        description="Exact replacement for available depot stockpile at this time step",
    )
    zone_modifications: List[ZoneModifier] = Field(
        default_factory=list,
        description="Specific zone demand/capacity/priority shifts for this time step",
    )


class FutureGapTimelineRequest(BaseModel):
    """Request payload to generate a Future Response Gap Timeline."""
    incident_id: str = Field(default="INC-TIMELINE-001", description="Incident reference identifier")
    base_available_resources: ResourceQuantity = Field(
        ..., description="Initial available resource capacity across depots at T+0h"
    )
    base_zones: List[ZoneDemand] = Field(
        ..., description="Baseline disaster zones evaluated at T+0h"
    )
    time_horizons_hours: List[float] = Field(
        default=[0.0, 6.0, 12.0, 18.0, 24.0],
        description="List of future time points in hours to evaluate (must be >= 0.0)",
    )
    step_projections: List[TimeStepProjection] = Field(
        default_factory=list,
        description="Explicit discrete scenario adjustments mapped to specific time offsets",
    )
    hourly_rules: List[HourlyGrowthRule] = Field(
        default_factory=list,
        description="Continuous deterministic growth/decay rules applied across time horizons",
    )
    run_optimization: bool = Field(
        default=True,
        description="Whether to run T-014 resource optimization for each projected time point",
    )
    objective: OptimizationGoal = Field(
        default=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        description="Objective function used when run_optimization is True",
    )
    constraints: Optional[OptimizationConstraint] = Field(
        default_factory=OptimizationConstraint,
        description="Dispatch constraints applied during optimization",
    )

    @field_validator("time_horizons_hours")
    @classmethod
    def validate_time_horizons(cls, v: List[float]) -> List[float]:
        """Ensure time horizons are non-empty, non-negative, and properly ordered."""
        if not v:
            raise ValueError("time_horizons_hours must contain at least one time offset.")
        for t in v:
            if t < 0.0:
                raise ValueError(f"Time offset {t} is invalid; time offsets must be >= 0.0 hours.")
        # Return sorted unique list
        return sorted(list(set(v)))

    @field_validator("base_zones")
    @classmethod
    def validate_base_zones(cls, v: List[ZoneDemand]) -> List[ZoneDemand]:
        """Ensure at least one zone is provided."""
        if not v:
            raise ValueError("base_zones must contain at least one disaster zone.")
        return v


class ZoneGapPoint(BaseModel):
    """Projected demand, capacity, and net response gap for a single zone at a specific time."""
    zone_id: str
    zone_name: str
    priority: int
    severity_score: float
    demand: ResourceQuantity
    local_capacity: ResourceQuantity
    response_gap: ResourceQuantity = Field(
        description="Net response gap: max(0, demand - local_capacity)"
    )
    allocated: Optional[ResourceQuantity] = Field(
        default=None, description="Resources allocated by T-014 optimization if run"
    )
    unmet_need: Optional[ResourceQuantity] = Field(
        default=None, description="Remaining unmet need after optimization dispatch"
    )
    fulfillment_rate: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Proportion of response gap met (0.0 to 1.0)"
    )


class TimelinePoint(BaseModel):
    """State of demand, capacity, response gap, and optimization at a discrete time point."""
    time_offset_hours: float
    label: str
    is_baseline: bool = Field(description="True if this is the T+0h initial baseline state")
    total_demand: ResourceQuantity
    total_local_capacity: ResourceQuantity
    total_response_gap: ResourceQuantity
    available_resources: ResourceQuantity
    zone_gaps: List[ZoneGapPoint]
    total_allocated: Optional[ResourceQuantity] = None
    total_unmet_demand: Optional[ResourceQuantity] = None
    overall_fulfillment_rate: Optional[float] = None
    optimization_status: Optional[str] = None


class TimelineSummary(BaseModel):
    """Executive summary of the projected response gap trajectory."""
    baseline_gap_units: int
    final_gap_units: int
    peak_gap_hours: float
    peak_gap_units: int
    gap_trend: str = Field(description="EXPANDING | CONTRACTING | STABLE")
    critical_bottleneck_resources: List[str] = Field(
        default_factory=list, description="Resource types with highest projected deficits"
    )
    summary_narrative: str = Field(
        description="Deterministic explanation of the projected timeline trajectory"
    )


class FutureGapTimelineResponse(BaseModel):
    """Complete response payload containing deterministic timeline projection."""
    incident_id: str
    is_demo_data: bool = Field(default=True, description="Explicitly flags synthetic resources as DEMO DATA")
    projection_type: str = Field(
        default="DETERMINISTIC_PLANNING_MODEL",
        description="Explicit notice: This is a deterministic planning model, not an ML/AI forecast.",
    )
    timeline_points: List[TimelinePoint]
    summary: TimelineSummary
    message: str = Field(
        default="Deterministic Future Response Gap Timeline projected successfully."
    )
