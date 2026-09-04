from __future__ import annotations

import socket
import time
from pathlib import Path

import pytest
import yaml

from plc_monitor.client import PlcClient
from plc_monitor.config import load_config
from plc_monitor.plotter import run_plot
from plc_monitor.sampler import Poller, SampleBuffer
from plc_monitor.simulator import SimulatorThread, synthetic_values


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def sim_config(tmp_path: Path):
    port = _free_port()
    source = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    source["plc"]["host"] = "127.0.0.1"
    source["plc"]["port"] = port
    source["plc"]["poll_ms"] = 50
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(source), encoding="utf-8")
    sim = SimulatorThread(host="127.0.0.1", port=port)
    sim.start()
    try:
        yield load_config(path)
    finally:
        sim.stop()


def test_read_live_signals(sim_config) -> None:
    client = PlcClient(sim_config)
    client.connect()
    try:
        first = client.read_all()
        time.sleep(0.4)
        second = client.read_all()
    finally:
        client.close()

    assert set(first) == {"Temperatura", "Pressione", "Velocita", "Allarme"}
    assert 10 < first["Temperatura"] < 35
    assert 0.5 < first["Pressione"] < 3.0
    assert 200 < first["Velocita"] < 1400
    assert first["Allarme"] in (0.0, 1.0)
    # il seno del simulatore deve muoversi
    assert first["Temperatura"] != pytest.approx(second["Temperatura"], abs=1e-6)


def test_synthetic_alarm_duty() -> None:
    assert synthetic_values(1.0)["Allarme"] is False
    assert synthetic_values(10.0)["Allarme"] is True


def test_plot_png(sim_config, tmp_path: Path) -> None:
    names = tuple(s.name for s in sim_config.signals)
    buffer = SampleBuffer(names, sim_config.plot.window_seconds)
    client = PlcClient(sim_config)
    client.connect()
    poller = Poller(client, sim_config, buffer)
    poller.start()
    try:
        out = tmp_path / "segnali.png"
        saved = run_plot(sim_config, buffer, save_path=str(out), seconds=1.2)
        assert saved is not None and saved.exists()
        assert saved.stat().st_size > 1000
        assert buffer.sample_count >= 3
    finally:
        poller.stop()
        poller.join(timeout=2)
        client.close()
