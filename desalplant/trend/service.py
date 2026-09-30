"""Orchestration of sampling, ordering guards, publication and corrections.

The service keeps one strictly ordered raw series per measurement point.
Live samples must arrive in tick order; gaps and regressions are partial
failures that mark an untrusted segment instead of breaking the series.
Late data enters through the backfill path, which never rewrites published
trend points: recomputation appends superseding versions and a correction
record, and replaying the same batch is a no-op.
"""

import math
from dataclasses import replace
from typing import Any, Iterable, Mapping

from ..audit.recorder import Recorder
from ..clock import LogicalClock
from ..errors import TrendConflictError, TrendOrderError
from ..store.store import Store
from . import compute, journal, points, reconcile as reconcile_module
from . import sample as sample_module
from . import untrusted as untrusted_module
from .correction import Correction, correction_id
from .point import COLLECT, CORRECTION, TrendPoint
from .points import PointSpec
from .sample import Sample
from .untrusted import UntrustedSegment


class TrendService:
    """Fixed-period sampler and trend keeper for the key measurement points."""

    def __init__(self, store: Store, recorder: Recorder, period: int = 1, window: int = 3) -> None:
        if period < 1:
            raise ValueError("sampling period must be at least one tick")
        if window < 1:
            raise ValueError("sliding window must hold at least one sample")
        self._store = store
        self._recorder = recorder
        self._period = period
        self._window = window
        self._clock = LogicalClock(journal.clock_tick(store))

    @property
    def period(self) -> int:
        """Ticks between two scheduled samples."""
        return self._period

    @property
    def window(self) -> int:
        """Samples averaged by the sliding window."""
        return self._window

    @property
    def tick(self) -> int:
        """Newest tick issued by the sampler."""
        return self._clock.tick

    # -------------------------------------------------------------- sampling

    def collect(
        self, readings: Mapping[str, float] | None = None, stamp: int | None = None
    ) -> dict[str, Any]:
        """Sample one fixed-period sweep and publish the trend of each point.

        ``readings`` maps point names onto fresh values; an empty sweep is a
        no-op. ``stamp`` overrides the source tick, otherwise the sampler
        clock advances by one period.
        """
        requested = dict(readings or {})
        for name in requested:
            points.spec(name)
        values = {name: self._checked_value(value) for name, value in requested.items()}
        if not values:
            return self._report(stamp=self._clock.tick, outcomes={}, published={}, warnings=[])
        tick = self._issue_tick(stamp)
        outcomes: dict[str, Any] = {}
        published: dict[str, Any] = {}
        raised: list[dict[str, Any]] = []
        for name, value in values.items():
            outcome, trend_point, point_warnings = self._ingest_live(points.spec(name), value, tick)
            outcomes[name] = outcome
            if trend_point is not None:
                published[name] = trend_point.to_dict()
            raised.extend(warning.to_dict() for warning in point_warnings)
        summary = ", ".join(
            f"{status} {sum(1 for o in outcomes.values() if o['status'] == status)}"
            for status in ("committed", "deduplicated", "gap", "regression", "conflict")
            if any(o["status"] == status for o in outcomes.values())
        )
        self._recorder.log("trend_collect", f"tick {tick}: {summary}")
        return self._report(stamp=tick, outcomes=outcomes, published=published, warnings=raised)

    def _issue_tick(self, stamp: int | None) -> int:
        """Tick of the sweep: the next scheduled one, or a validated claim."""
        if stamp is None:
            return self._advance(self._period)
        tick = self._checked_tick(stamp)
        if tick > self._clock.tick:
            self._advance(tick - self._clock.tick)
        return tick

    def _advance(self, steps: int) -> int:
        """Move the sampler clock and persist it so a restart resumes it."""
        tick = self._clock.advance(steps)
        journal.set_clock(self._store, tick)
        return tick

    def _ingest_live(
        self, spec: PointSpec, value: float, tick: int
    ) -> tuple[dict[str, Any], TrendPoint | None, tuple]:
        """Commit one live sample, guarding the order of the raw series."""
        name = spec.name
        last = journal.last_live_tick(self._store, name)
        if last is not None and tick <= last:
            existing = journal.raw_at(self._store, name, tick)
            if existing is not None and existing.value == value:
                return {"status": "deduplicated"}, None, ()
            segment = self._record_segment(name, tick, last, untrusted_module.REGRESSION, value)
            self._republish_from(spec, segment.start, segment)
            return {"status": "regression", "segments": [segment.to_dict()]}, None, ()
        segments: list[UntrustedSegment] = []
        status = "committed"
        existing = journal.raw_at(self._store, name, tick)
        if existing is None:
            journal.put_raw(
                self._store,
                Sample(point=name, tick=tick, value=value, origin=sample_module.LIVE),
            )
        elif existing.value == value:
            status = "deduplicated"
        else:
            status = "conflict"
            segment = self._record_segment(name, tick, tick, untrusted_module.CONFLICT, value)
            segments.append(segment)
            self._republish_from(spec, segment.start, segment)
        journal.set_live_tick(self._store, name, tick)
        if last is not None and tick > last + self._period:
            segments.append(
                self._record_segment(
                    name, last + self._period, tick - self._period, untrusted_module.GAP
                )
            )
            if status in ("committed", "deduplicated"):
                status = "gap"
        trend_point = None
        warnings: tuple = ()
        if existing is None:
            published_rows, warnings = self._publish(spec, (tick,), COLLECT)
            trend_point = published_rows[0] if published_rows else None
        outcome: dict[str, Any] = {"status": status}
        if segments:
            outcome["segments"] = [segment.to_dict() for segment in segments]
        return outcome, trend_point, warnings

    def _republish_from(
        self, spec: PointSpec, tick: int, segment: UntrustedSegment
    ) -> tuple[TrendPoint, ...]:
        """Append corrections for the published ticks a trust change revises.

        The earlier versions stay untouched; the effective view moves to the
        recomputed ones, and a correction record ties them to the segment.
        """
        ticks = tuple(t for t in journal.current_ticks(self._store, spec.name) if t >= tick)
        if not ticks:
            return ()
        marker = f"untrusted-{spec.name}-{segment.sequence}"
        published, _ = self._publish(spec, ticks, CORRECTION, correction=marker)
        if published:
            correction = Correction(
                sequence=journal.next_correction_sequence(self._store),
                id=marker,
                point=spec.name,
                late_ticks=(),
                revised=tuple(row.tick for row in published),
            )
            journal.put_correction(self._store, correction)
            self._recorder.log(
                "trend_correction",
                f"{spec.name}: revised {list(correction.revised)} after"
                f" {segment.reason} [{segment.start}, {segment.end}]",
            )
        return published

    def _record_segment(
        self, point: str, start: int, end: int, reason: str, claimed: float | None = None
    ) -> UntrustedSegment:
        """Append an untrusted segment and audit the partial failure."""
        segment = UntrustedSegment(
            point=point,
            start=start,
            end=end,
            reason=reason,
            sequence=journal.next_segment_sequence(self._store, point),
            claimed=claimed,
        )
        journal.put_segment(self._store, segment)
        self._recorder.log("trend_untrusted", f"{point} untrusted [{start}, {end}]: {reason}")
        return segment

    # -------------------------------------------------------------- backfill

    def backfill(self, point: str, samples: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """Merge late samples and append corrections for the revised ticks.

        Replaying the same batch is a no-op: identical samples are reported
        as duplicates and neither the store nor the audit record changes.
        A sample contradicting a committed reading is refused as a conflict.
        """
        spec = points.spec(point)
        batch = [self._checked_sample(row) for row in samples]
        if not batch:
            raise ValueError("backfill needs at least one sample")
        seen = [tick for tick, _ in batch]
        if len(set(seen)) != len(seen):
            raise ValueError("backfill batch repeats a tick")
        horizon = self._clock.tick
        for tick, _ in batch:
            if tick > horizon:
                raise TrendOrderError(
                    f"backfill tick {tick} is beyond the sampler horizon {horizon}"
                )
        duplicates = 0
        pending: list[tuple[int, float]] = []
        for tick, value in batch:
            existing = journal.raw_at(self._store, point, tick)
            if existing is None:
                pending.append((tick, value))
            elif existing.value == value:
                duplicates += 1
            else:
                raise TrendConflictError(
                    f"{point} already holds {existing.value} at tick {tick}, refused {value}"
                )
        for tick, value in pending:
            journal.put_raw(
                self._store,
                Sample(point=point, tick=tick, value=value, origin=sample_module.BACKFILL),
            )
        if not pending:
            return self._backfill_report(point, 0, duplicates, (), None)
        first = min(tick for tick, _ in pending)
        ticks = tuple(t for t in journal.current_ticks(self._store, point) if t >= first)
        late = tuple(sorted((tick, value) for tick, value in pending))
        cid = correction_id(point, late)
        published, _ = self._publish(spec, ticks, CORRECTION, correction=cid)
        revised = tuple(row.tick for row in published)
        correction = None
        if revised:
            correction = Correction(
                sequence=journal.next_correction_sequence(self._store),
                id=cid,
                point=point,
                late_ticks=tuple(tick for tick, _ in late),
                revised=revised,
            )
            journal.put_correction(self._store, correction)
        self._recorder.log(
            "trend_backfill",
            f"{point}: applied {len(pending)}, duplicates {duplicates},"
            f" revised {list(revised)}",
        )
        return self._backfill_report(point, len(pending), duplicates, revised, correction)

    @staticmethod
    def _backfill_report(
        point: str, applied: int, duplicates: int, revised: tuple[int, ...], correction
    ) -> dict[str, Any]:
        return {
            "point": point,
            "applied": applied,
            "duplicates": duplicates,
            "revised": list(revised),
            "correction": None if correction is None else correction.to_dict(),
        }

    # ------------------------------------------------------------ publication

    def _publish(
        self, spec: PointSpec, ticks: tuple[int, ...], origin: str, correction: str = ""
    ) -> tuple[TrendPoint, tuple]:
        """Append new versions for ``ticks`` whose recomputed content changed."""
        if not ticks:
            return (), ()
        samples = journal.raw_samples(self._store, spec.name)
        segments = journal.segments(self._store, spec.name)
        seed = journal.latest_current_before(self._store, spec.name, min(ticks))
        drafts = compute.evaluate_series(
            spec, samples, segments, self._period, self._window, ticks, seed
        )
        published: list[TrendPoint] = []
        raised: list = []
        for draft in drafts:
            current = journal.current_version(self._store, spec.name, draft.tick)
            if current:
                existing = journal.version_at(self._store, spec.name, draft.tick, current)
                if existing is not None and existing.same_content(draft):
                    continue
            row = replace(
                draft,
                version=current + 1,
                supersedes=current,
                origin=origin,
                correction=correction,
            )
            journal.put_version(self._store, row)
            journal.set_current(self._store, spec.name, row.tick, row.version)
            warnings = compute.warnings_for(spec, row)
            journal.put_warnings(self._store, spec.name, row.tick, warnings)
            for warning in warnings:
                self._recorder.log(
                    "trend_warning",
                    f"{spec.name} {warning.kind} at tick {row.tick}: {warning.message}",
                )
            published.append(row)
            raised.extend(warnings)
        return tuple(published), tuple(raised)

    # ------------------------------------------------------------------ reads

    def view(self, point: str | None = None, limit: int = 10) -> dict[str, Any]:
        """Effective trend of each point, for the console."""
        names = (points.spec(point).name,) if point is not None else points.names()
        view: dict[str, Any] = {}
        for name in names:
            spec = points.spec(name)
            ticks = journal.current_ticks(self._store, name)
            recent = ticks[-limit:] if limit > 0 else ticks
            series = [
                journal.current_at(self._store, name, tick).to_dict()
                for tick in reversed(recent)
            ]
            view[name] = {
                "limit": spec.limit,
                "rate_limit": spec.rate_limit,
                "latest": series[0] if series else None,
                "series": series,
                "untrusted": [
                    segment.to_dict() for segment in journal.segments(self._store, name)
                ],
                "warnings": [
                    warning.to_dict() for warning in journal.warnings(self._store, name)
                ],
            }
        return {
            "period": self._period,
            "window": self._window,
            "tick": self._clock.tick,
            "points": view,
        }

    def history(self, point: str) -> dict[str, Any]:
        """Every published version and correction of ``point``, in order."""
        spec = points.spec(point)
        return {
            "point": spec.name,
            "versions": [row.to_dict() for row in journal.history(self._store, spec.name)],
            "corrections": [
                row.to_dict() for row in journal.corrections(self._store, spec.name)
            ],
        }

    def reconcile(self, point: str) -> dict[str, Any]:
        """Check the published trend against the committed raw readings."""
        spec = points.spec(point)
        return reconcile_module.reconcile(self._store, spec, self._period, self._window)

    # -------------------------------------------------------------- validation

    @staticmethod
    def _checked_tick(raw: Any) -> int:
        """A source tick: a positive integer, never a boolean."""
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
            raise ValueError(f"trend tick must be a positive integer, got {raw!r}")
        return raw

    @staticmethod
    def _checked_value(raw: Any) -> float:
        """A reading: a finite number, never a boolean."""
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"reading must be a number, got {raw!r}")
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(f"reading must be finite, got {raw!r}")
        return value

    def _checked_sample(self, row: Mapping[str, Any]) -> tuple[int, float]:
        """Validate one late sample row of a backfill batch."""
        if not isinstance(row, Mapping):
            raise ValueError(f"backfill sample must be an object, got {row!r}")
        return self._checked_tick(row["tick"]), self._checked_value(row["value"])

    def _report(self, stamp: int, outcomes, published, warnings) -> dict[str, Any]:
        return {
            "tick": stamp,
            "outcomes": outcomes,
            "published": published,
            "warnings": warnings,
        }
