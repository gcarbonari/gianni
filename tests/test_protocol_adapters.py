from __future__ import annotations

import time

from data_center.adapters.arinc429 import Arinc429Adapter, LoopbackArincTransport
from data_center.adapters.can_j1939 import CanJ1939Adapter, LoopbackCanTransport
from data_center.arinc429 import ArincWord
from data_center.bus import TagBus
from data_center.dbc import load_dbc


def test_can_loopback_publishes_j1939_tags() -> None:
    bus = TagBus()
    adapter = CanJ1939Adapter(
        "can_vehicle",
        {
            "prefix": "veh",
            "dbc": "databases/vehicle.dbc",
            "protocol": "j1939",
            "transport": "loopback",
        },
        bus,
    )
    db = load_dbc("databases/vehicle.dbc")
    eec1 = next(m for m in db.messages if m.name == "EEC1")
    frame = db.encode(eec1, {"EngineSpeed": 1250.0, "EngineTorque": 20.0})
    assert isinstance(adapter.transport, LoopbackCanTransport)
    adapter.start()
    adapter.transport.send(frame)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not bus.get("veh.EEC1.EngineSpeed"):
        time.sleep(0.02)
    adapter.stop()
    rpm = bus.get("veh.EEC1.EngineSpeed")
    assert rpm is not None
    assert rpm.value == 1250.0
    assert rpm.unit == "rpm"
    assert rpm.meta["pgn"] == 61444


def test_arinc_loopback_publishes_heading() -> None:
    bus = TagBus()
    adapter = Arinc429Adapter(
        "arinc_avionics",
        {
            "prefix": "avionics",
            "icd": "databases/arinc429.yaml",
            "transport": "loopback",
        },
        bus,
    )
    spec = adapter.icd.get_by_name("heading")
    assert spec is not None
    word = ArincWord(word=adapter.icd.encode(spec, 90.0), timestamp_ns=time.time_ns())
    assert isinstance(adapter.transport, LoopbackArincTransport)
    adapter.start()
    adapter.transport.send(word)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not bus.get("avionics.heading"):
        time.sleep(0.02)
    adapter.stop()
    tag = bus.get("avionics.heading")
    assert tag is not None
    assert tag.value == 90.0
    assert tag.meta["label"] == "206"
