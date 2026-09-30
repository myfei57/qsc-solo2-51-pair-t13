"""Early warnings raised from the trend instead of the raw limit."""

from dataclasses import dataclass
from typing import Any, Mapping

RATE = "rate"
LIMIT = "limit"


@dataclass(frozen=True)
class TrendWarning:
    """A warning derived from a published trend point.

    ``rate`` warnings fire while the value is still inside its limit, which
    is the early hint; ``limit`` warnings fire once the average crosses it.
    """

    point: str
    tick: int
    kind: str
    severity: str
    message: str
    value: float
    limit: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "point": self.point,
            "tick": self.tick,
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "value": self.value,
            "limit": self.limit,
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "TrendWarning":
        """Rebuild a warning from a persisted row."""
        return cls(
            point=str(row["point"]),
            tick=int(row["tick"]),
            kind=str(row["kind"]),
            severity=str(row["severity"]),
            message=str(row["message"]),
            value=float(row["value"]),
            limit=float(row["limit"]),
        )
