"""Catalogo tag dal database del dispositivo (DBC / ICD / YAML), senza hardware.

È la fonte da cui HMI e TestStand scoprono i segnali. Cambia il DBC → cambia
il catalogo; le sequence non elencano a mano migliaia di variabili.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from data_center.config import AdapterSpec, DataCenterConfig
from data_center.registry import get_adapter_class


@dataclass(frozen=True)
class TagSpec:
    name: str
    source: str
    kind: str  # scalar | block
    dtype: str  # number | boolean
    unit: str = ""
    writable: bool = False
    adapter_type: str = ""
    meta: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["meta"] = dict(self.meta or {})
        return payload


def catalog_from_config(
    config: DataCenterConfig, *, include_disabled: bool = False
) -> list[TagSpec]:
    tags: list[TagSpec] = []
    for spec in config.adapters:
        if not spec.enabled and not include_disabled:
            continue
        tags.extend(catalog_from_adapter(spec))
    return tags


def catalog_from_adapter(spec: AdapterSpec) -> list[TagSpec]:
    type_name = spec.type.strip().lower()
    # risolve gli alias (can → can_j1939, …)
    cls = get_adapter_class(type_name)
    kind = cls.type_name
    prefix = str(spec.options.get("prefix") or spec.id)
    if kind == "can_j1939":
        return _from_dbc(spec, prefix)
    if kind == "arinc429":
        return _from_icd(spec, prefix)
    if kind == "plc_modbus":
        return _from_plc_modbus(spec, prefix)
    if kind == "plc_stream":
        return _from_plc_stream(spec, prefix)
    return []


def find_tags(catalog: Iterable[TagSpec], pattern: str) -> list[TagSpec]:
    import fnmatch

    return [tag for tag in catalog if fnmatch.fnmatchcase(tag.name, pattern)]


def _from_dbc(spec: AdapterSpec, prefix: str) -> list[TagSpec]:
    from data_center.dbc import load_dbc

    dbc = spec.options.get("dbc")
    if not dbc:
        return []
    db = load_dbc(dbc)
    tags: list[TagSpec] = []
    for msg in db.messages:
        for sig in msg.signals:
            tags.append(
                TagSpec(
                    name=f"{prefix}.{msg.name}.{sig.name}",
                    source=spec.id,
                    kind="scalar",
                    dtype="number",
                    unit=sig.unit,
                    writable=True,
                    adapter_type="can_j1939",
                    meta={
                        "message": msg.name,
                        "signal": sig.name,
                        "pgn": msg.pgn,
                        "can_id": msg.frame_id,
                    },
                )
            )
    return tags


def _from_icd(spec: AdapterSpec, prefix: str) -> list[TagSpec]:
    from data_center.arinc429 import load_icd

    icd_path = spec.options.get("icd")
    if not icd_path:
        return []
    icd = load_icd(icd_path)
    tags: list[TagSpec] = []
    for label in icd.labels:
        tags.append(
            TagSpec(
                name=f"{prefix}.{label.name}",
                source=spec.id,
                kind="scalar",
                dtype="number",
                unit=label.unit,
                writable=True,
                adapter_type="arinc429",
                meta={"label": label.octal_text, "encoding": label.encoding},
            )
        )
    return tags


def _from_plc_modbus(spec: AdapterSpec, prefix: str) -> list[TagSpec]:
    from plc_monitor.config import load_config

    path = spec.options.get("config")
    if not path:
        return []
    app = load_config(path)
    tags: list[TagSpec] = []
    for signal in app.signals:
        dtype = "boolean" if signal.dtype == "bool" else "number"
        tags.append(
            TagSpec(
                name=f"{prefix}.{signal.name}",
                source=spec.id,
                kind="scalar",
                dtype=dtype,
                unit=signal.unit,
                writable=True,
                adapter_type="plc_modbus",
                meta={"table": signal.table, "address": signal.address},
            )
        )
    return tags


def _from_plc_stream(spec: AdapterSpec, prefix: str) -> list[TagSpec]:
    from plc_monitor.stream_config import load_stream_config

    path = spec.options.get("config")
    if not path:
        return []
    stream = load_stream_config(path)
    channels = tuple(spec.options.get("plot_channels") or stream.plot_channels)
    tags: list[TagSpec] = [
        TagSpec(
            name=f"{prefix}.packet.seq",
            source=spec.id,
            kind="scalar",
            dtype="number",
            writable=False,
            adapter_type="plc_stream",
        )
    ]
    for ch in channels:
        name = f"{prefix}.ch{int(ch):02d}"
        tags.append(
            TagSpec(
                name=name,
                source=spec.id,
                kind="scalar",
                dtype="number",
                writable=False,
                adapter_type="plc_stream",
                meta={"channel": int(ch), "sample_hz": stream.sample_hz},
            )
        )
        tags.append(
            TagSpec(
                name=name,
                source=spec.id,
                kind="block",
                dtype="number",
                writable=False,
                adapter_type="plc_stream",
                meta={"channel": int(ch), "sample_hz": stream.sample_hz},
            )
        )
    return tags
