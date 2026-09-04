"""OpenRouter LLM Provider for CITYSHIELD Copilot (T-020 Step 4).

Connects to OpenAI-compatible OpenRouter endpoint for natural language query routing
and grounded tool planning. Follows strict security and grounding rules:
- API key read strictly from OPENROUTER_API_KEY env var
- Never logs API keys or leaks credentials
- Does not execute tools itself; only plans tool calls for ToolExecutor
- Never hallucinates GIS calculations, flood statistics, or optimization results
- Falls back safely on timeouts, HTTP errors, and malformed JSON
All synthetic disaster resources and geometries are labeled DEMO DATA per agent.md.
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
import httpx

from app.schemas.copilot import (
    CopilotMessage,
    CopilotToolCall,
    CopilotToolResult,
)
from app.services.copilot.provider import (
    BaseLLMProvider,
    LLMPlanResult,
    MockLLMProvider,
)
from app.services.copilot.tools import ToolDefinition, get_grounding_context

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "anthropic/claude-3.5-sonnet"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_DELAY_SECONDS = 0.2


class OpenRouterLLMProvider(BaseLLMProvider):
    """OpenRouter chat completion provider implementing tool-calling over registered backend services."""

    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        client: Optional[httpx.Client] = None,
    ):
        if not api_key or not api_key.strip():
            raise ValueError("OPENROUTER_API_KEY must be a non-empty string.")
        self.api_key = api_key.strip()
        self.model = model or os.getenv("COPILOT_MODEL", DEFAULT_MODEL)
        self.base_url = (base_url or os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self._custom_client = client

    @property
    def masked_api_key(self) -> str:
        """Return safe placeholder with NO secret material for logging and representation."""
        return "[REDACTED]"

    def __repr__(self) -> str:
        return f"<OpenRouterLLMProvider model='{self.model}' api_key='[REDACTED]'>"

    def _sanitize_string(self, text: str) -> str:
        """Strip raw API key from any error messages or trace strings."""
        if not self.api_key or not text:
            return text
        return text.replace(self.api_key, "[REDACTED]")

    def _build_headers(self) -> Dict[str, str]:
        """Construct HTTP headers without logging sensitive tokens."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://cityshield.rakshak.local",
            "X-Title": "CITYSHIELD GIS Disaster Response Copilot",
        }

    def _format_tools_payload(self, tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
        """Format ToolDefinitions into OpenAI function-calling specifications."""
        formatted_tools = []
        for tool in tools:
            formatted_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.argument_schema.model_json_schema(),
                },
            })
        return formatted_tools

    def _send_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send chat completion request to OpenRouter with bounded timeout and controlled retries."""
        url = f"{self.base_url}/chat/completions"
        headers = self._build_headers()

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                if self._custom_client is not None:
                    resp = self._custom_client.post(url, json=payload, headers=headers)
                else:
                    with httpx.Client(timeout=httpx.Timeout(self.timeout_seconds, connect=5.0)) as client:
                        resp = client.post(url, json=payload, headers=headers)

                # Retry on rate limits or transient upstream server errors
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(self.retry_delay_seconds * (attempt + 1))
                    continue

                resp.raise_for_status()
                return resp.json()

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_seconds * (attempt + 1))
                    continue
                raise
            except httpx.HTTPStatusError as exc:
                sanitized_msg = self._sanitize_string(str(exc))
                logger.error("OpenRouter HTTP error: %s", sanitized_msg)
                raise
            except Exception as exc:
                last_exc = exc
                sanitized_msg = self._sanitize_string(str(exc))
                logger.error("OpenRouter request failed: %s", sanitized_msg)
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_seconds * (attempt + 1))
                    continue
                raise

        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected termination of request retry loop")

    def plan_tool_call(
        self,
        query: str,
        history: List[CopilotMessage],
        tools: List[ToolDefinition],
        force_tool: Optional[str] = None,
    ) -> LLMPlanResult:
        """Route natural language query to backend tool call using OpenRouter function calling."""
        # 1. Format lean, grounded system message (tool schemas are passed via OpenAI tools parameter)
        system_content = (
            "You are the CITYSHIELD Disaster Response Copilot for Ahmedabad municipal operations [DEMO DATA].\n"
            "Analyze the disaster emergency query and invoke the single best tool from the available tools.\n\n"
            "CRITICAL CONSTRAINTS:\n"
            "- Never compute GIS coordinates, flood polygons, casualties, or optimization arithmetic yourself.\n"
            "- You MUST call the appropriate tool when user intent matches any of the registered tools.\n"
            "- If the query is conversational or out-of-scope, answer politely explaining your municipal scope.\n"
            "- Never invent imaginary tools or parameters not defined in the tool schemas.\n"
            "- All synthetic resources and incident operations are labeled DEMO DATA."
        )

        messages: List[Dict[str, str]] = [{"role": "system", "content": system_content}]
        # Preserve up to the last 6 non-empty turns to prevent context latency creep
        for msg in history[-6:]:
            if msg.content and msg.content.strip():
                messages.append({"role": msg.role.value, "content": msg.content.strip()})
        messages.append({"role": "user", "content": query.strip()})

        tools_payload = self._format_tools_payload(tools)

        # 2. Tool choice configuration
        tool_choice: Any = "auto"
        if force_tool:
            tool_choice = {"type": "function", "function": {"name": force_tool}}

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools_payload,
            "tool_choice": tool_choice,
            "temperature": 0.1,
        }

        # 3. Safe dispatch
        try:
            data = self._send_request(payload)
        except httpx.TimeoutException:
            logger.warning("OpenRouter timed out during plan_tool_call.")
            return LLMPlanResult(
                intent="provider_timeout",
                tool_call=None,
                direct_response=(
                    "The upstream LLM provider timed out while evaluating the disaster query. "
                    "No operations were modified. Please try again [DEMO DATA]."
                ),
            )
        except httpx.HTTPStatusError as exc:
            return LLMPlanResult(
                intent="provider_http_error",
                tool_call=None,
                direct_response=(
                    f"The upstream LLM provider returned an HTTP {exc.response.status_code} error. "
                    "No backend calculations were executed [DEMO DATA]."
                ),
            )
        except Exception as exc:
            sanitized_err = self._sanitize_string(str(exc))
            return LLMPlanResult(
                intent="provider_error",
                tool_call=None,
                direct_response=(
                    "An unexpected error occurred contacting the LLM provider. "
                    "No calculations were modified [DEMO DATA]."
                ),
            )

        # 4. Parse response defensively
        choices = data.get("choices", [])
        if not choices:
            return LLMPlanResult(
                intent="empty_provider_response",
                tool_call=None,
                direct_response="The LLM provider returned an empty response [DEMO DATA].",
            )

        message = choices[0].get("message", {})
        tool_calls = message.get("tool_calls")

        if tool_calls and isinstance(tool_calls, list) and len(tool_calls) > 0:
            first_call = tool_calls[0]
            func = first_call.get("function", {})
            tool_name = func.get("name", "")
            raw_args = func.get("arguments", "{}")

            # Parse JSON arguments defensively
            try:
                if isinstance(raw_args, str):
                    parsed_args = json.loads(raw_args)
                elif isinstance(raw_args, dict):
                    parsed_args = raw_args
                else:
                    parsed_args = {}

                # Unmarshal stringified nested JSON fields and normalize 'None'/'null' strings
                if isinstance(parsed_args, dict):
                    for k, v in list(parsed_args.items()):
                        if isinstance(v, str):
                            v_clean = v.strip()
                            if v_clean in ("None", "null"):
                                parsed_args[k] = None
                            elif v_clean.startswith(("{", "[")):
                                try:
                                    parsed_args[k] = json.loads(v)
                                except Exception:
                                    pass
            except (json.JSONDecodeError, TypeError) as json_err:
                logger.error("Failed to parse tool call arguments JSON from LLM: %s", str(json_err))
                return LLMPlanResult(
                    intent="malformed_tool_arguments",
                    tool_call=None,
                    direct_response=(
                        "The LLM provider emitted malformed tool arguments JSON. "
                        "Execution was safely halted to prevent ungrounded spatial calculations [DEMO DATA]."
                    ),
                )

            return LLMPlanResult(
                intent=f"tool_execution_{tool_name}",
                tool_call=CopilotToolCall(
                    tool_name=tool_name,
                    arguments=parsed_args if isinstance(parsed_args, dict) else {},
                ),
                direct_response=None,
            )

        # Direct conversational content
        content = message.get("content") or ""
        return LLMPlanResult(
            intent="conversational_response",
            tool_call=None,
            direct_response=content or (
                "I am the CITYSHIELD GIS Disaster Response Copilot. I can assist with flood spatial impact, "
                "resource allocation, What-If simulation, response gap timelines, and municipal asset queries [DEMO DATA]."
            ),
        )

    def explain_result(
        self,
        query: str,
        intent: str,
        tool_result: Optional[CopilotToolResult],
    ) -> str:
        """Synthesize grounded natural language explanation from backend tool results."""
        if tool_result is None:
            return (
                "No backend tool was executed for this query. CITYSHIELD Copilot is scoped to disaster response, "
                "flood spatial analysis, and resource optimization [DEMO DATA]."
            )

        if not tool_result.success:
            return f"Operational calculation could not be completed: {tool_result.error_message}"

        # Attempt live explanation grounded in verified result
        try:
            system_prompt = (
                "You are the CITYSHIELD Disaster Response Copilot. Explain the following backend tool result to the Incident Commander.\n"
                "CRITICAL RULES:\n"
                "1. Ground your explanation STRICTLY on the numbers and fields present in the tool result.\n"
                "2. Do NOT invent flood extents, casualties, costs, or unmentioned resources.\n"
                "3. Clearly mark synthetic outputs with [DEMO DATA].\n"
                "4. Never describe a building as 'destroyed'.\n"
                "5. Keep the explanation concise, professional, and operational."
            )
            user_prompt = (
                f"User Query: {query}\n"
                f"Executed Tool: {tool_result.tool_name}\n"
                f"Backend Tool Result JSON: {json.dumps(tool_result.result)}"
            )
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
            }
            resp_data = self._send_request(payload)
            choices = resp_data.get("choices", [])
            if choices:
                explanation = choices[0].get("message", {}).get("content", "").strip()
                if explanation:
                    return explanation
        except Exception as exc:
            logger.warning(
                "Live explanation generation failed (%s); falling back to deterministic grounded template.",
                self._sanitize_string(str(exc)),
            )

        # Fallback to deterministic template from MockLLMProvider
        return MockLLMProvider().explain_result(query, intent, tool_result)
