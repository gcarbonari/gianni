from __future__ import annotations

import json
import socket
import time
from pathlib import Path

from data_center.config import load_datacenter_config
from data_center.runtime import DataCenter
from data_center.util import free_tcp_port


def _write_config(tmp_path: Path) -> Path:
    root = Path(__file__).resolve().parents[1]
    port = free_tcp_port()
    text = f"""
data_center:
  name: test
  history: 32
  stale_ms: 0
  gateway:
    enabled: true
    host: 127.0.0.1
    port: {port}

adapters:
  - id: can_vehicle
    type: can_j1939
    prefix: veh
    dbc: {root / "databases" / "vehicle.dbc"}
    protocol: j1939
    transport: simulated
    period_ms: 10
  - id: arinc_avionics
    type: arinc429
    prefix: avionics
    icd: {root / "databases" / "arinc429.yaml"}
    transport: simulated
"""
    path = tmp_path / "dc.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_repo_config() -> None:
    cfg = load_datacenter_config("config.datacenter.yaml")
    types = [a.type for a in cfg.adapters if a.enabled]
    assert "can_j1939" in types
    assert "arinc429" in types
    assert Path(cfg.adapters[0].options["dbc"]).name == "vehicle.dbc"


def test_simulated_datacenter_and_json_gateway(tmp_path: Path) -> None:
    path = _write_config(tmp_path)
    dc = DataCenter.from_file(str(path))
    dc.start()
    try:
        assert dc.wait_tags(count=4, timeout=4.0)
        snap = dc.bus.snapshot("veh.*")
        assert any(name.endswith("EngineSpeed") for name in snap)
        assert dc.bus.get("avionics.heading") is not None
        health = {item.adapter_id: item for item in dc.health()}
        assert health["can_vehicle"].running
        assert health["arinc_avionics"].ok

        gw = dc.gateway
        assert gw is not None
        sock = socket.create_connection((gw.host, gw.port), timeout=2)
        sock.sendall(b'{"op":"snapshot","pattern":"avionics.*"}\n')
        line = b""
        sock.settimeout(2)
        while b"\n" not in line:
            chunk = sock.recv(4096)
            assert chunk
            line += chunk
        payload = json.loads(line.split(b"\n", 1)[0])
        sock.close()
        assert payload["op"] == "snapshot"
        names = {tag["name"] for tag in payload["tags"]}
        assert "avionics.heading" in names
    finally:
        dc.stop()
        time.sleep(0.1)
