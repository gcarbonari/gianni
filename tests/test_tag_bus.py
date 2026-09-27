from __future__ import annotations

import time

from data_center.bus import TagBus
from data_center.models import DataBlock, Quality, TagUpdate
import numpy as np


def _upd(name: str, value: float, source: str = "a") -> TagUpdate:
    return TagUpdate(
        name=name,
        value=value,
        timestamp_ns=time.time_ns(),
        source=source,
        quality=Quality.GOOD,
        unit="u",
    )


def test_snapshot_and_history() -> None:
    bus = TagBus(history=3)
    bus.publish(_upd("veh.rpm", 1))
    bus.publish(_upd("veh.rpm", 2))
    bus.publish(_upd("veh.rpm", 3))
    bus.publish(_upd("veh.rpm", 4))
    assert bus.get("veh.rpm").value == 4
    assert [u.value for u in bus.history_of("veh.rpm")] == [2, 3, 4]


def test_subscribe_pattern_and_coalesce() -> None:
    bus = TagBus()
    sub = bus.subscribe("veh.*", min_interval_ms=10_000)
    bus.publish(_upd("veh.rpm", 1))
    bus.publish(_upd("veh.rpm", 2))
    bus.publish(_upd("avionics.heading", 3))
    first = sub.get(timeout=0.2)
    second = sub.get(timeout=0.05)
    assert first is not None and first.value == 1
    assert second is None
    bus.unsubscribe(sub)


def test_publish_block() -> None:
    bus = TagBus()
    bus.publish_block(
        DataBlock(
            name="siemens.ch00",
            samples=np.arange(4, dtype=np.float32),
            timestamp_ns=1,
            sample_hz=1000.0,
            source="s",
        )
    )
    block = bus.fetch_block("siemens.ch00")
    assert block is not None
    assert block.n_samples == 4
