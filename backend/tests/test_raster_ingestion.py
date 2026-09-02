"""Unit tests for Phase 1 Step 2: Satellite GeoTIFF Raster Ingestion Foundation.

Validates:
- GeoTIFF metadata extraction (dimensions, resolution, CRS, bounding box)
- Reprojection of projected (UTM Zone 43N Ahmedabad) coordinates to WGS84
- Extraction of required optical bands (B03 Green, B08 NIR) and aliases
- Detection of directory-based band layouts
- Strict rejection of unreferenced rasters
- Clear error handling for missing files and missing bands
- Integration with FloodDetectionPipeline readiness validator

IMPORTANT:
All synthetic raster data in this test suite is generated transiently in-memory / tempfile
strictly for unit testing the raster reader. It is NEVER presented as real satellite imagery
or real flood results.
"""

import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.services.flood_service import (
    GeoTIFFRasterProcessor,
    FloodDetectionPipeline,
)
from app.schemas.flood import SatelliteSceneContract


class TestRasterIngestion(unittest.TestCase):
    """Test suite for GeoTIFF raster ingestion adapter."""

    def setUp(self):
        """Create a temporary directory for synthetic test fixtures."""
        self.temp_dir = tempfile.mkdtemp(prefix="test_satellite_")
        self.processor = GeoTIFFRasterProcessor()

    def tearDown(self):
        """Clean up temporary test directory."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_synthetic_geotiff(
        self,
        filename: str,
        crs: str = "EPSG:4326",
        transform=None,
        width: int = 20,
        height: int = 20,
        num_bands: int = 2,
        band_descriptions=None,
    ) -> str:
        """Helper to create a synthetic georeferenced GeoTIFF for reader testing only."""
        file_path = os.path.join(self.temp_dir, filename)
        if transform is None:
            # Default origin near Ahmedabad in EPSG:4326
            transform = from_origin(72.50, 23.10, 0.001, 0.001)

        data = np.ones((num_bands, height, width), dtype=np.uint16) * 1500

        with rasterio.open(
            file_path,
            "w",
            driver="GTiff",
            height=height,
            width=width,
            count=num_bands,
            dtype=data.dtype,
            crs=crs,
            transform=transform,
        ) as dst:
            dst.write(data)
            if band_descriptions:
                for idx, desc in enumerate(band_descriptions, start=1):
                    dst.set_band_description(idx, desc)

        return file_path

    def test_read_geotiff_metadata_wgs84(self):
        """Test reading metadata from a WGS84 GeoTIFF scene."""
        tif_path = self._create_synthetic_geotiff(
            "synthetic_scene_wgs84.tif",
            crs="EPSG:4326",
            transform=from_origin(72.50, 23.10, 0.001, 0.001),
            width=20,
            height=20,
            num_bands=2,
            band_descriptions=["B03", "B08"],
        )

        meta = self.processor.read_metadata(tif_path)

        self.assertEqual(meta.scene_id, "synthetic_scene_wgs84")
        self.assertEqual(meta.crs, "EPSG:4326")
        self.assertEqual(meta.width_px, 20)
        self.assertEqual(meta.height_px, 20)
        self.assertGreater(meta.resolution_meters, 0.0)
        self.assertAlmostEqual(meta.bbox.min_lon, 72.50, places=3)
        self.assertAlmostEqual(meta.bbox.max_lat, 23.10, places=3)
        self.assertIn("B03", meta.available_bands)
        self.assertIn("B08", meta.available_bands)

    def test_read_geotiff_metadata_utm43n_ahmedabad(self):
        """Test reading projected UTM 43N coordinates (Ahmedabad zone) and WGS84 reprojection."""
        # Coordinates in UTM Zone 43N for Ahmedabad center (~250000m E, 2550000m N)
        utm_transform = from_origin(250000.0, 2550000.0, 10.0, 10.0)
        tif_path = self._create_synthetic_geotiff(
            "synthetic_ahmedabad_utm43n.tif",
            crs="EPSG:32643",
            transform=utm_transform,
            width=30,
            height=30,
            num_bands=2,
            band_descriptions=["B03", "B08"],
        )

        meta = self.processor.read_metadata(tif_path)

        self.assertEqual(meta.crs, "EPSG:32643")
        self.assertEqual(meta.resolution_meters, 10.0)
        self.assertEqual(meta.width_px, 30)
        self.assertEqual(meta.height_px, 30)

        # Reprojected bounding box should be within Ahmedabad geographic extent (~72.5°E, ~23.0°N)
        self.assertGreaterEqual(meta.bbox.min_lon, 72.4)
        self.assertLessEqual(meta.bbox.max_lon, 72.7)
        self.assertGreaterEqual(meta.bbox.min_lat, 22.9)
        self.assertLessEqual(meta.bbox.max_lat, 23.2)

    def test_extract_bands_by_code_and_alias(self):
        """Test extracting bands by Sentinel-2 code ('B03', 'B08') and semantic alias ('GREEN', 'NIR')."""
        tif_path = self._create_synthetic_geotiff(
            "synthetic_spectral.tif",
            crs="EPSG:4326",
            width=10,
            height=10,
            num_bands=2,
            band_descriptions=["B03", "B08"],
        )

        # Extract by code
        bands_by_code = self.processor.extract_bands(tif_path, ["B03", "B08"])
        self.assertIn("B03", bands_by_code)
        self.assertIn("B08", bands_by_code)
        self.assertEqual(bands_by_code["B03"].shape, (10, 10))
        self.assertEqual(bands_by_code["B08"].shape, (10, 10))

        # Extract by alias
        bands_by_alias = self.processor.extract_bands(tif_path, ["GREEN", "NIR"])
        self.assertIn("GREEN", bands_by_alias)
        self.assertIn("NIR", bands_by_alias)
        self.assertEqual(bands_by_alias["GREEN"].shape, (10, 10))
        self.assertEqual(bands_by_alias["NIR"].shape, (10, 10))

    def test_read_and_extract_from_band_directory(self):
        """Test reading a directory of individual band GeoTIFF files."""
        dir_path = os.path.join(self.temp_dir, "S2A_AHMEDABAD_DIR")
        os.makedirs(dir_path, exist_ok=True)

        transform = from_origin(72.52, 23.05, 0.0001, 0.0001)
        data = np.ones((1, 15, 15), dtype=np.uint16) * 1200

        # Create B03.tif and B08.tif in directory
        for b_name in ["B03", "B08"]:
            b_path = os.path.join(dir_path, f"T43QDA_20260902_{b_name}.tif")
            with rasterio.open(
                b_path, "w", driver="GTiff", height=15, width=15, count=1,
                dtype=data.dtype, crs="EPSG:4326", transform=transform
            ) as dst:
                dst.write(data)

        meta = self.processor.read_metadata(dir_path)
        self.assertIn("B03", meta.available_bands)
        self.assertIn("B08", meta.available_bands)

        extracted = self.processor.extract_bands(dir_path, ["B03", "B08"])
        self.assertEqual(extracted["B03"].shape, (15, 15))
        self.assertEqual(extracted["B08"].shape, (15, 15))

    def test_reject_non_georeferenced_raster(self):
        """Rasters missing CRS or having identity transform must be rejected with ValueError."""
        unref_path = os.path.join(self.temp_dir, "unreferenced.tif")
        data = np.ones((1, 10, 10), dtype=np.uint8) * 100

        # Write TIFF with no CRS and default identity transform
        with rasterio.open(
            unref_path, "w", driver="GTiff", height=10, width=10, count=1, dtype=data.dtype
        ) as dst:
            dst.write(data)

        with self.assertRaises(ValueError) as ctx:
            self.processor.read_metadata(unref_path)
        self.assertIn("not georeferenced", str(ctx.exception))

    def test_missing_file_raises_filenotfound(self):
        """Non-existent raster path must raise FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            self.processor.read_metadata("non_existent_raster_scene.tif")

        with self.assertRaises(FileNotFoundError):
            self.processor.extract_bands("non_existent_raster_scene.tif", ["B03"])

    def test_missing_band_raises_keyerror(self):
        """Requesting unavailable band from raster must raise KeyError."""
        tif_path = self._create_synthetic_geotiff(
            "two_band.tif",
            num_bands=2,
            band_descriptions=["B03", "B08"],
        )
        with self.assertRaises(KeyError) as ctx:
            self.processor.extract_bands(tif_path, ["B12_SWIR"])
        self.assertIn("B12_SWIR", str(ctx.exception))

    def test_pipeline_wiring_with_raster_processor(self):
        """Wiring GeoTIFFRasterProcessor into FloodDetectionPipeline must register raster_processor as ready."""
        pipeline = FloodDetectionPipeline(raster_processor=self.processor)
        readiness = pipeline.validate_pipeline_readiness()

        self.assertTrue(readiness["raster_processor"])
        self.assertFalse(readiness["water_detector"])
        self.assertFalse(readiness["permanent_masker"])
        self.assertFalse(readiness["flood_analyzer"])
        self.assertFalse(readiness["geojson_exporter"])

    def test_satellite_scene_contract_schema(self):
        """Validate SatelliteSceneContract schema attributes."""
        contract = SatelliteSceneContract(
            scene_path="data/satellite/raw/ahmedabad_sentinel2_sample.tif",
            pilot_area="Ahmedabad",
            required_bands=["B03", "B08"],
            expected_crs="EPSG:32643",
        )
        self.assertEqual(contract.pilot_area, "Ahmedabad")
        self.assertEqual(contract.required_bands, ["B03", "B08"])
        self.assertEqual(contract.expected_crs, "EPSG:32643")


if __name__ == "__main__":
    unittest.main()
