# CURRENT STATE — CITYSHIELD GIS (RAKSHAK-GEO)

Last updated: September 2, 2026

## Overall Progress

Phase: Phase 1 — Step 4 (T-015 Completed)

Status:
██████░░░░ 60%

## Working / Verified in Repository

### Backend
- FastAPI Core Framework: OPERATIONAL (`backend/app/main.py`)
- Health Check: OPERATIONAL (`GET /api/health`)
- T-014 Resource Optimization API: **COMPLETED & OPERATIONAL**
  - Endpoints: `POST /api/v1/optimization/allocate`, `POST /api/v1/optimization/optimize`, `GET /api/v1/optimization/status`, `GET /api/v1/optimization/sample-payload`
  - Fully tested deterministic multi-criteria allocation solver
- T-015 What-If Simulation Engine: **COMPLETED & OPERATIONAL**
  - Endpoints:
    - `POST /api/v1/what-if/simulate` — Primary What-If scenario simulation endpoint
    - `GET /api/v1/what-if/sample-payload` — Sample reinforcement scenario (`DEMO DATA`)
  - Simulation Features:
    - Reuses T-014 optimization engine directly for baseline and simulated runs
    - Supports available stockpile deltas and overrides
    - Supports zone demand deltas and overrides
    - Supports zone local capacity shifts (clinic destruction/reinforcement)
    - Supports zone priority and severity score modifications
    - Preserves baseline data immutability (`copy.deepcopy`)
    - Enforces all T-014 capacity, demand, and non-negativity invariants
    - Computes granular zone-level and resource-level comparative deltas
    - Evaluates overall fulfillment rate shift and deterministic narrative verdict
  - Test Suite: 22/22 PASSED across all optimization and what-if test suites
- Phase 1 Step 2 Satellite & Raster Foundation: **COMPLETED & OPERATIONAL**
  - Implementation:
    - `GeoTIFFRasterProcessor` (`backend/app/services/flood_service.py`): Concrete raster reader using `rasterio` and `pyproj`
    - `SatelliteSceneContract` (`backend/app/schemas/flood.py`): Input specification schema for optical satellite scenes
    - Georeferencing verification: Mandatory CRS validation & affine transform validation (rejects unreferenced imagery)
    - Multi-band and directory support: Parses multi-band GeoTIFF chips and Sentinel-2 band folders
    - Optical Band Support: Ingests Green (`B03`) and NIR (`B08`) required for NDWI calculation
    - Spatial Extent: Reprojects UTM Zone 43N (Ahmedabad) coordinates to WGS84 bounding box
    - Pipeline wiring: Integrates with `FloodDetectionPipeline` readiness checks
  - Data Structure: `data/satellite/{raw, processed, test}` with `README.md` input specifications
  - Test Suite: 16/16 PASSED across `test_flood_foundation.py` and `test_raster_ingestion.py` (38/38 repository-wide)

### Data & Contracts
- Resource Quantities: ambulances, rescue boats, food packets, medical kits, personnel, custom items
- Synthetic Resources: explicitly tagged as `DEMO DATA`
- Satellite Test Fixtures: strictly ephemeral in-memory/tempfile fixtures for unit tests; no fake imagery stored

## Ready Next Tasks
- **Phase 1 Step 3**: Implement NDWI Surface Water Classification (`BaseWaterDetector`) on extracted B03/B08 bands
- **T-016**: Add Future Response Gap Timeline
- **T-017**: GIS Zone Detail Panel