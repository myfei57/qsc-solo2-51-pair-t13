"""Corrections appended when late data revises published trend points."""

from dataclasses import dataclass
from typing import Any, Mapping

from ..store.checksum import digest, short


def correction_id(point: str, samples: tuple[tuple[int, float], ...]) -> str:
    """Stable identifier of a late batch, derived from its content."""
    rows = {f"{tick:09d}": value for tick, value in sorted(samples)}
    return short(digest({"point": point, "samples": rows}))


@dataclass(frozen=True)
class Correction:
    """One appended correction: the trend ticks a late batch republished."""

    sequence: int
    id: str
    point: str
    late_ticks: tuple[int, ...]
    revised: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "id": self.id,
            "point": self.point,
            "late_ticks": list(self.late_ticks),
            "revised": list(self.revised),
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "Correction":
        """Rebuild a correction from a persisted row."""
        return cls(
            sequence=int(row["sequence"]),
            id=str(row["id"]),
            point=str(row["point"]),
            late_ticks=tuple(int(tick) for tick in row["late_ticks"]),
            revised=tuple(int(tick) for tick in row["revised"]),
        )
