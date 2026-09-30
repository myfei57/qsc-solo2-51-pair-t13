"""Operations that change the state of the line."""

from .http import Request, Response, json_response


def start(console, request: Request) -> Response:
    """Bring the line up."""
    request.body()
    event = console.plant.start()
    return json_response({"status": "started", "event": event.to_dict()})


def shutdown(console, request: Request) -> Response:
    """Stop the line."""
    request.body()
    event = console.plant.shutdown()
    return json_response({"status": "stopped", "event": event.to_dict()})


def switch(console, request: Request) -> Response:
    """Move production to the standby tank."""
    request.body()
    event = console.plant.switch_tank()
    return json_response({"status": "switched", "event": event.to_dict()})


def maintain(console, request: Request) -> Response:
    """Run the maintenance routine."""
    request.body()
    event = console.plant.maintain()
    return json_response({"status": "maintained", "event": event.to_dict()})


def collect_trends(console, request: Request) -> Response:
    """Sample the key measurement points and publish their trends."""
    body = request.body()
    report = console.plant.collect_trends(values=body.get("values"), stamp=body.get("tick"))
    return json_response(report)


def backfill_trend(console, request: Request) -> Response:
    """Merge late samples and append corrections for the revised ticks."""
    body = request.body()
    report = console.plant.backfill_trend(body["point"], body["samples"])
    return json_response(report)
