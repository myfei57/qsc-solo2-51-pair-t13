"""Registry of the key measurement points tracked for trends.

Each point carries the value limit used for limit alarms and the per-period
rate limit used for early warnings, so a drifting point raises attention
before the value itself crosses the limit.
"""

from dataclasses import dataclass

from ..errors import UnknownKeyError


@dataclass(frozen=True)
class PointSpec:
    """Tracking settings of one key measurement point."""

    name: str
    limit: float
    rate_limit: float


POINTS: dict[str, PointSpec] = {
    spec.name: spec
    for spec in (
        PointSpec(name="feed_flow", limit=100.0, rate_limit=15.0),
        PointSpec(name="screen_delta", limit=25.0, rate_limit=6.0),
        PointSpec(name="brine_recovery", limit=0.95, rate_limit=0.2),
        PointSpec(name="permeate_flow", limit=80.0, rate_limit=12.0),
        PointSpec(name="pump_pressure", limit=90.0, rate_limit=15.0),
        PointSpec(name="supply", limit=10.0, rate_limit=3.0),
    )
}


def names() -> tuple[str, ...]:
    """Registered point names, in registration order."""
    return tuple(POINTS)


def spec(name: str) -> PointSpec:
    """Tracking settings of ``name``, raising when the point is unknown."""
    try:
        return POINTS[name]
    except KeyError:
        raise UnknownKeyError(f"unknown measurement point {name}") from None
