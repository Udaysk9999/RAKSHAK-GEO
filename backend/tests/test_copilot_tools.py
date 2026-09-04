"""Test suite for T-020 Copilot Tool Registry, Validators, and Mock Provider.

Verifies:
1. All six tools are registered
2. Unknown tool is rejected
3. Valid arguments are accepted and processed
4. Invalid arguments are rejected with structured error
5. Tool executor invokes existing backend services
6. Mock provider maps natural-language queries to correct tools
7. Unsupported queries are handled safely without tool calls
8. Tool results are structured and typed
9. Arbitrary function execution is impossible
10. Grounding documentation generation
All synthetic disaster resources and geometries are labeled DEMO DATA per agent.md.
"""
import pytest

from app.schemas.copilot import (
    CityGISLayerType,
    CopilotToolCall,
    CopilotToolResult,
    GetCityGISDataArgs,
    ProjectFutureGapTimelineArgs,
)
from app.schemas.optimization import OptimizationGoal
from app.services.copilot.provider import MockLLMProvider
from app.services.copilot.tools import (
    ToolDefinition,
    ToolExecutor,
    ToolRegistry,
    default_tool_executor,
    default_tool_registry,
    get_grounding_context,
)


# -----------------------------------------------------------------------------
# 1. All Six Tools Registered
# -----------------------------------------------------------------------------
def test_all_six_tools_registered():
    """Verify exact 6 tools exist in the fixed registry."""
    tools = default_tool_registry.list_tools()
    assert len(tools) == 6

    expected_names = {
        "get_city_gis_data",
        "assess_flood_gis_impact",
        "optimize_resource_allocation",
        "simulate_what_if_scenario",
        "project_future_gap_timeline",
        "run_end_to_end_flood_response",
    }
    actual_names = {t.name for t in tools}
    assert actual_names == expected_names


# -----------------------------------------------------------------------------
# 2. Unknown Tool Rejected
# -----------------------------------------------------------------------------
def test_unknown_tool_rejected():
    """Verify unknown tool name raises KeyError in registry and fails gracefully in executor."""
    registry = default_tool_registry
    assert not registry.contains("arbitrary_hacker_function")

    with pytest.raises(KeyError):
        registry.get("arbitrary_hacker_function")

    # In executor, returns structured failure without crashing
    bad_call = CopilotToolCall(tool_name="arbitrary_hacker_function", arguments={})
    res = default_tool_executor.execute(bad_call)

    assert res.success is False
    assert res.result is None
    assert "not in the allowed Copilot tool registry" in res.error_message


# -----------------------------------------------------------------------------
# 3. Valid Arguments Accepted
# -----------------------------------------------------------------------------
def test_valid_arguments_accepted():
    """Verify valid arguments parse correctly into typed Pydantic models."""
    args = GetCityGISDataArgs(layer=CityGISLayerType.WARDS, city_id="AHMEDABAD")
    assert args.layer == CityGISLayerType.WARDS
    assert args.city_id == "AHMEDABAD"

    time_args = ProjectFutureGapTimelineArgs(time_horizons_hours=[0, 6, 12, 18], growth_rate_pct_per_hour=15.0)
    assert time_args.time_horizons_hours == [0, 6, 12, 18]
    assert time_args.growth_rate_pct_per_hour == 15.0


# -----------------------------------------------------------------------------
# 4. Invalid Arguments Rejected
# -----------------------------------------------------------------------------
def test_invalid_arguments_rejected():
    """Verify malformed arguments return structured failure from executor."""
    # layer missing from get_city_gis_data
    bad_call = CopilotToolCall(tool_name="get_city_gis_data", arguments={"invalid_key": "xyz"})
    res = default_tool_executor.execute(bad_call)

    assert res.success is False
    assert "Validation failed" in res.error_message or "missing" in res.error_message

    # negative time horizon in project_future_gap_timeline
    bad_time_call = CopilotToolCall(
        tool_name="project_future_gap_timeline",
        arguments={"time_horizons_hours": [-5, 10]},
    )
    res2 = default_tool_executor.execute(bad_time_call)
    assert res2.success is False
    assert "non-negative" in res2.error_message


# -----------------------------------------------------------------------------
# 5. Tool Executor Calls Existing Backend Services
# -----------------------------------------------------------------------------
def test_tool_executor_calls_existing_services():
    """Verify tool calls invoke CityGISRepository, GISFloodImpactService, Optimization, etc."""
    # Tool 1: get_city_gis_data
    call1 = CopilotToolCall(tool_name="get_city_gis_data", arguments={"layer": "hospitals", "city_id": "AHMEDABAD"})
    res1 = default_tool_executor.execute(call1)
    assert res1.success is True
    assert "hospitals" in res1.result
    assert res1.result["count"] >= 2

    # Tool 2: assess_flood_gis_impact
    call2 = CopilotToolCall(tool_name="assess_flood_gis_impact", arguments={"city_id": "AHMEDABAD"})
    res2 = default_tool_executor.execute(call2)
    assert res2.success is True
    assert "summary" in res2.result
    assert res2.result["summary"]["total_zones_analyzed"] >= 2

    # Tool 3: optimize_resource_allocation
    call3 = CopilotToolCall(
        tool_name="optimize_resource_allocation",
        arguments={"objective": "prioritize_critical_zones", "reserve_margin_pct": 5.0},
    )
    res3 = default_tool_executor.execute(call3)
    assert res3.success is True
    assert "allocations" in res3.result
    assert res3.result["overall_fulfillment_rate"] >= 0.0

    # Tool 4: simulate_what_if_scenario
    call4 = CopilotToolCall(
        tool_name="simulate_what_if_scenario",
        arguments={"changes": {"available_resource_deltas": {"rescue_boats": 5}}},
    )
    res4 = default_tool_executor.execute(call4)
    assert res4.success is True
    assert "summary" in res4.result

    # Tool 5: project_future_gap_timeline
    call5 = CopilotToolCall(
        tool_name="project_future_gap_timeline",
        arguments={"time_horizons_hours": [0, 6, 12]},
    )
    res5 = default_tool_executor.execute(call5)
    assert res5.success is True
    assert "timeline_points" in res5.result
    assert len(res5.result["timeline_points"]) == 3

    # Tool 6: run_end_to_end_flood_response
    call6 = CopilotToolCall(
        tool_name="run_end_to_end_flood_response",
        arguments={"objective": "prioritize_critical_zones"},
    )
    res6 = default_tool_executor.execute(call6)
    assert res6.success is True
    assert "zones" in res6.result
    assert "narrative_summary" in res6.result


# -----------------------------------------------------------------------------
# 6. Mock Provider Natural Language Tool Selection
# -----------------------------------------------------------------------------
def test_mock_provider_natural_language_mapping():
    """Verify MockLLMProvider maps queries to correct backend tools."""
    provider = MockLLMProvider()
    tools = default_tool_registry.list_tools()

    # Query 1: Flood impact
    plan1 = provider.plan_tool_call("What is the current flood impact?", [], tools)
    assert plan1.tool_call is not None
    assert plan1.tool_call.tool_name == "assess_flood_gis_impact"

    # Query 2: What-If
    plan2 = provider.plan_tool_call("What happens if I add 5 rescue boats to the depot?", [], tools)
    assert plan2.tool_call is not None
    assert plan2.tool_call.tool_name == "simulate_what_if_scenario"

    # Query 3: Future gap timeline
    plan3 = provider.plan_tool_call("How will the gap change over 12 hours?", [], tools)
    assert plan3.tool_call is not None
    assert plan3.tool_call.tool_name == "project_future_gap_timeline"

    # Query 4: Municipal hospitals
    plan4 = provider.plan_tool_call("Show hospitals in Maninagar", [], tools)
    assert plan4.tool_call is not None
    assert plan4.tool_call.tool_name == "get_city_gis_data"
    assert plan4.tool_call.arguments["layer"] == "hospitals"

    # Query 5: Optimization
    plan5 = provider.plan_tool_call("Allocate our stockpile across Ahmedabad zones", [], tools)
    assert plan5.tool_call is not None
    assert plan5.tool_call.tool_name == "optimize_resource_allocation"

    # Query 6: End-to-end full response
    plan6 = provider.plan_tool_call("Run end to end full response workflow", [], tools)
    assert plan6.tool_call is not None
    assert plan6.tool_call.tool_name == "run_end_to_end_flood_response"


# -----------------------------------------------------------------------------
# 7. Unsupported Query Handled Safely
# -----------------------------------------------------------------------------
def test_mock_provider_unsupported_query():
    """Verify out-of-scope queries return no tool call and polite boundary explanation."""
    provider = MockLLMProvider()
    tools = default_tool_registry.list_tools()

    plan = provider.plan_tool_call("Write a poem about the ocean", [], tools)
    assert plan.tool_call is None
    assert plan.intent == "unsupported_query"
    assert "CITYSHIELD GIS Disaster Response Copilot" in plan.direct_response


# -----------------------------------------------------------------------------
# 8. Tool Output is Structured & Explanation Grounded
# -----------------------------------------------------------------------------
def test_structured_output_and_explanation():
    """Verify tool result formats grounded narrative with DEMO DATA disclaimer."""
    provider = MockLLMProvider()

    # Execute assess_flood_gis_impact
    call = CopilotToolCall(tool_name="assess_flood_gis_impact", arguments={"city_id": "AHMEDABAD"})
    result = default_tool_executor.execute(call)
    assert isinstance(result, CopilotToolResult)
    assert result.success is True

    explanation = provider.explain_result("Check flood impact", "flood_gis_impact", result)
    assert "DEMO DATA" in explanation
    assert "Flood GIS Impact Assessment" in explanation


# -----------------------------------------------------------------------------
# 9. No Arbitrary Function Execution Possible
# -----------------------------------------------------------------------------
def test_no_arbitrary_function_execution():
    """Verify security boundary preventing arbitrary code execution."""
    malicious_inputs = [
        "os.system('rm -rf /')",
        "__import__('os').listdir()",
        "eval('1 + 1')",
        "SELECT * FROM users",
        "DROP TABLE cities",
    ]

    for attack in malicious_inputs:
        call = CopilotToolCall(tool_name=attack, arguments={})
        res = default_tool_executor.execute(call)
        assert res.success is False
        assert "not in the allowed Copilot tool registry" in res.error_message


# -----------------------------------------------------------------------------
# 10. Grounding Documentation Generation
# -----------------------------------------------------------------------------
def test_grounding_documentation():
    """Verify compact grounding documentation generation."""
    ctx = get_grounding_context()
    assert "# CITYSHIELD GIS COPILOT GROUNDING" in ctx
    assert "DEMO DATA" in ctx
    for tool_name in [
        "get_city_gis_data",
        "assess_flood_gis_impact",
        "optimize_resource_allocation",
        "simulate_what_if_scenario",
        "project_future_gap_timeline",
        "run_end_to_end_flood_response",
    ]:
        assert f"`{tool_name}`" in ctx
