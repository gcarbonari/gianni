"""Parser DBC minimale + encode/decode segnali CAN / J1939.

Il veicolo (o la centralina) è descritto dal file DBC, non dal codice.
Supporta BO_/SG_ Vector, Intel (@1) e Motorola (@0). I multiplexor
vengono ignorati in questa versione.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from data_center.j1939 import pgn_from_id

_BO = re.compile(r"^BO_\s+(\d+)\s+(\S+)\s*:\s*(\d+)\s+(\S+)")
_SG = re.compile(
    r"^\s*SG_\s+(\S+)"
    r"(?:\s+[Mm]\d*)?"
    r"\s*:\s*"
    r"(\d+)\|(\d+)@([01])([+-])\s*"
    r"\(\s*([^,]+)\s*,\s*([^)]+)\)\s*"
    r"\[\s*([^|]*)\s*\|\s*([^\]]*)\]\s*"
    r"\"([^\"]*)\""
)


@dataclass(frozen=True)
class CanSignal:
    name: str
    start_bit: int
    length: int
    little_endian: bool
    signed: bool
    factor: float
    offset: float
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None

    def phys(self, raw: int) -> float:
        return raw * self.factor + self.offset

    def to_raw(self, phys: float) -> int:
        if self.factor == 0:
            return 0
        raw = int(round((phys - self.offset) / self.factor))
        if self.signed:
            max_s = 1 << (self.length - 1)
            return max(-max_s, min(max_s - 1, raw))
        return max(0, min((1 << self.length) - 1, raw))


@dataclass(frozen=True)
class CanMessage:
    frame_id: int
    name: str
    length: int
    sender: str
    signals: tuple[CanSignal, ...]
    is_extended: bool = False

    @property
    def pgn(self) -> int | None:
        if not self.is_extended:
            return None
        return pgn_from_id(self.frame_id)


@dataclass(frozen=True)
class CanFrame:
    arbitration_id: int
    data: bytes
    is_extended: bool = False
    timestamp_ns: int = 0


@dataclass(frozen=True)
class CanDatabase:
    messages: tuple[CanMessage, ...]
    path: str | None = None

    def __post_init__(self) -> None:
        by_id = {msg.frame_id: msg for msg in self.messages}
        by_pgn: dict[int, CanMessage] = {}
        for msg in self.messages:
            if msg.pgn is not None:
                by_pgn.setdefault(msg.pgn, msg)
        object.__setattr__(self, "_by_id", by_id)
        object.__setattr__(self, "_by_pgn", by_pgn)

    def match(self, frame: CanFrame, *, j1939: bool) -> CanMessage | None:
        if j1939 and frame.is_extended:
            found = self._by_pgn.get(pgn_from_id(frame.arbitration_id))  # type: ignore[attr-defined]
            if found is not None:
                return found
        return self._by_id.get(frame.arbitration_id)  # type: ignore[attr-defined]

    def decode(
        self, frame: CanFrame, *, j1939: bool = False
    ) -> list[tuple[CanMessage, CanSignal, float, int]]:
        msg = self.match(frame, j1939=j1939)
        if msg is None:
            return []
        payload = frame.data.ljust(msg.length, b"\x00")[: msg.length]
        out: list[tuple[CanMessage, CanSignal, float, int]] = []
        for sig in msg.signals:
            raw = extract_raw(
                payload,
                sig.start_bit,
                sig.length,
                little_endian=sig.little_endian,
                signed=sig.signed,
            )
            out.append((msg, sig, sig.phys(raw), raw))
        return out

    def encode(self, message: CanMessage, values: dict[str, float]) -> CanFrame:
        payload = bytearray(message.length)
        for sig in message.signals:
            if sig.name not in values:
                continue
            insert_raw(
                payload,
                sig.to_raw(values[sig.name]),
                sig.start_bit,
                sig.length,
                little_endian=sig.little_endian,
                signed=sig.signed,
            )
        return CanFrame(
            arbitration_id=message.frame_id,
            data=bytes(payload),
            is_extended=message.is_extended,
        )


def load_dbc(path: str | Path) -> CanDatabase:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_dbc(text, path=str(path))


def parse_dbc(text: str, path: str | None = None) -> CanDatabase:
    messages: list[CanMessage] = []
    current: dict | None = None
    signals: list[CanSignal] = []

    def flush() -> None:
        nonlocal current, signals
        if current is None:
            return
        messages.append(
            CanMessage(
                frame_id=current["frame_id"],
                name=current["name"],
                length=current["length"],
                sender=current["sender"],
                signals=tuple(signals),
                is_extended=current["is_extended"],
            )
        )
        current = None
        signals = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("CM_") or line.startswith("VAL_"):
            continue
        bo = _BO.match(line)
        if bo:
            flush()
            frame_id = int(bo.group(1))
            current = {
                "frame_id": frame_id,
                "name": bo.group(2),
                "length": int(bo.group(3)),
                "sender": bo.group(4),
                "is_extended": frame_id > 0x7FF,
            }
            continue
        if current is None:
            continue
        sg = _SG.match(raw_line)
        if not sg:
            sg = _SG.match(line)
        if not sg:
            continue
        minimum = _opt_float(sg.group(8))
        maximum = _opt_float(sg.group(9))
        signals.append(
            CanSignal(
                name=sg.group(1),
                start_bit=int(sg.group(2)),
                length=int(sg.group(3)),
                little_endian=sg.group(4) == "1",
                signed=sg.group(5) == "-",
                factor=float(sg.group(6)),
                offset=float(sg.group(7)),
                unit=sg.group(10),
                minimum=minimum,
                maximum=maximum,
            )
        )
    flush()
    if not messages:
        raise ValueError("DBC senza messaggi BO_")
    return CanDatabase(messages=tuple(messages), path=path)


def extract_raw(
    data: bytes,
    start: int,
    length: int,
    *,
    little_endian: bool,
    signed: bool,
) -> int:
    if length <= 0 or length > 64:
        raise ValueError(f"lunghezza segnale non valida: {length}")
    if little_endian:
        raw_int = int.from_bytes(data.ljust(8, b"\x00")[:8], "little")
        value = (raw_int >> start) & ((1 << length) - 1)
    else:
        padded = data.ljust(8, b"\x00")[:8]
        raw_int = int.from_bytes(padded, "big")
        byte, bit = divmod(start, 8)
        msb_pos = byte * 8 + (7 - bit)
        shift = 8 * len(padded) - msb_pos - length
        if shift < 0:
            raise ValueError("segnale Motorola fuori dal payload")
        value = (raw_int >> shift) & ((1 << length) - 1)
    if signed and value & (1 << (length - 1)):
        value -= 1 << length
    return value


def insert_raw(
    data: bytearray,
    value: int,
    start: int,
    length: int,
    *,
    little_endian: bool,
    signed: bool,
) -> None:
    mask = (1 << length) - 1
    if signed and value < 0:
        value = value & mask
    else:
        value &= mask
    if little_endian:
        raw_int = int.from_bytes(bytes(data).ljust(8, b"\x00")[:8], "little")
        raw_int &= ~(mask << start)
        raw_int |= value << start
        packed = raw_int.to_bytes(8, "little")
        data[:] = packed[: len(data)]
        return
    padded = bytearray(bytes(data).ljust(8, b"\x00")[:8])
    raw_int = int.from_bytes(padded, "big")
    byte, bit = divmod(start, 8)
    msb_pos = byte * 8 + (7 - bit)
    shift = 64 - msb_pos - length
    raw_int &= ~(mask << shift)
    raw_int |= value << shift
    packed = raw_int.to_bytes(8, "big")
    data[:] = packed[: len(data)]


def _opt_float(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
