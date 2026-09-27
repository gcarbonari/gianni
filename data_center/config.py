"""Caricamento YAML del data center."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from data_center.util import resolve_path

_PATH_KEYS = ("dbc", "icd", "config")


@dataclass(frozen=True)
class AdapterSpec:
    id: str
    type: str
    enabled: bool = True
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GatewaySpec:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8765


@dataclass(frozen=True)
class DataCenterConfig:
    name: str = "data-center"
    history: int = 512
    stale_ms: int = 2000
    gateway: GatewaySpec = field(default_factory=GatewaySpec)
    adapters: tuple[AdapterSpec, ...] = ()
    source_path: Path | None = None


def load_datacenter_config(path: str | Path) -> DataCenterConfig:
    path = Path(path).resolve()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    dc = raw.get("data_center") or {}
    gw_raw = dc.get("gateway") or raw.get("gateway") or {}
    base = path.parent
    adapters: list[AdapterSpec] = []
    for i, item in enumerate(raw.get("adapters") or []):
        adapter_id = str(item.get("id") or f"adapter{i}")
        type_name = str(item.get("type") or "")
        if not type_name:
            raise ValueError(f"adapters[{i}] ({adapter_id}): manca 'type'")
        options = {
            key: value
            for key, value in item.items()
            if key not in {"id", "type", "enabled"}
        }
        for key in _PATH_KEYS:
            if key in options and options[key]:
                options[key] = str(resolve_path(options[key], base))
        adapters.append(
            AdapterSpec(
                id=adapter_id,
                type=type_name,
                enabled=bool(item.get("enabled", True)),
                options=options,
            )
        )
    return DataCenterConfig(
        name=str(dc.get("name", DataCenterConfig.name)),
        history=int(dc.get("history", DataCenterConfig.history)),
        stale_ms=int(dc.get("stale_ms", DataCenterConfig.stale_ms)),
        gateway=GatewaySpec(
            enabled=bool(gw_raw.get("enabled", True)),
            host=str(gw_raw.get("host", GatewaySpec.host)),
            port=int(gw_raw.get("port", GatewaySpec.port)),
        ),
        adapters=tuple(adapters),
        source_path=path,
    )
