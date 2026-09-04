"""Caricamento config stream multi-canale (Siemens / TCP)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class StreamConfig:
    host: str = "192.168.2.100"
    port: int = 2000
    timeout: float = 3.0
    channels: int = 100
    samples_per_packet: int = 100
    sample_hz: float = 1000.0
    packet_ms: float = 100.0
    plot_channels: tuple[int, ...] = (0, 1, 2, 3)
    window_packets: int = 50
    title: str = "Stream PLC"


def load_stream_config(path: str | Path) -> StreamConfig:
    path = Path(path)
    raw_all = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw: dict[str, Any] = raw_all.get("stream") or raw_all
    plot_ch = raw.get("plot_channels", [0, 1, 2, 3])
    return StreamConfig(
        host=str(raw.get("host", StreamConfig.host)),
        port=int(raw.get("port", StreamConfig.port)),
        timeout=float(raw.get("timeout", StreamConfig.timeout)),
        channels=int(raw.get("channels", StreamConfig.channels)),
        samples_per_packet=int(
            raw.get("samples_per_packet", StreamConfig.samples_per_packet)
        ),
        sample_hz=float(raw.get("sample_hz", StreamConfig.sample_hz)),
        packet_ms=float(raw.get("packet_ms", StreamConfig.packet_ms)),
        plot_channels=tuple(int(x) for x in plot_ch),
        window_packets=int(raw.get("window_packets", StreamConfig.window_packets)),
        title=str(raw.get("title", StreamConfig.title)),
    )


def apply_stream_overrides(cfg: StreamConfig, args: Any) -> StreamConfig:
    host = getattr(args, "host", None) or cfg.host
    port = cfg.port if getattr(args, "port", None) is None else args.port
    return StreamConfig(
        host=host,
        port=port,
        timeout=cfg.timeout,
        channels=cfg.channels,
        samples_per_packet=cfg.samples_per_packet,
        sample_hz=cfg.sample_hz,
        packet_ms=cfg.packet_ms,
        plot_channels=cfg.plot_channels,
        window_packets=cfg.window_packets,
        title=cfg.title,
    )
