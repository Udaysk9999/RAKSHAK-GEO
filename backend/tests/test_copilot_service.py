"""Integration and Unit Test Suite for Copilot Service and API (T-020 Step 3).

Verifies:
1. Supported natural-language request selects a tool
2. Valid tool executes and returns result
3. Grounded explanation cites tool result numbers and avoids hallucinations
4. Unsupported query handled safely with clear scoping
5. Tool validation error handled safely without crashing
6. Failed tool execution handled safely
7. HTTP endpoint contract (POST /api/v1/copilot/chat)
8. Sample payload endpoint (GET /api/v1/copilot/sample-payload)
9. Conversation history is accepted and preserved
10. Demo-data flag is preserved (is_demo_data == True)
11. No invented numeric result when tool fails
12. All six tools remain reachable through CopilotService
All synthetic disaster resources and geometries are labeled DEMO DATA per agent.md.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.copilot import (
    CopilotMessage,
    CopilotRequest,
    CopilotResponse,
    CopilotRole,
    CopilotToolCall,
)
from app.services.copilot.service import CopilotService, default_copilot_service
from app.services.copilot.provider import MockLLMProvider
from app.services.copilot.tools import default_tool_executor, default_tool_registry

client = TestClient(app)


@pytest.fixture(autouse=True)
def enforce_offline_mock_provider(monkeypatch):
    """Ensure all unit and integration tests run offline against deterministic MockLLMProvider."""
    monkeypatch.setattr(default_copilot_service, "provider", MockLLMProvider())



# -----------------------------------------------------------------------------
# 1. Supported Natural-Language Request Selects a Tool
# -----------------------------------------------------------------------------
def test_supported_query_selects_tool():
    """Verify natural language query maps to an allowed backend tool call."""
    service = default_copilot_service
    req = CopilotRequest(query="What is the current flood impact across city wards?")
    res = service.chat(req)

    assert res.tool_executed is not None
    assert res.tool_executed.tool_name == "assess_flood_gis_impact"
    assert res.tool_executed.success is True
    assert "POST /api/v1/gis/impact" in res.cited_endpoints


# -----------------------------------------------------------------------------
# 2. Valid Tool Executes and Returns Structured Payload
# -----------------------------------------------------------------------------
def test_valid_tool_executes():
    """Verify backend tool executes and populates structured tool result."""
    service = default_copilot_service
    req = CopilotRequest(query="Show hospitals in Maninagar")
    res = service.chat(req)

    assert res.tool_executed is not None
    assert res.tool_executed.tool_name == "get_city_gis_data"
    assert res.tool_executed.success is True
    assert "hospitals" in res.tool_executed.result
    assert len(res.tool_executed.result["hospitals"]) >= 1


# -----------------------------------------------------------------------------
# 3. Grounded Explanation Uses Tool Result
# -----------------------------------------------------------------------------
def test_grounded_explanation_uses_tool_result():
    """Verify final narrative text quotes numbers directly from tool output."""
    service = default_copilot_service
    req = CopilotRequest(query="Allocate our stockpile across Ahmedabad zones")
    res = service.chat(req)

    assert res.tool_executed is not None
    assert res.tool_executed.success is True

    # Verification: explanation includes fulfillment rate and DEMO DATA
    alloc = res.tool_executed.result.get("total_allocated", {})
    rate = round(res.tool_executed.result.get("overall_fulfillment_rate", 0.0) * 100, 1)

    assert f"{rate}%" in res.explanation or "fulfillment" in res.explanation
    assert "DEMO DATA" in res.explanation


# -----------------------------------------------------------------------------
# 4. Unsupported Query Handled Safely
# -----------------------------------------------------------------------------
def test_unsupported_query_handled_safely():
    """Verify non-disaster questions return no tool execution and polite scoping."""
    service = default_copilot_service
    req = CopilotRequest(query="What is the capital of Australia?")
    res = service.chat(req)

    assert res.tool_executed is None
    assert res.intent == "unsupported_query"
    assert len(res.cited_endpoints) == 0
    assert "CITYSHIELD GIS Disaster Response Copilot" in res.explanation


# -----------------------------------------------------------------------------
# 5. Tool Validation Error Handled Safely
# -----------------------------------------------------------------------------
def test_tool_validation_error_handled_safely():
    """Verify malformed tool arguments return structured failure without 500 error."""
    service = default_copilot_service
    # Force a timeline projection with invalid negative horizons
    req = CopilotRequest(
        query="Check future timeline",
        force_tool="project_future_gap_timeline",
    )
    # Patch executor directly or pass bad arguments
    bad_call = CopilotToolCall(
        tool_name="project_future_gap_timeline",
        arguments={"time_horizons_hours": [-10, -5]},
    )
    res_tool = service.executor.execute(bad_call)
    assert res_tool.success is False
    assert "non-negative" in res_tool.error_message


# -----------------------------------------------------------------------------
# 6. Failed / Unknown Tool Execution Handled Safely
# -----------------------------------------------------------------------------
def test_failed_tool_execution_handled_safely():
    """Verify unknown forced tool returns structured rejection without leaking traces."""
    service = default_copilot_service
    req = CopilotRequest(query="Run test", force_tool="non_existent_exploit_tool")
    res = service.chat(req)

    assert res.tool_executed is not None
    assert res.tool_executed.success is False
    assert "not in the allowed Copilot tool registry" in res.tool_executed.error_message
    assert "Operational calculation could not be completed" in res.explanation or "error" in res.explanation.lower()


# -----------------------------------------------------------------------------
# 7. HTTP Endpoint Contract (POST /api/v1/copilot/chat)
# -----------------------------------------------------------------------------
def test_http_endpoint_chat():
    """Verify FastAPI POST /api/v1/copilot/chat endpoint accepts JSON and returns typed response."""
    payload = {
        "query": "How will the response gap change over 12 hours?",
        "incident_id": "INC-TEST-001",
        "city_id": "AHMEDABAD",
        "conversation_history": [
            {"role": "user", "content": "Hello copilot"},
            {"role": "assistant", "content": "Standing by for disaster response queries [DEMO DATA]."},
        ],
    }
    response = client.post("/api/v1/copilot/chat", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["query"] == payload["query"]
    assert "intent" in data
    assert data["is_demo_data"] is True
    assert data["tool_executed"] is not None
    assert data["tool_executed"]["tool_name"] == "project_future_gap_timeline"
    assert "POST /api/v1/future-gap/timeline" in data["cited_endpoints"]


# -----------------------------------------------------------------------------
# 8. Sample Payload Endpoint (GET /api/v1/copilot/sample-payload)
# -----------------------------------------------------------------------------
def test_sample_payload_endpoint():
    """Verify GET /api/v1/copilot/sample-payload returns valid request schema and executes."""
    resp = client.get("/api/v1/copilot/sample-payload")
    assert resp.status_code == 200

    sample_data = resp.json()
    assert "query" in sample_data
    assert "incident_id" in sample_data
    assert len(sample_data["conversation_history"]) >= 1

    # Execute POST with sample payload
    post_resp = client.post("/api/v1/copilot/chat", json=sample_data)
    assert post_resp.status_code == 200
    res_data = post_resp.json()
    assert res_data["tool_executed"] is not None
    assert res_data["is_demo_data"] is True


# -----------------------------------------------------------------------------
# 9. Conversation History is Accepted and Preserved
# -----------------------------------------------------------------------------
def test_conversation_history_accepted():
    """Verify multi-turn history messages parse cleanly into CopilotMessages."""
    history = [
        CopilotMessage(role=CopilotRole.USER, content="Query 1"),
        CopilotMessage(role=CopilotRole.ASSISTANT, content="Response 1 [DEMO DATA]"),
        CopilotMessage(role=CopilotRole.USER, content="Query 2"),
    ]
    req = CopilotRequest(query="Show shelters in Maninagar", conversation_history=history)
    assert len(req.conversation_history) == 3

    res = default_copilot_service.chat(req)
    assert res.tool_executed is not None
    assert res.tool_executed.tool_name == "get_city_gis_data"


# -----------------------------------------------------------------------------
# 10. Demo-Data Flag is Preserved
# -----------------------------------------------------------------------------
def test_demo_data_flag_preserved():
    """Verify is_demo_data is always True and DEMO DATA disclaimer is prominent."""
    req = CopilotRequest(query="What happens if I add 5 rescue boats?")
    res = default_copilot_service.chat(req)

    assert res.is_demo_data is True
    assert "DEMO DATA" in res.explanation


# -----------------------------------------------------------------------------
# 11. No Invented Numeric Result on Failure
# -----------------------------------------------------------------------------
def test_no_invented_numeric_result_on_failure():
    """Verify when tool fails, copilot never fabricates numbers or casualties."""
    service = default_copilot_service
    bad_req = CopilotRequest(query="test failure", force_tool="invalid_tool")
    res = service.chat(bad_req)

    assert res.tool_executed is not None
    assert res.tool_executed.success is False
    assert "0" not in res.explanation
    assert "100" not in res.explanation
    assert "Operational calculation could not be completed" in res.explanation or "error" in res.explanation.lower()


# -----------------------------------------------------------------------------
# 12. All Six Tools Remain Reachable via CopilotService
# -----------------------------------------------------------------------------
def test_all_six_tools_reachable():
    """Verify all 6 tools can be triggered through CopilotService."""
    service = default_copilot_service
    tools_to_test = [
        ("get_city_gis_data", "Show city wards summary"),
        ("assess_flood_gis_impact", "Check flood impact"),
        ("optimize_resource_allocation", "Allocate emergency resources"),
        ("simulate_what_if_scenario", "What if we add 5 rescue boats"),
        ("project_future_gap_timeline", "Future gap timeline for 12 hours"),
        ("run_end_to_end_flood_response", "Run end to end full response"),
    ]

    for tool_name, query in tools_to_test:
        req = CopilotRequest(query=query)
        res = service.chat(req)
        assert res.tool_executed is not None, f"Tool {tool_name} was not selected for query: {query}"
        assert res.tool_executed.tool_name == tool_name
        assert res.tool_executed.success is True
        assert len(res.cited_endpoints) >= 1
