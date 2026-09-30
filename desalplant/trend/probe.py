"""Sampling of the key measurement points from the live line.

Mirrors the telemetry sweep so a scheduled collect reads the same sources
the console telemetry reports; the sweep parameters are duplicated here to
keep the trend package free of console imports.
"""

from typing import TYPE_CHECKING, Any

from ..ro.flow import FlowCheck

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checkers
    from ..console.plant import Plant

SCREEN_UPSTREAM = 96.0
SCREEN_DOWNSTREAM = 82.0
PERMEATE_FLOW = 52.0


def sample_plant(plant: "Plant") -> dict[str, Any]:
    """Read every registered measurement point from the line once."""
    check = FlowCheck()
    values: dict[str, Any] = {"feed_flow": check.measure(plant.membrane)}
    plant.screen.measure(SCREEN_UPSTREAM, SCREEN_DOWNSTREAM)
    values["screen_delta"] = plant.screen.delta
    values["brine_recovery"] = plant.brine_stream.recover(plant.hp_pump.pressure)
    values["permeate_flow"] = plant.permeate.measure_flow(PERMEATE_FLOW).flow_rate
    values["pump_pressure"] = plant.hp_pump.pressure
    values["supply"] = plant.hp_pump.supply
    return values
