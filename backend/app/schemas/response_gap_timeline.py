"""Data models and schemas for Future Response-Gap Timeline foundation (Step 6).

Provides a clean, deterministic, time-series foundation representing how
potential/new surface-water flood extent and response-gap observations evolve
across multiple observation timestamps.

Scientific and domain constraints:
- Flood detection represents potential/new surface-water flood extent, NOT structural building damage.
- Observations represent discrete historical or projected response-gap observations.
- Does NOT claim to predict real future disaster conditions without external validated forecasting data.
- Does NOT silently fabricate missing observations.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Union
from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.flood import FloodExtentResult
from app.schemas.optimization import ResourceQuantity


class DuplicateTimestampPolicy(str, Enum):
    """Deterministic resolution policy for duplicate observation timestamps."""
    REJECT = "reject"
    KEEP_LAST = "keep_last"
    KEEP_FIRST = "keep_first"


def _normalize_utc_datetime(v: Any) -> datetime:
    """Normalize input into a timezone-aware UTC datetime."""
    if isinstance(v, str):
        cleaned = v.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(cleaned)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid timestamp format: '{v}'. Expected valid ISO 8601 string.") from e
    elif isinstance(v, datetime):
        dt = v
    else:
        raise ValueError(f"Invalid timestamp type: {type(v)}. Must be an ISO 8601 string or datetime.")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


class ResponseGapTimelinePoint(BaseModel):
    """A discrete observation point combining flood extent metrics and response-gap indicators."""
    timestamp: datetime = Field(
        ...,
        description="Observation timestamp normalized to timezone-aware UTC"
    )
    flooded_area: float = Field(
        ...,
        ge=0.0,
        description="Potential/new surface-water flood extent area (must be >= 0.0)"
    )
    flooded_area_unit: str = Field(
        ...,
        description="Explicit measurement unit for flooded_area, e.g. 'sq_km' or 'sq_m'"
    )
    response_gap: Union[float, int, ResourceQuantity, Dict[str, Union[float, int]]] = Field(
        ...,
        description="Observed or calculated response-gap indicator (must be non-negative)"
    )
    response_gap_unit: Optional[str] = Field(
        default=None,
        description="Explicit unit for response_gap (e.g. 'resource_units', 'composite_index', 'shortfall')"
    )
    source: Optional[str] = Field(
        default=None,
        description="Observation data source or sensor identifier (e.g. 'Sentinel-2', 'ground_survey')"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Preserved provenance, spatial attributes, or processing metadata"
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_timestamp(cls, v: Any) -> datetime:
        """Validate and normalize timestamp to UTC datetime."""
        return _normalize_utc_datetime(v)

    @field_validator("flooded_area")
    @classmethod
    def validate_flooded_area(cls, v: float) -> float:
        """Ensure flooded_area is strictly non-negative."""
        if v < 0.0:
            raise ValueError(f"flooded_area must not be negative. Received: {v}")
        return float(v)

    @field_validator("flooded_area_unit")
    @classmethod
    def validate_flooded_area_unit(cls, v: str) -> str:
        """Ensure units are explicit rather than assumed."""
        if not v or not v.strip():
            raise ValueError("flooded_area_unit must be explicitly provided and non-empty.")
        return v.strip()

    @field_validator("response_gap")
    @classmethod
    def validate_response_gap(cls, v: Any) -> Any:
        """Ensure response gap is non-negative across scalar, ResourceQuantity, or dict forms."""
        if isinstance(v, (int, float)):
            if v < 0:
                raise ValueError(f"response_gap must not be negative. Received: {v}")
            return float(v) if isinstance(v, float) else v
        elif isinstance(v, ResourceQuantity):
            # ResourceQuantity fields are already ge=0
            return v
        elif isinstance(v, dict):
            for key, val in v.items():
                if isinstance(val, (int, float)) and val < 0:
                    raise ValueError(f"response_gap item '{key}' must not be negative. Received: {val}")
            return v
        raise ValueError(
            f"Unsupported response_gap type: {type(v)}. Must be a scalar number, ResourceQuantity, or dict."
        )

    @field_validator("response_gap_unit")
    @classmethod
    def validate_response_gap_unit(cls, v: Optional[str]) -> Optional[str]:
        """Ensure response_gap_unit, if provided, is non-empty."""
        if v is not None and not v.strip():
            raise ValueError("response_gap_unit if provided must be a non-empty string.")
        return v.strip() if v is not None else None

    @classmethod
    def from_flood_extent_result(
        cls,
        flood_result: FloodExtentResult,
        response_gap: Union[float, int, ResourceQuantity, Dict[str, Union[float, int]]],
        response_gap_unit: Optional[str] = None,
        timestamp: Optional[Union[datetime, str]] = None,
        source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ResponseGapTimelinePoint":
        """Cleanly construct a timeline observation point from a FloodExtentResult.
        
        Preserves spatial attributes, scene lineage, and explicit units.
        Does not silently fabricate timestamps: raises ValueError if no timestamp can be resolved.
        """
        resolved_ts = timestamp or flood_result.timestamp
        if resolved_ts is None:
            raise ValueError(
                "Timestamp must be explicitly provided or present on the FloodExtentResult."
            )

        combined_meta: Dict[str, Any] = {
            "scene_id": flood_result.scene_id,
            "crs": flood_result.crs,
            "resolution_meters": flood_result.resolution_meters,
            "polygon_count": flood_result.polygon_count,
            "flooded_pixel_count": flood_result.flooded_pixel_count,
        }
        if metadata:
            combined_meta.update(metadata)

        return cls(
            timestamp=resolved_ts,
            flooded_area=flood_result.flooded_area,
            flooded_area_unit=flood_result.area_unit,
            response_gap=response_gap,
            response_gap_unit=response_gap_unit,
            source=source or flood_result.scene_id,
            metadata=combined_meta,
        )


class ResponseGapTimeline(BaseModel):
    """Ordered time-series representation of potential flood extent and response-gap observations."""
    timeline_id: str = Field(
        default="TIMELINE-RESPONSE-GAP-001",
        description="Unique identifier for the timeline series"
    )
    points: List[ResponseGapTimelinePoint] = Field(
        default_factory=list,
        description="Chronologically ordered series of observation points"
    )
    start_timestamp: Optional[datetime] = Field(
        default=None,
        description="Earliest observation timestamp in the timeline series"
    )
    end_timestamp: Optional[datetime] = Field(
        default=None,
        description="Latest observation timestamp in the timeline series"
    )
    number_of_observations: int = Field(
        default=0,
        ge=0,
        description="Total count of discrete observations in the timeline"
    )
    latest_point: Optional[ResponseGapTimelinePoint] = Field(
        default=None,
        description="Most recent timeline observation point"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Timeline-level metadata, provenance, and contextual notes"
    )
    description: str = Field(
        default="Future response-gap timeline tracking potential/new surface-water flood extent and response gaps.",
        description="Descriptive scope and attribution label"
    )

    @model_validator(mode="after")
    def validate_and_order_timeline(self) -> "ResponseGapTimeline":
        """Enforce chronological ordering, reject duplicate timestamps, and derive boundary summaries."""
        if not self.points:
            self.number_of_observations = 0
            self.start_timestamp = None
            self.end_timestamp = None
            self.latest_point = None
            return self

        # Reject duplicate timestamps to preserve deterministic time-series invariants
        seen_timestamps = set()
        for pt in self.points:
            if pt.timestamp in seen_timestamps:
                raise ValueError(
                    f"Duplicate timestamp detected in timeline points: {pt.timestamp.isoformat()}"
                )
            seen_timestamps.add(pt.timestamp)

        # Deterministic chronological sort: timestamp primary, source secondary
        ordered = sorted(self.points, key=lambda p: (p.timestamp, p.source or ""))
        self.points = ordered
        self.number_of_observations = len(ordered)
        self.start_timestamp = ordered[0].timestamp
        self.end_timestamp = ordered[-1].timestamp
        self.latest_point = ordered[-1]
        return self

    @property
    def is_empty(self) -> bool:
        """Return True if the timeline contains no observation points."""
        return len(self.points) == 0
