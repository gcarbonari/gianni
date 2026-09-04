from __future__ import annotations

import struct

import numpy as np
import pytest

from plc_monitor.packet_proto import (
    HEADER_SIZE,
    MAGIC,
    VERSION,
    decode_packet,
    encode_packet,
    packet_size,
    synthesize_packet,
    try_decode_header,
)


def test_header_size() -> None:
    assert HEADER_SIZE == 24
    assert packet_size(100, 100) == 24 + 40_000


def test_encode_decode_roundtrip() -> None:
    data = np.arange(8, dtype=np.float32).reshape(2, 4)
    raw = encode_packet(sequence=42, timestamp_ns=1_700_000_000_123_456_789, data=data)
    assert len(raw) == packet_size(2, 4)
    packet = decode_packet(raw)
    assert packet.sequence == 42
    assert packet.timestamp_ns == 1_700_000_000_123_456_789
    assert packet.channels == 2
    assert packet.samples == 4
    assert packet.data.shape == (2, 4)
    np.testing.assert_allclose(packet.data, data)


def test_try_decode_header_rejects_bad_magic() -> None:
    data = np.zeros((1, 1), dtype=np.float32)
    raw = bytearray(encode_packet(0, 0, data))
    raw[0:4] = b"XXXX"
    assert try_decode_header(bytes(raw)) is None


def test_try_decode_header_incomplete() -> None:
    assert try_decode_header(b"PLC") is None


def test_decode_truncated_raises() -> None:
    data = np.ones((2, 2), dtype=np.float32)
    raw = encode_packet(1, 100, data)
    with pytest.raises(ValueError, match="troncato"):
        decode_packet(raw[: HEADER_SIZE + 4])


def test_synthesize_siemens_shape() -> None:
    packet = synthesize_packet(
        sequence=7,
        timestamp_ns=123456789,
        channels=100,
        samples=100,
        sample_hz=1000.0,
    )
    assert packet.channels == 100
    assert packet.samples == 100
    assert packet.data.dtype == np.float32
    raw = encode_packet(packet.sequence, packet.timestamp_ns, packet.data)
    assert len(raw) == packet_size(100, 100)
    back = decode_packet(raw)
    assert back.sequence == 7
    assert back.timestamp_ns == 123456789
    np.testing.assert_allclose(back.data, packet.data)


def test_header_layout_little_endian() -> None:
    data = np.array([[1.0, 2.0]], dtype=np.float32)
    raw = encode_packet(9, 99, data)
    magic, version, n_ch, n_samp, reserved, seq, ts = struct.unpack(
        "<4sHHHHIQ", raw[:HEADER_SIZE]
    )
    assert magic == MAGIC
    assert version == VERSION
    assert n_ch == 1 and n_samp == 2 and reserved == 0
    assert seq == 9 and ts == 99
