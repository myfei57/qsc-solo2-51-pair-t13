"""Consistency check of the published trend against the raw readings.

The effective trend must be a pure function of the committed raw samples
and the untrusted segments; this module recomputes that function and lists
every tick where the published view disagrees.
"""

from typing import Any

from ..store.store import Store
from . import compute, journal
from .points import PointSpec
from .sample import LIVE


def reconcile(store: Store, spec: PointSpec, period: int, window: int) -> dict[str, Any]:
    """Recompute the trend of ``spec`` from raw readings and compare.

    Every committed live sample must have an effective published point,
    every published point must trace back to a live sample, and the derived
    values must match the recomputation exactly.
    """
    name = spec.name
    samples = journal.raw_samples(store, name)
    segments = journal.segments(store, name)
    live_ticks = tuple(sample.tick for sample in samples if sample.origin == LIVE)
    drafts = compute.evaluate_series(spec, samples, segments, period, window, live_ticks)
    expected = {draft.tick: draft for draft in drafts}
    mismatches: list[dict[str, Any]] = []
    checked = 0
    for tick in journal.current_ticks(store, name):
        checked += 1
        current = journal.current_at(store, name, tick)
        draft = expected.pop(tick, None)
        if current is None:
            mismatches.append({"tick": tick, "issue": "current pointer has no published version"})
            continue
        if draft is None:
            mismatches.append({"tick": tick, "issue": "published without a live sample"})
            continue
        for field, want in draft.content().items():
            got = current.content()[field]
            if got != want:
                mismatches.append(
                    {"tick": tick, "field": field, "published": got, "expected": want}
                )
    for tick in sorted(expected):
        mismatches.append({"tick": tick, "issue": "expected by raw readings but not published"})
    return {
        "point": name,
        "ticks_checked": checked,
        "consistent": not mismatches,
        "mismatches": mismatches,
    }
