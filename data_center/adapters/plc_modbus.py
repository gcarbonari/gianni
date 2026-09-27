"""Adapter Modbus PLC: riusa plc_monitor e pubblica i segnali sul bus."""

from __future__ import annotations

import time
from typing import Any

from data_center.adapter import ProtocolAdapter
from data_center.models import Quality, TagUpdate
from plc_monitor.client import PlcClient, PlcReadError
from plc_monitor.config import load_config, with_plc
from plc_monitor.simulator import SimulatorThread


class PlcModbusAdapter(ProtocolAdapter):
    type_name = "plc_modbus"

    def __init__(self, adapter_id: str, config: dict[str, Any], bus: Any) -> None:
        super().__init__(adapter_id, config, bus)
        cfg_path = str(config.get("config") or "config.yaml")
        self.app = load_config(cfg_path)
        if config.get("host"):
            self.app = with_plc(
                self.app,
                host=config.get("host"),
                port=config.get("port"),
            )
        self.simulated = bool(config.get("simulated") or config.get("transport") == "simulated")
        self._sim: SimulatorThread | None = None

    def _run(self) -> None:
        from data_center.util import free_tcp_port

        app = self.app
        if self.simulated:
            port = free_tcp_port()
            self._sim = SimulatorThread(host="127.0.0.1", port=port)
            self._sim.start()
            app = with_plc(app, host="127.0.0.1", port=port)
        client = PlcClient(app)
        try:
            client.connect()
            while not self._halt.is_set():
                started = time.monotonic()
                try:
                    stamp, values = client.poll_once()
                    ts_ns = int(stamp * 1e9)
                    for signal in app.signals:
                        self.bus.publish(
                            TagUpdate(
                                name=self.tag_name(signal.name),
                                value=values[signal.name],
                                timestamp_ns=ts_ns,
                                source=self.id,
                                quality=Quality.GOOD,
                                unit=signal.unit,
                            )
                        )
                    self._count_frame()
                    self._count_pub(len(values))
                except PlcReadError as exc:
                    with self._lock:
                        self._error = str(exc)
                remaining = app.poll_interval - (time.monotonic() - started)
                if remaining > 0:
                    self._halt.wait(remaining)
        finally:
            client.close()
            if self._sim is not None:
                self._sim.stop()
