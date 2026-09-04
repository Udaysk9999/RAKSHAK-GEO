"""Copilot Tool Registry, Validators, and Deterministic Executor (T-020).

Enforces schema-aware tool invocation over a fixed allowlist of 6 backend capabilities:
1. get_city_gis_data
2. assess_flood_gis_impact
3. optimize_resource_allocation
4. simulate_what_if_scenario
5. project_future_gap_timeline
6. run_end_to_end_flood_response

The LLM is NOT the source of truth; all calculations are executed by verified backend services.
All synthetic resources and geometries are labeled DEMO DATA per agent.md.
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type, Union
from pydantic import BaseModel, ValidationError

from app.schemas.copilot import (
    AssessFloodGISImpactArgs,
    CityGISLayerType,
    CopilotToolCall,
    CopilotToolResult,
    GetCityGISDataArgs,
    OptimizeResourceAllocationArgs,
    ProjectFutureGapTimelineArgs,
    RunEndToEndFloodResponseArgs,
    SimulateWhatIfScenarioArgs,
)
from app.schemas.flood import GeoJSONGeometry
from app.schemas.flood_response import (
    FloodResponseAnalyzeRequest,
    ZoneBaselineProfile,
)
from app.schemas.gis import (
    BuildingFootprint,
    FloodImpactRequest,
    WardZoneGeometry,
)
from app.schemas.optimization import (
    OptimizationConstraint,
    OptimizationGoal,
    ResourceOptimizationRequest,
    ResourceQuantity,
    ZoneDemand,
)
from app.schemas.timeline import (
    FutureGapTimelineRequest,
    HourlyGrowthRule,
)
from app.schemas.what_if import (
    WhatIfSimulateRequest,
)
from app.services.city_gis_repository import CityGISRepository
from app.services.flood_response_service import FloodResponseService
from app.services.gis_service import GISFloodImpactService
from app.services.optimization_service import ResourceOptimizationService
from app.services.timeline_service import FutureGapTimelineService
from app.services.what_if_service import WhatIfSimulationService


def get_default_flood_extent() -> GeoJSONGeometry:
    """Return default detected flood corridor over Sabarmati Riverfront [DEMO DATA]."""
    return GeoJSONGeometry(
        type="Polygon",
        coordinates=[
            [
                [72.565, 23.020],
                [72.580, 23.020],
                [72.580, 23.050],
                [72.565, 23.050],
                [72.565, 23.020],
            ]
        ],
    )


def build_default_zone_demands(wards: List[WardZoneGeometry]) -> List[ZoneDemand]:
    """Helper building standard zone demands from city ward demographics [DEMO DATA]."""
    demands = []
    for w in wards:
        pop = w.population or 50000
        # Deterministic demand proportional to population
        gross_demand = ResourceQuantity(
            ambulances=max(2, int(pop / 10000)),
            rescue_boats=max(1, int(pop / 25000)),
            food_packets=max(500, int(pop / 50)),
            medical_kits=max(100, int(pop / 200)),
            personnel=max(10, int(pop / 2000)),
        )
        local_cap = ResourceQuantity(
            ambulances=1,
            rescue_boats=0,
            food_packets=200,
            medical_kits=30,
            personnel=5,
        )
        gap = ResourceQuantity(
            ambulances=max(0, gross_demand.ambulances - local_cap.ambulances),
            rescue_boats=max(0, gross_demand.rescue_boats - local_cap.rescue_boats),
            food_packets=max(0, gross_demand.food_packets - local_cap.food_packets),
            medical_kits=max(0, gross_demand.medical_kits - local_cap.medical_kits),
            personnel=max(0, gross_demand.personnel - local_cap.personnel),
        )
        demands.append(
            ZoneDemand(
                zone_id=w.zone_id,
                zone_name=w.zone_name,
                priority=7 if "WEST" in w.zone_id or "01" in w.zone_id else 5,
                severity_score=7.0 if "WEST" in w.zone_id or "01" in w.zone_id else 4.0,
                demand=gross_demand,
                local_capacity=local_cap,
                response_gap=gap,
            )
        )
    return demands


@dataclass
class ToolDefinition:
    """Specification of an allowed Copilot backend tool."""
    name: str
    description: str
    argument_schema: Type[BaseModel]
    executor: Callable[[BaseModel], Dict[str, Any]]
    cited_endpoint: str
    is_read_only: bool = True


class ToolRegistry:
    """Fixed, closed registry of allowed backend tools."""

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register an allowed tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition:
        """Retrieve a tool by exact name or raise KeyError."""
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' is not registered in the fixed Copilot allowlist.")
        return self._tools[name]

    def list_tools(self) -> List[ToolDefinition]:
        """Return all registered tool definitions."""
        return list(self._tools.values())

    def contains(self, name: str) -> bool:
        """Check if tool name is registered."""
        return name in self._tools


# -----------------------------------------------------------------------------
# Tool Implementation Functions (Calling verified services)
# -----------------------------------------------------------------------------

def _execute_get_city_gis_data(args: GetCityGISDataArgs) -> Dict[str, Any]:
    """Execute City GIS repository queries for municipal spatial layers."""
    layer = args.layer
    city_id = args.city_id
    zone_id = args.zone_id
    evacuation_only = args.evacuation_only

    if layer == CityGISLayerType.SUMMARY:
        summary = CityGISRepository.get_inventory_summary(city_id=city_id)
        return summary.model_dump()
    elif layer == CityGISLayerType.WARDS:
        wards = CityGISRepository.get_ward_geometries(city_id=city_id)
        return {"wards": [w.model_dump() for w in wards], "count": len(wards), "city_id": city_id}
    elif layer == CityGISLayerType.BUILDINGS:
        bldgs = CityGISRepository.get_building_footprints(city_id=city_id, zone_id=zone_id)
        return {"buildings": [b.model_dump() for b in bldgs], "count": len(bldgs), "zone_id": zone_id}
    elif layer == CityGISLayerType.HOSPITALS:
        hosps = CityGISRepository.get_hospitals(city_id=city_id, zone_id=zone_id)
        return {"hospitals": [h.model_dump() for h in hosps], "count": len(hosps), "zone_id": zone_id}
    elif layer == CityGISLayerType.SHELTERS:
        shelters = CityGISRepository.get_shelters(city_id=city_id, zone_id=zone_id)
        return {"shelters": [s.model_dump() for s in shelters], "count": len(shelters), "zone_id": zone_id}
    elif layer == CityGISLayerType.ROADS:
        roads = CityGISRepository.get_roads(city_id=city_id, zone_id=zone_id, evacuation_only=evacuation_only)
        return {"roads": [r.model_dump() for r in roads], "count": len(roads), "evacuation_only": evacuation_only}
    elif layer == CityGISLayerType.POPULATION:
        pop = CityGISRepository.get_population(city_id=city_id)
        return {"population_by_zone": pop, "total_population": sum(pop.values()), "city_id": city_id}
    elif layer == CityGISLayerType.RESOURCES:
        res = CityGISRepository.get_resources(city_id=city_id)
        return {"depot_resources": res.model_dump(), "city_id": city_id}
    else:
        raise ValueError(f"Unsupported layer '{layer}'.")


def _execute_assess_flood_gis_impact(args: AssessFloodGISImpactArgs) -> Dict[str, Any]:
    """Execute spatial 2D vector intersection via GISFloodImpactService."""
    city_id = args.city_id
    flood_extent = args.flood_extent or get_default_flood_extent()
    wards = CityGISRepository.get_ward_geometries(city_id=city_id)
    buildings = CityGISRepository.get_building_footprints(city_id=city_id)

    req = FloodImpactRequest(
        incident_id=f"INC-{city_id}-COPILOT-GIS",
        flood_extent=flood_extent,
        zones=wards,
        buildings=buildings,
    )
    res = GISFloodImpactService.assess_impact(req)
    return res.model_dump()


def _execute_optimize_resource_allocation(args: OptimizeResourceAllocationArgs) -> Dict[str, Any]:
    """Execute multi-criteria resource optimization solver via ResourceOptimizationService."""
    city_id = args.city_id
    avail = args.available_resources or CityGISRepository.get_resources(city_id=city_id)
    wards = CityGISRepository.get_ward_geometries(city_id=city_id)
    demands = build_default_zone_demands(wards)

    req = ResourceOptimizationRequest(
        incident_id=f"INC-{city_id}-COPILOT-OPT",
        objective=args.objective,
        available_resources=avail,
        zones=demands,
        constraints=OptimizationConstraint(reserve_margin_pct=args.reserve_margin_pct),
    )
    res = ResourceOptimizationService.optimize_allocation(req)
    return res.model_dump()


def _execute_simulate_what_if_scenario(args: SimulateWhatIfScenarioArgs) -> Dict[str, Any]:
    """Execute counterfactual shift comparison via WhatIfSimulationService."""
    city_id = args.city_id
    avail = CityGISRepository.get_resources(city_id=city_id)
    wards = CityGISRepository.get_ward_geometries(city_id=city_id)
    demands = build_default_zone_demands(wards)

    sim_req = WhatIfSimulateRequest(
        incident_id=f"INC-{city_id}-COPILOT-WHATIF",
        objective=OptimizationGoal.PRIORITIZE_CRITICAL_ZONES,
        base_available_resources=avail,
        base_zones=demands,
        changes=args.changes,
    )
    res = WhatIfSimulationService.simulate(sim_req)
    return res.model_dump()


def _execute_project_future_gap_timeline(args: ProjectFutureGapTimelineArgs) -> Dict[str, Any]:
    """Execute multi-horizon trajectory projection via FutureGapTimelineService."""
    city_id = args.city_id
    avail = CityGISRepository.get_resources(city_id=city_id)
    wards = CityGISRepository.get_ward_geometries(city_id=city_id)
    demands = build_default_zone_demands(wards)

    rule = HourlyGrowthRule(
        resource_type="all",
        rate_percentage_per_hour=args.growth_rate_pct_per_hour,
    )
    timeline_req = FutureGapTimelineRequest(
        incident_id=f"INC-{city_id}-COPILOT-TIMELINE",
        base_available_resources=avail,
        base_zones=demands,
        time_horizons_hours=[float(h) for h in args.time_horizons_hours],
        hourly_rules=[rule],
        run_optimization=True,
    )
    res = FutureGapTimelineService.generate_timeline(timeline_req)
    return res.model_dump()


def _execute_run_end_to_end_flood_response(args: RunEndToEndFloodResponseArgs) -> Dict[str, Any]:
    """Execute full operational chain via FloodResponseService."""
    city_id = args.city_id
    flood_extent = args.flood_extent or get_default_flood_extent()
    avail = args.available_resources or CityGISRepository.get_resources(city_id=city_id)
    wards = CityGISRepository.get_ward_geometries(city_id=city_id)
    buildings = CityGISRepository.get_building_footprints(city_id=city_id)

    profiles = [
        ZoneBaselineProfile(
            zone_id=w.zone_id,
            zone_name=w.zone_name,
            geometry=w.geometry,
            total_area_sq_km=w.total_area_sq_km,
            population=w.population,
            base_priority=7 if "WEST" in w.zone_id or "01" in w.zone_id else 5,
        )
        for w in wards
    ]

    req = FloodResponseAnalyzeRequest(
        incident_id=f"INC-{city_id}-COPILOT-E2E",
        flood_extent=flood_extent,
        zones=profiles,
        buildings=buildings,
        available_resources=avail,
        objective=args.objective,
        constraints=OptimizationConstraint(reserve_margin_pct=args.reserve_margin_pct),
        only_allocate_to_affected=args.only_allocate_to_affected,
    )
    res = FloodResponseService.analyze_and_optimize(req)
    return res.model_dump()


# -----------------------------------------------------------------------------
# Global Registry Construction
# -----------------------------------------------------------------------------

def build_default_tool_registry() -> ToolRegistry:
    """Instantiate and populate the fixed registry with exactly the 6 allowed tools."""
    registry = ToolRegistry()

    registry.register(
        ToolDefinition(
            name="get_city_gis_data",
            description="Query municipal spatial layers: wards, building footprints, hospitals, shelters, roads, population, or depot resources.",
            argument_schema=GetCityGISDataArgs,
            executor=_execute_get_city_gis_data,
            cited_endpoint="GET /api/v1/city-data/{layer}",
            is_read_only=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="assess_flood_gis_impact",
            description="Intersect detected flood extent with city wards and buildings to compute submerged area, percentage flooded, and affected structures.",
            argument_schema=AssessFloodGISImpactArgs,
            executor=_execute_assess_flood_gis_impact,
            cited_endpoint="POST /api/v1/gis/impact",
            is_read_only=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="optimize_resource_allocation",
            description="Dispatch central emergency stockpiles (ambulances, boats, food, medical kits, personnel) across zones using deterministic multi-criteria optimization.",
            argument_schema=OptimizeResourceAllocationArgs,
            executor=_execute_optimize_resource_allocation,
            cited_endpoint="POST /api/v1/optimization/allocate",
            is_read_only=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="simulate_what_if_scenario",
            description="Simulate counterfactual disaster scenarios (stockpile changes, localized demand surges, or hospital capacity degradation) against baseline allocations.",
            argument_schema=SimulateWhatIfScenarioArgs,
            executor=_execute_simulate_what_if_scenario,
            cited_endpoint="POST /api/v1/what-if/simulate",
            is_read_only=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="project_future_gap_timeline",
            description="Project disaster response gaps and shortage trajectories across future hourly horizons (e.g. 0h, 6h, 12h, 18h, 24h).",
            argument_schema=ProjectFutureGapTimelineArgs,
            executor=_execute_project_future_gap_timeline,
            cited_endpoint="POST /api/v1/future-gap/timeline",
            is_read_only=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="run_end_to_end_flood_response",
            description="Execute full operational disaster pipeline: Flood Extent -> Spatial GIS Impact -> Dynamic Priority & Severity -> Net Response Gaps -> Optimized Stockpile Allocation.",
            argument_schema=RunEndToEndFloodResponseArgs,
            executor=_execute_run_end_to_end_flood_response,
            cited_endpoint="POST /api/v1/flood-response/analyze",
            is_read_only=True,
        )
    )

    return registry


default_tool_registry = build_default_tool_registry()


# -----------------------------------------------------------------------------
# Tool Executor
# -----------------------------------------------------------------------------

class ToolExecutor:
    """Executes registered backend tools with strict argument validation."""

    def __init__(self, registry: ToolRegistry = default_tool_registry):
        self.registry = registry

    def execute(self, tool_call: CopilotToolCall) -> CopilotToolResult:
        """Execute a validated tool call or return structured error."""
        name = tool_call.tool_name

        if not self.registry.contains(name):
            return CopilotToolResult(
                tool_name=name,
                success=False,
                error_message=f"Execution rejected: '{name}' is not in the allowed Copilot tool registry.",
            )

        tool_def = self.registry.get(name)

        # Validate arguments using the tool's specific Pydantic schema
        try:
            validated_args = tool_def.argument_schema(**tool_call.arguments)
        except ValidationError as val_err:
            return CopilotToolResult(
                tool_name=name,
                success=False,
                error_message=f"Validation failed for tool '{name}' arguments: {val_err}",
            )
        except Exception as exc:
            return CopilotToolResult(
                tool_name=name,
                success=False,
                error_message=f"Invalid arguments for tool '{name}': {str(exc)}",
            )

        # Invoke verified backend service
        try:
            result_data = tool_def.executor(validated_args)
            return CopilotToolResult(
                tool_name=name,
                success=True,
                result=result_data,
            )
        except Exception as exc:
            return CopilotToolResult(
                tool_name=name,
                success=False,
                error_message=f"Backend execution error in tool '{name}': {str(exc)}",
            )


default_tool_executor = ToolExecutor()


# -----------------------------------------------------------------------------
# Grounding Context Generation
# -----------------------------------------------------------------------------

def get_grounding_context(registry: Union[ToolRegistry, List[ToolDefinition]] = default_tool_registry) -> str:
    """Generate deterministic schema grounding documentation for LLM prompts."""
    lines = [
        "# CITYSHIELD GIS COPILOT GROUNDING & TOOL REGISTRY",
        "",
        "You are the CITYSHIELD GIS Disaster Response Copilot. You assist incident commanders",
        "and city authorities during urban disasters (e.g. Ahmedabad floods).",
        "",
        "## STRICT OPERATIONAL RULES",
        "1. The backend services are the sole authoritative source of truth. You MUST NEVER fabricate",
        "   numbers, casualties, spatial coordinates, flooded areas, or resource counts.",
        "2. To answer factual disaster queries, you MUST invoke one of the 6 registered backend tools.",
        "3. All synthetic municipal resources and geometries MUST be labeled 'DEMO DATA'.",
        "4. Never describe buildings as 'destroyed'; use 'CRITICAL', 'HIGH', or 'submerged'.",
        "5. Arbitrary SQL queries, shell commands, or unverified math calculations are strictly prohibited.",
        "",
        "## REGISTERED TOOLS",
    ]

    tools = registry if isinstance(registry, list) else registry.list_tools()
    for t in tools:
        lines.append(f"### `{t.name}`")
        lines.append(f"- **Description**: {t.description}")
        lines.append(f"- **Backed By**: `{t.cited_endpoint}`")
        lines.append(f"- **Read Only**: `{t.is_read_only}`")
        lines.append(f"- **Argument Schema**: `{t.argument_schema.__name__}`")
        lines.append("")

    return "\n".join(lines)
