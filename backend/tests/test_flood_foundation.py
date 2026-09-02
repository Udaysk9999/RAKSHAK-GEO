"""Unit tests for Phase 1 Step 1: Satellite & Flood Detection Foundation.

Validates data schemas, contracts, and pipeline interface readiness.
Uses Python's standard unittest framework to execute without external test runners.
"""

import os
import sys
import unittest
from pathlib import Path
from pydantic import ValidationError

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.schemas.flood import (
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
from app.services.flood_service import FloodDetectionPipeline


class TestFloodFoundationSchemas(unittest.TestCase):
    """Test suite for flood detection schema validation."""

    def test_raster_bounding_box_valid(self):
        """Bounding box should accept valid lat/lon coordinates."""
        bbox = RasterBoundingBox(
            min_lon=72.45,
            min_lat=22.95,
            max_lon=72.68,
            max_lat=23.15
        )
        self.assertEqual(bbox.min_lon, 72.45)
        self.assertEqual(bbox.max_lat, 23.15)

    def test_raster_bounding_box_invalid_lat(self):
        """Bounding box should reject latitudes exceeding 90 degrees."""
        with self.assertRaises(ValidationError):
            RasterBoundingBox(
                min_lon=72.45,
                min_lat=-95.0,  # Invalid
                max_lon=72.68,
                max_lat=23.15
            )

    def test_raster_metadata_schema(self):
        """RasterMetadata should store scene properties accurately."""
        meta = RasterMetadata(
            scene_id="S2A_MSIL2A_20260902_AHMEDABAD",
            acquisition_date="2026-09-02T05:30:00Z",
            sensor="Sentinel-2",
            crs="EPSG:4326",
            bbox=RasterBoundingBox(min_lon=72.4, min_lat=22.9, max_lon=72.7, max_lat=23.2),
            width_px=1024,
            height_px=1024,
            resolution_meters=10.0,
            available_bands=["B02_BLUE", "B03_GREEN", "B04_RED", "B08_NIR", "B11_SWIR"]
        )
        self.assertEqual(meta.resolution_meters, 10.0)
        self.assertIn("B03_GREEN", meta.available_bands)

    def test_water_detection_config_defaults(self):
        """Default water detection config should use NDWI with 0.0 threshold."""
        config = WaterDetectionConfig()
        self.assertEqual(config.index_type, SpectralIndexType.NDWI)
        self.assertEqual(config.threshold, 0.0)

    def test_flood_metrics_and_geojson_collection(self):
        """Test GeoJSON FeatureCollection and flood response schema."""
        geom = GeoJSONGeometry(
            type="Polygon",
            coordinates=[[[72.50, 23.00], [72.52, 23.00], [72.52, 23.02], [72.50, 23.02], [72.50, 23.00]]]
        )
        feature = GeoJSONFeature(
            geometry=geom,
            properties={"water_type": "ephemeral_flood", "confidence": 0.92}
        )
        fc = GeoJSONFeatureCollection(features=[feature])
        metrics = FloodExtentMetrics(
            total_water_area_sq_km=14.5,
            permanent_water_area_sq_km=4.2,
            flood_extent_sq_km=10.3,
            affected_zones=["Zone-West", "Zone-Sabarmati"]
        )

        response = FloodExtentResponse(
            scene_id="S2A_TEST_001",
            timestamp="2026-09-02T10:00:00Z",
            metrics=metrics,
            geojson=fc,
            status="SUCCESS"
        )
        self.assertEqual(response.metrics.flood_extent_sq_km, 10.3)
        self.assertEqual(len(response.geojson.features), 1)
        self.assertEqual(response.geojson.features[0].geometry.type, "Polygon")


class TestFloodPipelineInterface(unittest.TestCase):
    """Test suite for pipeline orchestrator contract enforcement."""

    def test_empty_pipeline_reports_unready(self):
        """Unwired pipeline should report all stages as not ready."""
        pipeline = FloodDetectionPipeline()
        readiness = pipeline.validate_pipeline_readiness()
        for stage, ready in readiness.items():
            self.assertFalse(ready, f"Stage {stage} should not be ready without provider")

    def test_unwired_pipeline_raises_not_implemented(self):
        """Executing an unconfigured pipeline should raise NotImplementedError cleanly."""
        pipeline = FloodDetectionPipeline()
        with self.assertRaises(NotImplementedError) as ctx:
            pipeline.execute_pipeline(
                source_path="dummy_satellite.tif",
                water_config=WaterDetectionConfig(),
                mask_config=PermanentWaterMaskConfig(),
            )
        self.assertIn("pending integration", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
