"""Codec ARINC 429 guidato da ICD YAML (label → segnale).

Word 32 bit (bit 0 = LSB, numerazione ARINC 1-based tra parentesi):
  0-7   label trasmessa LSB-first  (ARINC 1-8) — in ICD si usa l'ottale
  8-9   SDI                        (ARINC 9-10)
  10-28 data 19 bit                (ARINC 11-29)
  29-30 SSM                        (ARINC 30-31)
  31    parity dispari             (ARINC 32)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

Encoding = Literal["bnr", "bcd", "discrete"]

SSM_BNR_NORMAL = 0b11
SSM_BNR_FAIL = 0b00
SSM_BNR_NCD = 0b01
SSM_BNR_FT = 0b10


def reverse_bits8(value: int) -> int:
    value &= 0xFF
    value = ((value & 0xF0) >> 4) | ((value & 0x0F) << 4)
    value = ((value & 0xCC) >> 2) | ((value & 0x33) << 2)
    value = ((value & 0xAA) >> 1) | ((value & 0x55) << 1)
    return value


def odd_parity32(word: int) -> int:
    bits = word & 0x7FFFFFFF
    parity = 0
    while bits:
        parity ^= bits & 1
        bits >>= 1
    return 1 if parity == 0 else 0


def pack_word(*, label_octal: int, sdi: int, data: int, ssm: int, data_bits: int = 19) -> int:
    tx_label = reverse_bits8(label_octal)
    data &= (1 << data_bits) - 1
    word = tx_label | ((sdi & 0x3) << 8) | ((data & 0x7FFFF) << 10) | ((ssm & 0x3) << 29)
    word |= odd_parity32(word) << 31
    return word & 0xFFFFFFFF


def unpack_word(word: int) -> dict[str, int]:
    word &= 0xFFFFFFFF
    return {
        "label_octal": reverse_bits8(word & 0xFF),
        "sdi": (word >> 8) & 0x3,
        "data": (word >> 10) & 0x7FFFF,
        "ssm": (word >> 29) & 0x3,
        "parity": (word >> 31) & 0x1,
        "parity_ok": ((word >> 31) & 0x1) == odd_parity32(word),
    }


def encode_bnr(value: float, bits: int, resolution: float) -> int:
    if resolution == 0:
        return 0
    raw = int(round(value / resolution))
    max_s = 1 << (bits - 1)
    raw = max(-max_s, min(max_s - 1, raw))
    if raw < 0:
        raw = raw & ((1 << bits) - 1)
    return raw


def decode_bnr(raw: int, bits: int, resolution: float) -> float:
    raw &= (1 << bits) - 1
    if raw & (1 << (bits - 1)):
        raw -= 1 << bits
    return raw * resolution


def encode_bcd(value: float, digits: int, scale: float) -> int:
    n = int(round(abs(value) / scale)) if scale else 0
    raw = 0
    for i in range(digits):
        raw |= (n % 10) << (4 * i)
        n //= 10
    return raw


def decode_bcd(raw: int, digits: int, scale: float) -> float:
    n = 0
    mul = 1
    for i in range(digits):
        nibble = (raw >> (4 * i)) & 0xF
        if nibble > 9:
            nibble = 0
        n += nibble * mul
        mul *= 10
    return n * scale


@dataclass(frozen=True)
class ArincLabel:
    label_octal: int
    name: str
    encoding: Encoding
    bits: int = 19
    resolution: float = 1.0
    scale: float = 1.0
    digits: int = 5
    unit: str = ""
    sdi: int = 0
    period_ms: int = 80

    @property
    def octal_text(self) -> str:
        return f"{self.label_octal:03o}"


@dataclass(frozen=True)
class ArincWord:
    word: int
    timestamp_ns: int = 0


@dataclass(frozen=True)
class ArincIcd:
    labels: tuple[ArincLabel, ...]
    path: str | None = None

    def __post_init__(self) -> None:
        by_label = {item.label_octal: item for item in self.labels}
        by_name = {item.name: item for item in self.labels}
        object.__setattr__(self, "_by_label", by_label)
        object.__setattr__(self, "_by_name", by_name)

    def get(self, label_octal: int) -> ArincLabel | None:
        return self._by_label.get(label_octal)  # type: ignore[attr-defined]

    def get_by_name(self, name: str) -> ArincLabel | None:
        return self._by_name.get(name)  # type: ignore[attr-defined]

    def decode(self, word: ArincWord) -> tuple[ArincLabel, float, dict[str, int]] | None:
        fields = unpack_word(word.word)
        spec = self.get(fields["label_octal"])
        if spec is None:
            return None
        data = fields["data"] & ((1 << spec.bits) - 1)
        if spec.encoding == "bnr":
            value = decode_bnr(data, spec.bits, spec.resolution)
        elif spec.encoding == "bcd":
            value = decode_bcd(data, spec.digits, spec.scale)
        else:
            value = float(data)
        return spec, value, fields

    def encode(self, spec: ArincLabel, value: float, *, ssm: int = SSM_BNR_NORMAL) -> int:
        if spec.encoding == "bnr":
            data = encode_bnr(value, spec.bits, spec.resolution)
        elif spec.encoding == "bcd":
            data = encode_bcd(value, spec.digits, spec.scale)
        else:
            data = int(value) & ((1 << spec.bits) - 1)
        return pack_word(
            label_octal=spec.label_octal,
            sdi=spec.sdi,
            data=data,
            ssm=ssm,
            data_bits=spec.bits,
        )


def load_icd(path: str | Path) -> ArincIcd:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return parse_icd(raw, path=str(path))


def parse_arinc_label(value: Any) -> int:
    """Label ARINC: in ICD si scrive in ottale ('206', '0o206')."""
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    if text.startswith("0o"):
        return int(text, 8)
    if text.startswith("0x"):
        return int(text, 16)
    return int(text, 8)


def parse_icd(raw: dict[str, Any], path: str | None = None) -> ArincIcd:
    items: list[ArincLabel] = []
    for entry in raw.get("labels") or []:
        label_octal = parse_arinc_label(entry.get("label"))
        encoding = str(entry.get("encoding", "bnr")).lower()
        if encoding not in ("bnr", "bcd", "discrete"):
            raise ValueError(f"encoding ARINC sconosciuto: {encoding}")
        items.append(
            ArincLabel(
                label_octal=label_octal,
                name=str(entry["name"]),
                encoding=encoding,  # type: ignore[arg-type]
                bits=int(entry.get("bits", 19)),
                resolution=float(entry.get("resolution", 1.0)),
                scale=float(entry.get("scale", 1.0)),
                digits=int(entry.get("digits", 5)),
                unit=str(entry.get("unit", "")),
                sdi=int(entry.get("sdi", 0)),
                period_ms=int(entry.get("period_ms", 80)),
            )
        )
    if not items:
        raise ValueError("ICD ARINC senza labels")
    return ArincIcd(labels=tuple(items), path=path)
