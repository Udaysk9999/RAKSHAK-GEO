"""Copilot Orchestration Service (T-020 Step 3).

Coordinates the end-to-end grounded conversational workflow:
User Query -> LLM Provider Plan -> Tool Executor -> Backend Execution -> Grounded Explanation.
The backend services are the sole authoritative source of truth; the LLM never invents numbers.
All synthetic resources and geometries are labeled DEMO DATA per agent.md.
"""
import logging
from typing import List, Optional

from app.schemas.copilot import (
    CopilotRequest,
    CopilotResponse,
    CopilotToolResult,
)
from app.services.copilot.provider import (
    BaseLLMProvider,
    MockLLMProvider,
    get_copilot_provider,
)
from app.services.copilot.tools import (
    ToolExecutor,
    ToolRegistry,
    default_tool_executor,
    default_tool_registry,
    get_grounding_context,
)

logger = logging.getLogger(__name__)


class CopilotService:
    """Orchestrates natural language intent planning, backend tool execution, and grounded explanation."""

    def __init__(
        self,
        provider: Optional[BaseLLMProvider] = None,
        executor: Optional[ToolExecutor] = None,
        registry: Optional[ToolRegistry] = None,
        fast_explanation: bool = True,
    ):
        self.registry = registry or default_tool_registry
        self.executor = executor or default_tool_executor
        self.provider = provider or get_copilot_provider()
        self.fast_explanation = fast_explanation

    def chat(self, request: CopilotRequest) -> CopilotResponse:
        """Process user query through grounded LLM tool planning and verified backend services."""
        try:
            # 1. Obtain tool plan or direct response from configured provider
            plan = self.provider.plan_tool_call(
                query=request.query,
                history=request.conversation_history,
                tools=self.registry.list_tools(),
                force_tool=request.force_tool,
            )

            # 2. Case A: No backend tool needed (conversational / out-of-scope / unsupported)
            if plan.tool_call is None:
                explanation = plan.direct_response or (
                    "I am the CITYSHIELD GIS Disaster Response Copilot. I can assist with flood spatial impact, "
                    "resource allocation, What-If simulation, response gap timelines, and municipal asset queries "
                    "for Ahmedabad [DEMO DATA]. Please ask a disaster-response related question."
                )
                return CopilotResponse(
                    query=request.query,
                    intent=plan.intent,
                    tool_executed=None,
                    explanation=explanation,
                    cited_endpoints=[],
                    is_demo_data=True,
                )

            # 3. Case B: Provider selected a backend tool to execute
            tool_name = plan.tool_call.tool_name
            cited_endpoints: List[str] = []

            if self.registry.contains(tool_name):
                tool_def = self.registry.get(tool_name)
                cited_endpoints.append(tool_def.cited_endpoint)

            # 4. Pass tool call through strict ToolExecutor
            tool_result: CopilotToolResult = self.executor.execute(plan.tool_call)

            # 5. Synthesize grounded explanation from actual backend result
            # Optimization Target 2: Avoid second LLM request for simple tool results when a
            # deterministic grounded explanation can safely be generated locally from the verified tool result.
            if self.fast_explanation and not getattr(request, "live_synthesis", False):
                explanation = MockLLMProvider().explain_result(
                    query=request.query,
                    intent=plan.intent,
                    tool_result=tool_result,
                )
            else:
                explanation = self.provider.explain_result(
                    query=request.query,
                    intent=plan.intent,
                    tool_result=tool_result,
                )

            return CopilotResponse(
                query=request.query,
                intent=plan.intent,
                tool_executed=tool_result,
                explanation=explanation,
                cited_endpoints=cited_endpoints,
                is_demo_data=True,
            )

        except Exception as exc:
            logger.error(f"Unhandled error in CopilotService.chat: {exc}", exc_info=True)
            return CopilotResponse(
                query=request.query,
                intent="error_handling",
                tool_executed=CopilotToolResult(
                    tool_name=request.force_tool or "unknown",
                    success=False,
                    error_message=f"Operational processing error: {str(exc)}",
                ),
                explanation=(
                    "An unexpected error occurred while executing the operational disaster response tool. "
                    "No calculations were modified. Please verify query parameters and try again [DEMO DATA]."
                ),
                cited_endpoints=[],
                is_demo_data=True,
            )


default_copilot_service = CopilotService()
