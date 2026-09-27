"""Runtime del data center: carica i moduli e li collega al bus."""

from __future__ import annotations

import threading
import time
from typing import Any

from data_center.adapter import ProtocolAdapter
from data_center.bus import TagBus
from data_center.config import DataCenterConfig, load_datacenter_config
from data_center.gateway import JsonLinesGateway
from data_center.models import Health
from data_center.registry import get_adapter_class


class DataCenter:
    def __init__(self, config: DataCenterConfig) -> None:
        self.config = config
        self.bus = TagBus(history=config.history)
        self.adapters: list[ProtocolAdapter] = []
        self.gateway: JsonLinesGateway | None = None
        self._halt = threading.Event()
        self._stale_thread: threading.Thread | None = None

    @classmethod
    def from_file(cls, path: str) -> DataCenter:
        return cls(load_datacenter_config(path))

    def start(self) -> None:
        for spec in self.config.adapters:
            if not spec.enabled:
                continue
            cls = get_adapter_class(spec.type)
            adapter = cls(spec.id, spec.options, self.bus)
            adapter.start()
            self.adapters.append(adapter)
        if self.config.gateway.enabled:
            gw = JsonLinesGateway(
                self.bus, host=self.config.gateway.host, port=self.config.gateway.port
            )
            gw.bind_handlers(health=self.health, write=self.write)
            gw.start_ready()
            self.gateway = gw
        if self.config.stale_ms > 0:
            self._stale_thread = threading.Thread(
                target=self._stale_loop, name="dc-stale", daemon=True
            )
            self._stale_thread.start()

    def stop(self) -> None:
        self._halt.set()
        for adapter in self.adapters:
            adapter.stop()
        if self.gateway is not None:
            self.gateway.stop()

    def health(self) -> list[Health]:
        return [adapter.health() for adapter in self.adapters]

    def write(self, tag: str, value: Any) -> None:
        prefix = tag.split(".", 1)[0]
        for adapter in self.adapters:
            if adapter.prefix == prefix or adapter.id == prefix:
                adapter.write(tag, value)
                return
        raise KeyError(f"Nessun adapter per il tag {tag}")

    def wait_tags(self, count: int = 1, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.bus.snapshot()) >= count:
                return True
            time.sleep(0.05)
        return False

    def _stale_loop(self) -> None:
        interval = max(self.config.stale_ms, 200) / 1000.0
        older = int(self.config.stale_ms * 1e6)
        while not self._halt.wait(interval):
            self.bus.mark_stale(older_than_ns=older)
