"""Contratto di un modulo protocollo innestabile nel data center."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any

from data_center.bus import TagBus
from data_center.models import Health


class ProtocolAdapter(ABC):
    """Un adapter = un bus di campo + un database (DBC / ICD / YAML PLC).

    Gira in un thread proprio. Non deve conoscere i client: pubblica sul TagBus.
    """

    type_name: str = "base"

    def __init__(self, adapter_id: str, config: dict[str, Any], bus: TagBus) -> None:
        self.id = adapter_id
        self.config = config
        self.bus = bus
        self.prefix = str(config.get("prefix") or adapter_id)
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: str | None = None
        self._frames = 0
        self._publishes = 0
        self._lock = threading.Lock()

    def tag_name(self, *parts: str) -> str:
        clean = [self.prefix, *[p.replace(" ", "_") for p in parts if p]]
        return ".".join(clean)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._halt.clear()
        self._thread = threading.Thread(
            target=self._guarded_run, name=f"dc-{self.type_name}-{self.id}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._halt.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def _guarded_run(self) -> None:
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001 — l'adapter non deve far cadere il data center
            with self._lock:
                self._error = str(exc)

    @abstractmethod
    def _run(self) -> None:
        raise NotImplementedError

    def write(self, tag: str, value: Any) -> None:
        raise NotImplementedError(f"{self.type_name} non supporta la scrittura di {tag}")

    def health(self) -> Health:
        with self._lock:
            error = self._error
            frames = self._frames
            publishes = self._publishes
        running = self._thread is not None and self._thread.is_alive() and not self._halt.is_set()
        return Health(
            adapter_id=self.id,
            type_name=self.type_name,
            running=running,
            ok=error is None,
            error=error,
            frames=frames,
            publishes=publishes,
        )

    def _count_frame(self) -> None:
        with self._lock:
            self._frames += 1

    def _count_pub(self, n: int = 1) -> None:
        with self._lock:
            self._publishes += n
