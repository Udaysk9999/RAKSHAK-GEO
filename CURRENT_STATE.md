# CURRENT STATE — CITYSHIELD GIS (RAKSHAK-GEO)

Last updated: September 2, 2026

## Overall Progress

Phase: Phase 1 — Step 4 (Permanent-Water Masking Completed)

Status:
███████░░░ 70%

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
- Phase 1 Step 2, 3 & 4 Satellite, Raster, NDWI & Permanent-Water Masking: **COMPLETED & OPERATIONAL**
  - Implementation:
    - `GeoTIFFRasterProcessor` (`backend/app/services/flood_service.py`): Concrete raster reader using `rasterio` and `pyproj`
    - `NDWIWaterDetector` (`backend/app/services/flood_service.py`): Concrete surface-water detector implementing McFeeters NDWI formula: `(Green - NIR) / (Green + NIR)`
    - `PermanentWaterMasker` (`backend/app/services/flood_service.py`): Concrete permanent-water masker implementing deterministic subtraction: `new_water = detected_water AND NOT permanent_water`
    - `SatelliteSceneContract`, `SurfaceWaterMaskResult` & `PotentialFloodWaterResult` (`backend/app/schemas/flood.py`): Typed Pydantic schemas for input contracts, surface-water detection results, and potential flood results
    - Spatial alignment validation: Rigorous shape, dimensionality, CRS, resolution, transform, and bounding-box validation between detected water and permanent water masks
    - Nodata safety: Nodata/invalid pixels are strictly guarded and never misclassified as flood water
    - Deterministic classification: `detected=1 & permanent=0 -> 1 (flood)`, all other combinations -> `0 (non-flood)`
    - Metadata preservation: Preserves CRS, affine transform, dimensions, bounds, resolution in `PotentialFloodWaterResult`
    - Readiness: `FloodDetectionPipeline` registers `raster_processor`, `water_detector`, and `permanent_masker` as active
  - Limitations & Boundaries:
    - Permanent water baseline is an input dependency (e.g. JRC Global Surface Water or prepared reference GeoTIFF)
    - Optical NDWI can be affected by cloud cover, cloud shadows, and dense terrain shadows
    - This stage identifies new/potential surface water; it does NOT prove structural building damage or destroyed infrastructure
    - No fake satellite imagery or fake flood results are fabricated; test suites utilize transient synthetic numpy/tempfile fixtures exclusively for mathematical and spatial validation
  - Test Suite: 45/45 PASSED across flood modules (`test_flood_foundation.py`, `test_raster_ingestion.py`, `test_ndwi_water_detector.py`, `test_permanent_water_masker.py`), 67/67 repository-wide

### Data & Contracts
- Resource Quantities: ambulances, rescue boats, food packets, medical kits, personnel, custom items
- Synthetic Resources: explicitly tagged as `DEMO DATA`
- Satellite Test Fixtures: strictly ephemeral in-memory/tempfile fixtures for unit tests; no fake imagery stored

## Ready Next Tasks
- **Phase 1 Step 5**: Flood Extent Derivation & Statistics (`BaseFloodExtentAnalyzer`)
- **Phase 1 Step 6**: GeoJSON Vector Export (`BaseGeoJSONExporter`)
- **T-016**: Add Future Response Gap Timeline
- **T-017**: GIS Zone Detail Panel
