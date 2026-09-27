"""Modello dati comune: ogni adapter pubblica TagUpdate sullo stesso bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class Quality(str, Enum):
    GOOD = "good"
    UNCERTAIN = "uncertain"
    BAD = "bad"
    STALE = "stale"


@dataclass(frozen=True)
class TagUpdate:
    """Un valore scalare normalizzato, indipendente dal bus di campo."""

    name: str
    value: Any
    timestamp_ns: int
    source: str
    quality: Quality = Quality.GOOD
    unit: str = ""
    raw: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": _jsonable(self.value),
            "timestamp_ns": self.timestamp_ns,
            "source": self.source,
            "quality": self.quality.value,
            "unit": self.unit,
            "raw": self.raw,
            "meta": self.meta,
        }


@dataclass(frozen=True)
class DataBlock:
    """Burst analogico (es. 1 kHz) da consegnare ai client on-demand."""

    name: str
    samples: np.ndarray
    timestamp_ns: int
    sample_hz: float
    source: str
    unit: str = ""

    @property
    def n_samples(self) -> int:
        return int(self.samples.size)


@dataclass(frozen=True)
class Health:
    adapter_id: str
    type_name: str
    running: bool
    ok: bool
    error: str | None = None
    frames: int = 0
    publishes: int = 0


def _jsonable(value: Any) -> Any:
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, np.generic):
        return value.item()
    return value
