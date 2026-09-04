"""Codifica/decodifica dei registri Modbus (16 bit)."""

from __future__ import annotations

import struct

REG_COUNT = {
    "bool": 1,
    "uint16": 1,
    "int16": 1,
    "uint32": 2,
    "int32": 2,
    "float32": 2,
}

# Indici rispetto a [word_alta, word_bassa] dopo eventuale byte-swap.
_WORD_INDEX = {
    "abcd": (0, 1),
    "badc": (0, 1),
    "cdab": (1, 0),
    "dcba": (1, 0),
}

_SWAP_BYTES = {
    "abcd": False,
    "cdab": False,
    "badc": True,
    "dcba": True,
}


def _swap_bytes(word: int) -> int:
    return ((word & 0xFF) << 8) | ((word >> 8) & 0xFF)


def _apply_byte_swap(hi: int, lo: int, word_order: str) -> tuple[int, int]:
    if _SWAP_BYTES[word_order]:
        return _swap_bytes(hi), _swap_bytes(lo)
    return hi, lo


def _to_words(raw: bytes, word_order: str) -> list[int]:
    hi, lo = struct.unpack(">HH", raw)
    hi, lo = _apply_byte_swap(hi, lo, word_order)
    words = [hi, lo]
    first, second = _WORD_INDEX[word_order]
    return [words[first], words[second]]


def _from_words(registers: list[int], word_order: str) -> bytes:
    if len(registers) < 2:
        raise ValueError("Servono 2 registri per un valore a 32 bit")
    first, second = _WORD_INDEX[word_order]
    ordered = [0, 0]
    ordered[first] = registers[0] & 0xFFFF
    ordered[second] = registers[1] & 0xFFFF
    hi, lo = _apply_byte_swap(ordered[0], ordered[1], word_order)
    return struct.pack(">HH", hi, lo)


def encode_value(value: float | int | bool, dtype: str, word_order: str = "abcd") -> list[int]:
    """Converte un valore engineering in registri Modbus 16 bit."""
    if dtype == "bool":
        return [1 if bool(value) else 0]
    if dtype == "uint16":
        return [int(value) & 0xFFFF]
    if dtype == "int16":
        packed = struct.pack(">h", int(value))
        return [struct.unpack(">H", packed)[0]]
    if dtype == "uint32":
        return _to_words(struct.pack(">I", int(value) & 0xFFFFFFFF), word_order)
    if dtype == "int32":
        return _to_words(struct.pack(">i", int(value)), word_order)
    if dtype == "float32":
        return _to_words(struct.pack(">f", float(value)), word_order)
    raise ValueError(f"Tipo non supportato: {dtype}")


def decode_registers(
    registers: list[int] | tuple[int, ...],
    dtype: str,
    word_order: str = "abcd",
    scale: float = 1.0,
    offset: float = 0.0,
) -> float:
    """Decodifica registri Modbus in un valore engineering (raw * scale + offset)."""
    if dtype == "bool":
        raw: float | int = 1.0 if registers and registers[0] else 0.0
    elif dtype == "uint16":
        raw = registers[0] & 0xFFFF
    elif dtype == "int16":
        raw = struct.unpack(">h", struct.pack(">H", registers[0] & 0xFFFF))[0]
    elif dtype == "uint32":
        raw = struct.unpack(">I", _from_words(list(registers), word_order))[0]
    elif dtype == "int32":
        raw = struct.unpack(">i", _from_words(list(registers), word_order))[0]
    elif dtype == "float32":
        raw = struct.unpack(">f", _from_words(list(registers), word_order))[0]
    else:
        raise ValueError(f"Tipo non supportato: {dtype}")
    return float(raw) * scale + offset
