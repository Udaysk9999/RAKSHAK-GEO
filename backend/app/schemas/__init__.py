"""Pydantic schemas for CITYSHIELD GIS backend."""
from .optimization import (
    ResourceQuantity,
    ResourceItemAllocation,
    ZoneDemand,
    OptimizationGoal,
    OptimizationConstraint,
    ResourceOptimizationRequest,
    ZoneAllocationResult,
    OptimizationSummary,
    ResourceOptimizationResponse,
    OptimizationStatusResponse,
)
from .what_if import (
    ZoneModifier,
    ScenarioChanges,
    WhatIfSimulateRequest,
    ResourceDelta,
    ZoneAllocationComparison,
    SimulationSummary,
    WhatIfSimulateResponse,
)

__all__ = [
    "ResourceQuantity",
    "ResourceItemAllocation",
    "ZoneDemand",
    "OptimizationGoal",
    "OptimizationConstraint",
    "ResourceOptimizationRequest",
    "ZoneAllocationResult",
    "OptimizationSummary",
    "ResourceOptimizationResponse",
    "OptimizationStatusResponse",
    "ZoneModifier",
    "ScenarioChanges",
    "WhatIfSimulateRequest",
    "ResourceDelta",
    "ZoneAllocationComparison",
    "SimulationSummary",
    "WhatIfSimulateResponse",
]
