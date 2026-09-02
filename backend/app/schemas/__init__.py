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
from .flood import (
    SpectralIndexType,
    RasterBoundingBox,
    RasterMetadata,
    WaterDetectionConfig,
    PermanentWaterMaskConfig,
    FloodExtentMetrics,
    GeoJSONGeometry,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    FloodExtentResponse,
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
    "SpectralIndexType",
    "RasterBoundingBox",
    "RasterMetadata",
    "WaterDetectionConfig",
    "PermanentWaterMaskConfig",
    "FloodExtentMetrics",
    "GeoJSONGeometry",
    "GeoJSONFeature",
    "GeoJSONFeatureCollection",
    "FloodExtentResponse",
]

