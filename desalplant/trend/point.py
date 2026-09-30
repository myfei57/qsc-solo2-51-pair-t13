"""Published trend points: immutable versions of a moving-average window."""

from dataclasses import dataclass
from typing import Any, Mapping

COLLECT = "collect"
CORRECTION = "correction"


@dataclass(frozen=True)
class TrendPoint:
    """One published version of the trend of a point at a tick.

    Versions are append-only: a correction never rewrites an earlier version,
    it publishes a newer one that supersedes it in the effective view.
    """

    point: str
    tick: int
    version: int
    average: float
    rate: float
    samples: int
    trusted: bool
    supersedes: int = 0
    origin: str = COLLECT
    correction: str = ""

    def content(self) -> dict[str, Any]:
        """The derived values, used to tell a real change from a republish."""
        return {
            "average": self.average,
            "rate": self.rate,
            "samples": self.samples,
            "trusted": self.trusted,
        }

    def same_content(self, other: "TrendPoint") -> bool:
        """Whether two versions carry identical derived values."""
        return self.content() == other.content()

    def to_dict(self) -> dict[str, Any]:
        return {
            "point": self.point,
            "tick": self.tick,
            "version": self.version,
            "average": self.average,
            "rate": self.rate,
            "samples": self.samples,
            "trusted": self.trusted,
            "supersedes": self.supersedes,
            "origin": self.origin,
            "correction": self.correction,
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "TrendPoint":
        """Rebuild a published version from a persisted row."""
        return cls(
            point=str(row["point"]),
            tick=int(row["tick"]),
            version=int(row["version"]),
            average=float(row["average"]),
            rate=float(row["rate"]),
            samples=int(row["samples"]),
            trusted=bool(row["trusted"]),
            supersedes=int(row.get("supersedes", 0)),
            origin=str(row.get("origin", COLLECT)),
            correction=str(row.get("correction", "")),
        )
