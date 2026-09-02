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
- Phase 1 Step 2 & 3 Satellite, Raster & NDWI Foundation: **COMPLETED & OPERATIONAL**
  - Implementation:
    - `GeoTIFFRasterProcessor` (`backend/app/services/flood_service.py`): Concrete raster reader using `rasterio` and `pyproj`
    - `NDWIWaterDetector` (`backend/app/services/flood_service.py`): Concrete surface-water detector implementing McFeeters NDWI formula: `(Green - NIR) / (Green + NIR)`
    - `SatelliteSceneContract` & `SurfaceWaterMaskResult` (`backend/app/schemas/flood.py`): Typed Pydantic schemas for input contracts and water-mask results
    - Band validation: Rigorous shape, dimensionality, CRS, resolution, and bounding-box alignment validation between B03 and B08
    - Division-by-zero safety: Zero-denominator pixels guarded and set to NaN without runtime exceptions
    - Nodata safety: Nodata pixels strictly masked out (never classified as water)
    - Deterministic classification: `NDWI >= threshold -> 1 (water)`, `NDWI < threshold -> 0 (non-water)`
    - Metadata preservation: Preserves CRS, affine transform, dimensions, bounds, resolution in `SurfaceWaterMaskResult`
    - Step 3 Boundary: Pure surface-water mask; permanent-water subtraction is strictly deferred to Step 4
  - Test Suite: 27/27 PASSED across flood modules (`test_flood_foundation.py`, `test_raster_ingestion.py`, `test_ndwi_water_detector.py`), 49/49 repository-wide

### Data & Contracts
- Resource Quantities: ambulances, rescue boats, food packets, medical kits, personnel, custom items
- Synthetic Resources: explicitly tagged as `DEMO DATA`
- Satellite Test Fixtures: strictly ephemeral in-memory/tempfile fixtures for unit tests; no fake imagery stored

## Ready Next Tasks
- **Phase 1 Step 4**: Implement Permanent-Water Masking (`BasePermanentWaterMasker`) to isolate flood water from baseline water bodies
- **T-016**: Add Future Response Gap Timeline
- **T-017**: GIS Zone Detail Panel
