"""Live OpenRouter Copilot Integration Test Suite (T-020 Step 5).

Exercises live tool calling over OpenRouter when OPENROUTER_API_KEY is configured.
If OPENROUTER_API_KEY is absent, cleanly reports LIVE TEST SKIPPED without failing.
All synthetic resources and geometries are labeled DEMO DATA per agent.md.
NEVER PRINTS OR LEAKS THE API KEY.
"""
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional
import httpx
import pytest

from app.core.config import settings
from app.schemas.copilot import (
    CopilotMessage,
    CopilotRequest,
    CopilotResponse,
    CopilotRole,
    CopilotToolCall,
    CopilotToolResult,
)
from app.services.copilot.openrouter_provider import OpenRouterLLMProvider
from app.services.copilot.provider import (
    BaseLLMProvider,
    MockLLMProvider,
    get_copilot_provider,
)
from app.services.copilot.service import CopilotService
from app.services.copilot.tools import default_tool_executor, default_tool_registry

API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_NAME = os.getenv("COPILOT_MODEL", "inception/mercury-2.5-preview")


def is_live_available() -> bool:
    """Check whether a non-empty OpenRouter API key is configured."""
    return bool(API_KEY and API_KEY.strip())


@pytest.fixture(scope="module")
def live_provider() -> Optional[OpenRouterLLMProvider]:
    """Provide initialized live OpenRouter provider if key is available."""
    if not is_live_available():
        pytest.skip("LIVE TEST SKIPPED: OPENROUTER_API_KEY is not configured.", allow_module_level=True)
    return OpenRouterLLMProvider(api_key=API_KEY.strip(), model=MODEL_NAME)


@pytest.fixture(scope="module")
def live_service(live_provider) -> CopilotService:
    """Provide CopilotService configured with the live OpenRouter provider."""
    return CopilotService(provider=live_provider)


# =============================================================================
# LIVE TESTS: Real Tool-Calling over OpenRouter
# =============================================================================

class TestLiveOpenRouterIntegration:
    """Verify live tool calling, deterministic execution, and grounded explanation."""

    def test_live_hospital_query(self, live_service):
        """Query 1: 'Show hospitals in Ahmedabad.' -> get_city_gis_data."""
        query = "Show hospitals in Ahmedabad."
        t0 = time.perf_counter()
        req = CopilotRequest(query=query)
        res = live_service.chat(req)
        total_latency = time.perf_counter() - t0

        assert res.tool_executed is not None, "Live LLM failed to return a tool call."
        assert res.tool_executed.tool_name == "get_city_gis_data"
        assert res.tool_executed.success is True
        assert res.tool_executed.result is not None
        assert "hospitals" in res.tool_executed.result
        assert "DEMO DATA" in res.explanation
        assert total_latency < 30.0

    def test_live_flood_impact_query(self, live_service):
        """Query 2: 'What is the current flood impact?' -> assess_flood_gis_impact."""
        query = "What is the current flood impact?"
        t0 = time.perf_counter()
        req = CopilotRequest(query=query)
        res = live_service.chat(req)
        total_latency = time.perf_counter() - t0

        assert res.tool_executed is not None, "Live LLM failed to return a tool call."
        assert res.tool_executed.tool_name == "assess_flood_gis_impact"
        assert res.tool_executed.success is True
        assert res.tool_executed.result is not None
        assert "summary" in res.tool_executed.result
        assert "DEMO DATA" in res.explanation
        assert total_latency < 30.0

    def test_live_what_if_query(self, live_service):
        """Query 3: 'What happens if I add 5 rescue teams?' -> simulate_what_if_scenario."""
        query = "What happens if I add 5 rescue teams?"
        t0 = time.perf_counter()
        req = CopilotRequest(query=query)
        res = live_service.chat(req)
        total_latency = time.perf_counter() - t0

        assert res.tool_executed is not None, "Live LLM failed to return a tool call."
        assert res.tool_executed.tool_name == "simulate_what_if_scenario"
        assert res.tool_executed.success is True
        assert res.tool_executed.result is not None
        assert "DEMO DATA" in res.explanation
        assert total_latency < 30.0

    def test_live_future_gap_query(self, live_service):
        """Query 4: 'How will the response gap change over the next 12 hours?' -> project_future_gap_timeline."""
        query = "How will the response gap change over the next 12 hours?"
        t0 = time.perf_counter()
        req = CopilotRequest(query=query)
        res = live_service.chat(req)
        total_latency = time.perf_counter() - t0

        assert res.tool_executed is not None, "Live LLM failed to return a tool call."
        assert res.tool_executed.tool_name == "project_future_gap_timeline"
        assert res.tool_executed.success is True
        assert res.tool_executed.result is not None
        assert "timeline_points" in res.tool_executed.result
        assert "DEMO DATA" in res.explanation
        assert total_latency < 30.0


# =============================================================================
# ERROR CASES
# =============================================================================

class TestLiveErrorCases:
    """Verify robust error recovery under edge conditions."""

    def test_timeout_handled_safely(self):
        """Bounded timeout must return a controlled timeout intent without crashing."""
        if not is_live_available():
            pytest.skip("LIVE TEST SKIPPED: OPENROUTER_API_KEY is not configured.")
        # Provider with practically zero timeout to force timeout handling
        fast_timeout_provider = OpenRouterLLMProvider(
            api_key=API_KEY.strip(),
            model=MODEL_NAME,
            timeout_seconds=0.00001,
            max_retries=0,
        )
        plan = fast_timeout_provider.plan_tool_call("Check hospitals", [], default_tool_registry.list_tools())
        assert plan.tool_call is None
        assert plan.intent == "provider_timeout"
        assert "timed out" in plan.direct_response.lower()

    def test_http_failure_handled_safely(self):
        """Upstream HTTP failure must return a controlled response without leaking stack traces."""
        fake_key = "test-sk-valid-key-12345"
        mock_client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(503, text="Service Unavailable")))
        provider = OpenRouterLLMProvider(api_key=fake_key, model=MODEL_NAME, client=mock_client, max_retries=0)
        plan = provider.plan_tool_call("Check flood", [], default_tool_registry.list_tools())
        assert plan.tool_call is None
        assert plan.intent == "provider_http_error"
        assert "503" in plan.direct_response

    def test_malformed_tool_call_handled_safely(self):
        """Malformed JSON arguments from provider must halt tool execution safely."""
        fake_key = "test-sk-valid-key-12345"
        mock_response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_bad",
                                "type": "function",
                                "function": {
                                    "name": "assess_flood_gis_impact",
                                    "arguments": "{INVALID_UNQUOTED_JSON",
                                },
                            }
                        ],
                    }
                }
            ]
        }
        mock_client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=mock_response)))
        provider = OpenRouterLLMProvider(api_key=fake_key, model=MODEL_NAME, client=mock_client)
        plan = provider.plan_tool_call("Check flood", [], default_tool_registry.list_tools())
        assert plan.tool_call is None
        assert plan.intent == "malformed_tool_arguments"
        assert "malformed" in plan.direct_response.lower()

    def test_unsupported_query_handled_safely(self, live_service):
        """Out of scope query must return scoped conversational refusal without executing backend tools."""
        req = CopilotRequest(query="Write a haiku about the sunset over the Arabian Sea.")
        res = live_service.chat(req)
        assert res.tool_executed is None
        assert len(res.explanation) > 0

    def test_missing_api_key_falls_back_to_mock(self, monkeypatch):
        """Missing API key must select MockLLMProvider and never crash application."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        provider = get_copilot_provider()
        assert isinstance(provider, MockLLMProvider)


# =============================================================================
# SECURITY AUDIT
# =============================================================================

class TestLiveSecurity:
    """Verify secrets are never leaked in responses, errors, or logs."""

    def test_api_key_never_in_response(self, live_service):
        """API key must never appear anywhere in the serialized CopilotResponse."""
        req = CopilotRequest(query="Show hospitals in Ahmedabad.")
        res = live_service.chat(req)
        dumped = res.model_dump_json()
        assert API_KEY not in dumped
        assert API_KEY not in res.explanation

    def test_api_key_masked_in_repr(self, live_provider):
        """API key must be masked in string representations and logs."""
        repr_str = repr(live_provider)
        assert API_KEY not in repr_str
        assert "..." in repr_str or "[REDACTED]" in repr_str
