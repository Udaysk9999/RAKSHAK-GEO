-- =============================================================================
-- CITYSHIELD GIS — PostgreSQL / PostGIS Spatial Database Schema
-- Standard: OGC Simple Features Specification (EPSG:4326 WGS84)
-- =============================================================================

-- 1. Enable PostGIS Spatial Extension
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 2. City Metadata Table
CREATE TABLE IF NOT EXISTS cities (
    city_id VARCHAR(50) PRIMARY KEY,
    city_name VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL,
    country VARCHAR(100) NOT NULL DEFAULT 'India',
    crs VARCHAR(20) NOT NULL DEFAULT 'EPSG:4326',
    total_population BIGINT,
    total_area_sq_km NUMERIC(10, 4),
    bbox GEOMETRY(Polygon, 4326),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Dataset Lineage & Provenance Metadata
CREATE TABLE IF NOT EXISTS dataset_sources (
    source_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    license VARCHAR(100) DEFAULT 'Open Data',
    version VARCHAR(20) DEFAULT '1.0.0',
    acquisition_date DATE,
    feature_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Administrative Wards / Zones (Polygons / MultiPolygons)
CREATE TABLE IF NOT EXISTS city_wards (
    zone_id VARCHAR(50) PRIMARY KEY,
    city_id VARCHAR(50) NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    zone_name VARCHAR(150) NOT NULL,
    total_area_sq_km NUMERIC(10, 4),
    population INTEGER DEFAULT 0,
    geom GEOMETRY(MultiPolygon, 4326) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_city_wards_geom ON city_wards USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_city_wards_city_id ON city_wards (city_id);

-- 5. Buildings & Structural Footprints (Polygon / Point)
CREATE TABLE IF NOT EXISTS city_buildings (
    building_id VARCHAR(50) PRIMARY KEY,
    city_id VARCHAR(50) NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    zone_id VARCHAR(50) REFERENCES city_wards(zone_id) ON DELETE SET NULL,
    name VARCHAR(200),
    building_type VARCHAR(50) DEFAULT 'general',
    geom GEOMETRY(Geometry, 4326) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_city_buildings_geom ON city_buildings USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_city_buildings_zone_id ON city_buildings (zone_id);

-- 6. Emergency Medical Facilities / Hospitals (Point / Polygon)
CREATE TABLE IF NOT EXISTS city_hospitals (
    hospital_id VARCHAR(50) PRIMARY KEY,
    city_id VARCHAR(50) NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    zone_id VARCHAR(50) NOT NULL REFERENCES city_wards(zone_id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    bed_capacity INTEGER DEFAULT 50,
    icu_beds INTEGER DEFAULT 10,
    has_emergency_ward BOOLEAN DEFAULT TRUE,
    geom GEOMETRY(Geometry, 4326) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_city_hospitals_geom ON city_hospitals USING GIST (geom);

-- 7. Evacuation Shelters & Relief Camps (Point / Polygon)
CREATE TABLE IF NOT EXISTS city_shelters (
    shelter_id VARCHAR(50) PRIMARY KEY,
    city_id VARCHAR(50) NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    zone_id VARCHAR(50) NOT NULL REFERENCES city_wards(zone_id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    occupancy_capacity INTEGER DEFAULT 500,
    has_generator BOOLEAN DEFAULT TRUE,
    potable_water_liters INTEGER DEFAULT 5000,
    geom GEOMETRY(Geometry, 4326) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_city_shelters_geom ON city_shelters USING GIST (geom);

-- 8. Road Network & Evacuation Corridors (LineString / MultiLineString)
CREATE TABLE IF NOT EXISTS city_roads (
    road_id VARCHAR(50) PRIMARY KEY,
    city_id VARCHAR(50) NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    zone_id VARCHAR(50) REFERENCES city_wards(zone_id) ON DELETE SET NULL,
    name VARCHAR(200),
    road_type VARCHAR(50) DEFAULT 'primary',
    lanes INTEGER DEFAULT 2,
    length_km NUMERIC(8, 3),
    is_evacuation_route BOOLEAN DEFAULT FALSE,
    geom GEOMETRY(MultiLineString, 4326) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_city_roads_geom ON city_roads USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_city_roads_is_evac ON city_roads (is_evacuation_route);

-- 9. Zone Demographic & Census Profiles
CREATE TABLE IF NOT EXISTS zone_demographics (
    zone_id VARCHAR(50) PRIMARY KEY REFERENCES city_wards(zone_id) ON DELETE CASCADE,
    city_id VARCHAR(50) NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    total_population INTEGER NOT NULL,
    elderly_count INTEGER DEFAULT 0,
    children_count INTEGER DEFAULT 0,
    household_count INTEGER DEFAULT 0,
    density_per_sq_km NUMERIC(10, 2),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 10. Emergency Depots & Central Stockpiles
CREATE TABLE IF NOT EXISTS emergency_depots (
    depot_id VARCHAR(50) PRIMARY KEY,
    city_id VARCHAR(50) NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    name VARCHAR(150) NOT NULL,
    ambulances INTEGER DEFAULT 0,
    rescue_boats INTEGER DEFAULT 0,
    food_packets INTEGER DEFAULT 0,
    medical_kits INTEGER DEFAULT 0,
    personnel INTEGER DEFAULT 0,
    geom GEOMETRY(Point, 4326),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
