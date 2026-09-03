"""Unit tests for Phase 1 Step 4: Permanent-Water Masking.

Validates:
1. All detected water is permanent -> zero new / potential flood water.
2. Detected water outside permanent mask -> correctly retained as new flood water.
3. Mixed permanent and new flood water -> only new flood pixels are retained.
4. No detected water -> zero new flood water.
5. Detected water = 0 and permanent water = 1 -> zero new water (baseline not detected as water).
6. Array dimension / shape mismatch -> rejected with clear ValueError.
7. CRS mismatch -> rejected with clear ValueError.
8. Spatial resolution mismatch -> rejected with clear ValueError.
9. Geospatial bounding box mismatch -> rejected with clear ValueError.
10. Affine transform mismatch -> rejected with clear ValueError.
11. Nodata / invalid pixels are handled safely and never classified as flood water.
12. Output metadata and spatial properties are fully preserved in PotentialFloodWaterResult.
13. Binary mask values are strictly restricted to uint8 values 0 and 1.
14. End-to-end integration from NDWI SurfaceWaterMaskResult to PotentialFloodWaterResult.
15. BasePermanentWaterMasker interface and apply_mask contract compliance.
16. GeoTIFF file-based permanent water ingestion via TemporaryDirectory.
17. FloodDetectionPipeline readiness registration with PermanentWaterMasker wired.

IMPORTANT:
Synthetic test arrays are used solely for validating mathematical and spatial logic.
They are NEVER presented as real satellite scenes or real flood outcomes.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_bounds, from_origin

# Ensure backend is in sys.path
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
    PermanentWaterMaskResult,
)
from app.services.flood_service import (
    NDWIWaterDetector,
    PermanentWaterMasker,
    BaselinePermanentWaterMasker,
    GeoTIFFRasterProcessor,
    FloodDetectionPipeline,
)


class TestPermanentWaterMasker(unittest.TestCase):
    """Test suite for permanent-water masking and potential flood derivation."""

    def setUp(self):
        """Set up standard test fixtures and spatial metadata."""
        self.masker = PermanentWaterMasker()
        self.detector = NDWIWaterDetector()

        self.bbox = RasterBoundingBox(
            min_lon=72.50,
            min_lat=22.95,
            max_lon=72.65,
            max_lat=23.10,
        )
        self.meta = RasterMetadata(
            scene_id="TEST_S2A_AHMEDABAD_SUBSET",
            sensor="Sentinel-2",
            crs="EPSG:32643",
            bbox=self.bbox,
            width_px=4,
            height_px=4,
            resolution_meters=10.0,
            available_bands=["B03", "B08"],
        )

    def test_all_detected_water_is_permanent(self):
        """When all detected water coincides with permanent water, new flood water must be zero."""
        # 4x4 raster where center 2x2 is water in both detected and permanent masks
        detected = np.array([
            [0, 0, 0, 0],
            [0, 1, 1, 0],
            [0, 1, 1, 0],
            [0, 0, 0, 0],
        ], dtype=np.uint8)

        permanent = np.array([
            [0, 0, 0, 0],
            [0, 1, 1, 0],
            [0, 1, 1, 0],
            [0, 0, 0, 0],
        ], dtype=np.uint8)

        result = self.masker.mask_permanent_water(
            detected_water=detected,
            permanent_water=permanent,
            metadata=self.meta,
        )

        self.assertIsInstance(result, PotentialFloodWaterResult)
        self.assertEqual(result.detected_water_pixels, 4)
        self.assertEqual(result.permanent_water_pixels, 4)
        self.assertEqual(result.new_flood_water_pixels, 0)
        self.assertEqual(result.flood_fraction, 0.0)
        self.assertTrue(np.all(result.flood_water_mask == 0))

    def test_detected_water_outside_permanent_mask_retained(self):
        """Detected water outside baseline permanent bodies must be retained as potential flood water."""
        detected = np.array([
            [1, 1, 0, 0],
            [1, 1, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ], dtype=np.uint8)

        permanent = np.zeros((4, 4), dtype=np.uint8)  # No baseline water

        result = self.masker.mask_permanent_water(
            detected_water=detected,
            permanent_water=permanent,
            metadata=self.meta,
        )

        self.assertEqual(result.detected_water_pixels, 4)
        self.assertEqual(result.permanent_water_pixels, 0)
        self.assertEqual(result.new_flood_water_pixels, 4)
        self.assertEqual(result.flood_fraction, 4 / 16)
        np.testing.assert_array_equal(result.flood_water_mask, detected)

    def test_mixed_permanent_and_new_flood_water(self):
        """Permanent river channel masked out while newly flooded adjacent areas are preserved."""
        # Row 1: River channel (permanent water)
        # Row 2: Overflowing riverbank flood (new water)
        detected = np.array([
            [1, 1, 1, 1],  # River
            [1, 1, 0, 0],  # Flood
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ], dtype=np.uint8)

        permanent = np.array([
            [1, 1, 1, 1],  # Permanent river
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ], dtype=np.uint8)

        result = self.masker.mask_permanent_water(
            detected_water=detected,
            permanent_water=permanent,
            metadata=self.meta,
        )

        expected_flood = np.array([
            [0, 0, 0, 0],
            [1, 1, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ], dtype=np.uint8)

        self.assertEqual(result.detected_water_pixels, 6)
        self.assertEqual(result.permanent_water_pixels, 4)
        self.assertEqual(result.new_flood_water_pixels, 2)
        self.assertAlmostEqual(result.flood_fraction, 2 / 16, places=5)
        np.testing.assert_array_equal(result.flood_water_mask, expected_flood)

    def test_no_detected_water_yields_zero_new_water(self):
        """When no water is detected by NDWI, new flood water must be zero even if permanent water exists."""
        detected = np.zeros((4, 4), dtype=np.uint8)
        permanent = np.array([
            [1, 1, 0, 0],
            [1, 1, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ], dtype=np.uint8)

        result = self.masker.mask_permanent_water(
            detected_water=detected,
            permanent_water=permanent,
            metadata=self.meta,
        )

        self.assertEqual(result.detected_water_pixels, 0)
        self.assertEqual(result.permanent_water_pixels, 4)
        self.assertEqual(result.new_flood_water_pixels, 0)
        self.assertEqual(result.flood_fraction, 0.0)
        self.assertTrue(np.all(result.flood_water_mask == 0))

    def test_dry_permanent_water_not_classified_as_flood(self):
        """Permanent water body that is dry (detected=0, permanent=1) must not be classified as flood."""
        detected = np.array([[0]], dtype=np.uint8)
        permanent = np.array([[1]], dtype=np.uint8)
        flood = self.masker.compute_new_flood_water(detected, permanent)
        self.assertEqual(int(flood[0, 0]), 0)

    def test_mismatched_dimensions_raises_value_error(self):
        """Masks with mismatched shapes must raise ValueError."""
        detected = np.zeros((4, 4), dtype=np.uint8)
        permanent = np.zeros((4, 5), dtype=np.uint8)

        with self.assertRaises(ValueError) as ctx:
            self.masker.mask_permanent_water(detected, permanent, self.meta)
        self.assertIn("shape mismatch", str(ctx.exception).lower())

    def test_mismatched_crs_raises_value_error(self):
        """Masks with mismatched CRS metadata must raise ValueError."""
        detected = np.zeros((4, 4), dtype=np.uint8)
        permanent = np.zeros((4, 4), dtype=np.uint8)

        meta_perm = self.meta.model_copy(update={"crs": "EPSG:4326"})

        with self.assertRaises(ValueError) as ctx:
            self.masker.mask_permanent_water(
                detected,
                permanent,
                metadata=self.meta,
                meta_permanent=meta_perm,
            )
        self.assertIn("crs mismatch", str(ctx.exception).lower())

    def test_mismatched_resolution_raises_value_error(self):
        """Masks with mismatched pixel resolution must raise ValueError."""
        detected = np.zeros((4, 4), dtype=np.uint8)
        permanent = np.zeros((4, 4), dtype=np.uint8)

        meta_perm = self.meta.model_copy(update={"resolution_meters": 20.0})

        with self.assertRaises(ValueError) as ctx:
            self.masker.mask_permanent_water(
                detected,
                permanent,
                metadata=self.meta,
                meta_permanent=meta_perm,
            )
        self.assertIn("resolution mismatch", str(ctx.exception).lower())

    def test_mismatched_bounding_box_raises_value_error(self):
        """Masks with non-overlapping / mismatched bounding boxes must raise ValueError."""
        detected = np.zeros((4, 4), dtype=np.uint8)
        permanent = np.zeros((4, 4), dtype=np.uint8)

        shifted_bbox = RasterBoundingBox(
            min_lon=73.50,
            min_lat=23.95,
            max_lon=73.65,
            max_lat=24.10,
        )
        meta_perm = self.meta.model_copy(update={"bbox": shifted_bbox})

        with self.assertRaises(ValueError) as ctx:
            self.masker.mask_permanent_water(
                detected,
                permanent,
                metadata=self.meta,
                meta_permanent=meta_perm,
            )
        self.assertIn("bounding box mismatch", str(ctx.exception).lower())

    def test_mismatched_affine_transform_raises_value_error(self):
        """Masks with different affine transforms must raise ValueError."""
        detected = np.zeros((4, 4), dtype=np.uint8)
        permanent = np.zeros((4, 4), dtype=np.uint8)

        t1 = (10.0, 0.0, 1000.0, 0.0, -10.0, 2000.0)
        t2 = (10.0, 0.0, 5000.0, 0.0, -10.0, 8000.0)

        with self.assertRaises(ValueError) as ctx:
            self.masker.mask_permanent_water(
                detected,
                permanent,
                metadata=self.meta,
                transform=t1,
                transform_permanent=t2,
            )
        self.assertIn("affine transform mismatch", str(ctx.exception).lower())

    def test_nodata_handling_safety(self):
        """Nodata / invalid pixels must be masked out and never become flood water."""
        # Detected has 1s everywhere, but [0,0] and [0,1] are nodata
        detected = np.ones((4, 4), dtype=np.uint8)
        permanent = np.zeros((4, 4), dtype=np.uint8)

        nodata = np.zeros((4, 4), dtype=bool)
        nodata[0, 0] = True
        nodata[0, 1] = True

        result = self.masker.mask_permanent_water(
            detected_water=detected,
            permanent_water=permanent,
            metadata=self.meta,
            nodata_mask=nodata,
        )

        self.assertEqual(result.total_pixels, 16)
        self.assertEqual(result.nodata_pixels, 2)
        self.assertEqual(result.valid_pixels, 14)
        self.assertEqual(result.new_flood_water_pixels, 14)
        self.assertEqual(result.detected_water_pixels, 14)
        self.assertEqual(int(result.flood_water_mask[0, 0]), 0)
        self.assertEqual(int(result.flood_water_mask[0, 1]), 0)
        self.assertEqual(int(result.flood_water_mask[1, 1]), 1)

    def test_nan_float_arrays_safely_masked(self):
        """Floating point arrays containing NaNs in detected or permanent are safely masked out."""
        detected = np.array([
            [1.0, np.nan],
            [1.0, 0.0],
        ], dtype=np.float32)

        permanent = np.array([
            [0.0, 0.0],
            [1.0, np.nan],
        ], dtype=np.float32)

        meta = self.meta.model_copy(update={"width_px": 2, "height_px": 2})
        result = self.masker.mask_permanent_water(detected, permanent, metadata=meta)

        self.assertEqual(result.total_pixels, 4)
        self.assertEqual(result.nodata_pixels, 2)
        self.assertEqual(result.valid_pixels, 2)
        # [0, 0]: detected=1, perm=0 -> flood (1)
        # [1, 0]: detected=1, perm=1 -> permanent (0)
        self.assertEqual(result.new_flood_water_pixels, 1)
        self.assertEqual(int(result.flood_water_mask[0, 0]), 1)
        self.assertEqual(int(result.flood_water_mask[0, 1]), 0)
        self.assertEqual(int(result.flood_water_mask[1, 0]), 0)
        self.assertEqual(int(result.flood_water_mask[1, 1]), 0)

    def test_binary_output_strictly_0_or_1(self):
        """Resulting flood mask must strictly contain only uint8 binary values 0 or 1."""
        h, w = 20, 20
        np.random.seed(42)
        detected = np.random.choice([0, 1], size=(h, w)).astype(np.uint8)
        permanent = np.random.choice([0, 1], size=(h, w)).astype(np.uint8)

        meta = self.meta.model_copy(update={"width_px": w, "height_px": h})
        result = self.masker.mask_permanent_water(detected, permanent, metadata=meta)

        unique_vals = set(np.unique(result.flood_water_mask))
        self.assertTrue(unique_vals.issubset({0, 1}))
        self.assertEqual(result.flood_water_mask.dtype, np.uint8)

    def test_metadata_preservation(self):
        """All spatial metadata fields must be preserved in PotentialFloodWaterResult."""
        detected = np.array([[1, 0], [0, 1]], dtype=np.uint8)
        permanent = np.array([[1, 0], [0, 0]], dtype=np.uint8)
        meta = self.meta.model_copy(update={"width_px": 2, "height_px": 2})

        transform = (10.0, 0.0, 72.5, 0.0, -10.0, 23.1)
        result = self.masker.mask_permanent_water(
            detected, permanent, metadata=meta, transform=transform
        )

        self.assertEqual(result.scene_id, "TEST_S2A_AHMEDABAD_SUBSET")
        self.assertEqual(result.metadata.crs, "EPSG:32643")
        self.assertEqual(result.metadata.resolution_meters, 10.0)
        self.assertEqual(result.metadata.bbox.min_lon, 72.50)
        self.assertEqual(result.transform, transform)
        self.assertEqual(result.total_pixels, 4)
        self.assertEqual(result.valid_pixels, 4)
        self.assertEqual(result.detected_water_pixels, 2)
        self.assertEqual(result.permanent_water_pixels, 1)
        self.assertEqual(result.new_flood_water_pixels, 1)

    def test_end_to_end_from_surface_water_mask_result(self):
        """SurfaceWaterMaskResult from NDWI detector can be fed directly to mask_permanent_water."""
        green = np.array([[0.5, 0.5], [0.1, 0.5]], dtype=np.float32)
        nir = np.array([[0.1, 0.1], [0.5, 0.1]], dtype=np.float32)
        meta = self.meta.model_copy(update={"width_px": 2, "height_px": 2})

        # Step 3: NDWI water detection
        surface_water_res = self.detector.detect_water_from_bands(
            green, nir, meta, config=WaterDetectionConfig(threshold=0.0)
        )
        self.assertEqual(surface_water_res.water_pixels, 3)

        # Step 4: Permanent water masking
        permanent = np.array([[1, 0], [0, 0]], dtype=np.uint8)
        flood_res = self.masker.mask_permanent_water(
            detected_water=surface_water_res,
            permanent_water=permanent,
        )

        self.assertEqual(flood_res.detected_water_pixels, 3)
        self.assertEqual(flood_res.permanent_water_pixels, 1)
        self.assertEqual(flood_res.new_flood_water_pixels, 2)
        self.assertAlmostEqual(flood_res.flood_fraction, 2 / 4, places=5)
        self.assertEqual(int(flood_res.flood_water_mask[0, 0]), 0)  # Permanent water removed
        self.assertEqual(int(flood_res.flood_water_mask[0, 1]), 1)  # Ephemeral flood retained
        self.assertEqual(int(flood_res.flood_water_mask[1, 0]), 0)  # Land remains 0
        self.assertEqual(int(flood_res.flood_water_mask[1, 1]), 1)  # Ephemeral flood retained

    def test_apply_mask_contract_compliance(self):
        """apply_mask method conforms to BasePermanentWaterMasker contract."""
        detected = np.array([[1, 1], [0, 0]], dtype=np.uint8)
        permanent = np.array([[1, 0], [0, 0]], dtype=np.uint8)
        config = PermanentWaterMaskConfig()

        mask = self.masker.apply_mask(
            detected_water_mask=detected,
            mask_config=config,
            permanent_water_mask=permanent,
        )

        expected = np.array([[0, 1], [0, 0]], dtype=np.uint8)
        np.testing.assert_array_equal(mask, expected)

    def test_geotiff_permanent_water_ingestion(self):
        """Consuming a permanent water mask GeoTIFF via file path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tif_path = os.path.join(tmpdir, "permanent_water_ref.tif")
            transform = from_origin(240000.0, 2540000.0, 10.0, 10.0)
            data = np.array([[1, 0], [1, 0]], dtype=np.uint8)

            with rasterio.open(
                tif_path,
                "w",
                driver="GTiff",
                height=2,
                width=2,
                count=1,
                dtype="uint8",
                crs="EPSG:32643",
                transform=transform,
            ) as dst:
                dst.write(data, 1)

            processor = GeoTIFFRasterProcessor()
            meta = processor.read_metadata(tif_path)
            detected = np.array([[1, 1], [1, 0]], dtype=np.uint8)

            result = self.masker.mask_permanent_water(
                detected_water=detected,
                permanent_water=tif_path,
                metadata=meta,
                transform=tuple(transform.to_gdal()),
            )

            self.assertEqual(result.detected_water_pixels, 3)
            self.assertEqual(result.permanent_water_pixels, 2)
            self.assertEqual(result.new_flood_water_pixels, 1)
            # [0, 1] was detected=1 and perm=0 -> flood=1
            self.assertEqual(int(result.flood_water_mask[0, 1]), 1)

    def test_pipeline_integration_readiness(self):
        """Wiring PermanentWaterMasker into FloodDetectionPipeline registers permanent_masker as ready."""
        pipeline = FloodDetectionPipeline(
            raster_processor=GeoTIFFRasterProcessor(),
            water_detector=self.detector,
            permanent_masker=self.masker,
        )
        readiness = pipeline.validate_pipeline_readiness()

        self.assertTrue(readiness["raster_processor"])
        self.assertTrue(readiness["water_detector"])
        self.assertTrue(readiness["permanent_masker"])
        self.assertFalse(readiness["flood_analyzer"])
        self.assertFalse(readiness["geojson_exporter"])


if __name__ == "__main__":
    unittest.main()
