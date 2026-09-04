"""Focused test suite for Future Response-Gap Timeline foundation (Step 6).

Covers all required validation, ordering, filtering, and integration scenarios:
- valid single observation
- multiple observations
- chronological sorting
- latest observation
- negative flooded area rejection
- negative response gap rejection
- invalid timestamps
- duplicate timestamps (rejection and deterministic resolution)
- empty timeline behavior (no silent fabrication)
- date-range filtering
- metadata and source preservation
- deterministic ordering and output
- integration compatibility with FloodExtentResult
"""
from datetime import datetime, timezone
import unittest
from pydantic import ValidationError

from app.schemas.flood import (
    FloodExtentMetrics,
    FloodExtentResult,
    GeoJSONFeatureCollection,
    RasterBoundingBox,
    RasterMetadata,
)
from app.schemas.optimization import ResourceQuantity
from app.schemas.response_gap_timeline import (
    DuplicateTimestampPolicy,
    ResponseGapTimeline,
    ResponseGapTimelinePoint,
)
from app.services.response_gap_timeline_service import FutureResponseGapTimelineService


class TestResponseGapTimelinePointValidation(unittest.TestCase):
    """Test validation and invariants of ResponseGapTimelinePoint."""

    def test_valid_single_observation(self):
        """Construct a valid single observation point and verify fields."""
        ts = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
        pt = ResponseGapTimelinePoint(
            timestamp=ts,
            flooded_area=12.5,
            flooded_area_unit="sq_km",
            response_gap=45.0,
            response_gap_unit="resource_units",
            source="Sentinel-2",
            metadata={"sensor": "MSI", "orbit": 12},
        )
        self.assertEqual(pt.timestamp, ts)
        self.assertEqual(pt.flooded_area, 12.5)
        self.assertEqual(pt.flooded_area_unit, "sq_km")
        self.assertEqual(pt.response_gap, 45.0)
        self.assertEqual(pt.response_gap_unit, "resource_units")
        self.assertEqual(pt.source, "Sentinel-2")
        self.assertEqual(pt.metadata["sensor"], "MSI")

    def test_valid_observation_with_iso_string_timestamp(self):
        """Construct point using ISO 8601 string, verifying UTC normalization."""
        pt = ResponseGapTimelinePoint(
            timestamp="2026-09-03T14:30:00Z",
            flooded_area=5.2,
            flooded_area_unit="sq_km",
            response_gap=10,
        )
        self.assertIsNotNone(pt.timestamp.tzinfo)
        self.assertEqual(pt.timestamp.year, 2026)
        self.assertEqual(pt.timestamp.month, 9)
        self.assertEqual(pt.timestamp.day, 3)
        self.assertEqual(pt.timestamp.hour, 14)
        self.assertEqual(pt.timestamp.minute, 30)

    def test_valid_observation_with_resource_quantity(self):
        """Allow ResourceQuantity as response_gap."""
        rq = ResourceQuantity(ambulances=5, rescue_boats=3, food_packets=250)
        pt = ResponseGapTimelinePoint(
            timestamp="2026-09-03T12:00:00Z",
            flooded_area=8.0,
            flooded_area_unit="sq_km",
            response_gap=rq,
            response_gap_unit="depot_stockpile",
        )
        self.assertEqual(pt.response_gap.ambulances, 5)
        self.assertEqual(pt.response_gap.rescue_boats, 3)
        self.assertEqual(pt.response_gap.food_packets, 250)

    def test_valid_observation_with_dict_response_gap(self):
        """Allow dictionary as response_gap with non-negative values."""
        gap_dict = {"ambulances": 4, "medical_kits": 120}
        pt = ResponseGapTimelinePoint(
            timestamp="2026-09-03T12:00:00Z",
            flooded_area=3.4,
            flooded_area_unit="sq_km",
            response_gap=gap_dict,
        )
        self.assertEqual(pt.response_gap["ambulances"], 4)
        self.assertEqual(pt.response_gap["medical_kits"], 120)

    def test_negative_flooded_area_rejection(self):
        """Reject negative flooded area values."""
        with self.assertRaises((ValidationError, ValueError)):
            ResponseGapTimelinePoint(
                timestamp="2026-09-03T12:00:00Z",
                flooded_area=-0.5,
                flooded_area_unit="sq_km",
                response_gap=10.0,
            )

    def test_negative_response_gap_rejection_scalar(self):
        """Reject negative scalar response gap values."""
        with self.assertRaises((ValidationError, ValueError)):
            ResponseGapTimelinePoint(
                timestamp="2026-09-03T12:00:00Z",
                flooded_area=5.0,
                flooded_area_unit="sq_km",
                response_gap=-15.0,
            )

    def test_negative_response_gap_rejection_dict(self):
        """Reject dictionary response gap with negative component values."""
        with self.assertRaises((ValidationError, ValueError)):
            ResponseGapTimelinePoint(
                timestamp="2026-09-03T12:00:00Z",
                flooded_area=5.0,
                flooded_area_unit="sq_km",
                response_gap={"rescue_boats": -2, "food_packets": 100},
            )

    def test_invalid_timestamps(self):
        """Reject unparseable or nonsensical timestamps."""
        invalid_ts_values = ["not-a-timestamp", "2026-13-45", "yesterday", 123456]
        for bad_ts in invalid_ts_values:
            with self.assertRaises((ValidationError, ValueError)):
                ResponseGapTimelinePoint(
                    timestamp=bad_ts,
                    flooded_area=2.0,
                    flooded_area_unit="sq_km",
                    response_gap=5.0,
                )

    def test_empty_units_rejection(self):
        """Units must be explicit rather than empty strings."""
        with self.assertRaises((ValidationError, ValueError)):
            ResponseGapTimelinePoint(
                timestamp="2026-09-03T12:00:00Z",
                flooded_area=2.0,
                flooded_area_unit="",  # empty
                response_gap=5.0,
            )

        with self.assertRaises((ValidationError, ValueError)):
            ResponseGapTimelinePoint(
                timestamp="2026-09-03T12:00:00Z",
                flooded_area=2.0,
                flooded_area_unit="   ",  # whitespace only
                response_gap=5.0,
            )

        with self.assertRaises((ValidationError, ValueError)):
            ResponseGapTimelinePoint(
                timestamp="2026-09-03T12:00:00Z",
                flooded_area=2.0,
                flooded_area_unit="sq_km",
                response_gap=5.0,
                response_gap_unit="   ",  # whitespace only
            )

    def test_metadata_and_source_preservation(self):
        """Ensure metadata and source attributes are preserved without alteration."""
        meta = {
            "algorithm": "NDWI_SURFACE_WATER",
            "threshold": 0.05,
            "scene_count": 3,
            "quality_flag": "VALID",
        }
        pt = ResponseGapTimelinePoint(
            timestamp="2026-09-03T12:00:00Z",
            flooded_area=4.5,
            flooded_area_unit="sq_km",
            response_gap=20.0,
            source="Sentinel-2A",
            metadata=meta,
        )
        self.assertEqual(pt.source, "Sentinel-2A")
        self.assertEqual(pt.metadata, meta)


class TestResponseGapTimelineConstruction(unittest.TestCase):
    """Test timeline construction, ordering, retrieval, and edge cases."""

    def setUp(self):
        """Prepare sample observation points across time."""
        self.pt1 = ResponseGapTimelinePoint(
            timestamp="2026-09-01T06:00:00Z",
            flooded_area=3.2,
            flooded_area_unit="sq_km",
            response_gap=15.0,
            source="Sentinel-2",
            metadata={"pass": 1},
        )
        self.pt2 = ResponseGapTimelinePoint(
            timestamp="2026-09-02T06:00:00Z",
            flooded_area=7.8,
            flooded_area_unit="sq_km",
            response_gap=35.0,
            source="Sentinel-2",
            metadata={"pass": 2},
        )
        self.pt3 = ResponseGapTimelinePoint(
            timestamp="2026-09-03T06:00:00Z",
            flooded_area=12.1,
            flooded_area_unit="sq_km",
            response_gap=60.0,
            source="Sentinel-2",
            metadata={"pass": 3},
        )

    def test_multiple_observations(self):
        """Construct timeline with multiple observations and verify summary properties."""
        timeline = FutureResponseGapTimelineService.construct_timeline(
            points=[self.pt1, self.pt2, self.pt3],
            metadata={"mission": "AHMEDABAD_FLOOD_RESPONSE"},
        )
        self.assertEqual(timeline.number_of_observations, 3)
        self.assertFalse(timeline.is_empty)
        self.assertEqual(timeline.start_timestamp, self.pt1.timestamp)
        self.assertEqual(timeline.end_timestamp, self.pt3.timestamp)
        self.assertEqual(timeline.latest_point.timestamp, self.pt3.timestamp)
        self.assertEqual(timeline.metadata["mission"], "AHMEDABAD_FLOOD_RESPONSE")

    def test_chronological_sorting(self):
        """Ensure observations provided in reversed or unordered sequence are sorted chronologically."""
        reversed_points = [self.pt3, self.pt1, self.pt2]
        timeline = FutureResponseGapTimelineService.construct_timeline(points=reversed_points)

        ordered_series = FutureResponseGapTimelineService.get_ordered_series(timeline)
        self.assertEqual(len(ordered_series), 3)
        self.assertEqual(ordered_series[0].timestamp, self.pt1.timestamp)
        self.assertEqual(ordered_series[1].timestamp, self.pt2.timestamp)
        self.assertEqual(ordered_series[2].timestamp, self.pt3.timestamp)
        self.assertEqual(timeline.start_timestamp, self.pt1.timestamp)
        self.assertEqual(timeline.end_timestamp, self.pt3.timestamp)

    def test_latest_observation(self):
        """Retrieve the latest observation from the timeline."""
        timeline = FutureResponseGapTimelineService.construct_timeline(
            points=[self.pt2, self.pt3, self.pt1]
        )
        latest = FutureResponseGapTimelineService.get_latest_observation(timeline)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.timestamp, self.pt3.timestamp)
        self.assertEqual(latest.flooded_area, 12.1)
        self.assertEqual(latest.response_gap, 60.0)

    def test_duplicate_timestamps_rejection(self):
        """Reject duplicate timestamps when duplicate policy is REJECT."""
        pt_dup = ResponseGapTimelinePoint(
            timestamp="2026-09-02T06:00:00Z",  # matches pt2
            flooded_area=9.0,
            flooded_area_unit="sq_km",
            response_gap=40.0,
        )
        with self.assertRaises(ValueError) as ctx:
            FutureResponseGapTimelineService.construct_timeline(
                points=[self.pt1, self.pt2, pt_dup],
                handle_duplicates=DuplicateTimestampPolicy.REJECT,
            )
        self.assertIn("Duplicate timestamp", str(ctx.exception))

    def test_duplicate_timestamps_deterministic_keep_last(self):
        """Deterministically keep the last observation when policy is KEEP_LAST."""
        pt_dup = ResponseGapTimelinePoint(
            timestamp="2026-09-02T06:00:00Z",
            flooded_area=9.0,
            flooded_area_unit="sq_km",
            response_gap=40.0,
            source="Updated-Observation",
        )
        timeline = FutureResponseGapTimelineService.construct_timeline(
            points=[self.pt1, self.pt2, pt_dup],
            handle_duplicates=DuplicateTimestampPolicy.KEEP_LAST,
        )
        self.assertEqual(timeline.number_of_observations, 2)
        # Should keep pt_dup instead of pt2 for 2026-09-02T06:00:00Z
        mid_point = timeline.points[1]
        self.assertEqual(mid_point.flooded_area, 9.0)
        self.assertEqual(mid_point.source, "Updated-Observation")

    def test_duplicate_timestamps_deterministic_keep_first(self):
        """Deterministically keep the first observation when policy is KEEP_FIRST."""
        pt_dup = ResponseGapTimelinePoint(
            timestamp="2026-09-02T06:00:00Z",
            flooded_area=9.0,
            flooded_area_unit="sq_km",
            response_gap=40.0,
            source="Updated-Observation",
        )
        timeline = FutureResponseGapTimelineService.construct_timeline(
            points=[self.pt1, self.pt2, pt_dup],
            handle_duplicates=DuplicateTimestampPolicy.KEEP_FIRST,
        )
        self.assertEqual(timeline.number_of_observations, 2)
        mid_point = timeline.points[1]
        self.assertEqual(mid_point.flooded_area, 7.8)  # pt2 retained
        self.assertEqual(mid_point.source, "Sentinel-2")

    def test_empty_timeline_behavior(self):
        """Handle empty timeline explicitly without fabricating observations."""
        timeline = FutureResponseGapTimelineService.construct_timeline(points=[])
        self.assertTrue(timeline.is_empty)
        self.assertEqual(timeline.number_of_observations, 0)
        self.assertEqual(len(timeline.points), 0)
        self.assertIsNone(timeline.start_timestamp)
        self.assertIsNone(timeline.end_timestamp)
        self.assertIsNone(timeline.latest_point)

        latest = FutureResponseGapTimelineService.get_latest_observation(timeline)
        self.assertIsNone(latest)

        series = FutureResponseGapTimelineService.get_ordered_series(timeline)
        self.assertEqual(series, [])

    def test_append_observation(self):
        """Append a new observation to an existing timeline and verify sorted result."""
        timeline = FutureResponseGapTimelineService.construct_timeline(points=[self.pt1, self.pt3])
        self.assertEqual(timeline.number_of_observations, 2)

        updated = FutureResponseGapTimelineService.append_observation(timeline, self.pt2)
        self.assertEqual(updated.number_of_observations, 3)
        self.assertEqual(updated.points[1].timestamp, self.pt2.timestamp)


class TestResponseGapTimelineFiltering(unittest.TestCase):
    """Test date-range filtering and boundary preservation."""

    def setUp(self):
        """Prepare sample observations."""
        self.points = [
            ResponseGapTimelinePoint(
                timestamp=f"2026-09-0{i}T12:00:00Z",
                flooded_area=float(i * 3),
                flooded_area_unit="sq_km",
                response_gap=float(i * 10),
            )
            for i in range(1, 6)  # Days 1 to 5
        ]
        self.timeline = FutureResponseGapTimelineService.construct_timeline(
            points=self.points,
            metadata={"region": "Ahmedabad_East"},
        )

    def test_date_range_filtering_both_bounds(self):
        """Filter timeline between Day 2 and Day 4 inclusive."""
        filtered = FutureResponseGapTimelineService.filter_by_timerange(
            timeline=self.timeline,
            start="2026-09-02T00:00:00Z",
            end="2026-09-04T23:59:59Z",
        )
        self.assertEqual(filtered.number_of_observations, 3)
        self.assertEqual(filtered.start_timestamp, self.points[1].timestamp)  # Day 2
        self.assertEqual(filtered.end_timestamp, self.points[3].timestamp)    # Day 4
        self.assertEqual(filtered.latest_point.timestamp, self.points[3].timestamp)
        self.assertEqual(filtered.metadata["region"], "Ahmedabad_East")

    def test_date_range_filtering_start_only(self):
        """Filter timeline from Day 3 onwards."""
        filtered = FutureResponseGapTimelineService.filter_by_timerange(
            timeline=self.timeline,
            start="2026-09-03T00:00:00Z",
        )
        self.assertEqual(filtered.number_of_observations, 3)  # Days 3, 4, 5
        self.assertEqual(filtered.start_timestamp, self.points[2].timestamp)

    def test_date_range_filtering_end_only(self):
        """Filter timeline up to Day 2."""
        filtered = FutureResponseGapTimelineService.filter_by_timerange(
            timeline=self.timeline,
            end="2026-09-02T23:59:59Z",
        )
        self.assertEqual(filtered.number_of_observations, 2)  # Days 1, 2
        self.assertEqual(filtered.end_timestamp, self.points[1].timestamp)

    def test_date_range_filtering_no_matches(self):
        """Filter with timerange that matches zero points."""
        filtered = FutureResponseGapTimelineService.filter_by_timerange(
            timeline=self.timeline,
            start="2026-10-01T00:00:00Z",
            end="2026-10-02T00:00:00Z",
        )
        self.assertTrue(filtered.is_empty)
        self.assertEqual(filtered.number_of_observations, 0)
        self.assertIsNone(filtered.start_timestamp)
        self.assertIsNone(filtered.end_timestamp)

    def test_invalid_date_range_rejection(self):
        """Reject date range where start > end."""
        with self.assertRaises(ValueError) as ctx:
            FutureResponseGapTimelineService.filter_by_timerange(
                timeline=self.timeline,
                start="2026-09-05T00:00:00Z",
                end="2026-09-01T00:00:00Z",
            )
        self.assertIn("Invalid date range", str(ctx.exception))


class TestDeterministicOrderingAndOutput(unittest.TestCase):
    """Test deterministic output and absence of silent fabrication."""

    def test_deterministic_ordering_across_permutations(self):
        """Verify identical output regardless of input ordering."""
        p1 = ResponseGapTimelinePoint(
            timestamp="2026-09-01T10:00:00Z",
            flooded_area=2.0,
            flooded_area_unit="sq_km",
            response_gap=10.0,
            source="Source-A",
        )
        p2 = ResponseGapTimelinePoint(
            timestamp="2026-09-02T10:00:00Z",
            flooded_area=4.0,
            flooded_area_unit="sq_km",
            response_gap=20.0,
            source="Source-B",
        )
        p3 = ResponseGapTimelinePoint(
            timestamp="2026-09-03T10:00:00Z",
            flooded_area=6.0,
            flooded_area_unit="sq_km",
            response_gap=30.0,
            source="Source-C",
        )

        perm1 = FutureResponseGapTimelineService.construct_timeline([p1, p2, p3])
        perm2 = FutureResponseGapTimelineService.construct_timeline([p3, p1, p2])
        perm3 = FutureResponseGapTimelineService.construct_timeline([p2, p3, p1])

        self.assertEqual(
            [p.timestamp for p in perm1.points],
            [p.timestamp for p in perm2.points],
        )
        self.assertEqual(
            [p.timestamp for p in perm2.points],
            [p.timestamp for p in perm3.points],
        )
        self.assertEqual(
            [p.flooded_area for p in perm1.points],
            [p.flooded_area for p in perm3.points],
        )

    def test_no_silent_fabrication_of_missing_observations(self):
        """Timeline contains strictly supplied observations without interpolation."""
        p1 = ResponseGapTimelinePoint(
            timestamp="2026-09-01T00:00:00Z",
            flooded_area=1.0,
            flooded_area_unit="sq_km",
            response_gap=5.0,
        )
        p2 = ResponseGapTimelinePoint(
            timestamp="2026-09-05T00:00:00Z",  # 4-day gap
            flooded_area=10.0,
            flooded_area_unit="sq_km",
            response_gap=50.0,
        )
        timeline = FutureResponseGapTimelineService.construct_timeline([p1, p2])
        self.assertEqual(timeline.number_of_observations, 2)
        self.assertEqual(len(timeline.points), 2)
        # Verify no intermediate days were inserted
        self.assertEqual(timeline.points[0].timestamp, p1.timestamp)
        self.assertEqual(timeline.points[1].timestamp, p2.timestamp)


class TestFloodExtentResultIntegration(unittest.TestCase):
    """Test integration compatibility with FloodExtentResult from the flood detection pipeline."""

    def setUp(self):
        """Construct a mock FloodExtentResult matching the pipeline contract."""
        bbox = RasterBoundingBox(min_lon=72.50, min_lat=22.95, max_lon=72.65, max_lat=23.10)
        meta = RasterMetadata(
            scene_id="S2A_MSIL2A_20260903T054641_R120",
            sensor="Sentinel-2",
            crs="EPSG:32643",
            bbox=bbox,
            width_px=100,
            height_px=100,
            resolution_meters=10.0,
            available_bands=["B03", "B08"],
        )
        metrics = FloodExtentMetrics(
            total_water_area_sq_km=0.55,
            permanent_water_area_sq_km=0.10,
            flood_extent_sq_km=0.45,
            affected_zones=["ZONE-AHM-01"],
        )
        self.flood_result = FloodExtentResult(
            scene_id="S2A_MSIL2A_20260903T054641_R120",
            metadata=meta,
            flooded_pixel_count=4500,
            polygon_count=12,
            flooded_area=0.45,
            area_unit="sq_km",
            bbox=[72.50, 22.95, 72.65, 23.10],
            crs="EPSG:32643",
            resolution_meters=10.0,
            geojson=GeoJSONFeatureCollection(type="FeatureCollection", features=[]),
            metrics=metrics,
            timestamp="2026-09-03T05:46:41Z",
        )

    def test_create_point_from_flood_extent_result(self):
        """Construct ResponseGapTimelinePoint directly from FloodExtentResult."""
        point = ResponseGapTimelinePoint.from_flood_extent_result(
            flood_result=self.flood_result,
            response_gap=18.5,
            response_gap_unit="personnel_shortfall",
            metadata={"command_sector": "Sector_4"},
        )
        self.assertEqual(point.timestamp, datetime(2026, 9, 3, 5, 46, 41, tzinfo=timezone.utc))
        self.assertEqual(point.flooded_area, 0.45)
        self.assertEqual(point.flooded_area_unit, "sq_km")
        self.assertEqual(point.response_gap, 18.5)
        self.assertEqual(point.response_gap_unit, "personnel_shortfall")
        self.assertEqual(point.source, "S2A_MSIL2A_20260903T054641_R120")
        self.assertEqual(point.metadata["crs"], "EPSG:32643")
        self.assertEqual(point.metadata["polygon_count"], 12)
        self.assertEqual(point.metadata["command_sector"], "Sector_4")

    def test_service_create_point_from_flood_extent(self):
        """Use service helper method to create a point from FloodExtentResult."""
        point = FutureResponseGapTimelineService.create_point_from_flood_extent(
            flood_result=self.flood_result,
            response_gap=ResourceQuantity(rescue_boats=4, medical_kits=50),
            response_gap_unit="stockpile_deficit",
        )
        self.assertEqual(point.flooded_area, 0.45)
        self.assertEqual(point.response_gap.rescue_boats, 4)
        self.assertEqual(point.response_gap.medical_kits, 50)

    def test_missing_timestamp_on_flood_result_raises_error(self):
        """If no timestamp on FloodExtentResult and none provided, reject without fabricating."""
        bad_result = self.flood_result.model_copy(update={"timestamp": None})
        with self.assertRaises(ValueError) as ctx:
            ResponseGapTimelinePoint.from_flood_extent_result(
                flood_result=bad_result,
                response_gap=10.0,
            )
        self.assertIn("Timestamp must be explicitly provided", str(ctx.exception))

    def test_end_to_end_timeline_from_flood_extent_results(self):
        """Construct complete timeline from multiple FloodExtentResult instances."""
        r1 = self.flood_result.model_copy(update={"timestamp": "2026-09-01T06:00:00Z", "flooded_area": 0.20})
        r2 = self.flood_result.model_copy(update={"timestamp": "2026-09-02T06:00:00Z", "flooded_area": 0.35})
        r3 = self.flood_result.model_copy(update={"timestamp": "2026-09-03T06:00:00Z", "flooded_area": 0.50})

        pt1 = FutureResponseGapTimelineService.create_point_from_flood_extent(r1, response_gap=10.0)
        pt2 = FutureResponseGapTimelineService.create_point_from_flood_extent(r2, response_gap=22.0)
        pt3 = FutureResponseGapTimelineService.create_point_from_flood_extent(r3, response_gap=40.0)

        timeline = FutureResponseGapTimelineService.construct_timeline([pt2, pt3, pt1])
        self.assertEqual(timeline.number_of_observations, 3)
        self.assertEqual(timeline.points[0].flooded_area, 0.20)
        self.assertEqual(timeline.points[1].flooded_area, 0.35)
        self.assertEqual(timeline.points[2].flooded_area, 0.50)
        self.assertEqual(timeline.latest_point.flooded_area, 0.50)
        self.assertEqual(timeline.latest_point.response_gap, 40.0)


if __name__ == "__main__":
    unittest.main()
