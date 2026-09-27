"""Adapter CAN classico e J1939, guidato da DBC.

Transport:
  simulated  — genera frame dal DBC (nessuna scheda)
  loopback   — coda in-process, utile ai test
  hardware   — punto di innesto per Peak / Kvaser / SocketCAN (da implementare)
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Any, Protocol

from data_center.adapter import ProtocolAdapter
from data_center.dbc import CanDatabase, CanFrame, CanMessage, load_dbc
from data_center.models import Quality, TagUpdate


class CanTransport(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def recv(self, timeout: float) -> CanFrame | None: ...
    def send(self, frame: CanFrame) -> None: ...


class LoopbackCanTransport:
    def __init__(self) -> None:
        self._q: deque[CanFrame] = deque()
        self._lock = threading.Lock()
        self._not_empty = threading.Event()

    def open(self) -> None:
        return

    def close(self) -> None:
        self._not_empty.set()

    def recv(self, timeout: float) -> CanFrame | None:
        end = time.monotonic() + timeout
        while True:
            with self._lock:
                if self._q:
                    return self._q.popleft()
            remaining = end - time.monotonic()
            if remaining <= 0:
                return None
            self._not_empty.wait(timeout=remaining)
            self._not_empty.clear()

    def send(self, frame: CanFrame) -> None:
        with self._lock:
            self._q.append(frame)
            self._not_empty.set()


class SimulatedCanTransport:
    """Genera frame periodici dal DBC, con valori sinusoidali di default."""

    def __init__(self, db: CanDatabase, period_s: float = 0.02) -> None:
        self.db = db
        self.period_s = period_s
        self.values: dict[str, dict[str, float]] = {}
        self._next = 0.0
        self._msg_index = 0
        for msg in db.messages:
            self.values[msg.name] = {
                sig.name: _default_phys(sig.minimum, sig.maximum, sig.offset)
                for sig in msg.signals
            }

    def open(self) -> None:
        self._next = time.monotonic()

    def close(self) -> None:
        return

    def recv(self, timeout: float) -> CanFrame | None:
        now = time.monotonic()
        if now < self._next:
            time.sleep(min(timeout, self._next - now))
            now = time.monotonic()
            if now < self._next:
                return None
        if not self.db.messages:
            return None
        msg = self.db.messages[self._msg_index % len(self.db.messages)]
        self._msg_index += 1
        self._next = now + self.period_s / max(len(self.db.messages), 1)
        t = time.time()
        phys = dict(self.values[msg.name])
        for i, sig in enumerate(msg.signals):
            if sig.name not in phys:
                continue
            mid = _default_phys(sig.minimum, sig.maximum, sig.offset)
            span = abs((sig.maximum or (mid + 10)) - mid) or 10.0
            phys[sig.name] = mid + span * 0.25 * math.sin(t + i)
        self.values[msg.name] = phys
        frame = self.db.encode(msg, phys)
        return CanFrame(
            arbitration_id=frame.arbitration_id,
            data=frame.data,
            is_extended=frame.is_extended,
            timestamp_ns=time.time_ns(),
        )

    def send(self, frame: CanFrame) -> None:
        return


class CanJ1939Adapter(ProtocolAdapter):
    type_name = "can_j1939"

    def __init__(self, adapter_id: str, config: dict[str, Any], bus: Any) -> None:
        super().__init__(adapter_id, config, bus)
        dbc_path = config.get("dbc")
        if not dbc_path:
            raise ValueError(f"{adapter_id}: manca 'dbc'")
        self.db: CanDatabase = load_dbc(dbc_path)
        self.j1939 = str(config.get("protocol", "j1939")).lower() in {"j1939", "can_j1939"}
        self.period_s = float(config.get("period_ms", 20)) / 1000.0
        transport_name = str(config.get("transport") or config.get("bus") or "simulated")
        self.transport = self._make_transport(transport_name)
        self._writes: dict[str, float] = {}

    def _make_transport(self, name: str) -> CanTransport:
        if name in {"simulated", "sim"}:
            return SimulatedCanTransport(self.db, period_s=self.period_s)
        if name == "loopback":
            return LoopbackCanTransport()
        raise NotImplementedError(
            f"Transport CAN '{name}' non collegato. "
            "Per Peak/Kvaser/SocketCAN implementa CanTransport e registralo qui. "
            "Usa transport: simulated oppure loopback."
        )

    def _run(self) -> None:
        self.transport.open()
        try:
            while not self._halt.is_set():
                frame = self.transport.recv(timeout=0.05)
                if frame is None:
                    continue
                self._ingest(frame)
        finally:
            self.transport.close()

    def inject(self, frame: CanFrame) -> None:
        """Ingresso per test / schede custom."""
        self._ingest(frame)

    def _ingest(self, frame: CanFrame) -> None:
        self._count_frame()
        decoded = self.db.decode(frame, j1939=self.j1939)
        ts = frame.timestamp_ns or time.time_ns()
        n = 0
        for msg, sig, value, raw in decoded:
            self.bus.publish(
                TagUpdate(
                    name=self.tag_name(msg.name, sig.name),
                    value=value,
                    timestamp_ns=ts,
                    source=self.id,
                    quality=Quality.GOOD,
                    unit=sig.unit,
                    raw=raw,
                    meta={
                        "can_id": frame.arbitration_id,
                        "pgn": msg.pgn,
                        "extended": frame.is_extended,
                    },
                )
            )
            n += 1
        self._count_pub(n)

    def write(self, tag: str, value: Any) -> None:
        parts = tag.split(".")
        if len(parts) < 2:
            raise KeyError(tag)
        msg_name, sig_name = parts[-2], parts[-1]
        msg = next((m for m in self.db.messages if m.name == msg_name), None)
        if msg is None:
            raise KeyError(tag)
        sim = self.transport
        if isinstance(sim, SimulatedCanTransport):
            sim.values.setdefault(msg.name, {})[sig_name] = float(value)
            return
        current = {s.name: 0.0 for s in msg.signals}
        if isinstance(sim, LoopbackCanTransport):
            current[sig_name] = float(value)
            sim.send(self.db.encode(msg, current))
            return
        raise NotImplementedError("write su transport hardware non ancora collegato")


def _default_phys(minimum: float | None, maximum: float | None, offset: float) -> float:
    if minimum is not None and maximum is not None:
        return (minimum + maximum) / 2.0
    return offset
