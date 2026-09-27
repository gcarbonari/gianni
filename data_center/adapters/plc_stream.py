"""Adapter stream Siemens: pacchetti 100 ch @ 1 kHz → tag + DataBlock."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from data_center.adapter import ProtocolAdapter
from data_center.models import DataBlock, Quality, TagUpdate
from plc_monitor.stream_client import PacketBuffer, StreamClient
from plc_monitor.stream_config import load_stream_config
from plc_monitor.stream_sim import PacketStreamServer


class PlcStreamAdapter(ProtocolAdapter):
    type_name = "plc_stream"

    def __init__(self, adapter_id: str, config: dict[str, Any], bus: Any) -> None:
        super().__init__(adapter_id, config, bus)
        cfg_path = str(config.get("config") or "config.siemens.yaml")
        self.stream = load_stream_config(cfg_path)
        changes = {}
        if config.get("host"):
            changes["host"] = str(config["host"])
        if config.get("port"):
            changes["port"] = int(config["port"])
        if changes:
            self.stream = replace(self.stream, **changes)
        self.simulated = bool(config.get("simulated") or config.get("transport") == "simulated")
        self.plot_channels = tuple(
            config.get("plot_channels") or getattr(self.stream, "plot_channels", (0, 1, 2, 3))
        )
        self._server: PacketStreamServer | None = None

    def _run(self) -> None:
        host, port = self.stream.host, self.stream.port
        if self.simulated:
            self._server = PacketStreamServer(
                host="127.0.0.1",
                port=0,
                channels=self.stream.channels,
                samples=self.stream.samples_per_packet,
                sample_hz=self.stream.sample_hz,
                packet_ms=self.stream.packet_ms,
            )
            self._server.start_ready()
            host, port = self._server.host, self._server.port
        buffer = PacketBuffer()
        client = StreamClient(
            host,
            port,
            buffer,
            expected_channels=self.stream.channels,
            expected_samples=self.stream.samples_per_packet,
        )
        client.start()
        last_seq: int | None = None
        try:
            while not self._halt.is_set():
                packet = buffer.latest()
                if packet is None or packet.sequence == last_seq:
                    self._halt.wait(0.02)
                    continue
                last_seq = packet.sequence
                self._count_frame()
                ts = packet.timestamp_ns
                n = 0
                for ch in self.plot_channels:
                    if ch >= packet.channels:
                        continue
                    samples = packet.data[ch]
                    last = float(samples[-1])
                    self.bus.publish(
                        TagUpdate(
                            name=self.tag_name(f"ch{ch:02d}"),
                            value=last,
                            timestamp_ns=ts,
                            source=self.id,
                            quality=Quality.GOOD,
                            unit="",
                            meta={"sequence": packet.sequence, "n_samples": packet.samples},
                        )
                    )
                    self.bus.publish_block(
                        DataBlock(
                            name=self.tag_name(f"ch{ch:02d}"),
                            samples=samples.copy(),
                            timestamp_ns=ts,
                            sample_hz=float(self.stream.sample_hz),
                            source=self.id,
                        )
                    )
                    n += 1
                self.bus.publish(
                    TagUpdate(
                        name=self.tag_name("packet", "seq"),
                        value=packet.sequence,
                        timestamp_ns=ts,
                        source=self.id,
                        quality=Quality.GOOD,
                    )
                )
                self._count_pub(n + 1)
        finally:
            client.stop()
            client.join(timeout=2.0)
            if self._server is not None:
                self._server.stop()
