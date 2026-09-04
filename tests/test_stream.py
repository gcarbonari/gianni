from __future__ import annotations

import socket
import time
from pathlib import Path

import pytest
import yaml

from plc_monitor.cli import main
from plc_monitor.stream_client import PacketBuffer, StreamClient
from plc_monitor.stream_config import load_stream_config
from plc_monitor.stream_sim import PacketStreamServer


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def stream_pair(tmp_path: Path):
    port = _free_port()
    server = PacketStreamServer(
        host="127.0.0.1",
        port=port,
        channels=8,
        samples=10,
        sample_hz=1000.0,
        packet_ms=20.0,
    )
    server.start_ready()
    buffer = PacketBuffer(maxlen=100)
    client = StreamClient(
        "127.0.0.1",
        port,
        buffer,
        timeout=2.0,
        expected_channels=8,
        expected_samples=10,
    )
    client.start()
    try:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and buffer.stats.packets < 3:
            time.sleep(0.05)
        yield buffer, port, tmp_path
    finally:
        client.stop()
        client.join(timeout=2)
        server.stop()


def test_stream_sim_delivers_packets(stream_pair) -> None:
    buffer, _port, _tmp = stream_pair
    packets, stats = buffer.snapshot()
    assert stats.packets >= 3
    assert stats.gaps == 0
    assert packets[-1].channels == 8
    assert packets[-1].samples == 10
    assert packets[-1].timestamp_ns > 0
    assert stats.last_seq is not None
    assert stats.rate_hz > 0


def test_stream_config_siemens_defaults() -> None:
    cfg = load_stream_config("config.siemens.yaml")
    assert cfg.host == "192.168.2.100"
    assert cfg.port == 2000
    assert cfg.channels == 100
    assert cfg.samples_per_packet == 100
    assert cfg.sample_hz == 1000.0
    assert cfg.packet_ms == 100.0


def test_cli_stream_demo_headless(tmp_path: Path) -> None:
    port = _free_port()
    source = yaml.safe_load(Path("config.siemens.yaml").read_text(encoding="utf-8"))
    source["stream"]["host"] = "127.0.0.1"
    source["stream"]["port"] = port
    source["stream"]["channels"] = 4
    source["stream"]["samples_per_packet"] = 10
    source["stream"]["packet_ms"] = 20
    source["stream"]["plot_channels"] = [0, 1]
    cfg_path = tmp_path / "stream.yaml"
    cfg_path.write_text(yaml.safe_dump(source), encoding="utf-8")
    out = tmp_path / "stream.png"
    rc = main(
        [
            "stream-demo",
            "-c",
            str(cfg_path),
            "--seconds",
            "0.8",
            "--save",
            str(out),
        ]
    )
    assert rc == 0
    assert out.exists()
    assert out.stat().st_size > 1000
