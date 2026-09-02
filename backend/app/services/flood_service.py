"""Satellite Imagery and Flood Detection Service Foundation.

Defines the modular interfaces and orchestrator for the 5-stage flood detection pipeline:
1. Raster Processing Interface
2. Water Detection Interface (NDWI / MNDWI)
3. Permanent Water Masking Interface
4. Flood Extent Derivation Interface
5. GeoJSON Vector Export Interface

Note: This is the foundation architecture for Phase 1 - Step 1.
Full algorithm implementations, GDAL/Rasterio bindings, and Sentinel ingestion
will be integrated once satellite data sources and GIS libraries are established.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from app.schemas.flood import (
    RasterMetadata,
    WaterDetectionConfig,
    PermanentWaterMaskConfig,
    FloodExtentMetrics,
    GeoJSONFeatureCollection,
    FloodExtentResponse,
)


class BaseRasterProcessor(ABC):
    """Abstract interface for raster ingestion, metadata extraction, and band splitting."""

    @abstractmethod
    def read_metadata(self, source_path: str) -> RasterMetadata:
        """Extract spatial reference, dimensions, resolution, and band inventory from raster source."""
        pass

    @abstractmethod
    def extract_bands(self, source_path: str, band_names: List[str]) -> Dict[str, Any]:
        """Extract requested spectral bands (e.g., Green, NIR, SWIR) as normalized numerical arrays."""
        pass


class BaseWaterDetector(ABC):
    """Abstract interface for spectral index computation and surface water classification."""

    @abstractmethod
    def compute_index(
        self,
        band_green: Any,
        band_nir_or_swir: Any,
        config: WaterDetectionConfig
    ) -> Any:
        """Calculate normalized difference spectral index (e.g. NDWI = (Green - NIR) / (Green + NIR))."""
        pass

    @abstractmethod
    def classify_water(self, index_array: Any, threshold: float) -> Any:
        """Classify raster pixels as water (1) or non-water (0) based on threshold."""
        pass


class BasePermanentWaterMasker(ABC):
    """Abstract interface for masking baseline permanent water bodies (rivers, lakes, reservoirs)."""

    @abstractmethod
    def apply_mask(
        self,
        detected_water_mask: Any,
        mask_config: PermanentWaterMaskConfig,
        spatial_bounds: Any
    ) -> Any:
        """Subtract permanent water bodies from detected water mask to isolate ephemeral flood water."""
        pass


class BaseFloodExtentAnalyzer(ABC):
    """Abstract interface for calculating quantitative flood statistics and affected metrics."""

    @abstractmethod
    def calculate_metrics(
        self,
        flood_water_mask: Any,
        pixel_resolution_m: float,
        permanent_water_mask: Optional[Any] = None
    ) -> FloodExtentMetrics:
        """Compute square kilometer flood areas and spatial statistics from pixel masks."""
        pass


class BaseGeoJSONExporter(ABC):
    """Abstract interface for vectorizing binary flood raster masks into RFC 7946 GeoJSON polygons."""

    @abstractmethod
    def export_geojson(
        self,
        flood_water_mask: Any,
        metadata: RasterMetadata,
        properties: Optional[Dict[str, Any]] = None
    ) -> GeoJSONFeatureCollection:
        """Convert raster flood clusters into clean GeoJSON polygons with coordinate transforms."""
        pass


class FloodDetectionPipeline:
    """Orchestrator class encapsulating the satellite-to-GeoJSON flood detection pipeline.

    Workflow:
    Satellite Image -> Raster Processing -> Water Detection -> Permanent Water Mask -> Flood Extent -> GeoJSON Output
    """

    def __init__(
        self,
        raster_processor: Optional[BaseRasterProcessor] = None,
        water_detector: Optional[BaseWaterDetector] = None,
        permanent_masker: Optional[BasePermanentWaterMasker] = None,
        flood_analyzer: Optional[BaseFloodExtentAnalyzer] = None,
        geojson_exporter: Optional[BaseGeoJSONExporter] = None,
    ):
        self.raster_processor = raster_processor
        self.water_detector = water_detector
        self.permanent_masker = permanent_masker
        self.flood_analyzer = flood_analyzer
        self.geojson_exporter = geojson_exporter

    def validate_pipeline_readiness(self) -> Dict[str, bool]:
        """Check whether each pipeline stage processor has been wired with an active implementation."""
        return {
            "raster_processor": self.raster_processor is not None,
            "water_detector": self.water_detector is not None,
            "permanent_masker": self.permanent_masker is not None,
            "flood_analyzer": self.flood_analyzer is not None,
            "geojson_exporter": self.geojson_exporter is not None,
        }

    def execute_pipeline(
        self,
        source_path: str,
        water_config: WaterDetectionConfig,
        mask_config: PermanentWaterMaskConfig,
    ) -> FloodExtentResponse:
        """Execute the full 5-stage flood pipeline.

        Raises:
            NotImplementedError: If any pipeline stage component has not yet been implemented or injected.
            FileNotFoundError: If the satellite image source path cannot be found.
        """
        readiness = self.validate_pipeline_readiness()
        unconfigured = [stage for stage, ready in readiness.items() if not ready]
        if unconfigured:
            raise NotImplementedError(
                f"Flood detection pipeline foundation established, but active providers for {unconfigured} "
                "are pending integration of GIS data/libraries in subsequent steps."
            )

        # Future pipeline sequence:
        # 1. meta = self.raster_processor.read_metadata(source_path)
        # 2. bands = self.raster_processor.extract_bands(source_path, ["GREEN", "NIR"])
        # 3. idx = self.water_detector.compute_index(bands["GREEN"], bands["NIR"], water_config)
        # 4. total_water = self.water_detector.classify_water(idx, water_config.threshold)
        # 5. flood_water = self.permanent_masker.apply_mask(total_water, mask_config, meta.bbox)
        # 6. metrics = self.flood_analyzer.calculate_metrics(flood_water, meta.resolution_meters)
        # 7. geojson = self.geojson_exporter.export_geojson(flood_water, meta)
        raise NotImplementedError("Full pipeline execution pending implementation of GIS providers.")
