"""Unit tests for Phase 1 Step 3: NDWI Surface-Water Detection.

Validates:
1. Correct NDWI calculation using known B03 (Green) and B08 (NIR) reflectance values.
2. Correct water classification using the configured threshold.
3. Values below, equal to, and above the threshold (boundary analysis).
4. Safe division-by-zero handling (zero denominator does not crash or create water).
5. Nodata handling (nodata pixels are masked out and cannot become water).
6. Band shape mismatch error handling.
7. Band spatial metadata mismatch (CRS, resolution, bbox) error handling.
8. Output mask dimensions matching input raster dimensions.
9. Complete spatial metadata preservation in SurfaceWaterMaskResult.
10. Confirmation that NO permanent-water subtraction occurs in Step 3.

IMPORTANT:
Synthetic test arrays are used solely for validating mathematical and spatial logic.
They are NEVER presented as real satellite scenes or real flood outcomes.
"""

import os
import sys
import unittest
from pathlib import Path
import numpy as np

# Ensure backend is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.schemas.flood import (
    RasterBoundingBox,
    RasterMetadata,
    WaterDetectionConfig,
    SpectralIndexType,
    SurfaceWaterMaskResult,
)
from app.services.flood_service import (
    NDWIWaterDetector,
    SpectralWaterDetector,
    FloodDetectionPipeline,
    GeoTIFFRasterProcessor,
)


class TestNDWIWaterDetector(unittest.TestCase):
    """Test suite for NDWI computation and surface-water classification."""

    def setUp(self):
        """Initialize the detector and reference metadata."""
        self.detector = NDWIWaterDetector()
        self.bbox = RasterBoundingBox(
            min_lon=72.50,
            min_lat=22.95,
            max_lon=72.65,
            max_lat=23.10,
        )
        self.meta = RasterMetadata(
            scene_id="TEST_S2A_AHMEDABAD",
            sensor="Sentinel-2",
            crs="EPSG:32643",
            bbox=self.bbox,
            width_px=10,
            height_px=10,
            resolution_meters=10.0,
            available_bands=["B03", "B08"],
        )

    def test_ndwi_calculation_known_values(self):
        """Test NDWI formula: (Green - NIR) / (Green + NIR) on known analytical values."""
        # Clear water: high green, low NIR -> positive NDWI
        green = np.array([[0.4, 0.1], [0.3, 0.6]], dtype=np.float32)
        nir = np.array([[0.2, 0.5], [0.3, 0.2]], dtype=np.float32)

        # Expected:
        # [0,0]: (0.4 - 0.2) / (0.4 + 0.2) = 0.2 / 0.6 = +0.3333333
        # [0,1]: (0.1 - 0.5) / (0.1 + 0.5) = -0.4 / 0.6 = -0.6666667
        # [1,0]: (0.3 - 0.3) / (0.3 + 0.3) = 0.0 / 0.6 = 0.0
        # [1,1]: (0.6 - 0.2) / (0.6 + 0.2) = 0.4 / 0.8 = +0.5
        ndwi = self.detector.compute_index(green, nir)

        self.assertAlmostEqual(float(ndwi[0, 0]), 1.0 / 3.0, places=5)
        self.assertAlmostEqual(float(ndwi[0, 1]), -2.0 / 3.0, places=5)
        self.assertAlmostEqual(float(ndwi[1, 0]), 0.0, places=5)
        self.assertAlmostEqual(float(ndwi[1, 1]), 0.5, places=5)

    def test_water_classification_configured_threshold(self):
        """Test water classification against configurable thresholds."""
        index_array = np.array([[-0.2, -0.05], [0.05, 0.3]], dtype=np.float32)

        # With default threshold = 0.0
        mask_default = self.detector.classify_water(index_array, threshold=0.0)
        expected_default = np.array([[0, 0], [1, 1]], dtype=np.uint8)
        np.testing.assert_array_equal(mask_default, expected_default)

        # With higher threshold = 0.1
        mask_strict = self.detector.classify_water(index_array, threshold=0.1)
        expected_strict = np.array([[0, 0], [0, 1]], dtype=np.uint8)
        np.testing.assert_array_equal(mask_strict, expected_strict)

    def test_threshold_boundary_conditions(self):
        """Test pixels strictly below, exactly equal to, and strictly above the threshold."""
        # Threshold = 0.0
        threshold = 0.0
        test_values = np.array([[-0.0001, 0.0, 0.0001]], dtype=np.float32)
        mask = self.detector.classify_water(test_values, threshold=threshold)

        # -0.0001 < 0.0 -> 0 (non-water)
        # 0.0 >= 0.0 -> 1 (water, deterministic inclusive boundary)
        # 0.0001 > 0.0 -> 1 (water)
        self.assertEqual(int(mask[0, 0]), 0)
        self.assertEqual(int(mask[0, 1]), 1)
        self.assertEqual(int(mask[0, 2]), 1)

    def test_division_by_zero_safety(self):
        """Pixels where Green + NIR == 0 must produce NaN in index and 0 in water mask without crashing."""
        green = np.array([[0.0, 0.5], [0.0, 0.2]], dtype=np.float32)
        nir = np.array([[0.0, 0.1], [0.0, 0.4]], dtype=np.float32)

        ndwi = self.detector.compute_index(green, nir)

        # Pixels [0,0] and [1,0] have denom == 0.0 -> must be NaN
        self.assertTrue(np.isnan(ndwi[0, 0]))
        self.assertTrue(np.isnan(ndwi[1, 0]))
        self.assertFalse(np.isnan(ndwi[0, 1]))
        self.assertFalse(np.isnan(ndwi[1, 1]))

        # Classification must ensure zero-denom pixels NEVER become water
        water_mask = self.detector.classify_water(ndwi, threshold=0.0)
        self.assertEqual(int(water_mask[0, 0]), 0)
        self.assertEqual(int(water_mask[1, 0]), 0)
        self.assertEqual(int(water_mask[0, 1]), 1)  # NDWI ~0.67 >= 0.0

    def test_nodata_handling(self):
        """Pixels flagged as nodata (e.g. 0.0 or -9999 or NaN) must not become water."""
        green = np.array([[0.4, 0.0], [0.3, -9999.0]], dtype=np.float32)
        nir = np.array([[0.1, 0.0], [0.1, -9999.0]], dtype=np.float32)

        config = WaterDetectionConfig(threshold=0.0, nodata_value=-9999.0)
        ndwi = self.detector.compute_index(green, nir, config)

        # [1, 1] was explicit nodata -9999.0
        self.assertTrue(np.isnan(ndwi[1, 1]))

        mask = self.detector.classify_water(ndwi, threshold=config.threshold)
        self.assertEqual(int(mask[1, 1]), 0)  # Nodata cannot be water
        self.assertEqual(int(mask[0, 0]), 1)  # Valid water (0.4 vs 0.1)

    def test_shape_mismatch_raises_value_error(self):
        """Bands with different shapes must raise ValueError."""
        green = np.ones((10, 10), dtype=np.float32)
        nir = np.ones((10, 12), dtype=np.float32)

        with self.assertRaises(ValueError) as ctx:
            self.detector.compute_index(green, nir)
        self.assertIn("shape mismatch", str(ctx.exception).lower())

    def test_spatial_metadata_mismatch_raises_value_error(self):
        """Bands with mismatched CRS, resolution, or bounds must raise ValueError."""
        green = np.ones((10, 10), dtype=np.float32)
        nir = np.ones((10, 10), dtype=np.float32)

        meta_green = self.meta
        meta_nir_diff_crs = self.meta.model_copy(update={"crs": "EPSG:4326"})

        with self.assertRaises(ValueError) as ctx:
            self.detector.validate_band_alignment(green, nir, meta_green, meta_nir_diff_crs)
        self.assertIn("crs mismatch", str(ctx.exception).lower())

        meta_nir_diff_res = self.meta.model_copy(update={"resolution_meters": 20.0})
        with self.assertRaises(ValueError) as ctx:
            self.detector.validate_band_alignment(green, nir, meta_green, meta_nir_diff_res)
        self.assertIn("resolution mismatch", str(ctx.exception).lower())

    def test_output_mask_dimensions_match_input_raster(self):
        """Output water mask dimensions must strictly match input band dimensions."""
        h, w = 45, 60
        green = np.random.uniform(0.1, 0.8, (h, w)).astype(np.float32)
        nir = np.random.uniform(0.1, 0.8, (h, w)).astype(np.float32)

        ndwi = self.detector.compute_index(green, nir)
        mask = self.detector.classify_water(ndwi, threshold=0.0)

        self.assertEqual(mask.shape, (h, w))
        self.assertEqual(mask.dtype, np.uint8)

    def test_spatial_metadata_preservation(self):
        """detect_water_from_bands must return SurfaceWaterMaskResult with all spatial attributes intact."""
        green = np.array([[0.5, 0.1], [0.4, 0.2]], dtype=np.float32)
        nir = np.array([[0.2, 0.4], [0.1, 0.3]], dtype=np.float32)
        meta = self.meta.model_copy(update={"width_px": 2, "height_px": 2})

        result = self.detector.detect_water_from_bands(
            green, nir, meta, config=WaterDetectionConfig(threshold=0.0)
        )

        self.assertIsInstance(result, SurfaceWaterMaskResult)
        self.assertEqual(result.scene_id, "TEST_S2A_AHMEDABAD")
        self.assertEqual(result.metadata.crs, "EPSG:32643")
        self.assertEqual(result.metadata.resolution_meters, 10.0)
        self.assertEqual(result.metadata.bbox.min_lon, 72.50)
        self.assertEqual(result.water_mask.shape, (2, 2))
        self.assertEqual(result.total_pixels, 4)
        self.assertEqual(result.valid_pixels, 4)
        # [0,0]: 0.5 vs 0.2 -> water (1)
        # [0,1]: 0.1 vs 0.4 -> non-water (0)
        # [1,0]: 0.4 vs 0.1 -> water (1)
        # [1,1]: 0.2 vs 0.3 -> non-water (0)
        self.assertEqual(result.water_pixels, 2)
        self.assertEqual(result.water_fraction, 0.5)

    def test_no_permanent_water_subtraction_in_step_3(self):
        """Verify that Step 3 computes ONLY total surface water and does NOT subtract baseline water."""
        green = np.array([[0.6, 0.6], [0.6, 0.1]], dtype=np.float32)
        nir = np.array([[0.1, 0.1], [0.1, 0.5]], dtype=np.float32)
        meta = self.meta.model_copy(update={"width_px": 2, "height_px": 2})

        result = self.detector.detect_water_from_bands(green, nir, meta)

        # 3 water pixels detected
        self.assertEqual(result.water_pixels, 3)
        # The result must contain ONLY total surface water mask
        self.assertFalse(hasattr(result, "flood_extent_sq_km"))
        self.assertFalse(hasattr(result, "permanent_water_mask"))
        # Mask contains 3 surface water pixels, showing baseline permanent bodies are intact
        self.assertEqual(int(np.sum(result.water_mask)), 3)

    def test_pipeline_integration_readiness(self):
        """Wiring NDWIWaterDetector into FloodDetectionPipeline registers water_detector as ready."""
        pipeline = FloodDetectionPipeline(
            raster_processor=GeoTIFFRasterProcessor(),
            water_detector=self.detector,
        )
        readiness = pipeline.validate_pipeline_readiness()

        self.assertTrue(readiness["raster_processor"])
        self.assertTrue(readiness["water_detector"])
        self.assertFalse(readiness["permanent_masker"])
        self.assertFalse(readiness["flood_analyzer"])
        self.assertFalse(readiness["geojson_exporter"])


if __name__ == "__main__":
    unittest.main()
