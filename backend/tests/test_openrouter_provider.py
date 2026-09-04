"""Tests for OpenRouter LLM Provider Abstraction (T-020 Step 4).

Verifies OpenAI-compatible function calling, schema grounding, safe error handling,
secret protection, and deterministic offline fallback to MockLLMProvider.
ZERO external HTTP calls are performed in these tests.
All synthetic resources and geometries are labeled DEMO DATA per agent.md.
"""
import json
from unittest.mock import MagicMock
import httpx
import pytest

from app.schemas.copilot import (
    CopilotMessage,
    CopilotRole,
    CopilotToolCall,
    CopilotToolResult,
)
from app.services.copilot.openrouter_provider import OpenRouterLLMProvider
from app.services.copilot.provider import (
    BaseLLMProvider,
    LLMPlanResult,
    MockLLMProvider,
    get_copilot_provider,
)
from app.services.copilot.tools import default_tool_registry


def test_missing_api_key_selects_mock_provider(monkeypatch):
    """When OPENROUTER_API_KEY is not set, factory must return MockLLMProvider."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = get_copilot_provider()
    assert isinstance(provider, MockLLMProvider)


def test_empty_api_key_selects_mock_provider(monkeypatch):
    """When OPENROUTER_API_KEY is whitespace or empty, factory returns MockLLMProvider."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "   ")
    provider = get_copilot_provider()
    assert isinstance(provider, MockLLMProvider)


def test_configured_api_key_selects_openrouter_provider(monkeypatch):
    """When OPENROUTER_API_KEY is set, factory returns OpenRouterLLMProvider with model config."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake-test-key-12345678")
    monkeypatch.setenv("COPILOT_MODEL", "google/gemini-2.5-flash")

    provider = get_copilot_provider()
    assert isinstance(provider, OpenRouterLLMProvider)
    assert provider.model == "google/gemini-2.5-flash"


def test_api_key_is_never_exposed_in_logs_or_errors():
    """Confidential API keys must never appear in repr, string representations, or sanitized logs."""
    fake_secret = "super-secret-openrouter-key-999888777"
    provider = OpenRouterLLMProvider(api_key=fake_secret)

    repr_str = repr(provider)
    assert fake_secret not in repr_str
    assert "..." in repr_str or "[REDACTED]" in repr_str

    sanitized = provider._sanitize_string(f"Failed Authorization: Bearer {fake_secret} at endpoint")
    assert fake_secret not in sanitized
    assert "[REDACTED]" in sanitized


def test_request_payload_contains_grounded_tool_definitions():
    """OpenRouter payload must format all 6 registered backend tools into OpenAI function calling schema."""
    fake_key = "test-sk-valid-key-12345"
    mock_client = MagicMock(spec=httpx.Client)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Standing by for disaster command queries [DEMO DATA].",
                    "tool_calls": None,
                }
            }
        ]
    }
    mock_client.post.return_value = mock_resp

    provider = OpenRouterLLMProvider(api_key=fake_key, client=mock_client)
    tools = default_tool_registry.list_tools()
    history = [
        CopilotMessage(role=CopilotRole.USER, content="Incident logged [DEMO DATA]"),
    ]

    res = provider.plan_tool_call("Overview of operations", history, tools)

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args[1]
    payload = call_kwargs["json"]
    headers = call_kwargs["headers"]

    # Check headers
    assert headers["Authorization"] == f"Bearer {fake_key}"
    assert "HTTP-Referer" in headers

    # Check 6 tools present in OpenAI function specification
    assert "tools" in payload
    assert len(payload["tools"]) == 6
    tool_names = [t["function"]["name"] for t in payload["tools"]]
    expected_tools = [
        "get_city_gis_data",
        "assess_flood_gis_impact",
        "optimize_resource_allocation",
        "simulate_what_if_scenario",
        "project_future_gap_timeline",
        "run_end_to_end_flood_response",
    ]
    for expected in expected_tools:
        assert expected in tool_names

    # Check parameters have JSON schema
    for t in payload["tools"]:
        assert t["type"] == "function"
        assert "parameters" in t["function"]
        assert t["function"]["parameters"]["type"] == "object"

    # Check conversational response returned
    assert res.tool_call is None
    assert "Standing by" in res.direct_response


def test_valid_tool_call_response_parses_correctly():
    """Valid function calling response from OpenRouter must parse into CopilotToolCall without modification."""
    fake_key = "test-sk-valid-key-12345"
    mock_client = MagicMock(spec=httpx.Client)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {
                                "name": "assess_flood_gis_impact",
                                "arguments": json.dumps({"city_id": "AHMEDABAD", "flood_depth_threshold_m": 0.25}),
                            },
                        }
                    ],
                }
            }
        ]
    }
    mock_client.post.return_value = mock_resp

    provider = OpenRouterLLMProvider(api_key=fake_key, client=mock_client)
    tools = default_tool_registry.list_tools()

    res = provider.plan_tool_call("Assess flood impact across Ahmedabad", [], tools)

    assert res.tool_call is not None
    assert res.tool_call.tool_name == "assess_flood_gis_impact"
    assert res.tool_call.arguments == {"city_id": "AHMEDABAD", "flood_depth_threshold_m": 0.25}


def test_malformed_tool_call_response_fails_safely():
    """Malformed JSON arguments from the LLM must fail safely and never execute invalid tools or invent parameters."""
    fake_key = "test-sk-valid-key-12345"
    mock_client = MagicMock(spec=httpx.Client)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_broken",
                            "type": "function",
                            "function": {
                                "name": "optimize_resource_allocation",
                                "arguments": "{malformed_json_without_quotes: 123",
                            },
                        }
                    ],
                }
            }
        ]
    }
    mock_client.post.return_value = mock_resp

    provider = OpenRouterLLMProvider(api_key=fake_key, client=mock_client)
    tools = default_tool_registry.list_tools()

    res = provider.plan_tool_call("Optimize resources", [], tools)

    assert res.tool_call is None
    assert res.intent == "malformed_tool_arguments"
    assert "malformed" in res.direct_response.lower()


def test_provider_timeout_is_handled_safely():
    """Upstream provider timeout must be caught cleanly without crashing the API or service."""
    fake_key = "test-sk-valid-key-12345"
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.side_effect = httpx.TimeoutException("Read timed out after 15.0s")

    provider = OpenRouterLLMProvider(api_key=fake_key, client=mock_client, max_retries=0)
    tools = default_tool_registry.list_tools()

    res = provider.plan_tool_call("Simulate what-if scenario", [], tools)

    assert res.tool_call is None
    assert res.intent == "provider_timeout"
    assert "timed out" in res.direct_response.lower()


def test_provider_http_failure_is_handled_safely():
    """Upstream HTTP 5xx or 4xx errors must produce controlled diagnostic message without leaking secrets."""
    fake_key = "test-sk-valid-key-12345"
    mock_client = MagicMock(spec=httpx.Client)
    mock_req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    mock_resp = httpx.Response(502, request=mock_req)
    mock_client.post.side_effect = httpx.HTTPStatusError("502 Bad Gateway", request=mock_req, response=mock_resp)

    provider = OpenRouterLLMProvider(api_key=fake_key, client=mock_client, max_retries=0)
    tools = default_tool_registry.list_tools()

    res = provider.plan_tool_call("Check hospital capacity", [], tools)

    assert res.tool_call is None
    assert res.intent == "provider_http_error"
    assert "502" in res.direct_response


def test_existing_mock_llm_provider_behavior_remains_unchanged():
    """MockLLMProvider must continue to operate 100% deterministically and offline without API keys."""
    mock_provider = MockLLMProvider()
    tools = default_tool_registry.list_tools()

    # Supported tool query
    plan = mock_provider.plan_tool_call("What is the flood impact across Ahmedabad?", [], tools)
    assert plan.tool_call is not None
    assert plan.tool_call.tool_name == "assess_flood_gis_impact"

    # Out-of-scope query
    plan_oos = mock_provider.plan_tool_call("Tell me a poem about the sea", [], tools)
    assert plan_oos.tool_call is None
    assert "CITYSHIELD" in plan_oos.direct_response


def test_openrouter_explain_result_with_live_response_and_fallback():
    """Live explanation uses LLM response if available, and cleanly falls back to deterministic template on error."""
    fake_key = "test-sk-valid-key-12345"
    mock_client = MagicMock(spec=httpx.Client)

    # 1. Successful live explanation
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Live grounded summary: 3 zones submerged in Ahmedabad [DEMO DATA].",
                }
            }
        ]
    }
    mock_client.post.return_value = mock_resp
    provider = OpenRouterLLMProvider(api_key=fake_key, client=mock_client)

    tool_result = CopilotToolResult(
        tool_name="assess_flood_gis_impact",
        success=True,
        result={"summary": {"total_zones_analyzed": 5, "affected_zones_count": 3, "total_flood_area_sq_km": 4.5, "total_buildings_affected": 250}},
    )
    explanation = provider.explain_result("Assess flood", "tool_call", tool_result)
    assert "Live grounded summary" in explanation

    # 2. Upstream network failure -> fallback to MockLLMProvider deterministic template
    mock_client.post.side_effect = httpx.ConnectError("Network unreachable")
    fallback_exp = provider.explain_result("Assess flood", "tool_call", tool_result)
    assert "[DEMO DATA]" in fallback_exp
    assert "Inundation analysis" in fallback_exp
    assert "4.5 sq km submerged" in fallback_exp
