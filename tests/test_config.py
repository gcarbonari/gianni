from pathlib import Path

import pytest

from plc_monitor.config import load_config


def test_default_config_loads() -> None:
    cfg = load_config(Path("config.yaml"))
    assert cfg.plc.port == 502
    assert cfg.plc.host == "192.168.1.10"
    assert [s.name for s in cfg.signals] == ["Temperatura", "Pressione", "Velocita", "Allarme"]
    assert cfg.poll_interval == pytest.approx(0.2)


def test_with_plc_overrides_host() -> None:
    from plc_monitor.config import with_plc

    cfg = load_config(Path("config.yaml"))
    updated = with_plc(cfg, host="10.0.0.5", port=1502)
    assert updated.plc.host == "10.0.0.5"
    assert updated.plc.port == 1502
    assert cfg.plc.host == "192.168.1.10"


def test_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_config("non_esiste.yaml")


def test_invalid_table(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        """
plc: {host: 127.0.0.1, port: 502}
signals:
  - name: X
    table: holdingx
    address: 0
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Tabella sconosciuta"):
        load_config(path)
