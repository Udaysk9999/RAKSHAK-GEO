"""Service layer for Future Response-Gap Timeline foundation (Step 6).

Provides high-integrity time-series construction, chronological ordering,
validation, querying, and filtering for potential/new surface-water flood extent
and response-gap observations.

Architectural and domain constraints:
- Does NOT replace or modify the existing Response Gap Engine.
- Consumes discrete response-gap and flood extent observations when available.
- Deterministic, reproducible ordering and filtering without stochastic methods.
- Does NOT silently fabricate missing observations.
- Uses cautious terminology: potential/new surface-water flood extent, response-gap observation, future response-gap timeline.
"""
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Union

from app.schemas.flood import FloodExtentResult
from app.schemas.optimization import ResourceQuantity
from app.schemas.response_gap_timeline import (
    DuplicateTimestampPolicy,
    ResponseGapTimeline,
    ResponseGapTimelinePoint,
    _normalize_utc_datetime,
)


class FutureResponseGapTimelineService:
    """Service providing core operations for Future Response-Gap Timelines."""

    @classmethod
    def validate_point(
        cls,
        point: Union[ResponseGapTimelinePoint, Dict[str, Any]],
    ) -> ResponseGapTimelinePoint:
        """Validate and return a single ResponseGapTimelinePoint.
        
        Raises ValidationError or ValueError if invariants (non-negative area,
        non-negative gap, valid datetime, explicit units) are violated.
        """
        if isinstance(point, ResponseGapTimelinePoint):
            return point
        elif isinstance(point, dict):
            return ResponseGapTimelinePoint(**point)
        else:
            raise ValueError(
                f"Expected ResponseGapTimelinePoint or dict, got: {type(point)}"
            )

    @classmethod
    def validate_observations(
        cls,
        points: Sequence[Union[ResponseGapTimelinePoint, Dict[str, Any]]],
        reject_duplicates: bool = True,
    ) -> List[ResponseGapTimelinePoint]:
        """Validate a sequence of observation points and optionally reject duplicate timestamps.
        
        Raises ValueError if any point fails validation or if duplicates are found with reject_duplicates=True.
        """
        validated: List[ResponseGapTimelinePoint] = [
            cls.validate_point(pt) for pt in points
        ]

        if reject_duplicates:
            seen_timestamps = set()
            for pt in validated:
                if pt.timestamp in seen_timestamps:
                    raise ValueError(
                        f"Duplicate timestamp detected in observations: {pt.timestamp.isoformat()}"
                    )
                seen_timestamps.add(pt.timestamp)

        return validated

    @classmethod
    def sort_observations(
        cls,
        points: Sequence[ResponseGapTimelinePoint],
    ) -> List[ResponseGapTimelinePoint]:
        """Deterministically sort observations chronologically by timestamp (primary) and source (secondary)."""
        return sorted(points, key=lambda p: (p.timestamp, p.source or ""))

    @classmethod
    def construct_timeline(
        cls,
        points: Sequence[Union[ResponseGapTimelinePoint, Dict[str, Any]]],
        handle_duplicates: Union[str, DuplicateTimestampPolicy] = DuplicateTimestampPolicy.REJECT,
        metadata: Optional[Dict[str, Any]] = None,
        timeline_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> ResponseGapTimeline:
        """Construct a validated, chronologically ordered ResponseGapTimeline from supplied observations.
        
        Duplicate handling:
        - 'reject' (default): raises ValueError if identical timestamps are supplied.
        - 'keep_last': deterministically keeps the latest observation for each timestamp.
        - 'keep_first': deterministically keeps the first observation for each timestamp.
        
        Does not silently fabricate missing observations. An empty sequence produces an empty timeline.
        """
        policy = (
            handle_duplicates
            if isinstance(handle_duplicates, DuplicateTimestampPolicy)
            else DuplicateTimestampPolicy(handle_duplicates)
        )

        # 1. Validate individual points
        raw_validated = [cls.validate_point(pt) for pt in points]

        # 2. Handle duplicates according to policy
        deduped: List[ResponseGapTimelinePoint] = []
        if policy == DuplicateTimestampPolicy.REJECT:
            seen_ts = set()
            for pt in raw_validated:
                if pt.timestamp in seen_ts:
                    raise ValueError(
                        f"Duplicate timestamp detected in observation points: {pt.timestamp.isoformat()}"
                    )
                seen_ts.add(pt.timestamp)
            deduped = raw_validated
        elif policy == DuplicateTimestampPolicy.KEEP_LAST:
            ts_map: Dict[datetime, ResponseGapTimelinePoint] = {}
            for pt in raw_validated:
                ts_map[pt.timestamp] = pt
            deduped = list(ts_map.values())
        elif policy == DuplicateTimestampPolicy.KEEP_FIRST:
            seen_ts = set()
            for pt in raw_validated:
                if pt.timestamp not in seen_ts:
                    deduped.append(pt)
                    seen_ts.add(pt.timestamp)

        # 3. Sort observations deterministically
        sorted_points = cls.sort_observations(deduped)

        # 4. Construct timeline model
        kwargs: Dict[str, Any] = {
            "points": sorted_points,
            "metadata": deepcopy(metadata) if metadata is not None else {},
        }
        if timeline_id:
            kwargs["timeline_id"] = timeline_id
        if description:
            kwargs["description"] = description

        return ResponseGapTimeline(**kwargs)

    @classmethod
    def get_latest_observation(
        cls,
        timeline: ResponseGapTimeline,
    ) -> Optional[ResponseGapTimelinePoint]:
        """Retrieve the latest chronologically ordered observation from the timeline, or None if empty."""
        return timeline.latest_point

    @classmethod
    def get_ordered_series(
        cls,
        timeline: ResponseGapTimeline,
    ) -> List[ResponseGapTimelinePoint]:
        """Retrieve the full chronologically ordered series of observation points."""
        return list(timeline.points)

    @classmethod
    def filter_by_timerange(
        cls,
        timeline: ResponseGapTimeline,
        start: Optional[Union[datetime, str]] = None,
        end: Optional[Union[datetime, str]] = None,
    ) -> ResponseGapTimeline:
        """Filter the timeline by start and/or end datetime (inclusive).
        
        Returns a new ResponseGapTimeline preserving timeline metadata and updating derived boundaries.
        Raises ValueError if start > end.
        """
        start_dt = _normalize_utc_datetime(start) if start is not None else None
        end_dt = _normalize_utc_datetime(end) if end is not None else None

        if start_dt is not None and end_dt is not None and start_dt > end_dt:
            raise ValueError(
                f"Invalid date range: start ({start_dt.isoformat()}) cannot be after end ({end_dt.isoformat()})"
            )

        filtered_points = [
            pt for pt in timeline.points
            if (start_dt is None or pt.timestamp >= start_dt)
            and (end_dt is None or pt.timestamp <= end_dt)
        ]

        return ResponseGapTimeline(
            timeline_id=f"{timeline.timeline_id}-FILTERED",
            points=filtered_points,
            metadata=deepcopy(timeline.metadata),
            description=f"Filtered view of {timeline.timeline_id}",
        )

    @classmethod
    def create_point_from_flood_extent(
        cls,
        flood_result: FloodExtentResult,
        response_gap: Union[float, int, ResourceQuantity, Dict[str, Union[float, int]]],
        response_gap_unit: Optional[str] = None,
        timestamp: Optional[Union[datetime, str]] = None,
        source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ResponseGapTimelinePoint:
        """Convenience method to construct a timeline point directly from a FloodExtentResult."""
        return ResponseGapTimelinePoint.from_flood_extent_result(
            flood_result=flood_result,
            response_gap=response_gap,
            response_gap_unit=response_gap_unit,
            timestamp=timestamp,
            source=source,
            metadata=metadata,
        )

    @classmethod
    def append_observation(
        cls,
        timeline: ResponseGapTimeline,
        point: Union[ResponseGapTimelinePoint, Dict[str, Any]],
        handle_duplicates: Union[str, DuplicateTimestampPolicy] = DuplicateTimestampPolicy.REJECT,
    ) -> ResponseGapTimeline:
        """Append a new observation point to an existing timeline and return an updated timeline."""
        validated_new = cls.validate_point(point)
        current_points = list(timeline.points) + [validated_new]
        return cls.construct_timeline(
            points=current_points,
            handle_duplicates=handle_duplicates,
            metadata=timeline.metadata,
            timeline_id=timeline.timeline_id,
            description=timeline.description,
        )
