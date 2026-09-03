# City Spatial Datasets Directory (`data/city/`)

This directory is designated for municipal and urban GIS datasets ingested into CITYSHIELD GIS.

## Directory Layout
```
data/city/
├── raw/            # Ingested unprocessed shapefiles, GeoJSON, OSM extracts, or DXF files
├── processed/      # Validated, topology-checked, and GeoPackage/GeoJSON spatial layers
└── test/           # Ephemeral synthetic DEMO/TEST fixtures for automated testing
```

## Spatial Data Invariants
1. **Coordinate Reference System (CRS)**: All vector layers MUST be projected or transformed to **WGS 84 (EPSG:4326)** prior to ingestion.
2. **Standard Layer Types**:
   - `wards`: Municipal ward and administrative zone boundaries (Polygon / MultiPolygon)
   - `buildings`: Footprints of residential, commercial, and civic structures (Polygon / Point)
   - `hospitals`: Healthcare and trauma facilities (Point / Polygon)
   - `shelters`: Designated disaster relief camps and emergency shelters (Point / Polygon)
   - `roads`: Evacuation routes and major transport corridors (LineString / MultiLineString)
   - `demographics`: Ward-level population, household, and vulnerability census records
3. **Data Provenance**:
   - Every ingested dataset must be registered in the `dataset_sources` database table with its license, acquisition timestamp, and provider details.
4. **Synthetic Data Rule**:
   - In accordance with `agent.md`, all synthetic, sample, or integration test geometries must be explicitly labeled `DEMO DATA` or `TEST DATA`.
