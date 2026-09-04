"""Copilot API Endpoints (T-020 Step 3).

Exposes conversational natural language endpoints grounded in verified backend services:
POST /api/v1/copilot/chat
GET  /api/v1/copilot/sample-payload
All synthetic disaster resources and geometries are labeled DEMO DATA per agent.md.
"""
from fastapi import APIRouter, status

from app.schemas.copilot import (
    CopilotMessage,
    CopilotRequest,
    CopilotResponse,
    CopilotRole,
)
from app.services.copilot.service import default_copilot_service

router = APIRouter(prefix="/copilot", tags=["Disaster Response LLM Copilot"])


@router.post(
    "/chat",
    response_model=CopilotResponse,
    status_code=status.HTTP_200_OK,
    summary="Query Disaster Response Copilot",
    description=(
        "Processes natural language queries for disaster command and response. Plans backend "
        "tool execution over a fixed allowlist of 6 services (GIS impact, optimization, What-If, "
        "timeline, city GIS data, end-to-end response), executes the tool, and returns a grounded "
        "factual explanation. Does not hallucinate numerical values [DEMO DATA]."
    ),
)
def chat_with_copilot(request: CopilotRequest) -> CopilotResponse:
    """Execute grounded conversational query through CopilotService."""
    return default_copilot_service.chat(request)


@router.get(
    "/sample-payload",
    response_model=CopilotRequest,
    status_code=status.HTTP_200_OK,
    summary="Get Reference Copilot Request [DEMO DATA]",
    description="Returns a sample conversational disaster response query for Ahmedabad flood operations.",
)
def get_sample_copilot_payload() -> CopilotRequest:
    """Return a representative sample request with synthetic DEMO DATA."""
    return CopilotRequest(
        query="What is the current flood impact across Ahmedabad wards and which zones need boats?",
        incident_id="INC-AHM-FLOOD-COPILOT-01",
        city_id="AHMEDABAD",
        conversation_history=[
            CopilotMessage(
                role=CopilotRole.USER,
                content="Incident Commander logged in for Ahmedabad disaster operations [DEMO DATA].",
            ),
            CopilotMessage(
                role=CopilotRole.ASSISTANT,
                content="Standing by for operational queries on flood impact, hospital capacities, and stockpile dispatch [DEMO DATA].",
            ),
        ],
        force_tool=None,
    )
