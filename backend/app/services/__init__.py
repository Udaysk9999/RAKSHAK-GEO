"""Service layer initialization for CITYSHIELD GIS."""

from .optimization_service import ResourceOptimizationService
from .what_if_service import WhatIfSimulationService
from .timeline_service import FutureGapTimelineService
from .gis_service import GISFloodImpactService
from .flood_service import (
    BaseRasterProcessor,
    GeoTIFFRasterProcessor,
    BaseWaterDetector,
    NDWIWaterDetector,
    SpectralWaterDetector,
    BasePermanentWaterMasker,
    BaseFloodExtentAnalyzer,
    BaseGeoJSONExporter,
    FloodDetectionPipeline,
)
from .flood_response_service import FloodResponseService
from .city_gis_repository import CityGISRepository
from .copilot import (
    ToolDefinition,
    ToolRegistry,
    ToolExecutor,
    default_tool_registry,
    default_tool_executor,
    get_grounding_context,
    BaseLLMProvider,
    MockLLMProvider,
    OpenRouterLLMProvider,
    LLMPlanResult,
    get_copilot_provider,
    CopilotService,
    default_copilot_service,
)

__all__ = [
    "ResourceOptimizationService",
    "WhatIfSimulationService",
    "FutureGapTimelineService",
    "GISFloodImpactService",
    "BaseRasterProcessor",
    "GeoTIFFRasterProcessor",
    "BaseWaterDetector",
    "NDWIWaterDetector",
    "SpectralWaterDetector",
    "BasePermanentWaterMasker",
    "BaseFloodExtentAnalyzer",
    "BaseGeoJSONExporter",
    "FloodDetectionPipeline",
    "FloodResponseService",
    "CityGISRepository",
    "ToolDefinition",
    "ToolRegistry",
    "ToolExecutor",
    "default_tool_registry",
    "default_tool_executor",
    "get_grounding_context",
    "BaseLLMProvider",
    "MockLLMProvider",
    "OpenRouterLLMProvider",
    "LLMPlanResult",
    "get_copilot_provider",
    "CopilotService",
    "default_copilot_service",
]
