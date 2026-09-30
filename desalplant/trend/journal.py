"""Persistence of the trend series: raw samples, versions and corrections.

Raw samples and published versions are append-only. The only mutable keys
are derived pointers (the effective version of a tick, the current warnings
of a tick), which always reference immutable rows.
"""

from ..store import keys
from ..store.store import Store
from .correction import Correction
from .point import TrendPoint
from .sample import Sample
from .untrusted import UntrustedSegment
from .warning import TrendWarning


# ------------------------------------------------------------------ clock

def clock_tick(store: Store) -> int:
    """Newest tick issued by the sampler, zero before the first collect."""
    return int(store.get(keys.TREND_CLOCK, 0) or 0)


def set_clock(store: Store, tick: int) -> None:
    """Persist the newest tick issued by the sampler."""
    store.put(keys.TREND_CLOCK, tick)


# ----------------------------------------------------------- live frontier

def last_live_tick(store: Store, point: str) -> int | None:
    """Newest committed live tick of ``point``, or ``None`` before any."""
    value = store.get(keys.trend_live_key(point))
    return None if value is None else int(value)


def set_live_tick(store: Store, point: str, tick: int) -> None:
    """Advance the committed live frontier of ``point``."""
    store.put(keys.trend_live_key(point), tick)


# -------------------------------------------------------------- raw samples

def put_raw(store: Store, sample: Sample) -> None:
    """Commit a raw sample; the key makes one tick hold exactly one sample."""
    store.put(keys.trend_raw_key(sample.point, sample.tick), sample.to_dict())


def raw_at(store: Store, point: str, tick: int) -> Sample | None:
    """Raw sample committed at ``tick``, or ``None`` when the tick is empty."""
    row = store.get(keys.trend_raw_key(point, tick))
    return None if row is None else Sample.from_dict(row)


def raw_samples(store: Store, point: str) -> tuple[Sample, ...]:
    """Every committed raw sample of ``point``, in ascending tick order."""
    prefix = f"{keys.TREND_RAW_PREFIX}{point}/"
    return tuple(Sample.from_dict(store.require(key)) for key in store.keys(prefix))


# -------------------------------------------------------- untrusted segments

def put_segment(store: Store, segment: UntrustedSegment) -> None:
    """Append an untrusted segment and advance the per-point count."""
    store.put(keys.trend_untrusted_count_key(segment.point), segment.sequence)
    store.put(keys.trend_untrusted_key(segment.point, segment.sequence), segment.to_dict())


def next_segment_sequence(store: Store, point: str) -> int:
    """Sequence the next untrusted segment of ``point`` will receive."""
    return int(store.get(keys.trend_untrusted_count_key(point), 0) or 0) + 1


def segments(store: Store, point: str) -> tuple[UntrustedSegment, ...]:
    """Every untrusted segment of ``point``, in recording order."""
    prefix = f"{keys.TREND_UNTRUSTED_PREFIX}{point}/"
    return tuple(UntrustedSegment.from_dict(store.require(key)) for key in store.keys(prefix))


# -------------------------------------------------------- published versions

def put_version(store: Store, point: TrendPoint) -> None:
    """Append one immutable version of a trend point."""
    store.put(
        keys.trend_published_key(point.point, point.tick, point.version),
        point.to_dict(),
    )


def version_at(store: Store, point: str, tick: int, version: int) -> TrendPoint | None:
    """One published version, or ``None`` when it was never written."""
    row = store.get(keys.trend_published_key(point, tick, version))
    return None if row is None else TrendPoint.from_dict(row)


def set_current(store: Store, point: str, tick: int, version: int) -> None:
    """Point the effective view of a tick at a published version."""
    store.put(keys.trend_current_key(point, tick), version)


def current_version(store: Store, point: str, tick: int) -> int:
    """Version the effective view of a tick points at, zero when none."""
    return int(store.get(keys.trend_current_key(point, tick), 0) or 0)


def current_at(store: Store, point: str, tick: int) -> TrendPoint | None:
    """Effective trend point of a tick, or ``None`` when none was published."""
    version = current_version(store, point, tick)
    if version < 1:
        return None
    return version_at(store, point, tick, version)


def current_ticks(store: Store, point: str) -> tuple[int, ...]:
    """Ticks that hold an effective trend point, ascending."""
    prefix = f"{keys.TREND_CURRENT_PREFIX}{point}/"
    return tuple(int(key.rsplit("/", 1)[1]) for key in store.keys(prefix))


def latest_current_before(store: Store, point: str, tick: int) -> TrendPoint | None:
    """Effective trend point of the newest tick below ``tick``, if any."""
    earlier = [t for t in current_ticks(store, point) if t < tick]
    if not earlier:
        return None
    return current_at(store, point, max(earlier))


def history(store: Store, point: str) -> tuple[TrendPoint, ...]:
    """Every published version of ``point``, ascending by tick and version."""
    prefix = f"{keys.TREND_PUBLISHED_PREFIX}{point}/"
    return tuple(TrendPoint.from_dict(store.require(key)) for key in store.keys(prefix))


# -------------------------------------------------------------- corrections

def next_correction_sequence(store: Store) -> int:
    """Sequence the next correction will receive."""
    return int(store.get(keys.TREND_CORRECTION_SEQUENCE, 0) or 0) + 1


def put_correction(store: Store, correction: Correction) -> None:
    """Append a correction and advance the sequence."""
    store.put(keys.TREND_CORRECTION_SEQUENCE, correction.sequence)
    store.put(keys.trend_correction_key(correction.sequence), correction.to_dict())


def corrections(store: Store, point: str | None = None) -> tuple[Correction, ...]:
    """Every correction, optionally narrowed to one point."""
    rows = tuple(
        Correction.from_dict(store.require(key))
        for key in store.keys(keys.TREND_CORRECTION_PREFIX)
    )
    if point is None:
        return rows
    return tuple(row for row in rows if row.point == point)


# ----------------------------------------------------------------- warnings

def put_warnings(store: Store, point: str, tick: int, warnings: tuple[TrendWarning, ...]) -> None:
    """Replace the derived warning list of a tick (empty clears it)."""
    store.put(
        keys.trend_warning_key(point, tick),
        [warning.to_dict() for warning in warnings],
    )


def warnings(store: Store, point: str | None = None) -> tuple[TrendWarning, ...]:
    """Warnings of the effective trend points, newest ticks first."""
    points = (point,) if point is not None else _warning_points(store)
    collected: list[TrendWarning] = []
    for name in points:
        prefix = f"{keys.TREND_WARNING_PREFIX}{name}/"
        for key in reversed(store.keys(prefix)):
            collected.extend(TrendWarning.from_dict(row) for row in store.require(key))
    return tuple(collected)


def _warning_points(store: Store) -> tuple[str, ...]:
    """Point names that hold any warning key."""
    prefix = keys.TREND_WARNING_PREFIX
    seen: dict[str, None] = {}
    for key in store.keys(prefix):
        seen.setdefault(key[len(prefix):].split("/", 1)[0], None)
    return tuple(seen)
