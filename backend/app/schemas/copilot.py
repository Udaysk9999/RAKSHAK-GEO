"""Pydantic schemas for CITYSHIELD GIS LLM Copilot (T-020).

Defines structured contracts for natural-language queries, tool invocations,
tool execution results, and grounded conversational responses.
All synthetic resources and geometries are labeled DEMO DATA per agent.md.
"""
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from app.schemas.flood import GeoJSONGeometry
from app.schemas.gis import BuildingFootprint, WardZoneGeometry
from app.schemas.optimization import (
    OptimizationConstraint,
    OptimizationGoal,
    ResourceQuantity,
    ZoneDemand,
)
from app.schemas.what_if import ScenarioChanges


class CopilotRole(str, Enum):
    """Message sender role."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class CopilotMessage(BaseModel):
    """Conversation history message."""
    role: CopilotRole
    content: str = Field(..., min_length=1)


class CopilotToolCall(BaseModel):
    """Structured instruction requesting execution of an allowed backend tool."""
    tool_name: str = Field(..., description="Name of the tool in the fixed allowlist")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Typed arguments for the tool")


class CopilotToolResult(BaseModel):
    """Deterministic result payload returned by backend tool execution."""
    tool_name: str
    success: bool
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class CopilotRequest(BaseModel):
    """Incoming user request for the disaster response Copilot."""
    query: str = Field(..., min_length=2, description="Natural language disaster question or command")
    incident_id: str = Field(default="INC-COPILOT-001", description="Operational incident identifier")
    city_id: str = Field(default="AHMEDABAD", description="Target city identifier")
    conversation_history: List[CopilotMessage] = Field(default_factory=list)
    force_tool: Optional[str] = Field(default=None, description="Optional override to force a specific tool for testing")
    live_synthesis: bool = Field(
        default=False,
        description="If True, requests a secondary LLM pass for natural language synthesis; if False, generates deterministic local grounded explanation.",
    )


class CopilotResponse(BaseModel):
    """Grounded natural language response generated from backend execution results."""
    query: str
    intent: str
    tool_executed: Optional[CopilotToolResult] = None
    explanation: str = Field(..., description="Grounded, factual narrative citing exact backend figures")
    cited_endpoints: List[str] = Field(default_factory=list, description="Backend API endpoints providing ground truth")
    is_demo_data: bool = Field(default=True, description="Identifies synthetic disaster resources as DEMO DATA")


# -----------------------------------------------------------------------------
# Tool-Specific Argument Schemas
# -----------------------------------------------------------------------------

class CityGISLayerType(str, Enum):
    """Supported municipal GIS layers."""
    SUMMARY = "summary"
    WARDS = "wards"
    BUILDINGS = "buildings"
    HOSPITALS = "hospitals"
    SHELTERS = "shelters"
    ROADS = "roads"
    POPULATION = "population"
    RESOURCES = "resources"


class GetCityGISDataArgs(BaseModel):
    """Arguments for querying municipal GIS datasets from PostGIS / City repository."""
    layer: CityGISLayerType = Field(..., description="Target municipal spatial layer")
    city_id: str = Field(default="AHMEDABAD", description="City identifier")
    zone_id: Optional[str] = Field(default=None, description="Optional administrative zone ID filter")
    evacuation_only: bool = Field(default=False, description="Filter for designated emergency evacuation corridors")


class AssessFloodGISImpactArgs(BaseModel):
    """Arguments for spatial intersection between flood extent and city assets."""
    flood_extent: Optional[GeoJSONGeometry] = Field(
        default=None,
        description="Optional flood vector polygon; if None, uses default detected Sentinel-2 extent [DEMO DATA]",
    )
    city_id: str = Field(default="AHMEDABAD", description="City identifier")


class OptimizeResourceAllocationArgs(BaseModel):
    """Arguments for multi-criteria emergency stockpile optimization."""
    available_resources: Optional[ResourceQuantity] = Field(
        default=None,
        description="Available stockpile; if None, pulls central depot resources from City GIS repository [DEMO DATA]",
    )
    objective: OptimizationGoal = Field(
        default=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        description="Optimization objective function",
    )
    reserve_margin_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=50.0,
        description="Safety stockpile reserve buffer percentage [0..50%]",
    )
    city_id: str = Field(default="AHMEDABAD", description="City identifier")


class SimulateWhatIfScenarioArgs(BaseModel):
    """Arguments for counterfactual What-If scenario shifts."""
    changes: ScenarioChanges = Field(
        ...,
        description="Hypothetical shifts: resource stockpile deltas or zone demand/capacity modifiers",
    )
    city_id: str = Field(default="AHMEDABAD", description="City identifier")


class ProjectFutureGapTimelineArgs(BaseModel):
    """Arguments for multi-horizon future response gap timeline projection."""
    time_horizons_hours: List[int] = Field(
        default=[0, 6, 12, 18, 24],
        min_length=1,
        description="Future time horizons in hours (e.g. [0, 6, 12, 18, 24])",
    )
    growth_rate_pct_per_hour: float = Field(
        default=10.0,
        ge=0.0,
        le=100.0,
        description="Compounding demand escalation percentage per hour",
    )
    city_id: str = Field(default="AHMEDABAD", description="City identifier")

    @field_validator("time_horizons_hours")
    @classmethod
    def validate_horizons(cls, v: List[int]) -> List[int]:
        """Ensure horizons are non-negative integers."""
        if any(h < 0 for h in v):
            raise ValueError("All time horizons must be non-negative integers.")
        return sorted(list(set(v)))


class RunEndToEndFloodResponseArgs(BaseModel):
    """Arguments for full operational pipeline: Flood -> GIS Impact -> Need -> Allocation."""
    flood_extent: Optional[GeoJSONGeometry] = Field(
        default=None,
        description="Optional flood vector polygon; if None, uses default detected extent [DEMO DATA]",
    )
    available_resources: Optional[ResourceQuantity] = Field(
        default=None,
        description="Optional stockpile; if None, pulls central depot resources from City GIS repository",
    )
    objective: OptimizationGoal = Field(
        default=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        description="Optimization objective function",
    )
    reserve_margin_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=50.0,
        description="Safety stockpile reserve buffer percentage",
    )
    only_allocate_to_affected: bool = Field(
        default=True,
        description="If True, only zones with verified flood inundation receive emergency dispatches",
    )
    city_id: str = Field(default="AHMEDABAD", description="City identifier")
