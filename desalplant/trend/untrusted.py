"""Segments of a series that must not take part in the trend."""

from dataclasses import dataclass
from typing import Any, Mapping

GAP = "gap"
REGRESSION = "regression"
CONFLICT = "conflict"
REASONS = (GAP, REGRESSION, CONFLICT)


@dataclass(frozen=True)
class UntrustedSegment:
    """A tick range marked untrustworthy after a partial sampling failure.

    Live readings inside the range are excluded from the trend; the record
    itself is append-only, so the failure stays visible after later
    corrections heal the series.
    """

    point: str
    start: int
    end: int
    reason: str
    sequence: int
    claimed: float | None = None

    def covers(self, tick: int) -> bool:
        """Whether ``tick`` falls inside the segment."""
        return self.start <= tick <= self.end

    def intersects(self, start: int, end: int) -> bool:
        """Whether the segment overlaps the inclusive range."""
        return self.start <= end and self.end >= start

    def to_dict(self) -> dict[str, Any]:
        return {
            "point": self.point,
            "start": self.start,
            "end": self.end,
            "reason": self.reason,
            "sequence": self.sequence,
            "claimed": self.claimed,
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "UntrustedSegment":
        """Rebuild a segment from a persisted row."""
        claimed = row.get("claimed")
        return cls(
            point=str(row["point"]),
            start=int(row["start"]),
            end=int(row["end"]),
            reason=str(row["reason"]),
            sequence=int(row["sequence"]),
            claimed=None if claimed is None else float(claimed),
        )
