"""Raw readings committed to the trend series."""

from dataclasses import dataclass
from typing import Any, Mapping

LIVE = "live"
BACKFILL = "backfill"
ORIGINS = (LIVE, BACKFILL)


@dataclass(frozen=True)
class Sample:
    """One raw reading of a measurement point, stamped with its source tick."""

    point: str
    tick: int
    value: float
    origin: str = LIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "point": self.point,
            "tick": self.tick,
            "value": self.value,
            "origin": self.origin,
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "Sample":
        """Rebuild a sample from a persisted row."""
        return cls(
            point=str(row["point"]),
            tick=int(row["tick"]),
            value=float(row["value"]),
            origin=str(row.get("origin", LIVE)),
        )
