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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import rasterio
import rasterio.features
import rasterio.transform
from rasterio.transform import Affine
import pyproj
import shapely.geometry
import shapely.validation

from app.schemas.flood import (
    RasterBoundingBox,
    RasterMetadata,
    WaterDetectionConfig,
    SurfaceWaterMaskResult,
    PermanentWaterMaskConfig,
    PotentialFloodWaterResult,
    PermanentWaterMaskResult,
    FloodExtentMetrics,
    GeoJSONGeometry,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    FloodExtentExtractionConfig,
    FloodExtentResponse,
    FloodExtentResult,
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


class PermanentWaterMasker(BasePermanentWaterMasker):
    """Concrete permanent-water masker separating detected surface water from baseline water bodies.

    Scientific & Operational Rationale:
        Satellite optical water detection (NDWI) classifies all water surfaces indiscriminately
        (rivers, lakes, reservoirs, swimming pools, retention basins, and flood waters).
        To derive potential/ephemeral flood inundation, baseline permanent water must be subtracted:
            new_flood_water = detected_water AND NOT permanent_water

    Deterministic Masking Rules:
        - detected_water = 1, permanent_water = 1 -> new_water = 0 (baseline river/lake)
        - detected_water = 1, permanent_water = 0 -> new_water = 1 (potential flood inundation)
        - detected_water = 0, permanent_water = 0 -> new_water = 0 (dry land)
        - detected_water = 0, permanent_water = 1 -> new_water = 0 (receded baseline or dry riverbed)
        - nodata / invalid pixels -> new_water = 0 (never classified as flood)

    Spatial Alignment Validation:
        Strictly validates that detected water and permanent water masks have matching:
        - Array shape / dimensions (height, width)
        - CRS (Coordinate Reference System)
        - Spatial resolution in meters
        - Affine transform / Bounding box
        Raises ValueError on any spatial mismatch to avoid silent geometric distortions.

    Limitations:
        - Identifies new/potential surface water; does NOT prove structural building damage.
        - Accuracy depends on the quality and temporal relevance of the permanent water baseline.
    """

    def validate_mask_alignment(
        self,
        detected_water_mask: Any,
        permanent_water_mask: Any,
        meta_detected: Optional[RasterMetadata] = None,
        meta_permanent: Optional[RasterMetadata] = None,
        transform_detected: Optional[Any] = None,
        transform_permanent: Optional[Any] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Validate shape, dimensionality, and spatial metadata compatibility of water masks."""
        det_arr = np.asarray(detected_water_mask)
        perm_arr = np.asarray(permanent_water_mask)

        # Squeeze 3D single-band raster arrays
        if det_arr.ndim == 3 and det_arr.shape[0] == 1:
            det_arr = det_arr[0]
        if perm_arr.ndim == 3 and perm_arr.shape[0] == 1:
            perm_arr = perm_arr[0]

        if det_arr.ndim != 2 or perm_arr.ndim != 2:
            raise ValueError(
                f"Expected 2D raster masks, but received detected ndim={det_arr.ndim} and permanent ndim={perm_arr.ndim}."
            )

        if det_arr.shape != perm_arr.shape:
            raise ValueError(
                f"Mask shape mismatch: detected water mask {det_arr.shape} != permanent water mask {perm_arr.shape}."
            )

        # Validate spatial metadata if provided
        if meta_detected is not None and meta_permanent is not None:
            if meta_detected.crs != meta_permanent.crs:
                raise ValueError(
                    f"CRS mismatch: detected water CRS '{meta_detected.crs}' != permanent water CRS '{meta_permanent.crs}'."
                )
            if abs(meta_detected.resolution_meters - meta_permanent.resolution_meters) > 1e-3:
                raise ValueError(
                    f"Resolution mismatch: detected water ({meta_detected.resolution_meters}m) != "
                    f"permanent water ({meta_permanent.resolution_meters}m)."
                )
            if meta_detected.width_px != meta_permanent.width_px or meta_detected.height_px != meta_permanent.height_px:
                raise ValueError(
                    f"Pixel dimension mismatch: detected ({meta_detected.width_px}x{meta_detected.height_px}) != "
                    f"permanent ({meta_permanent.width_px}x{meta_permanent.height_px})."
                )
            if (
                abs(meta_detected.bbox.min_lon - meta_permanent.bbox.min_lon) > 1e-4
                or abs(meta_detected.bbox.min_lat - meta_permanent.bbox.min_lat) > 1e-4
                or abs(meta_detected.bbox.max_lon - meta_permanent.bbox.max_lon) > 1e-4
                or abs(meta_detected.bbox.max_lat - meta_permanent.bbox.max_lat) > 1e-4
            ):
                raise ValueError(
                    f"Geospatial bounding box mismatch between detected water ({meta_detected.bbox}) "
                    f"and permanent water ({meta_permanent.bbox})."
                )

        # Validate transform if provided
        if transform_detected is not None and transform_permanent is not None:
            t_det = tuple(transform_detected) if hasattr(transform_detected, "__iter__") else transform_detected
            t_perm = tuple(transform_permanent) if hasattr(transform_permanent, "__iter__") else transform_permanent
            if t_det != t_perm:
                if len(t_det) == len(t_perm):
                    if not np.allclose(np.array(t_det, dtype=float), np.array(t_perm, dtype=float), atol=1e-5):
                        raise ValueError(
                            f"Affine transform mismatch: detected {t_det} != permanent {t_perm}."
                        )
                else:
                    raise ValueError(
                        f"Affine transform mismatch: detected {t_det} != permanent {t_perm}."
                    )

        return det_arr, perm_arr

    def compute_new_flood_water(
        self,
        detected_water_mask: Any,
        permanent_water_mask: Any,
        nodata_mask: Optional[Any] = None,
    ) -> np.ndarray:
        """Compute new / potential flood water: (detected == 1) & (permanent == 0) & (~nodata)."""
        det_arr, perm_arr = self.validate_mask_alignment(detected_water_mask, permanent_water_mask)

        # Identify invalid / nodata elements in inputs
        invalid_mask = np.zeros(det_arr.shape, dtype=bool)
        if np.issubdtype(det_arr.dtype, np.floating):
            invalid_mask |= np.isnan(det_arr) | np.isinf(det_arr)
        if np.issubdtype(perm_arr.dtype, np.floating):
            invalid_mask |= np.isnan(perm_arr) | np.isinf(perm_arr)

        if nodata_mask is not None:
            invalid_mask |= np.asarray(nodata_mask, dtype=bool)

        # Binary water condition: detected == 1 and permanent == 0
        det_is_water = (det_arr == 1) & (~invalid_mask)
        perm_is_water = (perm_arr == 1) & (~invalid_mask)

        new_flood_bool = det_is_water & (~perm_is_water)

        flood_mask = np.zeros(det_arr.shape, dtype=np.uint8)
        flood_mask[new_flood_bool] = 1

        return flood_mask

    def mask_permanent_water(
        self,
        detected_water: Union[SurfaceWaterMaskResult, np.ndarray],
        permanent_water: Union[np.ndarray, str],
        metadata: Optional[RasterMetadata] = None,
        meta_permanent: Optional[RasterMetadata] = None,
        nodata_mask: Optional[np.ndarray] = None,
        transform: Optional[Any] = None,
        transform_permanent: Optional[Any] = None,
        raster_processor: Optional[BaseRasterProcessor] = None,
        config: Optional[PermanentWaterMaskConfig] = None,
    ) -> PotentialFloodWaterResult:
        """Execute permanent water masking and produce quantitative flood statistics and mask."""
        if config is None:
            config = PermanentWaterMaskConfig()

        # Extract parameters if SurfaceWaterMaskResult was passed
        if isinstance(detected_water, SurfaceWaterMaskResult):
            det_mask = detected_water.water_mask
            scene_id = detected_water.scene_id
            if metadata is None:
                metadata = detected_water.metadata
            if transform is None:
                transform = detected_water.transform
            if nodata_mask is None and detected_water.ndwi_array is not None:
                nodata_mask = np.isnan(detected_water.ndwi_array) | np.isinf(detected_water.ndwi_array)
        else:
            det_mask = detected_water
            scene_id = metadata.scene_id if metadata else "UNKNOWN_SCENE"

        # Load permanent water from file if string path was provided
        if isinstance(permanent_water, str):
            if not os.path.exists(permanent_water):
                raise FileNotFoundError(f"Permanent water raster file not found: '{permanent_water}'")
            if raster_processor is None:
                raster_processor = GeoTIFFRasterProcessor()
            meta_perm_file = raster_processor.read_metadata(permanent_water)
            if meta_permanent is None:
                meta_permanent = meta_perm_file
            with rasterio.open(permanent_water) as src:
                perm_mask = src.read(1)
                if transform_permanent is None and src.transform is not None:
                    transform_permanent = tuple(src.transform.to_gdal())
        else:
            perm_mask = permanent_water

        # Alignment validation
        det_arr, perm_arr = self.validate_mask_alignment(
            det_mask,
            perm_mask,
            meta_detected=metadata,
            meta_permanent=meta_permanent,
            transform_detected=transform,
            transform_permanent=transform_permanent,
        )

        # Derive nodata mask
        total_pixels = int(det_arr.size)
        invalid_pixels = np.zeros(det_arr.shape, dtype=bool)
        if np.issubdtype(det_arr.dtype, np.floating):
            invalid_pixels |= np.isnan(det_arr) | np.isinf(det_arr)
        if np.issubdtype(perm_arr.dtype, np.floating):
            invalid_pixels |= np.isnan(perm_arr) | np.isinf(perm_arr)
        if nodata_mask is not None:
            invalid_pixels |= np.asarray(nodata_mask, dtype=bool)

        nodata_count = int(np.sum(invalid_pixels))
        valid_pixels = total_pixels - nodata_count

        # Compute new flood mask
        flood_mask = self.compute_new_flood_water(det_arr, perm_arr, nodata_mask=invalid_pixels)

        # Compute pixel counts on valid pixels
        valid_det_water = (det_arr == 1) & (~invalid_pixels)
        valid_perm_water = (perm_arr == 1) & (~invalid_pixels)
        detected_water_pixels = int(np.sum(valid_det_water))
        permanent_water_pixels = int(np.sum(valid_perm_water))
        new_flood_water_pixels = int(np.sum(flood_mask == 1))

        flood_fraction = (
            round(float(new_flood_water_pixels / valid_pixels), 6) if valid_pixels > 0 else 0.0
        )

        transform_tuple = None
        if transform is not None:
            if hasattr(transform, "to_gdal"):
                transform_tuple = tuple(transform.to_gdal())
            elif isinstance(transform, (tuple, list)):
                transform_tuple = tuple(transform)

        if metadata is None:
            metadata = RasterMetadata(
                scene_id=scene_id,
                crs="UNKNOWN",
                bbox=RasterBoundingBox(min_lon=0.0, min_lat=0.0, max_lon=0.0, max_lat=0.0),
                width_px=det_arr.shape[1],
                height_px=det_arr.shape[0],
                resolution_meters=10.0,
            )

        perm_uint8 = np.zeros(perm_arr.shape, dtype=np.uint8)
        perm_uint8[valid_perm_water] = 1

        return PotentialFloodWaterResult(
            scene_id=scene_id,
            metadata=metadata,
            flood_water_mask=flood_mask,
            permanent_water_mask=perm_uint8,
            total_pixels=total_pixels,
            valid_pixels=valid_pixels,
            nodata_pixels=nodata_count,
            detected_water_pixels=detected_water_pixels,
            permanent_water_pixels=permanent_water_pixels,
            new_flood_water_pixels=new_flood_water_pixels,
            flood_fraction=flood_fraction,
            transform=transform_tuple,
        )

    def apply_mask(
        self,
        detected_water_mask: Any,
        mask_config: PermanentWaterMaskConfig,
        spatial_bounds: Any = None,
        permanent_water_mask: Optional[Any] = None,
        metadata: Optional[RasterMetadata] = None,
    ) -> Any:
        """Subtract permanent water bodies from detected water mask adhering to BasePermanentWaterMasker contract."""
        if permanent_water_mask is None:
            if mask_config.mask_identifier and os.path.exists(mask_config.mask_identifier):
                result = self.mask_permanent_water(
                    detected_water=detected_water_mask,
                    permanent_water=mask_config.mask_identifier,
                    metadata=metadata,
                    config=mask_config,
                )
                return result.flood_water_mask
            else:
                raise ValueError(
                    "Permanent water mask array or valid mask_identifier file path must be provided."
                )

        if isinstance(detected_water_mask, SurfaceWaterMaskResult) or metadata is not None:
            result = self.mask_permanent_water(
                detected_water=detected_water_mask,
                permanent_water=permanent_water_mask,
                metadata=metadata,
                config=mask_config,
            )
            return result.flood_water_mask
        else:
            return self.compute_new_flood_water(detected_water_mask, permanent_water_mask)


# Alias for backward and forward compatibility
BaselinePermanentWaterMasker = PermanentWaterMasker


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


class FloodExtentAnalyzer(BaseFloodExtentAnalyzer):
    """Concrete statistical flood extent analyzer calculating surface inundation metrics.

    Scientific & Operational Rationale:
        Quantifies surface water extent from binary raster masks using the source raster's
        spatial pixel resolution. Differentiates net new/ephemeral flood inundation from baseline
        permanent water bodies.

    Guarantees:
        - Rejects invalid/empty masks or negative spatial resolutions with descriptive ValueError.
        - Calculates area deterministically from pixel counts and ground-sampling distance (GSD).
        - Area unit for FloodExtentMetrics is strictly square kilometers (sq km).
        - Correctly returns 0.0 metrics for all-zero masks.
    """

    def calculate_metrics(
        self,
        flood_water_mask: Any,
        pixel_resolution_m: float,
        permanent_water_mask: Optional[Any] = None,
        affected_zones: Optional[List[str]] = None,
    ) -> FloodExtentMetrics:
        """Compute square kilometer flood areas and spatial statistics from pixel masks."""
        flood_arr = np.asarray(flood_water_mask)
        if flood_arr.ndim == 3 and flood_arr.shape[0] == 1:
            flood_arr = flood_arr[0]

        if flood_arr.ndim != 2:
            raise ValueError(f"Expected 2D flood water mask, but received array with ndim={flood_arr.ndim}.")

        if flood_arr.size == 0:
            raise ValueError("Flood water mask cannot be empty.")

        if pixel_resolution_m <= 0.0:
            raise ValueError(f"Pixel resolution must be positive, but received {pixel_resolution_m} meters.")

        # Pixel area in square kilometers: (meters^2) / 1,000,000
        pixel_area_sq_km = (float(pixel_resolution_m) ** 2) / 1_000_000.0

        # Filter out NaN/invalid from count
        valid_flood = (flood_arr == 1)
        if np.issubdtype(flood_arr.dtype, np.floating):
            valid_flood &= ~np.isnan(flood_arr) & ~np.isinf(flood_arr)

        flood_pixel_count = int(np.sum(valid_flood))
        flood_extent_sq_km = round(float(flood_pixel_count * pixel_area_sq_km), 6)

        if permanent_water_mask is not None:
            perm_arr = np.asarray(permanent_water_mask)
            if perm_arr.ndim == 3 and perm_arr.shape[0] == 1:
                perm_arr = perm_arr[0]

            if perm_arr.shape != flood_arr.shape:
                raise ValueError(
                    f"Mask shape mismatch: flood water {flood_arr.shape} != permanent water {perm_arr.shape}."
                )

            valid_perm = (perm_arr == 1)
            if np.issubdtype(perm_arr.dtype, np.floating):
                valid_perm &= ~np.isnan(perm_arr) & ~np.isinf(perm_arr)

            perm_pixel_count = int(np.sum(valid_perm))
            perm_extent_sq_km = round(float(perm_pixel_count * pixel_area_sq_km), 6)
            total_extent_sq_km = round(float((flood_pixel_count + perm_pixel_count) * pixel_area_sq_km), 6)
        else:
            perm_extent_sq_km = 0.0
            total_extent_sq_km = flood_extent_sq_km

        return FloodExtentMetrics(
            total_water_area_sq_km=total_extent_sq_km,
            permanent_water_area_sq_km=perm_extent_sq_km,
            flood_extent_sq_km=flood_extent_sq_km,
            affected_zones=affected_zones or [],
        )


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


class GeoJSONFloodExporter(BaseGeoJSONExporter):
    """Concrete raster-to-vector polygonizer converting binary flood masks into RFC 7946 GeoJSON.

    Scientific & Operational Rationale:
        Vectorizes contiguous flood pixel clusters into geographic polygon geometries while
        strictly preserving the raster's affine transformation and Coordinate Reference System (CRS).
        Provides polygon cleaning, small-region noise filtering, and deterministic region metrics.

    Geographic Area Calculation:
        - For projected CRS (e.g. UTM Zone 43N / EPSG:32643), area is calculated in planar square units (m² / km²).
        - For geographic CRS (e.g. WGS84 / EPSG:4326), geodesic ellipsoidal area is computed using pyproj.Geod
          to ensure degree² is NEVER falsely reported as square meters.

    Guarantees:
        - Disconnected flood regions are extracted as separate polygon features.
        - All-zero masks cleanly return an empty GeoJSON FeatureCollection with zero features.
        - Generated polygons are valid shapely geometries (closed linear rings conforming to RFC 7946).
        - Small-region noise filtering is explicitly configurable via FloodExtentExtractionConfig.
        - Rejects non-2D arrays, empty masks, or mismatched metadata shapes with informative ValueErrors.
    """

    def _resolve_affine_transform(
        self,
        metadata: RasterMetadata,
        transform: Optional[Any] = None,
    ) -> Affine:
        """Resolve or reconstruct affine transform from transform tuple/Affine or metadata bounding box."""
        if transform is not None:
            if isinstance(transform, Affine):
                return transform
            if hasattr(transform, "to_gdal"):
                return Affine.from_gdal(*transform.to_gdal())
            if isinstance(transform, (tuple, list)):
                if len(transform) == 6:
                    try:
                        # Test if tuple is in GDAL format (c, a, b, f, d, e)
                        return Affine.from_gdal(*transform)
                    except Exception:
                        return Affine(*transform)
                elif len(transform) == 9:
                    return Affine(*transform[:6])

        # Derive affine transform from bounding box and pixel dimensions
        if metadata.bbox is not None and metadata.width_px > 0 and metadata.height_px > 0:
            return rasterio.transform.from_bounds(
                metadata.bbox.min_lon,
                metadata.bbox.min_lat,
                metadata.bbox.max_lon,
                metadata.bbox.max_lat,
                metadata.width_px,
                metadata.height_px,
            )

        raise ValueError(
            f"Cannot resolve affine transform: neither transform nor valid metadata bounding box was provided."
        )

    def _compute_polygon_area_m2(
        self,
        polygon: Any,
        crs_str: str,
        resolution_meters: float,
    ) -> float:
        """Compute true geodesic or planar area in square meters for a Shapely polygon."""
        if polygon is None or polygon.is_empty:
            return 0.0

        try:
            crs_obj = pyproj.CRS.from_user_input(crs_str)
            if crs_obj.is_geographic or crs_str.upper() in ("EPSG:4326", "OGC:CRS84", "WGS84"):
                geod = pyproj.Geod(ellps="WGS84")
                area_m2, _ = geod.geometry_area_perimeter(polygon)
                return abs(float(area_m2))
            else:
                # Projected CRS: polygon.area is in linear CRS units (m^2 for standard projected systems)
                return abs(float(polygon.area))
        except Exception:
            # Fallback for unknown / unparseable CRS: use polygon area or pixel-based estimate
            return abs(float(polygon.area))

    def export_geojson(
        self,
        flood_water_mask: Any,
        metadata: RasterMetadata,
        transform: Optional[Any] = None,
        config: Optional[FloodExtentExtractionConfig] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> GeoJSONFeatureCollection:
        """Convert binary flood raster mask into RFC 7946 GeoJSON FeatureCollection."""
        if config is None:
            config = FloodExtentExtractionConfig()

        if metadata is None:
            raise ValueError("RasterMetadata is required for GeoJSON export.")

        if not metadata.crs:
            raise ValueError("Raster metadata must include a valid CRS string.")

        if metadata.width_px <= 0 or metadata.height_px <= 0:
            raise ValueError(
                f"Invalid raster dimensions in metadata: width={metadata.width_px}, height={metadata.height_px}."
            )

        if metadata.resolution_meters <= 0.0:
            raise ValueError(f"Raster resolution must be positive, received {metadata.resolution_meters}m.")

        flood_arr = np.asarray(flood_water_mask)
        if flood_arr.ndim == 3 and flood_arr.shape[0] == 1:
            flood_arr = flood_arr[0]

        if flood_arr.ndim != 2:
            raise ValueError(f"Expected 2D flood water mask, but received array with ndim={flood_arr.ndim}.")

        if flood_arr.size == 0:
            raise ValueError("Flood water mask cannot be empty.")

        if flood_arr.shape != (metadata.height_px, metadata.width_px):
            raise ValueError(
                f"Mask shape {flood_arr.shape} does not match metadata dimensions "
                f"({metadata.height_px}, {metadata.width_px})."
            )

        # Handle all-zero mask cleanly
        if np.sum(flood_arr == 1) == 0:
            return GeoJSONFeatureCollection(type="FeatureCollection", features=[], bbox=None)

        aff = self._resolve_affine_transform(metadata, transform)
        connectivity = config.connectivity if config.connectivity in (4, 8) else 8

        # Binary uint8 mask for rasterio shapes
        bin_mask = (flood_arr == 1).astype(np.uint8)

        shapes_gen = rasterio.features.shapes(
            bin_mask,
            mask=(bin_mask == 1),
            transform=aff,
            connectivity=connectivity,
        )

        features: List[GeoJSONFeature] = []
        all_shapely_polygons: List[Any] = []
        region_counter = 0

        for geom_dict, val in shapes_gen:
            if val != 1:
                continue

            try:
                poly = shapely.geometry.shape(geom_dict)
            except Exception:
                continue

            if not poly.is_valid:
                poly = shapely.validation.make_valid(poly)

            if poly.is_empty:
                continue

            # Extract individual polygons from MultiPolygon / GeometryCollection
            if poly.geom_type == "Polygon":
                poly_parts = [poly]
            elif poly.geom_type in ("MultiPolygon", "GeometryCollection"):
                poly_parts = [p for p in poly.geoms if p.geom_type == "Polygon" and not p.is_empty and p.area > 0]
            else:
                continue

            for p in poly_parts:
                # Count exact flood pixels within this polygon boundary
                try:
                    p_mask = rasterio.features.geometry_mask(
                        [p],
                        out_shape=flood_arr.shape,
                        transform=aff,
                        invert=True,
                    )
                    poly_px_count = int(np.sum((flood_arr == 1) & p_mask))
                except Exception:
                    poly_px_count = 1

                if poly_px_count == 0:
                    continue

                # Configurable small-region filtering
                if poly_px_count < config.min_pixel_cluster_size:
                    continue

                # Geometry simplification if requested
                if config.simplify_tolerance is not None and config.simplify_tolerance > 0.0:
                    p_simplified = p.simplify(config.simplify_tolerance, preserve_topology=True)
                    if not p_simplified.is_valid:
                        p_simplified = shapely.validation.make_valid(p_simplified)
                    if not p_simplified.is_empty and p_simplified.geom_type == "Polygon":
                        p = p_simplified

                # Compute area
                area_m2 = self._compute_polygon_area_m2(p, metadata.crs, metadata.resolution_meters)
                if config.area_unit == "sq_km":
                    poly_area = round(float(area_m2 / 1_000_000.0), 6)
                    area_unit_str = "sq_km"
                else:
                    poly_area = round(float(area_m2), 2)
                    area_unit_str = "sq_m"

                region_counter += 1
                region_id = f"region_{region_counter}"

                feature_props: Dict[str, Any] = {
                    "region_id": region_id,
                    "flooded_pixel_count": poly_px_count,
                    "area": poly_area,
                    "area_unit": area_unit_str,
                }
                if properties:
                    for k, v in properties.items():
                        if k not in feature_props:
                            feature_props[k] = v

                # Convert coordinates to GeoJSON schema
                geo_mapping = shapely.geometry.mapping(p)
                geojson_geom = GeoJSONGeometry(
                    type=p.geom_type,
                    coordinates=geo_mapping["coordinates"],
                )
                feature = GeoJSONFeature(
                    type="Feature",
                    geometry=geojson_geom,
                    properties=feature_props,
                )
                features.append(feature)
                all_shapely_polygons.append(p)

        # Compute overall bounding box of extracted features
        fc_bbox: Optional[List[float]] = None
        if all_shapely_polygons:
            min_x = min(p.bounds[0] for p in all_shapely_polygons)
            min_y = min(p.bounds[1] for p in all_shapely_polygons)
            max_x = max(p.bounds[2] for p in all_shapely_polygons)
            max_y = max(p.bounds[3] for p in all_shapely_polygons)
            fc_bbox = [round(min_x, 6), round(min_y, 6), round(max_x, 6), round(max_y, 6)]

        return GeoJSONFeatureCollection(
            type="FeatureCollection",
            features=features,
            bbox=fc_bbox,
        )


class FloodExtentExtractor:
    """End-to-end service combining statistical analysis and vector polygon extraction for flood extents.

    Orchestrates:
        1. BaseGeoJSONExporter (vectorization & polygonization)
        2. BaseFloodExtentAnalyzer (quantitative flood statistics)
        3. Packaging into typed FloodExtentResult & FloodExtentResponse
    """

    def __init__(
        self,
        analyzer: Optional[BaseFloodExtentAnalyzer] = None,
        exporter: Optional[BaseGeoJSONExporter] = None,
    ):
        self.analyzer = analyzer or FloodExtentAnalyzer()
        self.exporter = exporter or GeoJSONFloodExporter()

    def extract_flood_extent(
        self,
        flood_input: Union[PotentialFloodWaterResult, SurfaceWaterMaskResult, np.ndarray],
        metadata: Optional[RasterMetadata] = None,
        permanent_water_mask: Optional[np.ndarray] = None,
        transform: Optional[Any] = None,
        config: Optional[FloodExtentExtractionConfig] = None,
        affected_zones: Optional[List[str]] = None,
    ) -> FloodExtentResult:
        """Extract flood extent polygons and calculate quantitative metrics."""
        if config is None:
            config = FloodExtentExtractionConfig()

        if isinstance(flood_input, PotentialFloodWaterResult):
            flood_mask = flood_input.flood_water_mask
            scene_id = flood_input.scene_id
            meta = metadata or flood_input.metadata
            tf = transform or flood_input.transform
            perm_mask = permanent_water_mask if permanent_water_mask is not None else flood_input.permanent_water_mask
        elif isinstance(flood_input, SurfaceWaterMaskResult):
            flood_mask = flood_input.water_mask
            scene_id = flood_input.scene_id
            meta = metadata or flood_input.metadata
            tf = transform or flood_input.transform
            perm_mask = permanent_water_mask
        else:
            flood_mask = flood_input
            if metadata is None:
                raise ValueError("RasterMetadata must be provided when flood_input is a raw numpy array.")
            scene_id = metadata.scene_id
            meta = metadata
            tf = transform
            perm_mask = permanent_water_mask

        # Generate GeoJSON vector features
        geojson_fc = self.exporter.export_geojson(
            flood_water_mask=flood_mask,
            metadata=meta,
            transform=tf,
            config=config,
        )

        # Calculate quantitative statistical metrics
        metrics = self.analyzer.calculate_metrics(
            flood_water_mask=flood_mask,
            pixel_resolution_m=meta.resolution_meters,
            permanent_water_mask=perm_mask,
            affected_zones=affected_zones,
        )

        # Compute totals from extracted features
        polygon_count = len(geojson_fc.features)
        flooded_pixel_count = sum(f.properties.get("flooded_pixel_count", 0) for f in geojson_fc.features)
        flooded_area = round(sum(f.properties.get("area", 0.0) for f in geojson_fc.features), 6)

        now_iso = datetime.now(timezone.utc).isoformat()

        return FloodExtentResult(
            scene_id=scene_id,
            metadata=meta,
            flooded_pixel_count=flooded_pixel_count,
            polygon_count=polygon_count,
            flooded_area=flooded_area,
            area_unit=config.area_unit,
            bbox=geojson_fc.bbox,
            crs=meta.crs,
            resolution_meters=meta.resolution_meters,
            geojson=geojson_fc,
            metrics=metrics,
            timestamp=now_iso,
        )


# Aliases for flexibility and naming consistency
FloodExtentVectorExporter = GeoJSONFloodExporter
FloodExtentDeriver = FloodExtentExtractor


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
        flood_extractor: Optional[FloodExtentExtractor] = None,
    ):
        self.raster_processor = raster_processor
        self.water_detector = water_detector
        self.permanent_masker = permanent_masker
        self.flood_analyzer = flood_analyzer
        self.geojson_exporter = geojson_exporter
        self.flood_extractor = flood_extractor or FloodExtentExtractor(
            analyzer=flood_analyzer,
            exporter=geojson_exporter,
        )

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
        water_config: Optional[WaterDetectionConfig] = None,
        mask_config: Optional[PermanentWaterMaskConfig] = None,
        extraction_config: Optional[FloodExtentExtractionConfig] = None,
    ) -> FloodExtentResponse:
        """Execute the full 5-stage flood pipeline from satellite image to FloodExtentResponse.

        Raises:
            NotImplementedError: If any pipeline stage component has not been injected.
            FileNotFoundError: If the satellite image source path cannot be found.
        """
        readiness = self.validate_pipeline_readiness()
        unconfigured = [stage for stage, ready in readiness.items() if not ready]
        if unconfigured:
            raise NotImplementedError(
                f"Flood detection pipeline foundation established, but active providers for {unconfigured} "
                "are pending integration of GIS data/libraries in subsequent steps."
            )

        if water_config is None:
            water_config = WaterDetectionConfig()
        if mask_config is None:
            mask_config = PermanentWaterMaskConfig()
        if extraction_config is None:
            extraction_config = FloodExtentExtractionConfig()

        # 1. Ingest raster metadata and extract spectral bands
        metadata = self.raster_processor.read_metadata(source_path)
        bands = self.raster_processor.extract_bands(source_path, ["B03", "B08"])

        # 2. Spectral NDWI surface water detection
        surface_water = self.water_detector.detect_water_from_bands(
            band_green=bands["B03"],
            band_nir=bands["B08"],
            metadata=metadata,
            config=water_config,
        )

        # 3. Permanent water masking
        if mask_config.mask_identifier and os.path.exists(mask_config.mask_identifier):
            potential_flood = self.permanent_masker.mask_permanent_water(
                detected_water=surface_water,
                permanent_water=mask_config.mask_identifier,
                metadata=metadata,
                raster_processor=self.raster_processor,
                config=mask_config,
            )
        else:
            # When baseline mask path is not supplied, use zero permanent water
            zero_perm = np.zeros(surface_water.water_mask.shape, dtype=np.uint8)
            potential_flood = self.permanent_masker.mask_permanent_water(
                detected_water=surface_water,
                permanent_water=zero_perm,
                metadata=metadata,
                config=mask_config,
            )

        # 4 & 5. Flood extent extraction, metrics calculation, and GeoJSON export
        extent_result = self.flood_extractor.extract_flood_extent(
            flood_input=potential_flood,
            metadata=metadata,
            config=extraction_config,
        )

        return extent_result.to_response()

