# Satellite Data Repository — CITYSHIELD GIS (RAKSHAK-GEO)

This directory defines the storage architecture and input contract for satellite imagery used in surface water detection and flood extent analysis.

## Pilot Target: Ahmedabad, Gujarat, India
- **Bounding Box (WGS84)**:
  - Western Longitude: `72.45° E`
  - Eastern Longitude: `72.68° E`
  - Southern Latitude: `22.95° N`
  - Northern Latitude: `23.15° N`
- **Recommended Coordinate Systems**:
  - `EPSG:32643` (WGS 84 / UTM Zone 43N) — metric projected coordinate system for area calculations
  - `EPSG:4326` (WGS 84 geographic)

---

## Directory Organization
- `raw/`: Unprocessed satellite granules, multi-band GeoTIFFs, or Sentinel-2 SAFE / band directories as acquired from data providers (Copernicus Browser, USGS EarthExplorer).
- `processed/`: Cropped, radiometrically calibrated, cloud-masked, or reprojected scenes covering the Ahmedabad pilot zones.
- `test/`: Ground-truth reference scenes and benchmark test GeoTIFF chips for pipeline verification.

> [!NOTE]
> Synthetic raster data is strictly restricted to automated unit test memory fixtures. No fake satellite imagery or simulated disaster results are stored in this repository.

---

## Input Contract: Sentinel-2 Optical Workflow

### Required Spectral Bands
For optical surface water detection (NDWI):
1. **Green Band (B03)**:
   - Central Wavelength: ~560 nm
   - Spatial Resolution: 10 meters / pixel
2. **Near-Infrared / NIR Band (B08)**:
   - Central Wavelength: ~842 nm
   - Spatial Resolution: 10 meters / pixel

### Future Index: Normalized Difference Water Index (NDWI)
$$\text{NDWI} = \frac{\text{B03 (Green)} - \text{B08 (NIR)}}{\text{B03 (Green)} + \text{B08 (NIR)}}$$

### Accepted Input Formats
1. **Multi-band GeoTIFF** (`.tif`, `.tiff`):
   - A single georeferenced raster containing at least 2 bands mapped to B03 (Green) and B08 (NIR).
2. **Band Directory**:
   - A directory containing individual single-band GeoTIFFs named by band (e.g., `B03.tif`, `B08.tif` or `B03_10m.tif`, `B08_10m.tif`).

### Mandatory Georeferencing Constraints
- Raster MUST contain valid Coordinate Reference System (CRS) metadata (e.g., EPSG:32643 or EPSG:4326).
- Raster MUST contain a non-degenerate affine transformation matrix mapping pixel coordinates to spatial coordinates.
- Non-georeferenced images (e.g. plain JPEG/PNG or uncalibrated TIFFs) are rejected at ingestion time.
