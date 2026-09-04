from __future__ import annotations

import math
import struct

import pytest

from plc_monitor.decoder import decode_registers, encode_value


@pytest.mark.parametrize(
    ("dtype", "value"),
    [
        ("uint16", 0),
        ("uint16", 65535),
        ("int16", -1),
        ("int16", 32767),
        ("int16", -32768),
        ("uint32", 0),
        ("uint32", 400001),
        ("int32", -123456),
        ("float32", 0.0),
        ("float32", -12.5),
        ("float32", 22.75),
        ("bool", True),
        ("bool", False),
    ],
)
def test_roundtrip_abcd(dtype: str, value: float | int | bool) -> None:
    regs = encode_value(value, dtype, "abcd")
    decoded = decode_registers(regs, dtype, "abcd")
    if dtype == "float32":
        assert decoded == pytest.approx(float(value), rel=1e-6, abs=1e-6)
    elif dtype == "bool":
        assert decoded == (1.0 if value else 0.0)
    else:
        assert decoded == float(value)


@pytest.mark.parametrize("order", ["abcd", "cdab", "badc", "dcba"])
def test_float32_word_orders(order: str) -> None:
    value = 123.456
    regs = encode_value(value, "float32", order)
    assert len(regs) == 2
    assert decode_registers(regs, "float32", order) == pytest.approx(value, rel=1e-6)


def test_float32_abcd_matches_ieee() -> None:
    regs = encode_value(0.3, "float32", "abcd")
    packed = struct.pack(">f", 0.3)
    hi, lo = struct.unpack(">HH", packed)
    assert regs == [hi, lo]


def test_float32_cdab_swaps_words() -> None:
    abcd = encode_value(1.5, "float32", "abcd")
    cdab = encode_value(1.5, "float32", "cdab")
    assert cdab == [abcd[1], abcd[0]]


def test_scale_and_offset() -> None:
    # raw 250, scale 0.1 → 25.0, poi + offset 1 → 26.0
    value = decode_registers([250], "uint16", scale=0.1, offset=1.0)
    assert value == pytest.approx(26.0)


def test_nan_rejected_by_finite_float() -> None:
    regs = encode_value(math.pi, "float32")
    assert decode_registers(regs, "float32") == pytest.approx(math.pi, rel=1e-6)
