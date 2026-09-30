"""Fixed-period sampling, trend publication and late-data corrections."""

import pytest

from desalplant.store import keys
from desalplant.trend import compute, journal
from desalplant.trend.points import spec
from desalplant.trend.sample import BACKFILL, LIVE, Sample
from desalplant.trend.untrusted import GAP, REGRESSION, UntrustedSegment

from support import build, call, ok, refused


def collect(console, values, tick=None):
    """POST one sampling sweep and require success."""
    body = {"values": values}
    if tick is not None:
        body["tick"] = tick
    return ok(console, "POST", "/api/trends/collect", body)


def test_collect_publishes_sliding_average_and_rate(console):
    for value in (10, 20, 30, 40):
        collect(console, {"feed_flow": value})
    view = ok(console, "GET", "/api/trends?point=feed_flow")
    point = view["points"]["feed_flow"]
    assert point["latest"]["average"] == 30.0
    assert point["latest"]["rate"] == 10.0
    assert point["latest"]["trusted"] is True
    series = point["series"]
    assert [row["tick"] for row in series] == [4, 3, 2, 1]
    assert [row["average"] for row in series] == [30.0, 20.0, 15.0, 10.0]
    assert [row["rate"] for row in series] == [10.0, 5.0, 5.0, 0.0]
    assert point["untrusted"] == []
    assert point["warnings"] == []


def test_collect_defaults_to_the_plant_probe(console):
    report = ok(console, "POST", "/api/trends/collect", {})
    assert set(report["outcomes"]) == {
        "feed_flow",
        "screen_delta",
        "brine_recovery",
        "permeate_flow",
        "pump_pressure",
        "supply",
    }
    assert all(o["status"] == "committed" for o in report["outcomes"].values())
    assert report["published"]["feed_flow"]["average"] == 80.0


def test_rate_anomaly_warns_before_the_limit(console):
    for value in (10, 10, 10):
        collect(console, {"feed_flow": value})
    report = collect(console, {"feed_flow": 60})
    kinds = [warning["kind"] for warning in report["warnings"]]
    assert kinds == ["rate"]
    warning = report["warnings"][0]
    assert warning["severity"] == "warning"
    assert warning["value"] > 15.0
    assert warning["limit"] == 15.0
    view = ok(console, "GET", "/api/trends?point=feed_flow")
    assert view["points"]["feed_flow"]["latest"]["average"] < 100.0
    assert [w["kind"] for w in view["points"]["feed_flow"]["warnings"]] == ["rate"]
    collect(console, {"feed_flow": 200})
    report = collect(console, {"feed_flow": 200})
    kinds = {warning["kind"] for warning in report["warnings"]}
    assert kinds == {"rate", "limit"}
    limit = next(w for w in report["warnings"] if w["kind"] == "limit")
    assert limit["severity"] == "critical"
    events = ok(console, "GET", "/api/events")["events"]
    trend_warnings = [e for e in events if e["kind"] == "trend_warning"]
    assert "rate" in trend_warnings[-1]["detail"]
    assert any("crossed limit" in e["detail"] for e in trend_warnings)


def test_untrusted_points_never_warn(console):
    collect(console, {"feed_flow": 10})
    collect(console, {"feed_flow": 10})
    report = collect(console, {"feed_flow": 200}, tick=6)
    assert report["outcomes"]["feed_flow"]["status"] == "gap"
    assert report["published"]["feed_flow"]["trusted"] is False
    assert report["published"]["feed_flow"]["rate"] > 15.0
    assert report["warnings"] == []


def test_gap_is_a_partial_failure_marked_untrusted(console):
    collect(console, {"feed_flow": 10, "supply": 1})
    collect(console, {"feed_flow": 20, "supply": 1})
    report = collect(console, {"feed_flow": 30, "supply": 1}, tick=5)
    assert report["outcomes"]["feed_flow"]["status"] == "gap"
    assert report["outcomes"]["supply"]["status"] == "gap"
    segment = report["outcomes"]["feed_flow"]["segments"][0]
    assert segment["reason"] == "gap"
    assert (segment["start"], segment["end"]) == (3, 4)
    point = report["published"]["feed_flow"]
    assert point["trusted"] is False
    assert point["average"] == 20.0
    view = ok(console, "GET", "/api/trends?point=feed_flow")
    assert view["points"]["feed_flow"]["untrusted"][0]["reason"] == "gap"
    supply = ok(console, "GET", "/api/trends?point=supply")["points"]["supply"]
    assert supply["latest"]["trusted"] is False
    assert ok(console, "GET", "/api/trends/reconcile?point=feed_flow")["consistent"] is True


def test_exact_replay_of_a_live_sample_changes_no_trend(console):
    collect(console, {"feed_flow": 10})
    collect(console, {"feed_flow": 20})
    before = ok(console, "GET", "/api/trends/history?point=feed_flow")
    report = collect(console, {"feed_flow": 10}, tick=1)
    assert report["outcomes"]["feed_flow"]["status"] == "deduplicated"
    after = ok(console, "GET", "/api/trends/history?point=feed_flow")
    assert after["versions"] == before["versions"]
    view = ok(console, "GET", "/api/trends?point=feed_flow")
    assert view["points"]["feed_flow"]["untrusted"] == []
    assert ok(console, "GET", "/api/trends/reconcile?point=feed_flow")["consistent"] is True


def test_regression_is_refused_and_the_order_is_kept(console):
    collect(console, {"feed_flow": 10})
    collect(console, {"feed_flow": 20})
    collect(console, {"feed_flow": 30})
    report = collect(console, {"feed_flow": 999}, tick=2)
    outcome = report["outcomes"]["feed_flow"]
    assert outcome["status"] == "regression"
    assert "feed_flow" not in report["published"]
    segment = outcome["segments"][0]
    assert segment["reason"] == "regression"
    assert (segment["start"], segment["end"]) == (2, 3)
    assert segment["claimed"] == 999.0
    history = ok(console, "GET", "/api/trends/history?point=feed_flow")
    tick2 = [row for row in history["versions"] if row["tick"] == 2]
    assert [row["average"] for row in tick2] == [15.0, 10.0]
    assert tick2[0]["trusted"] is True
    assert tick2[1]["trusted"] is False
    assert tick2[1]["origin"] == "correction"
    view = ok(console, "GET", "/api/trends?point=feed_flow")
    assert view["points"]["feed_flow"]["latest"]["trusted"] is False
    assert ok(console, "GET", "/api/trends/reconcile?point=feed_flow")["consistent"] is True


def test_late_data_appends_corrections_without_rewriting(console):
    collect(console, {"feed_flow": 10})
    collect(console, {"feed_flow": 20})
    collect(console, {"feed_flow": 30})
    collect(console, {"feed_flow": 50}, tick=5)
    before = ok(console, "GET", "/api/trends/history?point=feed_flow")
    report = ok(
        console,
        "POST",
        "/api/trends/backfill",
        {"point": "feed_flow", "samples": [{"tick": 4, "value": 40}]},
    )
    assert report["applied"] == 1
    assert report["duplicates"] == 0
    assert report["revised"] == [5]
    assert report["correction"]["late_ticks"] == [4]
    after = ok(console, "GET", "/api/trends/history?point=feed_flow")
    assert len(after["versions"]) == len(before["versions"]) + 1
    original = [row for row in after["versions"] if row["tick"] == 5 and row["version"] == 1]
    assert original[0]["average"] == pytest.approx(100.0 / 3.0)
    assert original[0]["trusted"] is False
    revised = [row for row in after["versions"] if row["tick"] == 5 and row["version"] == 2]
    assert revised[0]["average"] == 40.0
    assert revised[0]["trusted"] is True
    assert revised[0]["supersedes"] == 1
    assert revised[0]["origin"] == "correction"
    assert revised[0]["correction"] == report["correction"]["id"]
    view = ok(console, "GET", "/api/trends?point=feed_flow")
    assert view["points"]["feed_flow"]["latest"]["average"] == 40.0
    assert view["points"]["feed_flow"]["untrusted"][0]["reason"] == "gap"
    assert after["corrections"][0]["revised"] == [5]
    assert ok(console, "GET", "/api/trends/reconcile?point=feed_flow")["consistent"] is True


def test_backfill_replay_is_a_no_op(console, services):
    collect(console, {"feed_flow": 10})
    collect(console, {"feed_flow": 20})
    collect(console, {"feed_flow": 40}, tick=4)
    batch = {"point": "feed_flow", "samples": [{"tick": 3, "value": 30}]}
    first = ok(console, "POST", "/api/trends/backfill", batch)
    assert first["applied"] == 1
    checksum = services.store.checksum()
    events = services.plant.event_count()
    replay = ok(console, "POST", "/api/trends/backfill", batch)
    assert replay["applied"] == 0
    assert replay["duplicates"] == 1
    assert replay["correction"] is None
    assert services.store.checksum() == checksum
    assert services.plant.event_count() == events


def test_backfill_contradicting_a_committed_reading_is_refused(console):
    collect(console, {"feed_flow": 10})
    collect(console, {"feed_flow": 20})
    response = refused(
        console,
        "POST",
        "/api/trends/backfill",
        {"point": "feed_flow", "samples": [{"tick": 1, "value": 99}]},
    )
    assert response.status == 409
    assert "already holds" in response.body["error"]


def test_backfill_beyond_the_sampler_horizon_is_refused(console):
    collect(console, {"feed_flow": 10})
    response = refused(
        console,
        "POST",
        "/api/trends/backfill",
        {"point": "feed_flow", "samples": [{"tick": 99, "value": 1}]},
    )
    assert response.status == 409
    assert "horizon" in response.body["error"]


def test_reconcile_flags_a_tampered_trend(console, services):
    collect(console, {"feed_flow": 10})
    collect(console, {"feed_flow": 20})
    assert ok(console, "GET", "/api/trends/reconcile?point=feed_flow")["consistent"] is True
    row = dict(services.store.require(keys.trend_published_key("feed_flow", 2, 1)))
    row["average"] = 999.0
    services.store.put(keys.trend_published_key("feed_flow", 2, 1), row)
    report = ok(console, "GET", "/api/trends/reconcile?point=feed_flow")
    assert report["consistent"] is False
    assert report["mismatches"][0]["tick"] == 2
    assert report["mismatches"][0]["field"] == "average"
    assert report["mismatches"][0]["published"] == 999.0


def test_trends_survive_a_restart(config):
    first = build(config)
    collect(first.console, {"feed_flow": 10})
    collect(first.console, {"feed_flow": 20})
    reopened = build(config)
    view = ok(reopened.console, "GET", "/api/trends?point=feed_flow")
    assert view["points"]["feed_flow"]["latest"]["average"] == 15.0
    report = collect(reopened.console, {"feed_flow": 30})
    assert report["tick"] == 3
    assert report["outcomes"]["feed_flow"]["status"] == "committed"
    history = ok(reopened.console, "GET", "/api/trends/history?point=feed_flow")
    assert [row["tick"] for row in history["versions"]] == [1, 2, 3]


def test_unknown_point_is_not_found(console):
    response = refused(console, "GET", "/api/trends?point=nope")
    assert response.status == 404
    response = refused(console, "POST", "/api/trends/collect", {"values": {"nope": 1}})
    assert response.status == 404
    response = refused(console, "GET", "/api/trends/history?point=nope")
    assert response.status == 404


def test_history_and_reconcile_need_a_point(console):
    assert refused(console, "GET", "/api/trends/history").status == 400
    assert refused(console, "GET", "/api/trends/reconcile").status == 400


def test_malformed_trend_requests_are_refused(console):
    assert call(console, "POST", "/api/trends/collect", {"values": {"feed_flow": "x"}}).status == 400
    assert call(console, "POST", "/api/trends/collect", {"values": {"feed_flow": 1}, "tick": 0}).status == 400
    assert call(console, "POST", "/api/trends/backfill", {"point": "feed_flow"}).status == 400
    assert call(console, "POST", "/api/trends/backfill", {"samples": []}).status == 400
    bad_tick = {"point": "feed_flow", "samples": [{"tick": -1, "value": 1}]}
    assert call(console, "POST", "/api/trends/backfill", bad_tick).status == 400
    empty = {"point": "feed_flow", "samples": []}
    assert call(console, "POST", "/api/trends/backfill", empty).status == 400


def test_trend_routes_are_registered(console):
    routes = console.routes()
    assert ("GET", "/api/trends") in routes
    assert ("GET", "/api/trends/history") in routes
    assert ("GET", "/api/trends/reconcile") in routes
    assert ("POST", "/api/trends/collect") in routes
    assert ("POST", "/api/trends/backfill") in routes


def test_audit_record_covers_the_trend_lifecycle(console):
    collect(console, {"feed_flow": 10})
    collect(console, {"feed_flow": 20})
    collect(console, {"feed_flow": 40}, tick=4)
    ok(
        console,
        "POST",
        "/api/trends/backfill",
        {"point": "feed_flow", "samples": [{"tick": 3, "value": 30}]},
    )
    collect(console, {"feed_flow": 50}, tick=2)
    kinds = [event["kind"] for event in ok(console, "GET", "/api/events")["events"]]
    assert "trend_collect" in kinds
    assert "trend_untrusted" in kinds
    assert "trend_backfill" in kinds
    assert "trend_correction" in kinds


def test_evaluate_series_excludes_untrusted_and_heals_gaps():
    point = spec("feed_flow")
    samples = tuple(
        Sample(point="feed_flow", tick=tick, value=value, origin=origin)
        for tick, value, origin in (
            (1, 10.0, LIVE),
            (2, 20.0, LIVE),
            (3, 30.0, LIVE),
            (5, 50.0, LIVE),
        )
    )
    gap = UntrustedSegment(point="feed_flow", start=4, end=4, reason=GAP, sequence=1)
    drafts = compute.evaluate_series(point, samples, (gap,), 1, 3, (5,))
    assert drafts[0].average == pytest.approx(100.0 / 3.0)
    assert drafts[0].trusted is False
    healed = samples + (Sample(point="feed_flow", tick=4, value=40.0, origin=BACKFILL),)
    drafts = compute.evaluate_series(point, healed, (gap,), 1, 3, (5,))
    assert drafts[0].average == 40.0
    assert drafts[0].trusted is True
    regression = UntrustedSegment(point="feed_flow", start=2, end=3, reason=REGRESSION, sequence=2)
    drafts = compute.evaluate_series(point, samples, (regression,), 1, 3, (3, 5))
    assert drafts[0].average == 10.0
    assert drafts[0].trusted is False
    assert drafts[1].average == pytest.approx(30.0)


def test_journal_resumes_the_sampler_clock(store):
    from desalplant.audit.recorder import Recorder
    from desalplant.trend.service import TrendService

    service = TrendService(store, Recorder(store))
    service.collect({"feed_flow": 10})
    service.collect({"feed_flow": 20})
    resumed = TrendService(store, Recorder(store))
    assert resumed.tick == 2
    report = resumed.collect({"feed_flow": 30})
    assert report["tick"] == 3
    assert journal.clock_tick(store) == 3
