"""Pydantic schemas for Satellite Imagery and Flood Detection Pipeline.

Defines typed contracts for the multi-stage flood detection pipeline:
1. Satellite Image Ingestion & Metadata
2. Raster Processing & Band Extraction
3. Water Detection (NDWI / MNDWI)
4. Permanent Water Masking
5. Flood Extent Derivation & Statistics
6. GeoJSON Vector Output
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class SpectralIndexType(str, Enum):
    """Supported spectral indices for surface water detection."""
    NDWI = "NDWI"      # Normalized Difference Water Index: (Green - NIR) / (Green + NIR)
    MNDWI = "MNDWI"    # Modified NDWI: (Green - SWIR) / (Green + SWIR)
    AWEI = "AWEI"      # Automated Water Extraction Index


class RasterBoundingBox(BaseModel):
    """Geographic bounding box coordinates in WGS84 (EPSG:4326)."""
    min_lon: float = Field(..., ge=-180.0, le=180.0, description="Westernmost longitude")
    min_lat: float = Field(..., ge=-90.0, le=90.0, description="Southernmost latitude")
    max_lon: float = Field(..., ge=-180.0, le=180.0, description="Easternmost longitude")
    max_lat: float = Field(..., ge=-90.0, le=90.0, description="Northernmost latitude")


class RasterMetadata(BaseModel):
    """Metadata describing an ingested raster / satellite scene."""
    scene_id: str = Field(..., description="Unique scene or acquisition identifier")
    acquisition_date: Optional[str] = Field(None, description="Acquisition timestamp in ISO 8601 format")
    sensor: Optional[str] = Field(None, description="Satellite sensor (e.g., Sentinel-2, Landsat-8)")
    crs: str = Field(default="EPSG:4326", description="Coordinate Reference System")
    bbox: RasterBoundingBox = Field(..., description="Spatial extent of raster")
    width_px: int = Field(..., gt=0, description="Raster width in pixels")
    height_px: int = Field(..., gt=0, description="Raster height in pixels")
    resolution_meters: float = Field(..., gt=0.0, description="Spatial resolution per pixel in meters")
    available_bands: List[str] = Field(default_factory=list, description="List of band names in the raster")


class SatelliteSceneContract(BaseModel):
    """Specification contract for satellite scene ingestion."""
    scene_path: str = Field(..., description="Path to GeoTIFF file or Sentinel-2 band directory")
    pilot_area: str = Field(default="Ahmedabad", description="Target pilot region")
    required_bands: List[str] = Field(
        default_factory=lambda: ["B03", "B08"],
        description="Required spectral bands for water detection (e.g. B03 Green, B08 NIR)"
    )
    expected_crs: Optional[str] = Field(
        default=None,
        description="Expected CRS (e.g. EPSG:4326 or EPSG:32643 UTM Zone 43N)"
    )


class WaterDetectionConfig(BaseModel):
    """Configuration parameters for spectral water classification."""
    index_type: SpectralIndexType = Field(default=SpectralIndexType.NDWI, description="Index formula to use")
    threshold: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Index threshold above which pixel is classified as water (typically >= 0.0)"
    )
    nodata_value: Optional[float] = Field(
        default=None,
        description="Optional nodata value to ignore during calculation (e.g. 0.0, -9999.0)"
    )


class SurfaceWaterMaskResult(BaseModel):
    """Result of spectral surface water detection on a satellite scene."""
    model_config = {"arbitrary_types_allowed": True}

    scene_id: str = Field(..., description="Source scene identifier")
    metadata: RasterMetadata = Field(..., description="Spatial metadata of source raster")
    water_mask: Any = Field(..., description="Binary 2D numpy array (1=water, 0=non-water, uint8)")
    ndwi_array: Optional[Any] = Field(None, description="2D float32 NDWI array with NaN for nodata/invalid")
    threshold: float = Field(default=0.0, description="Configured NDWI threshold used for classification")
    total_pixels: int = Field(..., description="Total pixel count of the raster scene")
    valid_pixels: int = Field(..., description="Count of valid (non-nodata) pixels")
    water_pixels: int = Field(..., description="Count of classified surface-water pixels")
    water_fraction: float = Field(..., description="Ratio of water pixels to valid pixels (0.0 to 1.0)")
    nodata_pixels: int = Field(default=0, description="Count of masked nodata pixels")
    transform: Optional[Tuple[float, ...]] = Field(None, description="Affine transformation coefficients")



class PermanentWaterMaskConfig(BaseModel):
    """Configuration for masking out permanent/baseline water bodies."""
    mask_source: str = Field(default="jrc_global_surface_water", description="Permanent water reference source")
    mask_identifier: Optional[str] = Field(None, description="Identifier or path for permanent water baseline dataset")
    threshold_recurrence_pct: float = Field(
        default=80.0,
        ge=0.0,
        le=100.0,
        description="Occurrence percentage to qualify as permanent water"
    )


class PotentialFloodWaterResult(BaseModel):
    """Result of permanent water masking separating newly flooded areas from baseline water bodies."""
    model_config = {"arbitrary_types_allowed": True}

    scene_id: str = Field(..., description="Source scene identifier")
    metadata: RasterMetadata = Field(..., description="Spatial metadata of source raster")
    flood_water_mask: Any = Field(..., description="Binary 2D numpy array of new/potential flood water (1=flood, 0=non-flood/permanent, uint8)")
    permanent_water_mask: Optional[Any] = Field(None, description="Binary 2D numpy array of permanent water (1=permanent, 0=non-permanent, uint8)")
    total_pixels: int = Field(..., description="Total pixel count of the raster scene")
    valid_pixels: int = Field(..., description="Count of valid (non-nodata) pixels")
    nodata_pixels: int = Field(default=0, description="Count of masked nodata pixels")
    detected_water_pixels: int = Field(..., description="Total NDWI surface water pixels before masking")
    permanent_water_pixels: int = Field(..., description="Baseline permanent water pixels within valid scene area")
    new_flood_water_pixels: int = Field(..., description="Net new / potential flood water pixels (detected - permanent)")
    flood_fraction: float = Field(..., description="Ratio of new flood water pixels to valid pixels (0.0 to 1.0)")
    transform: Optional[Tuple[float, ...]] = Field(None, description="Affine transformation coefficients")


# Alias for compatibility
PermanentWaterMaskResult = PotentialFloodWaterResult


class FloodExtentMetrics(BaseModel):
    """Quantitative statistical metrics for detected flood extent."""
    total_water_area_sq_km: float = Field(..., ge=0.0, description="Total detected surface water area in sq km")
    permanent_water_area_sq_km: float = Field(..., ge=0.0, description="Baseline permanent water area in sq km")
    flood_extent_sq_km: float = Field(..., ge=0.0, description="Net newly flooded area (Total - Permanent)")
    affected_zones: List[str] = Field(default_factory=list, description="IDs or names of intersected administrative zones")


class GeoJSONGeometry(BaseModel):
    """GeoJSON geometry definition conforming to RFC 7946."""
    type: str = Field(..., description="Geometry type (Polygon, MultiPolygon)")
    coordinates: List[Any] = Field(..., description="Coordinate rings conforming to GeoJSON spec")


class GeoJSONFeature(BaseModel):
    """GeoJSON Feature conforming to RFC 7946."""
    type: str = Field(default="Feature", description="GeoJSON type")
    geometry: GeoJSONGeometry = Field(..., description="Geometry representation")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Feature attributes and metadata")


class GeoJSONFeatureCollection(BaseModel):
    """GeoJSON FeatureCollection representing vectorized flood extent."""
    type: str = Field(default="FeatureCollection", description="GeoJSON FeatureCollection type")
    features: List[GeoJSONFeature] = Field(default_factory=list, description="List of vectorized polygon features")
    bbox: Optional[List[float]] = Field(None, description="Optional bounding box [minX, minY, maxX, maxY]")


class FloodExtentResponse(BaseModel):
    """Standard API response schema for flood detection pipeline results."""
    scene_id: str = Field(..., description="Input scene identifier")
    timestamp: str = Field(..., description="Processing timestamp (ISO 8601)")
    metrics: FloodExtentMetrics = Field(..., description="Statistical flood metrics")
    geojson: GeoJSONFeatureCollection = Field(..., description="Vectorized flood extent boundary")
    status: str = Field(default="SUCCESS", description="Pipeline execution status")
    notes: Optional[str] = Field(None, description="Processing notes or warnings")
