"""Pure trend arithmetic: sliding averages and per-period rates.

Everything here is a pure function of the committed raw samples and the
untrusted segments, so the published trend can always be recomputed from the
raw readings when the two are checked for consistency.
"""

from . import sample as sample_module
from . import untrusted as untrusted_module
from .point import TrendPoint
from .points import PointSpec
from .sample import Sample
from .untrusted import UntrustedSegment
from .warning import LIMIT, RATE, TrendWarning


def trusted_samples(
    samples: tuple[Sample, ...], segments: tuple[UntrustedSegment, ...]
) -> tuple[Sample, ...]:
    """Samples allowed into the trend, in tick order.

    Late data committed through the backfill path is verified and always
    counts; live readings inside an untrusted segment never do.
    """
    return tuple(
        sample
        for sample in samples
        if sample.origin == sample_module.BACKFILL
        or not any(segment.covers(sample.tick) for segment in segments)
    )


def evaluate_series(
    spec: PointSpec,
    samples: tuple[Sample, ...],
    segments: tuple[UntrustedSegment, ...],
    period: int,
    window: int,
    ticks: tuple[int, ...],
    seed: TrendPoint | None = None,
) -> tuple[TrendPoint, ...]:
    """Draft the trend at each of ``ticks``, chaining rates along the way.

    ``seed`` is the effective trend point just before the first tick, used
    as the rate baseline; the returned drafts carry no version yet.
    """
    trusted = trusted_samples(samples, segments)
    healed = {sample.tick for sample in samples if sample.origin == sample_module.BACKFILL}
    drafts: list[TrendPoint] = []
    previous = seed
    for tick in sorted(ticks):
        window_samples = tuple(s for s in trusted if s.tick <= tick)[-window:]
        if not window_samples:
            continue
        average = sum(s.value for s in window_samples) / len(window_samples)
        rate = 0.0
        if previous is not None and tick > previous.tick:
            rate = (average - previous.average) * period / (tick - previous.tick)
        start = window_samples[0].tick
        is_trusted = not any(
            _unhealed_intersection(segment, start, tick, healed) for segment in segments
        )
        draft = TrendPoint(
            point=spec.name,
            tick=tick,
            version=0,
            average=average,
            rate=rate,
            samples=len(window_samples),
            trusted=is_trusted,
        )
        drafts.append(draft)
        previous = draft
    return tuple(drafts)


def _unhealed_intersection(
    segment: UntrustedSegment, start: int, end: int, healed: set[int]
) -> bool:
    """Whether a segment still distrusts any tick of the inclusive range.

    A gap segment heals tick by tick as verified late samples fill it;
    regression and conflict segments stay until an operator resolves them.
    """
    if not segment.intersects(start, end):
        return False
    if segment.reason != untrusted_module.GAP:
        return True
    first = max(start, segment.start)
    last = min(end, segment.end)
    return any(tick not in healed for tick in range(first, last + 1))


def warnings_for(spec: PointSpec, point: TrendPoint) -> tuple[TrendWarning, ...]:
    """Warnings raised by a trend point; untrusted points never warn.

    A rate warning is the early hint: it fires while the average is still
    inside the value limit, before the point would trip the limit itself.
    """
    if not point.trusted:
        return ()
    warnings: list[TrendWarning] = []
    if abs(point.rate) > spec.rate_limit:
        warnings.append(
            TrendWarning(
                point=spec.name,
                tick=point.tick,
                kind=RATE,
                severity="warning",
                message=(
                    f"rate {point.rate:.2f}/period exceeds {spec.rate_limit:.2f}"
                    f" while average {point.average:.2f} is still within"
                    f" {spec.limit:.2f}"
                ),
                value=point.rate,
                limit=spec.rate_limit,
            )
        )
    if abs(point.average) > spec.limit:
        warnings.append(
            TrendWarning(
                point=spec.name,
                tick=point.tick,
                kind=LIMIT,
                severity="critical",
                message=f"average {point.average:.2f} crossed limit {spec.limit:.2f}",
                value=point.average,
                limit=spec.limit,
            )
        )
    return tuple(warnings)
