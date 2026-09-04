"""Caricamento della configurazione YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TABLES = ("holding", "input", "coil", "discrete")
DTYPES = ("uint16", "int16", "uint32", "int32", "float32", "bool")
WORD_ORDERS = ("abcd", "cdab", "badc", "dcba")


@dataclass(frozen=True)
class PlcConfig:
    host: str = "127.0.0.1"
    port: int = 502
    unit_id: int = 1
    timeout: float = 2.0
    poll_ms: int = 200


@dataclass(frozen=True)
class PlotConfig:
    title: str = "Segnali PLC"
    window_seconds: float = 30.0


@dataclass(frozen=True)
class CsvConfig:
    enabled: bool = False
    path: str = "segnali.csv"


@dataclass(frozen=True)
class Signal:
    name: str
    table: str = "holding"
    address: int = 0
    dtype: str = "uint16"
    word_order: str = "abcd"
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""


@dataclass(frozen=True)
class AppConfig:
    plc: PlcConfig = field(default_factory=PlcConfig)
    plot: PlotConfig = field(default_factory=PlotConfig)
    csv: CsvConfig = field(default_factory=CsvConfig)
    signals: tuple[Signal, ...] = ()

    @property
    def poll_interval(self) -> float:
        return max(self.plc.poll_ms, 20) / 1000.0


def _require(mapping: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in mapping:
        raise ValueError(f"Manca la chiave '{key}' in {ctx}")
    return mapping[key]


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File di configurazione non trovato: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    plc_raw = raw.get("plc") or {}
    plot_raw = raw.get("plot") or {}
    csv_raw = raw.get("csv") or {}

    plc = PlcConfig(
        host=str(plc_raw.get("host", PlcConfig.host)),
        port=int(plc_raw.get("port", PlcConfig.port)),
        unit_id=int(plc_raw.get("unit_id", PlcConfig.unit_id)),
        timeout=float(plc_raw.get("timeout", PlcConfig.timeout)),
        poll_ms=int(plc_raw.get("poll_ms", PlcConfig.poll_ms)),
    )
    plot = PlotConfig(
        title=str(plot_raw.get("title", PlotConfig.title)),
        window_seconds=float(plot_raw.get("window_seconds", PlotConfig.window_seconds)),
    )
    csv = CsvConfig(
        enabled=bool(csv_raw.get("enabled", CsvConfig.enabled)),
        path=str(csv_raw.get("path", CsvConfig.path)),
    )

    signals: list[Signal] = []
    for i, item in enumerate(raw.get("signals") or []):
        name = str(_require(item, "name", f"signals[{i}]"))
        table = str(item.get("table", "holding")).lower()
        dtype = str(item.get("dtype", "uint16")).lower()
        word_order = str(item.get("word_order", "abcd")).lower()
        if table not in TABLES:
            raise ValueError(f"Tabella sconosciuta '{table}' per il segnale '{name}'")
        if dtype not in DTYPES:
            raise ValueError(f"Tipo sconosciuto '{dtype}' per il segnale '{name}'")
        if word_order not in WORD_ORDERS:
            raise ValueError(f"Word order sconosciuto '{word_order}' per il segnale '{name}'")
        if dtype == "bool" and table not in ("coil", "discrete"):
            raise ValueError(f"Il segnale '{name}' di tipo bool deve stare in coil o discrete")
        signals.append(
            Signal(
                name=name,
                table=table,
                address=int(_require(item, "address", f"signals[{i}]")),
                dtype=dtype,
                word_order=word_order,
                scale=float(item.get("scale", 1.0)),
                offset=float(item.get("offset", 0.0)),
                unit=str(item.get("unit", "")),
            )
        )

    if not signals:
        raise ValueError("Nessun segnale definito in configurazione")

    return AppConfig(plc=plc, plot=plot, csv=csv, signals=tuple(signals))
