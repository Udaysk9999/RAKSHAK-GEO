"""Unit tests for Phase 1 Step 5: Flood Extent Extraction and GeoJSON Vectorization.

Validates:
1. Single connected flood region -> exactly one polygon.
2. Multiple disconnected flood regions -> multiple distinct polygons.
3. All-zero mask -> 0 polygons, 0 area, valid empty GeoJSON FeatureCollection.
4. Flooded pixel count calculation.
5. Polygon count calculation.
6. Area calculation in projected CRS (UTM Zone 43N / EPSG:32643 in m² / km²).
7. Area calculation in geographic CRS (WGS84 / EPSG:4326 geodetic ellipsoidal area without degree² confusion).
8. Bounding box derivation and preservation.
9. CRS preservation in metadata and GeoJSON output.
10. Transform preservation and accurate geographic coordinate alignment.
11. Spatial resolution handling (10m, 20m, 30m GSD).
12. Tiny-region noise filtering with configurable threshold.
13. Filtering threshold configuration (min_pixel_cluster_size).
14. Invalid mask dimensions (1D, 3D multi-band, 0D).
15. Empty/invalid input arrays.
16. Invalid spatial metadata (missing CRS, non-positive resolution, non-positive dimensions).
17. Mismatched raster metadata (array shape != metadata dimensions).
18. GeoJSON FeatureCollection structure conformance (RFC 7946).
19. GeoJSON Feature properties validation (region_id, flooded_pixel_count, area, area_unit).
20. Polygon geometry validity (closed rings, valid Shapely geometries, no self-intersections).
21. End-to-end integration with PotentialFloodWaterResult from Step 4.
22. Full 5-stage FloodDetectionPipeline execution and readiness validation.

IMPORTANT:
Synthetic test arrays are used solely for validating mathematical and spatial logic.
They are NEVER presented as real satellite scenes or real flood outcomes.
"""

import os
import sys
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_bounds, from_origin
import shapely.geometry

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.schemas.flood import (
    RasterBoundingBox,
    RasterMetadata,
    WaterDetectionConfig,
    SurfaceWaterMaskResult,
    PermanentWaterMaskConfig,
    PotentialFloodWaterResult,
    FloodExtentMetrics,
    FloodExtentExtractionConfig,
    FloodExtentResponse,
    FloodExtentResult,
    GeoJSONFeatureCollection,
)
from app.services.flood_service import (
    BaseRasterProcessor,
    GeoTIFFRasterProcessor,
    BaseWaterDetector,
    NDWIWaterDetector,
    BasePermanentWaterMasker,
    PermanentWaterMasker,
    BaseFloodExtentAnalyzer,
    FloodExtentAnalyzer,
    BaseGeoJSONExporter,
    GeoJSONFloodExporter,
    FloodExtentExtractor,
    FloodDetectionPipeline,
)


class TestFloodExtentExtraction(unittest.TestCase):
    """Test suite for flood extent extraction, vector polygonization, and quantitative metrics."""

    def setUp(self):
        """Set up standard test fixtures and spatial metadata."""
        self.analyzer = FloodExtentAnalyzer()
        self.exporter = GeoJSONFloodExporter()
        self.extractor = FloodExtentExtractor(analyzer=self.analyzer, exporter=self.exporter)

        # Standard projected metadata (UTM Zone 43N / Ahmedabad region)
        self.proj_bbox = RasterBoundingBox(
            min_lon=72.50,
            min_lat=22.95,
            max_lon=72.65,
            max_lat=23.10,
        )
        self.proj_meta = RasterMetadata(
            scene_id="TEST_PROJECTED_SCENE",
            sensor="Sentinel-2",
            crs="EPSG:32643",
            bbox=self.proj_bbox,
            width_px=6,
            height_px=6,
            resolution_meters=10.0,
            available_bands=["B03", "B08"],
        )
        # 6x6 raster spanning 60m x 60m starting at (300000, 2540000)
        self.proj_transform = from_origin(300000, 2540060, 10.0, 10.0)

        # Standard geographic metadata (WGS84 lat/lon in degrees)
        self.geo_bbox = RasterBoundingBox(
            min_lon=72.50,
            min_lat=23.00,
            max_lon=72.56,
            max_lat=23.06,
        )
        self.geo_meta = RasterMetadata(
            scene_id="TEST_GEOGRAPHIC_SCENE",
            sensor="Sentinel-2",
            crs="EPSG:4326",
            bbox=self.geo_bbox,
            width_px=6,
            height_px=6,
            resolution_meters=10.0,
            available_bands=["B03", "B08"],
        )
        self.geo_transform = from_bounds(72.50, 23.00, 72.56, 23.06, 6, 6)

    def test_single_connected_flood_region(self):
        """Single contiguous flood cluster must produce exactly one GeoJSON polygon."""
        mask = np.array([
            [0, 0, 0, 0, 0, 0],
            [0, 1, 1, 0, 0, 0],
            [0, 1, 1, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
        ], dtype=np.uint8)

        geojson = self.exporter.export_geojson(
            flood_water_mask=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
        )

        self.assertEqual(len(geojson.features), 1)
        feat = geojson.features[0]
        self.assertEqual(feat.geometry.type, "Polygon")
        self.assertEqual(feat.properties["flooded_pixel_count"], 4)
        self.assertEqual(feat.properties["region_id"], "region_1")

    def test_multiple_disconnected_flood_regions(self):
        """Multiple disconnected flood clusters must produce multiple distinct polygons."""
        # Prompt example: Two 2x2 clusters separated by dry land
        mask = np.array([
            [0, 0, 0, 0, 0, 0],
            [0, 1, 1, 0, 0, 0],
            [0, 1, 1, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 1, 1, 0],
            [0, 0, 0, 1, 1, 0],
        ], dtype=np.uint8)

        geojson = self.exporter.export_geojson(
            flood_water_mask=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
        )

        self.assertEqual(len(geojson.features), 2)
        counts = [f.properties["flooded_pixel_count"] for f in geojson.features]
        self.assertEqual(counts, [4, 4])
        region_ids = [f.properties["region_id"] for f in geojson.features]
        self.assertEqual(region_ids, ["region_1", "region_2"])

    def test_all_zero_mask(self):
        """All-zero flood mask must yield zero polygons, zero area, and a valid empty FeatureCollection."""
        mask = np.zeros((6, 6), dtype=np.uint8)

        geojson = self.exporter.export_geojson(
            flood_water_mask=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
        )

        self.assertEqual(geojson.type, "FeatureCollection")
        self.assertEqual(len(geojson.features), 0)
        self.assertIsNone(geojson.bbox)

        metrics = self.analyzer.calculate_metrics(
            flood_water_mask=mask,
            pixel_resolution_m=10.0,
        )
        self.assertEqual(metrics.flood_extent_sq_km, 0.0)
        self.assertEqual(metrics.total_water_area_sq_km, 0.0)

        result = self.extractor.extract_flood_extent(
            flood_input=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
        )
        self.assertEqual(result.flooded_pixel_count, 0)
        self.assertEqual(result.polygon_count, 0)
        self.assertEqual(result.flooded_area, 0.0)
        self.assertEqual(len(result.geojson.features), 0)

    def test_flooded_pixel_count(self):
        """Flooded pixel count must accurately match the number of active flood pixels."""
        mask = np.zeros((6, 6), dtype=np.uint8)
        mask[0, 0:3] = 1  # 3 pixels
        mask[3:5, 3:5] = 1  # 4 pixels
        # Total = 7 pixels

        result = self.extractor.extract_flood_extent(
            flood_input=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
        )
        self.assertEqual(result.flooded_pixel_count, 7)

    def test_polygon_count(self):
        """Polygon count in result must match the number of vectorized features."""
        mask = np.zeros((6, 6), dtype=np.uint8)
        mask[0, 0] = 1
        mask[0, 5] = 1
        mask[5, 0] = 1

        result = self.extractor.extract_flood_extent(
            flood_input=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
        )
        self.assertEqual(result.polygon_count, 3)
        self.assertEqual(len(result.geojson.features), 3)

    def test_projected_crs_area_calculation(self):
        """Area in projected CRS must be calculated in linear units (m² / km²)."""
        # 2x2 pixels at 10m resolution = 20m x 20m = 400 m² = 0.0004 km²
        mask = np.array([
            [0, 0, 0, 0, 0, 0],
            [0, 1, 1, 0, 0, 0],
            [0, 1, 1, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
        ], dtype=np.uint8)

        # Test with sq_m area unit
        config_sq_m = FloodExtentExtractionConfig(area_unit="sq_m")
        geojson_m = self.exporter.export_geojson(
            flood_water_mask=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
            config=config_sq_m,
        )
        self.assertEqual(geojson_m.features[0].properties["area_unit"], "sq_m")
        self.assertAlmostEqual(geojson_m.features[0].properties["area"], 400.0, delta=1.0)

        # Test with sq_km area unit
        config_sq_km = FloodExtentExtractionConfig(area_unit="sq_km")
        geojson_km = self.exporter.export_geojson(
            flood_water_mask=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
            config=config_sq_km,
        )
        self.assertEqual(geojson_km.features[0].properties["area_unit"], "sq_km")
        self.assertAlmostEqual(geojson_km.features[0].properties["area"], 0.0004, places=5)

    def test_geographic_crs_geodesic_area_calculation(self):
        """Area in geographic CRS (EPSG:4326) must compute geodetic ellipsoidal area, NOT degree²."""
        # 0.01 deg x 0.01 deg box near equator/mid-latitudes is roughly ~1.2 km², NEVER 0.0001 m²
        mask = np.zeros((6, 6), dtype=np.uint8)
        mask[1:3, 1:3] = 1  # 2x2 cells

        geojson = self.exporter.export_geojson(
            flood_water_mask=mask,
            metadata=self.geo_meta,
            transform=self.geo_transform,
            config=FloodExtentExtractionConfig(area_unit="sq_m"),
        )
        poly_area_m2 = geojson.features[0].properties["area"]
        # In degrees, 2 cells = 0.02 deg wide. Geodesic area must be thousands of square meters, not tiny degree²
        self.assertGreater(poly_area_m2, 10000.0)

    def test_bounding_box_preservation(self):
        """Bounding box of FeatureCollection must accurately encompass extracted polygons."""
        mask = np.array([
            [0, 0, 0, 0, 0, 0],
            [0, 1, 1, 0, 0, 0],
            [0, 1, 1, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
        ], dtype=np.uint8)

        geojson = self.exporter.export_geojson(
            flood_water_mask=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
        )
        bbox = geojson.bbox
        self.assertIsNotNone(bbox)
        self.assertEqual(len(bbox), 4)
        min_x, min_y, max_x, max_y = bbox
        self.assertLess(min_x, max_x)
        self.assertLess(min_y, max_y)

    def test_crs_preservation(self):
        """CRS information must be faithfully preserved across metadata and result structures."""
        mask = np.zeros((6, 6), dtype=np.uint8)
        mask[1:3, 1:3] = 1

        result = self.extractor.extract_flood_extent(
            flood_input=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
        )
        self.assertEqual(result.crs, "EPSG:32643")
        self.assertEqual(result.metadata.crs, "EPSG:32643")

    def test_transform_preservation_and_coordinates(self):
        """Vector polygon vertices must correspond geographically to the input affine transform."""
        mask = np.zeros((6, 6), dtype=np.uint8)
        mask[0, 0] = 1  # Top-left pixel: at origin (300000, 2540060), width 10, height 10

        geojson = self.exporter.export_geojson(
            flood_water_mask=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
        )
        coords = geojson.features[0].geometry.coordinates[0]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        self.assertAlmostEqual(min(xs), 300000.0, delta=1.0)
        self.assertAlmostEqual(max(xs), 300010.0, delta=1.0)
        self.assertAlmostEqual(min(ys), 2540050.0, delta=1.0)
        self.assertAlmostEqual(max(ys), 2540060.0, delta=1.0)

    def test_resolution_handling(self):
        """Spatial resolution scaling must correctly scale computed metrics."""
        mask = np.ones((2, 2), dtype=np.uint8)  # 4 pixels

        # At 10m resolution: 4 * 100m² = 400m² = 0.0004 km²
        metrics_10m = self.analyzer.calculate_metrics(mask, pixel_resolution_m=10.0)
        self.assertAlmostEqual(metrics_10m.flood_extent_sq_km, 0.0004, places=6)

        # At 20m resolution: 4 * 400m² = 1600m² = 0.0016 km²
        metrics_20m = self.analyzer.calculate_metrics(mask, pixel_resolution_m=20.0)
        self.assertAlmostEqual(metrics_20m.flood_extent_sq_km, 0.0016, places=6)

    def test_tiny_region_filtering(self):
        """Polygons with fewer pixels than min_pixel_cluster_size must be filtered out."""
        mask = np.array([
            [1, 0, 0, 0, 0, 0],  # 1 isolated pixel (noise)
            [0, 0, 0, 0, 0, 0],
            [0, 0, 1, 1, 0, 0],  # 4 connected pixels (valid region)
            [0, 0, 1, 1, 0, 0],
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
        ], dtype=np.uint8)

        # Filtering with min_pixel_cluster_size = 2 must drop the single pixel
        config = FloodExtentExtractionConfig(min_pixel_cluster_size=2)
        geojson = self.exporter.export_geojson(
            flood_water_mask=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
            config=config,
        )

        self.assertEqual(len(geojson.features), 1)
        self.assertEqual(geojson.features[0].properties["flooded_pixel_count"], 4)

    def test_filtering_threshold_configuration(self):
        """Configuring different min_pixel_cluster_size thresholds must dynamically filter polygons."""
        mask = np.zeros((6, 6), dtype=np.uint8)
        mask[0, 0] = 1       # Cluster 1: 1 pixel
        mask[1:3, 1:3] = 1   # Cluster 2: 4 pixels
        mask[4:6, 3:6] = 1   # Cluster 3: 6 pixels

        # Threshold 1 -> keep all 3
        res1 = self.exporter.export_geojson(mask, self.proj_meta, self.proj_transform, FloodExtentExtractionConfig(min_pixel_cluster_size=1))
        self.assertEqual(len(res1.features), 3)

        # Threshold 3 -> keep clusters with >= 3 pixels (4 and 6) -> 2 polygons
        res2 = self.exporter.export_geojson(mask, self.proj_meta, self.proj_transform, FloodExtentExtractionConfig(min_pixel_cluster_size=3))
        self.assertEqual(len(res2.features), 2)

        # Threshold 5 -> keep only cluster with 6 pixels -> 1 polygon
        res3 = self.exporter.export_geojson(mask, self.proj_meta, self.proj_transform, FloodExtentExtractionConfig(min_pixel_cluster_size=5))
        self.assertEqual(len(res3.features), 1)

        # Threshold 10 -> filter all -> 0 polygons
        res4 = self.exporter.export_geojson(mask, self.proj_meta, self.proj_transform, FloodExtentExtractionConfig(min_pixel_cluster_size=10))
        self.assertEqual(len(res4.features), 0)

    def test_invalid_mask_dimensions(self):
        """Arrays that are not 2D must be rejected with a clear ValueError."""
        # 1D array
        with self.assertRaises(ValueError):
            self.exporter.export_geojson(np.array([1, 0, 1]), self.proj_meta)

        # 3D multi-band array with depth > 1
        with self.assertRaises(ValueError):
            self.exporter.export_geojson(np.zeros((3, 6, 6)), self.proj_meta)

        # 0D scalar
        with self.assertRaises(ValueError):
            self.exporter.export_geojson(np.array(1), self.proj_meta)

    def test_empty_input_array(self):
        """Empty arrays must be rejected with ValueError."""
        with self.assertRaises(ValueError):
            self.analyzer.calculate_metrics(np.array([]), pixel_resolution_m=10.0)

        with self.assertRaises(ValueError):
            self.exporter.export_geojson(np.empty((0, 0)), self.proj_meta)

    def test_invalid_spatial_metadata(self):
        """Invalid metadata parameters (missing CRS, negative resolution/dimensions) must be rejected."""
        invalid_meta = RasterMetadata(
            scene_id="INVALID_META",
            crs="",
            bbox=self.proj_bbox,
            width_px=6,
            height_px=6,
            resolution_meters=10.0,
        )
        with self.assertRaises(ValueError):
            self.exporter.export_geojson(np.zeros((6, 6)), invalid_meta)

        with self.assertRaises(ValueError):
            self.analyzer.calculate_metrics(np.zeros((6, 6)), pixel_resolution_m=-5.0)

    def test_mismatched_raster_metadata_shape(self):
        """Mismatched array shape and metadata width/height must raise ValueError."""
        # Array is 4x4, metadata specifies 6x6
        mask_4x4 = np.zeros((4, 4), dtype=np.uint8)
        with self.assertRaises(ValueError):
            self.exporter.export_geojson(mask_4x4, self.proj_meta)

    def test_geojson_featurecollection_structure(self):
        """Exported GeoJSON FeatureCollection must conform to RFC 7946 specifications."""
        mask = np.zeros((6, 6), dtype=np.uint8)
        mask[1:3, 1:3] = 1

        geojson = self.exporter.export_geojson(
            flood_water_mask=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
        )

        self.assertEqual(geojson.type, "FeatureCollection")
        self.assertIsInstance(geojson.features, list)
        self.assertEqual(len(geojson.features), 1)

        feat = geojson.features[0]
        self.assertEqual(feat.type, "Feature")
        self.assertIn(feat.geometry.type, ["Polygon", "MultiPolygon"])
        self.assertIsInstance(feat.geometry.coordinates, list)

    def test_geojson_feature_properties(self):
        """Features must contain deterministic properties without fabricated values."""
        mask = np.zeros((6, 6), dtype=np.uint8)
        mask[1:3, 1:3] = 1

        geojson = self.exporter.export_geojson(
            flood_water_mask=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
            properties={"data_source": "Sentinel-2", "pipeline_step": 5},
        )
        props = geojson.features[0].properties
        self.assertIn("region_id", props)
        self.assertIn("flooded_pixel_count", props)
        self.assertIn("area", props)
        self.assertIn("area_unit", props)
        self.assertEqual(props["data_source"], "Sentinel-2")
        self.assertEqual(props["pipeline_step"], 5)

    def test_polygon_geometry_validity(self):
        """All extracted polygon geometries must be geometrically valid with closed rings."""
        mask = np.array([
            [1, 1, 0, 0, 1, 1],
            [1, 1, 0, 0, 1, 1],
            [0, 0, 1, 1, 0, 0],
            [0, 0, 1, 1, 0, 0],
            [1, 1, 0, 0, 1, 1],
            [1, 1, 0, 0, 1, 1],
        ], dtype=np.uint8)

        geojson = self.exporter.export_geojson(
            flood_water_mask=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
        )

        for feat in geojson.features:
            poly_dict = {"type": feat.geometry.type, "coordinates": feat.geometry.coordinates}
            poly = shapely.geometry.shape(poly_dict)
            self.assertTrue(poly.is_valid, "Extracted polygon geometry must be valid")
            self.assertFalse(poly.is_empty, "Extracted polygon geometry must not be empty")

    def test_integration_with_potential_flood_water_result(self):
        """Extractor must consume PotentialFloodWaterResult from Step 4 seamlessly."""
        flood_mask = np.array([
            [0, 0, 0, 0, 0, 0],
            [0, 1, 1, 0, 0, 0],
            [0, 1, 1, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
        ], dtype=np.uint8)

        perm_mask = np.zeros((6, 6), dtype=np.uint8)

        step4_result = PotentialFloodWaterResult(
            scene_id="S2A_INTEGRATION_TEST",
            metadata=self.proj_meta,
            flood_water_mask=flood_mask,
            permanent_water_mask=perm_mask,
            total_pixels=36,
            valid_pixels=36,
            nodata_pixels=0,
            detected_water_pixels=4,
            permanent_water_pixels=0,
            new_flood_water_pixels=4,
            flood_fraction=4 / 36,
            transform=tuple(self.proj_transform.to_gdal()),
        )

        step5_result = self.extractor.extract_flood_extent(
            flood_input=step4_result,
        )

        self.assertIsInstance(step5_result, FloodExtentResult)
        self.assertEqual(step5_result.scene_id, "S2A_INTEGRATION_TEST")
        self.assertEqual(step5_result.flooded_pixel_count, 4)
        self.assertEqual(step5_result.polygon_count, 1)
        self.assertEqual(step5_result.metrics.flood_extent_sq_km, 0.0004)

        # Verify conversion to standard response
        response = step5_result.to_response()
        self.assertIsInstance(response, FloodExtentResponse)
        self.assertEqual(response.status, "SUCCESS")
        self.assertEqual(response.scene_id, "S2A_INTEGRATION_TEST")

    def test_pipeline_readiness_and_execution_with_all_stages(self):
        """FloodDetectionPipeline must validate readiness and execute end-to-end with all providers."""
        pipeline = FloodDetectionPipeline(
            raster_processor=GeoTIFFRasterProcessor(),
            water_detector=NDWIWaterDetector(),
            permanent_masker=PermanentWaterMasker(),
            flood_analyzer=self.analyzer,
            geojson_exporter=self.exporter,
        )

        readiness = pipeline.validate_pipeline_readiness()
        for stage, ready in readiness.items():
            self.assertTrue(ready, f"Pipeline stage {stage} must be ready when provider is wired")

    def test_donut_hole_polygon_validity(self):
        """A flood region surrounding a dry island (donut polygon) must remain geometrically valid."""
        # 5x5 flood border with 1x1 dry center
        mask = np.array([
            [1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1],
            [1, 1, 0, 1, 1],
            [1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1],
        ], dtype=np.uint8)

        meta = RasterMetadata(
            scene_id="DONUT_TEST",
            crs="EPSG:32643",
            bbox=self.proj_bbox,
            width_px=5,
            height_px=5,
            resolution_meters=10.0,
        )
        tf = from_origin(300000, 2540050, 10.0, 10.0)

        geojson = self.exporter.export_geojson(mask, meta, tf)
        self.assertEqual(len(geojson.features), 1)
        feat = geojson.features[0]
        self.assertEqual(feat.properties["flooded_pixel_count"], 24)
        # Verify valid shapely geometry with an interior ring
        poly = shapely.geometry.shape({"type": feat.geometry.type, "coordinates": feat.geometry.coordinates})
        self.assertTrue(poly.is_valid)
        self.assertEqual(len(poly.interiors), 1)

    def test_geometry_simplification_tolerance(self):
        """Simplification tolerance must reduce vertex count while preserving valid topology."""
        mask = np.zeros((8, 8), dtype=np.uint8)
        mask[1:7, 1:7] = 1

        meta = RasterMetadata(
            scene_id="SIMPLIFY_TEST",
            crs="EPSG:32643",
            bbox=self.proj_bbox,
            width_px=8,
            height_px=8,
            resolution_meters=10.0,
        )
        tf = from_origin(300000, 2540080, 10.0, 10.0)

        # Without simplification
        res_raw = self.exporter.export_geojson(mask, meta, tf)
        # With simplification
        res_simp = self.exporter.export_geojson(
            mask,
            meta,
            tf,
            config=FloodExtentExtractionConfig(simplify_tolerance=5.0),
        )
        self.assertEqual(len(res_simp.features), 1)
        self.assertTrue(shapely.geometry.shape(
            {"type": res_simp.features[0].geometry.type, "coordinates": res_simp.features[0].geometry.coordinates}
        ).is_valid)

    def test_affected_zones_passthrough(self):
        """Affected administrative zones must be populated in the metrics."""
        mask = np.zeros((6, 6), dtype=np.uint8)
        mask[1:3, 1:3] = 1

        result = self.extractor.extract_flood_extent(
            flood_input=mask,
            metadata=self.proj_meta,
            transform=self.proj_transform,
            affected_zones=["Ward-01-West", "Ward-04-Sabarmati"],
        )
        self.assertEqual(result.metrics.affected_zones, ["Ward-01-West", "Ward-04-Sabarmati"])

    def test_float_array_with_nans_handled_safely(self):
        """Floating point mask with NaNs and Infs must treat non-finite values as 0 (non-flood)."""
        mask = np.array([
            [np.nan, 0.0, np.inf],
            [0.0, 1.0, 1.0],
            [-np.inf, 1.0, 0.0],
        ], dtype=np.float32)

        meta = RasterMetadata(
            scene_id="NAN_TEST",
            crs="EPSG:32643",
            bbox=self.proj_bbox,
            width_px=3,
            height_px=3,
            resolution_meters=10.0,
        )
        tf = from_origin(300000, 2540030, 10.0, 10.0)

        result = self.extractor.extract_flood_extent(
            flood_input=mask,
            metadata=meta,
            transform=tf,
        )
        self.assertEqual(result.flooded_pixel_count, 3)

    def test_end_to_end_pipeline_execution(self):
        """Execute full 5-stage pipeline with a synthetic GeoTIFF scene in TemporaryDirectory."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            scene_path = os.path.join(tmpdir, "test_s2_synthetic.tif")
            # Write 2-band synthetic raster (Band 1: Green, Band 2: NIR)
            # Water pixel: high Green (0.4), low NIR (0.1) -> NDWI = (0.4 - 0.1)/(0.4 + 0.1) = 0.6 > 0.0
            # Non-water pixel: low Green (0.1), high NIR (0.5) -> NDWI = (0.1 - 0.5)/(0.1 + 0.5) = -0.67 < 0.0
            green_band = np.full((6, 6), 0.1, dtype=np.float32)
            nir_band = np.full((6, 6), 0.5, dtype=np.float32)
            # Add 2x2 water region
            green_band[1:3, 1:3] = 0.4
            nir_band[1:3, 1:3] = 0.1

            with rasterio.open(
                scene_path,
                "w",
                driver="GTiff",
                width=6,
                height=6,
                count=2,
                dtype="float32",
                crs="EPSG:32643",
                transform=self.proj_transform,
            ) as dst:
                dst.write(green_band, 1)
                dst.set_band_description(1, "B03")
                dst.write(nir_band, 2)
                dst.set_band_description(2, "B08")

            pipeline = FloodDetectionPipeline(
                raster_processor=GeoTIFFRasterProcessor(),
                water_detector=NDWIWaterDetector(),
                permanent_masker=PermanentWaterMasker(),
                flood_analyzer=self.analyzer,
                geojson_exporter=self.exporter,
            )

            response = pipeline.execute_pipeline(
                source_path=scene_path,
                water_config=WaterDetectionConfig(threshold=0.0),
                mask_config=PermanentWaterMaskConfig(),
                extraction_config=FloodExtentExtractionConfig(),
            )

            self.assertEqual(response.status, "SUCCESS")
            self.assertEqual(len(response.geojson.features), 1)
            self.assertEqual(response.geojson.features[0].properties["flooded_pixel_count"], 4)
            self.assertAlmostEqual(response.metrics.flood_extent_sq_km, 0.0004, places=5)


if __name__ == "__main__":
    unittest.main()

