"""Adapter ARINC 429 guidato da ICD YAML."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Any, Protocol

from data_center.adapter import ProtocolAdapter
from data_center.arinc429 import ArincIcd, ArincWord, load_icd
from data_center.models import Quality, TagUpdate


class ArincTransport(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def recv(self, timeout: float) -> ArincWord | None: ...
    def send(self, word: ArincWord) -> None: ...


class LoopbackArincTransport:
    def __init__(self) -> None:
        self._q: deque[ArincWord] = deque()
        self._lock = threading.Lock()
        self._not_empty = threading.Event()

    def open(self) -> None:
        return

    def close(self) -> None:
        self._not_empty.set()

    def recv(self, timeout: float) -> ArincWord | None:
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

    def send(self, word: ArincWord) -> None:
        with self._lock:
            self._q.append(word)
            self._not_empty.set()


class SimulatedArincTransport:
    def __init__(self, icd: ArincIcd) -> None:
        self.icd = icd
        self.values = {
            spec.name: _mid(spec.encoding, spec.resolution)
            for spec in icd.labels
        }
        self._due = {spec.name: 0.0 for spec in icd.labels}

    def open(self) -> None:
        now = time.monotonic()
        for spec in self.icd.labels:
            self._due[spec.name] = now

    def close(self) -> None:
        return

    def recv(self, timeout: float) -> ArincWord | None:
        deadline = time.monotonic() + timeout
        while True:
            now = time.monotonic()
            due_name = None
            due_at = None
            for spec in self.icd.labels:
                t = self._due[spec.name]
                if due_at is None or t < due_at:
                    due_at = t
                    due_name = spec.name
            if due_name is None or due_at is None:
                return None
            if now < due_at:
                sleep_s = min(due_at - now, deadline - now)
                if sleep_s <= 0:
                    return None
                time.sleep(sleep_s)
                continue
            spec = self.icd.get_by_name(due_name)
            if spec is None:
                return None
            self._due[due_name] = now + spec.period_ms / 1000.0
            t = time.time()
            base = self.values.get(spec.name, 0.0)
            value = base + 0.05 * abs(base or 1.0) * math.sin(t)
            word = self.icd.encode(spec, value)
            return ArincWord(word=word, timestamp_ns=time.time_ns())

    def send(self, word: ArincWord) -> None:
        return


class Arinc429Adapter(ProtocolAdapter):
    type_name = "arinc429"

    def __init__(self, adapter_id: str, config: dict[str, Any], bus: Any) -> None:
        super().__init__(adapter_id, config, bus)
        icd_path = config.get("icd")
        if not icd_path:
            raise ValueError(f"{adapter_id}: manca 'icd'")
        self.icd: ArincIcd = load_icd(icd_path)
        transport_name = str(config.get("transport") or config.get("channel") or "simulated")
        self.transport = self._make_transport(transport_name)

    def _make_transport(self, name: str) -> ArincTransport:
        if name in {"simulated", "sim"}:
            return SimulatedArincTransport(self.icd)
        if name == "loopback":
            return LoopbackArincTransport()
        raise NotImplementedError(
            f"Transport ARINC '{name}' non collegato. "
            "Per schede AIT/Ballard/Condor implementa ArincTransport. "
            "Usa transport: simulated oppure loopback."
        )

    def _run(self) -> None:
        self.transport.open()
        try:
            while not self._halt.is_set():
                word = self.transport.recv(timeout=0.05)
                if word is None:
                    continue
                self._ingest(word)
        finally:
            self.transport.close()

    def inject(self, word: ArincWord) -> None:
        self._ingest(word)

    def _ingest(self, word: ArincWord) -> None:
        self._count_frame()
        decoded = self.icd.decode(word)
        if decoded is None:
            return
        spec, value, fields = decoded
        quality = Quality.GOOD if fields["parity_ok"] and fields["ssm"] == 0b11 else Quality.UNCERTAIN
        if not fields["parity_ok"]:
            quality = Quality.BAD
        self.bus.publish(
            TagUpdate(
                name=self.tag_name(spec.name),
                value=value,
                timestamp_ns=word.timestamp_ns or time.time_ns(),
                source=self.id,
                quality=quality,
                unit=spec.unit,
                raw=word.word,
                meta={
                    "label": spec.octal_text,
                    "sdi": fields["sdi"],
                    "ssm": fields["ssm"],
                    "encoding": spec.encoding,
                },
            )
        )
        self._count_pub()

    def write(self, tag: str, value: Any) -> None:
        name = tag.split(".")[-1]
        spec = self.icd.get_by_name(name)
        if spec is None:
            raise KeyError(tag)
        if isinstance(self.transport, SimulatedArincTransport):
            self.transport.values[spec.name] = float(value)
            return
        if isinstance(self.transport, LoopbackArincTransport):
            packed = self.icd.encode(spec, float(value))
            self.transport.send(ArincWord(word=packed, timestamp_ns=time.time_ns()))
            return
        raise NotImplementedError("write su transport hardware non ancora collegato")


def _mid(encoding: str, resolution: float) -> float:
    if encoding == "bnr":
        return 10.0 * resolution * 100
    if encoding == "bcd":
        return 123.0
    return 1.0
