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

import os
import math
import glob
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import rasterio
import pyproj

from app.schemas.flood import (
    RasterBoundingBox,
    RasterMetadata,
    WaterDetectionConfig,
    SurfaceWaterMaskResult,
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


SENTINEL2_ALIASES = {
    "GREEN": "B03",
    "NIR": "B08",
    "RED": "B04",
    "BLUE": "B02",
    "SWIR": "B11",
    "SWIR2": "B12",
}


class GeoTIFFRasterProcessor(BaseRasterProcessor):
    """Concrete raster processor for GeoTIFF imagery using Rasterio and PyProj.

    Supports:
    - Single multi-band or single-band GeoTIFF scenes (.tif, .tiff)
    - Sentinel-2 band directories containing individual band GeoTIFFs (e.g. B03.tif, B08.tif)
    - Full metadata validation (CRS, affine transform, dimensions, spatial resolution)
    - Strict georeferencing validation (rejects unreferenced rasters)
    - Band extraction with standard Sentinel-2 naming and aliases (B03/GREEN, B08/NIR)
    """

    def read_metadata(self, source_path: str) -> RasterMetadata:
        """Extract spatial reference, dimensions, resolution, and band inventory from raster source."""
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Raster source path does not exist: '{source_path}'")

        if os.path.isdir(source_path):
            return self._read_directory_metadata(source_path)
        else:
            return self._read_file_metadata(source_path)

    def _read_file_metadata(self, file_path: str) -> RasterMetadata:
        with rasterio.open(file_path) as src:
            # 1. Georeferencing validation
            if src.crs is None:
                raise ValueError(f"Raster '{file_path}' is not georeferenced: CRS metadata is missing.")
            if src.transform is None or src.transform.is_identity:
                raise ValueError(f"Raster '{file_path}' is not georeferenced: affine transform is missing or identity.")

            # 2. Dimensions
            width_px = src.width
            height_px = src.height

            # 3. CRS and Bounding Box
            crs_str = src.crs.to_string() if src.crs else "UNKNOWN"
            if src.crs.is_geographic or crs_str in ("EPSG:4326", "OGC:CRS84"):
                min_lon = float(src.bounds.left)
                min_lat = float(src.bounds.bottom)
                max_lon = float(src.bounds.right)
                max_lat = float(src.bounds.top)
            else:
                try:
                    transformer = pyproj.Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True)
                    xs = [src.bounds.left, src.bounds.right, src.bounds.right, src.bounds.left]
                    ys = [src.bounds.bottom, src.bounds.bottom, src.bounds.top, src.bounds.top]
                    lons, lats = transformer.transform(xs, ys)
                    min_lon = float(min(lons))
                    min_lat = float(min(lats))
                    max_lon = float(max(lons))
                    max_lat = float(max(lats))
                except Exception as e:
                    raise ValueError(f"Failed to project raster bounding box to WGS84: {str(e)}")

            # Validate coordinate bounds are within valid WGS84 range
            if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0 and
                    -90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
                raise ValueError(
                    f"Derived bounding box out of valid WGS84 range: [{min_lon}, {min_lat}, {max_lon}, {max_lat}]"
                )

            bbox = RasterBoundingBox(
                min_lon=round(min_lon, 6),
                min_lat=round(min_lat, 6),
                max_lon=round(max_lon, 6),
                max_lat=round(max_lat, 6),
            )

            # 4. Spatial resolution in meters
            res_x, _ = src.res
            if src.crs.is_projected:
                resolution_meters = round(float(res_x), 2)
            else:
                center_lat = (min_lat + max_lat) / 2.0
                resolution_meters = round(float(res_x * 111320.0 * math.cos(math.radians(center_lat))), 2)

            if resolution_meters <= 0.0:
                resolution_meters = 10.0

            # 5. Available bands
            available_bands = []
            if src.descriptions and any(src.descriptions):
                available_bands = [d for d in src.descriptions if d]
            elif src.count == 2:
                available_bands = ["B03", "B08"]
            else:
                available_bands = [f"BAND_{i}" for i in range(1, src.count + 1)]

            scene_id = Path(file_path).stem

            return RasterMetadata(
                scene_id=scene_id,
                sensor="Sentinel-2",
                crs=crs_str,
                bbox=bbox,
                width_px=width_px,
                height_px=height_px,
                resolution_meters=resolution_meters,
                available_bands=available_bands,
            )

    def _read_directory_metadata(self, dir_path: str) -> RasterMetadata:
        band_files = sorted(glob.glob(os.path.join(dir_path, "*.tif*")))
        if not band_files:
            raise FileNotFoundError(f"No GeoTIFF files (*.tif, *.tiff) found in directory: '{dir_path}'")

        # Read spatial attributes from first band file
        first_band = band_files[0]
        meta = self._read_file_metadata(first_band)

        # Detect band names from filenames in directory
        discovered_bands = []
        for bf in band_files:
            stem = Path(bf).stem.upper()
            matched = False
            for b in ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B11", "B12", "GREEN", "NIR", "RED", "BLUE"]:
                if b in stem:
                    discovered_bands.append(b)
                    matched = True
                    break
            if not matched:
                discovered_bands.append(stem)

        scene_id = Path(dir_path).name
        return RasterMetadata(
            scene_id=scene_id,
            sensor="Sentinel-2",
            crs=meta.crs,
            bbox=meta.bbox,
            width_px=meta.width_px,
            height_px=meta.height_px,
            resolution_meters=meta.resolution_meters,
            available_bands=discovered_bands,
        )

    def extract_bands(self, source_path: str, band_names: List[str]) -> Dict[str, Any]:
        """Extract requested spectral bands as numpy arrays."""
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Raster source path does not exist: '{source_path}'")

        if os.path.isdir(source_path):
            return self._extract_bands_from_directory(source_path, band_names)
        else:
            return self._extract_bands_from_file(source_path, band_names)

    def _extract_bands_from_file(self, file_path: str, band_names: List[str]) -> Dict[str, Any]:
        extracted = {}
        with rasterio.open(file_path) as src:
            meta = self._read_file_metadata(file_path)
            avail = meta.available_bands

            # Build lookup from band name to 1-based band index
            band_lookup = {}
            for i, name in enumerate(avail, start=1):
                band_lookup[name.upper()] = i
                for alias, target in SENTINEL2_ALIASES.items():
                    if target.upper() == name.upper():
                        band_lookup[alias] = i

            if src.count >= 2:
                band_lookup.setdefault("B03", 1)
                band_lookup.setdefault("GREEN", 1)
                band_lookup.setdefault("B08", 2)
                band_lookup.setdefault("NIR", 2)

            for req_name in band_names:
                normalized_name = req_name.upper()
                idx = band_lookup.get(normalized_name)
                if idx is None:
                    raise KeyError(
                        f"Requested band '{req_name}' not available in raster '{file_path}'. "
                        f"Available bands: {avail}"
                    )
                extracted[req_name] = src.read(idx)

        return extracted

    def _extract_bands_from_directory(self, dir_path: str, band_names: List[str]) -> Dict[str, Any]:
        extracted = {}
        band_files = sorted(glob.glob(os.path.join(dir_path, "*.tif*")))
        if not band_files:
            raise FileNotFoundError(f"No GeoTIFF files found in directory: '{dir_path}'")

        for req_name in band_names:
            normalized_name = req_name.upper()
            target_code = SENTINEL2_ALIASES.get(normalized_name, normalized_name)

            matched_file = None
            for bf in band_files:
                stem = Path(bf).stem.upper()
                if target_code in stem or normalized_name in stem:
                    matched_file = bf
                    break

            if not matched_file:
                raise KeyError(
                    f"Requested band '{req_name}' (target '{target_code}') not found in directory '{dir_path}'."
                )

            with rasterio.open(matched_file) as src:
                extracted[req_name] = src.read(1)

        return extracted



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


class NDWIWaterDetector(BaseWaterDetector):
    """Concrete surface-water detector implementing McFeeters Normalized Difference Water Index (NDWI).

    Scientific Formula:
        NDWI = (Green - NIR) / (Green + NIR)
        For Sentinel-2: Green = B03, NIR = B08

    Deterministic Classification:
        NDWI >= threshold -> water (1)
        NDWI < threshold  -> non-water (0)
        Nodata / Division-by-Zero / NaN -> non-water (0)

    Guarantees:
        - Division by zero is safely guarded (zero denominator yields NaN and 0 in mask).
        - Nodata pixels are masked out and cannot accidentally become water.
        - Preserves input raster spatial metadata (CRS, transform, dimensions, bounds, resolution).
        - Strictly detects surface water; does NOT subtract permanent water (deferred to Step 4).
    """

    def validate_band_alignment(
        self,
        band_green: Any,
        band_nir: Any,
        meta_green: Optional[RasterMetadata] = None,
        meta_nir: Optional[RasterMetadata] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Validate shape, dimensionality, and spatial metadata compatibility of Green and NIR bands."""
        green_arr = np.asarray(band_green)
        nir_arr = np.asarray(band_nir)

        # Squeeze 3D single-band raster arrays (e.g. from rasterio read)
        if green_arr.ndim == 3 and green_arr.shape[0] == 1:
            green_arr = green_arr[0]
        if nir_arr.ndim == 3 and nir_arr.shape[0] == 1:
            nir_arr = nir_arr[0]

        if green_arr.ndim != 2 or nir_arr.ndim != 2:
            raise ValueError(
                f"Expected 2D raster band arrays, but received Green ndim={green_arr.ndim} and NIR ndim={nir_arr.ndim}."
            )

        if green_arr.shape != nir_arr.shape:
            raise ValueError(
                f"Raster shape mismatch between B03 Green {green_arr.shape} and B08 NIR {nir_arr.shape}."
            )

        # Validate spatial metadata compatibility if provided
        if meta_green is not None and meta_nir is not None:
            if meta_green.crs != meta_nir.crs:
                raise ValueError(
                    f"CRS mismatch: B03 Green CRS '{meta_green.crs}' != B08 NIR CRS '{meta_nir.crs}'."
                )
            if abs(meta_green.resolution_meters - meta_nir.resolution_meters) > 1e-3:
                raise ValueError(
                    f"Resolution mismatch: B03 ({meta_green.resolution_meters}m) != B08 ({meta_nir.resolution_meters}m)."
                )
            if meta_green.width_px != meta_nir.width_px or meta_green.height_px != meta_nir.height_px:
                raise ValueError(
                    f"Pixel dimension mismatch: B03 ({meta_green.width_px}x{meta_green.height_px}) != "
                    f"B08 ({meta_nir.width_px}x{meta_nir.height_px})."
                )
            if (
                abs(meta_green.bbox.min_lon - meta_nir.bbox.min_lon) > 1e-4
                or abs(meta_green.bbox.max_lat - meta_nir.bbox.max_lat) > 1e-4
            ):
                raise ValueError(
                    f"Geospatial bounding box mismatch between B03 ({meta_green.bbox}) and B08 ({meta_nir.bbox})."
                )

        return green_arr, nir_arr

    def compute_index(
        self,
        band_green: Any,
        band_nir_or_swir: Any,
        config: Optional[WaterDetectionConfig] = None,
    ) -> np.ndarray:
        """Calculate NDWI = (Green - NIR) / (Green + NIR) with safe division and nodata masking."""
        if config is None:
            config = WaterDetectionConfig()

        green_arr, nir_arr = self.validate_band_alignment(band_green, band_nir_or_swir)

        # Cast to float32 for continuous floating point division
        green = green_arr.astype(np.float32, copy=False)
        nir = nir_arr.astype(np.float32, copy=False)

        # Identify invalid / nodata pixels
        nodata_mask = np.isnan(green) | np.isnan(nir) | np.isinf(green) | np.isinf(nir)
        if config.nodata_value is not None:
            nodata_mask = (
                nodata_mask
                | np.isclose(green, config.nodata_value)
                | np.isclose(nir, config.nodata_value)
            )

        numerator = green - nir
        denominator = green + nir

        # Guard division by zero: where denominator is close to 0.0 or pixel is nodata
        valid_denom = (~nodata_mask) & (np.abs(denominator) > 1e-7)

        ndwi = np.full(green.shape, np.nan, dtype=np.float32)
        np.divide(numerator, denominator, out=ndwi, where=valid_denom)

        # Clip numerical precision spillover to theoretical index range [-1.0, 1.0]
        valid_indices = ~np.isnan(ndwi)
        ndwi[valid_indices] = np.clip(ndwi[valid_indices], -1.0, 1.0)

        return ndwi

    def classify_water(
        self,
        index_array: Any,
        threshold: float = 0.0,
        nodata_mask: Optional[Any] = None,
    ) -> np.ndarray:
        """Classify NDWI array into binary water mask (1=water, 0=non-water) deterministically."""
        idx = np.asarray(index_array)
        water_mask = np.zeros(idx.shape, dtype=np.uint8)

        # Valid pixels must be finite and not flagged as nodata
        valid_pixels = ~np.isnan(idx) & ~np.isinf(idx)
        if nodata_mask is not None:
            valid_pixels = valid_pixels & (~np.asarray(nodata_mask, dtype=bool))

        # NDWI >= threshold -> water (1), else non-water (0)
        water_condition = valid_pixels & (idx >= threshold)
        water_mask[water_condition] = 1
        water_mask[~water_condition] = 0

        return water_mask

    def detect_water_from_bands(
        self,
        band_green: Any,
        band_nir: Any,
        metadata: RasterMetadata,
        config: Optional[WaterDetectionConfig] = None,
        transform: Optional[Any] = None,
    ) -> SurfaceWaterMaskResult:
        """Execute NDWI calculation and water classification, preserving complete raster metadata."""
        if config is None:
            config = WaterDetectionConfig()

        ndwi = self.compute_index(band_green, band_nir, config)
        water_mask = self.classify_water(ndwi, threshold=config.threshold)

        total_pixels = int(water_mask.size)
        valid_pixels = int(np.sum(~np.isnan(ndwi)))
        nodata_pixels = total_pixels - valid_pixels
        water_pixels = int(np.sum(water_mask == 1))
        water_fraction = (
            round(float(water_pixels / valid_pixels), 6) if valid_pixels > 0 else 0.0
        )

        transform_tuple = None
        if transform is not None:
            if hasattr(transform, "to_gdal"):
                transform_tuple = tuple(transform.to_gdal())
            elif isinstance(transform, (tuple, list)):
                transform_tuple = tuple(transform)

        return SurfaceWaterMaskResult(
            scene_id=metadata.scene_id,
            metadata=metadata,
            water_mask=water_mask,
            ndwi_array=ndwi,
            threshold=config.threshold,
            total_pixels=total_pixels,
            valid_pixels=valid_pixels,
            water_pixels=water_pixels,
            water_fraction=water_fraction,
            nodata_pixels=nodata_pixels,
            transform=transform_tuple,
        )

    def detect_water_from_scene(
        self,
        scene_path: str,
        raster_processor: BaseRasterProcessor,
        config: Optional[WaterDetectionConfig] = None,
    ) -> SurfaceWaterMaskResult:
        """Ingest a satellite scene, extract B03/B08, and compute surface water mask."""
        if config is None:
            config = WaterDetectionConfig()

        metadata = raster_processor.read_metadata(scene_path)
        bands = raster_processor.extract_bands(scene_path, ["B03", "B08"])
        return self.detect_water_from_bands(
            band_green=bands["B03"],
            band_nir=bands["B08"],
            metadata=metadata,
            config=config,
        )


# Alias for backward and forward compatibility
SpectralWaterDetector = NDWIWaterDetector


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
