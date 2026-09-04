"""LLM Provider Abstraction and Deterministic Mock Provider (T-020).

Enables natural language intent routing and tool planning without vendor coupling.
The MockLLMProvider operates fully offline using deterministic pattern matching,
ensuring 100% reproducible testing without live external API keys.
All synthetic resources and geometries are labeled DEMO DATA per agent.md.
"""
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from app.schemas.copilot import (
    CityGISLayerType,
    CopilotMessage,
    CopilotToolCall,
    CopilotToolResult,
)
from app.schemas.optimization import OptimizationGoal, ResourceQuantity
from app.schemas.what_if import ResourceDelta, ScenarioChanges, ZoneModifier
from app.services.copilot.tools import ToolDefinition


class LLMPlanResult(BaseModel):
    """Result of LLM intent analysis: either a tool call to execute or direct conversational reply."""
    intent: str
    tool_call: Optional[CopilotToolCall] = None
    direct_response: Optional[str] = None


class BaseLLMProvider(ABC):
    """Abstract interface decoupling CITYSHIELD from specific LLM providers."""

    @abstractmethod
    def plan_tool_call(
        self,
        query: str,
        history: List[CopilotMessage],
        tools: List[ToolDefinition],
        force_tool: Optional[str] = None,
    ) -> LLMPlanResult:
        """Analyze query and determine appropriate backend tool call or direct message."""
        pass

    @abstractmethod
    def explain_result(
        self,
        query: str,
        intent: str,
        tool_result: Optional[CopilotToolResult],
    ) -> str:
        """Synthesize a grounded natural language explanation from backend tool results."""
        pass


class MockLLMProvider(BaseLLMProvider):
    """Deterministic, offline rule-based provider for testing and validation."""

    def plan_tool_call(
        self,
        query: str,
        history: List[CopilotMessage],
        tools: List[ToolDefinition],
        force_tool: Optional[str] = None,
    ) -> LLMPlanResult:
        """Map natural language queries to backend tool calls using deterministic regex rules."""
        # 1. Handle forced tool override (used for testing or explicit UI buttons)
        if force_tool:
            return self._build_forced_tool_call(force_tool, query)

        q = query.strip().lower()

        # 2. Pattern: What-If simulation
        if any(term in q for term in ["what if", "what-if", "suppose", "scenario", "add 5", "capacity drop"]):
            # Extract possible rescue boats or ambulances delta from query
            delta_boats = 5 if "5 rescue" in q or "5 boat" in q else 2
            changes = ScenarioChanges(
                description=f"Simulated addition of {delta_boats} rescue boats [DEMO DATA]",
                available_resource_deltas={"rescue_boats": delta_boats},
            )
            return LLMPlanResult(
                intent="what_if_simulation",
                tool_call=CopilotToolCall(
                    tool_name="simulate_what_if_scenario",
                    arguments={"changes": changes.model_dump(), "city_id": "AHMEDABAD"},
                ),
            )

        # 3. Pattern: Future Gap Timeline
        if any(term in q for term in ["timeline", "future gap", "future-gap", "hours", "horizon", "projection", "forecast"]):
            # Check if specific horizons are mentioned (e.g. 12 hours)
            if "12" in q:
                horizons = [0, 6, 12]
            elif "24" in q:
                horizons = [0, 6, 12, 18, 24]
            else:
                horizons = [0, 6, 12, 18]

            return LLMPlanResult(
                intent="future_gap_projection",
                tool_call=CopilotToolCall(
                    tool_name="project_future_gap_timeline",
                    arguments={"time_horizons_hours": horizons, "growth_rate_pct_per_hour": 10.0, "city_id": "AHMEDABAD"},
                ),
            )

        # 4. Pattern: End-to-end full flood response or highest response gap
        if any(term in q for term in ["end to end", "full response", "highest gap", "highest response gap", "operational response"]):
            return LLMPlanResult(
                intent="end_to_end_flood_response",
                tool_call=CopilotToolCall(
                    tool_name="run_end_to_end_flood_response",
                    arguments={"objective": OptimizationGoal.PRIORITIZE_CRITICAL_ZONES.value, "city_id": "AHMEDABAD"},
                ),
            )

        # 5. Pattern: Resource Optimization / Allocation
        if any(term in q for term in ["optimize", "allocation", "allocate", "dispatch", "distribute", "stockpile"]):
            return LLMPlanResult(
                intent="resource_optimization",
                tool_call=CopilotToolCall(
                    tool_name="optimize_resource_allocation",
                    arguments={"objective": OptimizationGoal.PRIORITIZE_CRITICAL_ZONES.value, "reserve_margin_pct": 5.0, "city_id": "AHMEDABAD"},
                ),
            )

        # 6. Pattern: Flood GIS Impact
        if any(term in q for term in ["flood impact", "inundat", "submerge", "flood extent", "flooded"]):
            return LLMPlanResult(
                intent="flood_gis_impact",
                tool_call=CopilotToolCall(
                    tool_name="assess_flood_gis_impact",
                    arguments={"city_id": "AHMEDABAD"},
                ),
            )

        # 7. Pattern: City GIS Data queries (Hospitals, Shelters, Roads, Wards, Demographics, Resources)
        if any(term in q for term in ["hospital", "clinic", "medical post"]):
            zone = "ZONE-AHM-EAST-02" if "maninagar" in q else None
            return LLMPlanResult(
                intent="query_city_hospitals",
                tool_call=CopilotToolCall(
                    tool_name="get_city_gis_data",
                    arguments={"layer": CityGISLayerType.HOSPITALS.value, "zone_id": zone, "city_id": "AHMEDABAD"},
                ),
            )

        if any(term in q for term in ["shelter", "relief camp", "evacuation camp"]):
            zone = "ZONE-AHM-EAST-02" if "maninagar" in q else None
            return LLMPlanResult(
                intent="query_city_shelters",
                tool_call=CopilotToolCall(
                    tool_name="get_city_gis_data",
                    arguments={"layer": CityGISLayerType.SHELTERS.value, "zone_id": zone, "city_id": "AHMEDABAD"},
                ),
            )

        if any(term in q for term in ["road", "corridor", "route", "egress", "evacuation route"]):
            return LLMPlanResult(
                intent="query_city_roads",
                tool_call=CopilotToolCall(
                    tool_name="get_city_gis_data",
                    arguments={"layer": CityGISLayerType.ROADS.value, "city_id": "AHMEDABAD", "evacuation_only": "evacuation" in q},
                ),
            )

        if any(term in q for term in ["population", "census", "resident", "people"]):
            return LLMPlanResult(
                intent="query_city_population",
                tool_call=CopilotToolCall(
                    tool_name="get_city_gis_data",
                    arguments={"layer": CityGISLayerType.POPULATION.value, "city_id": "AHMEDABAD"},
                ),
            )

        if any(term in q for term in ["ward", "zone", "boundary"]):
            return LLMPlanResult(
                intent="query_city_wards",
                tool_call=CopilotToolCall(
                    tool_name="get_city_gis_data",
                    arguments={"layer": CityGISLayerType.WARDS.value, "city_id": "AHMEDABAD"},
                ),
            )

        if any(term in q for term in ["inventory", "summary", "overview", "layers"]):
            return LLMPlanResult(
                intent="query_city_summary",
                tool_call=CopilotToolCall(
                    tool_name="get_city_gis_data",
                    arguments={"layer": CityGISLayerType.SUMMARY.value, "city_id": "AHMEDABAD"},
                ),
            )

        # 8. Unsupported / Out-of-Scope Query
        return LLMPlanResult(
            intent="unsupported_query",
            tool_call=None,
            direct_response=(
                "I am the CITYSHIELD GIS Disaster Response Copilot. I can assist with flood spatial impact, "
                "resource allocation, What-If simulation, response gap timelines, and municipal asset queries "
                "for Ahmedabad [DEMO DATA]. Please ask a disaster-response related question."
            ),
        )

    def explain_result(
        self,
        query: str,
        intent: str,
        tool_result: Optional[CopilotToolResult],
    ) -> str:
        """Format grounded, factual natural language narrative from tool results."""
        if tool_result is None:
            return (
                "No backend tool was executed for this query. CITYSHIELD Copilot is scoped to disaster response, "
                "flood spatial analysis, and resource optimization."
            )

        if not tool_result.success:
            return f"Operational calculation could not be completed: {tool_result.error_message}"

        res = tool_result.result or {}
        tool_name = tool_result.tool_name

        if tool_name == "assess_flood_gis_impact":
            summary = res.get("summary", {})
            return (
                f"Flood GIS Impact Assessment [DEMO DATA]: Inundation analysis across "
                f"{summary.get('total_zones_analyzed', 0)} wards identified "
                f"{summary.get('affected_zones_count', 0)} flooded zones with "
                f"{summary.get('total_flood_area_sq_km', 0.0)} sq km submerged and "
                f"{summary.get('total_buildings_affected', 0)} structures impacted."
            )

        elif tool_name == "optimize_resource_allocation":
            alloc = res.get("total_allocated", {})
            unmet = res.get("total_remaining_unmet", {})
            rate = round(res.get("overall_fulfillment_rate", 0.0) * 100, 1)
            status = res.get("status", "OPTIMAL")
            return (
                f"Resource Optimization Completed [DEMO DATA]: Solved multi-criteria dispatch with "
                f"{rate}% overall fulfillment (Status: {status}). Allocated: {alloc.get('ambulances', 0)} ambulances, "
                f"{alloc.get('rescue_boats', 0)} rescue boats, {alloc.get('food_packets', 0)} food packets. "
                f"Remaining unmet need: {unmet.get('ambulances', 0)} ambulances."
            )

        elif tool_name == "simulate_what_if_scenario":
            sim_sum = res.get("summary", {})
            delta_rate = round(sim_sum.get("fulfillment_rate_delta", 0.0) * 100, 1)
            return (
                f"What-If Simulation Result [DEMO DATA]: Evaluated counterfactual scenario shifts. "
                f"Overall demand fulfillment shifted by {delta_rate}%. "
                f"Before: {round(sim_sum.get('baseline_fulfillment_rate', 0.0) * 100, 1)}% -> "
                f"After: {round(sim_sum.get('simulated_fulfillment_rate', 0.0) * 100, 1)}% "
                f"(Status: {sim_sum.get('impact_assessment', 'EVALUATED')})."
            )

        elif tool_name == "project_future_gap_timeline":
            pts = res.get("timeline_points", [])
            last_pt = pts[-1] if pts else {}
            return (
                f"Future Response Gap Projection [DEMO DATA]: Projected across {len(pts)} horizons "
                f"(0h to {last_pt.get('time_hours', 0)}h). At {last_pt.get('time_hours', 0)}h, "
                f"total response gap widens to {last_pt.get('total_response_gap', {}).get('ambulances', 0)} ambulances "
                f"and {last_pt.get('total_response_gap', {}).get('rescue_boats', 0)} boats."
            )

        elif tool_name == "run_end_to_end_flood_response":
            narrative = res.get("narrative_summary", "")
            return f"End-to-End Flood Response [DEMO DATA]: {narrative}"

        elif tool_name == "get_city_gis_data":
            if "hospitals" in res:
                hosps = res["hospitals"]
                return f"City GIS Query [DEMO DATA]: Found {len(hosps)} emergency medical facilities registered in Ahmedabad."
            elif "shelters" in res:
                shelters = res["shelters"]
                return f"City GIS Query [DEMO DATA]: Found {len(shelters)} designated evacuation shelters registered."
            elif "roads" in res:
                roads = res["roads"]
                return f"City GIS Query [DEMO DATA]: Found {len(roads)} road corridors."
            elif "population_by_zone" in res:
                pop = res["total_population"]
                return f"City Demographic Query [DEMO DATA]: Total resident population indexed across wards is {pop:,}."
            elif "wards" in res:
                wards = res["wards"]
                return f"City GIS Query [DEMO DATA]: Retrieved {len(wards)} municipal administrative ward boundaries."
            else:
                return f"City GIS Query executed successfully [DEMO DATA]."

        return f"Tool '{tool_name}' executed successfully with {len(res)} fields returned [DEMO DATA]."

    def _build_forced_tool_call(self, tool_name: str, query: str) -> LLMPlanResult:
        """Helper for force_tool testing overrides."""
        if tool_name == "assess_flood_gis_impact":
            return LLMPlanResult(
                intent="forced_gis_impact",
                tool_call=CopilotToolCall(tool_name=tool_name, arguments={"city_id": "AHMEDABAD"}),
            )
        elif tool_name == "optimize_resource_allocation":
            return LLMPlanResult(
                intent="forced_optimization",
                tool_call=CopilotToolCall(tool_name=tool_name, arguments={"city_id": "AHMEDABAD"}),
            )
        elif tool_name == "simulate_what_if_scenario":
            return LLMPlanResult(
                intent="forced_what_if",
                tool_call=CopilotToolCall(
                    tool_name=tool_name,
                    arguments={"changes": {"available_resource_deltas": {"ambulances": 5}}, "city_id": "AHMEDABAD"},
                ),
            )
        elif tool_name == "project_future_gap_timeline":
            return LLMPlanResult(
                intent="forced_timeline",
                tool_call=CopilotToolCall(
                    tool_name=tool_name,
                    arguments={"time_horizons_hours": [0, 6, 12], "city_id": "AHMEDABAD"},
                ),
            )
        elif tool_name == "run_end_to_end_flood_response":
            return LLMPlanResult(
                intent="forced_end_to_end",
                tool_call=CopilotToolCall(tool_name=tool_name, arguments={"city_id": "AHMEDABAD"}),
            )
        elif tool_name == "get_city_gis_data":
            return LLMPlanResult(
                intent="forced_city_data",
                tool_call=CopilotToolCall(
                    tool_name=tool_name,
                    arguments={"layer": "summary", "city_id": "AHMEDABAD"},
                ),
            )
        else:
            return LLMPlanResult(
                intent="unknown_forced_tool",
                tool_call=CopilotToolCall(tool_name=tool_name, arguments={}),
            )


def get_copilot_provider(
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    **kwargs: Any,
) -> BaseLLMProvider:
    """Factory selecting OpenRouterLLMProvider when OPENROUTER_API_KEY is available, else MockLLMProvider.

    Ensures safe offline-by-default behavior: if no API key is provided or found in the
    environment, MockLLMProvider is returned with zero network side effects.
    """
    effective_key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY")
    if effective_key and effective_key.strip():
        from app.services.copilot.openrouter_provider import OpenRouterLLMProvider

        effective_model = model or os.getenv("COPILOT_MODEL")
        return OpenRouterLLMProvider(
            api_key=effective_key.strip(),
            model=effective_model,
            base_url=base_url,
            timeout_seconds=timeout_seconds or 15.0,
            **kwargs,
        )
    return MockLLMProvider()

