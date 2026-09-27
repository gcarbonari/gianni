"""Binding TestStand: il dispositivo descrive i tag, il profilo di test sceglie il sottoinsieme.

Non si creano a mano migliaia di StationGlobals. All'avvio della sequence:

1. si carica il catalogo dal DBC/ICD del DUT
2. si applica un profilo (i segnali che QUESTO test usa)
3. si creano solo quelle proprietà (InsertIfMissing) sotto StationGlobals.DC
4. i burst 1 kHz restano DataBlock, non variabili scalari

Le sequence restano uguali da un veicolo all'altro: cambiano catalogo + profilo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from data_center.catalog import TagSpec, find_tags

# TestStand API: PropertyObject.SetVal*(lookup, options, value)
# https://www.ni.com/docs — PropOption_InsertIfMissing
PROP_INSERT_IF_MISSING = 0x400


class BindError(ValueError):
    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(
            "Nel catalogo del dispositivo mancano i tag richiesti dal test: "
            + ", ".join(missing)
        )


@dataclass(frozen=True)
class BoundSignal:
    tag: str
    ts_path: str
    kind: str
    dtype: str
    unit: str
    writable: bool
    source: str
    low: float | None = None
    high: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "ts_path": self.ts_path,
            "kind": self.kind,
            "dtype": self.dtype,
            "unit": self.unit,
            "writable": self.writable,
            "source": self.source,
            "low": self.low,
            "high": self.high,
        }


@dataclass
class TestProfile:
    name: str
    root: str = "StationGlobals.DC"
    require: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    blocks: tuple[str, ...] = ()
    limits: dict[str, dict[str, float]] = field(default_factory=dict)


def load_profile(path: str | Path) -> TestProfile:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    limits = raw.get("limits") or {}
    return TestProfile(
        name=str(raw.get("name") or Path(path).stem),
        root=str(raw.get("root") or "StationGlobals.DC"),
        require=tuple(str(x) for x in (raw.get("require") or [])),
        patterns=tuple(str(x) for x in (raw.get("patterns") or [])),
        blocks=tuple(str(x) for x in (raw.get("blocks") or [])),
        limits={str(k): dict(v) for k, v in limits.items()},
    )


def bind_profile(catalog: Iterable[TagSpec], profile: TestProfile) -> list[BoundSignal]:
    """Seleziona i tag del test e assegna il path TestStand.

    Se un tag richiesto non c'è nel DBC/ICD del DUT, fallisce subito
    (meglio in ProcessSetup che a metà sequence).
    """
    scalars = [t for t in catalog if t.kind == "scalar"]
    blocks = [t for t in catalog if t.kind == "block"]
    by_scalar = {t.name: t for t in scalars}
    by_block = {t.name: t for t in blocks}

    wanted: list[str] = list(profile.require)
    for pattern in profile.patterns:
        wanted.extend(t.name for t in find_tags(scalars, pattern))
    # uniq preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for name in wanted:
        if name not in seen:
            seen.add(name)
            ordered.append(name)

    missing = [name for name in ordered if name not in by_scalar]
    missing += [name for name in profile.blocks if name not in by_block]
    if missing:
        raise BindError(missing)

    bound: list[BoundSignal] = []
    for name in ordered:
        spec = by_scalar[name]
        lim = profile.limits.get(name) or {}
        bound.append(
            _bound(profile.root, spec, low=lim.get("min"), high=lim.get("max"))
        )
    for name in profile.blocks:
        spec = by_block[name]
        bound.append(_bound(profile.root, spec))
    return bound


def _bound(
    root: str, spec: TagSpec, low: float | None = None, high: float | None = None
) -> BoundSignal:
    return BoundSignal(
        tag=spec.name,
        ts_path=f"{root}.{spec.name}",
        kind=spec.kind,
        dtype=spec.dtype,
        unit=spec.unit,
        writable=spec.writable,
        source=spec.source,
        low=low,
        high=high,
    )


class MemoryGlobals:
    """Albero proprietà come StationGlobals (senza COM TestStand).

    Su Windows si può avvolgere lo stesso lookup string verso
    SequenceContext.StationGlobals.SetValNumber(..., InsertIfMissing, value).
    """

    def __init__(self) -> None:
        self._root: dict[str, Any] = {}

    def set_val(self, lookup: str, value: Any, *, insert: bool = True) -> None:
        parts = [p for p in lookup.split(".") if p]
        if not parts:
            raise ValueError("lookup vuoto")
        cur: dict[str, Any] = self._root
        for name in parts[:-1]:
            nxt = cur.get(name)
            if nxt is None:
                if not insert:
                    raise KeyError(lookup)
                nxt = {}
                cur[name] = nxt
            if not isinstance(nxt, dict):
                raise TypeError(f"{name} non è un container")
            cur = nxt
        leaf = parts[-1]
        if leaf not in cur and not insert:
            raise KeyError(lookup)
        cur[leaf] = value

    def get_val(self, lookup: str) -> Any:
        parts = [p for p in lookup.split(".") if p]
        cur: Any = self._root
        for name in parts:
            if not isinstance(cur, dict) or name not in cur:
                raise KeyError(lookup)
            cur = cur[name]
        return cur

    def create_from_bind(self, bound: Iterable[BoundSignal], default: float = 0.0) -> None:
        for item in bound:
            if item.kind != "scalar":
                continue
            value: Any = False if item.dtype == "boolean" else default
            self.set_val(item.ts_path, value, insert=True)

    def sync_snapshot(
        self, bound: Iterable[BoundSignal], snapshot: Mapping[str, Any]
    ) -> int:
        """Copia i valori live (tag → variabile). Ritorna quanti ne ha scritti."""
        n = 0
        for item in bound:
            if item.kind != "scalar":
                continue
            upd = snapshot.get(item.tag)
            if upd is None:
                continue
            value = upd.value if hasattr(upd, "value") else upd
            self.set_val(item.ts_path, value, insert=True)
            n += 1
        return n

    def as_dict(self) -> dict[str, Any]:
        return self._root


def check_limits(bound: Iterable[BoundSignal], snapshot: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    for item in bound:
        if item.low is None and item.high is None:
            continue
        upd = snapshot.get(item.tag)
        if upd is None:
            failures.append(f"{item.tag}: assente")
            continue
        value = float(upd.value if hasattr(upd, "value") else upd)
        if item.low is not None and value < item.low:
            failures.append(f"{item.tag}: {value} < min {item.low}")
        if item.high is not None and value > item.high:
            failures.append(f"{item.tag}: {value} > max {item.high}")
    return failures
