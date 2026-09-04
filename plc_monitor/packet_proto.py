"""Protocollo binario per pacchetti multi-canale ad alta frequenza.

Formato little-endian (compatibile con TSEND/TRCV Siemens se mappato così):

  Offset  Size  Campo
  0       4     magic = b'PLCP'
  4       2     version = 1
  6       2     n_channels
  8       2     n_samples   (campioni per canale in questo pacchetto)
  10      2     reserved
  12      4     sequence
  16      8     timestamp_ns  (monotonic/unix nanosecondi lato PLC)
  24      N     float32 payload, ordine: canale-major
                [ch0_s0, ch0_s1, ... ch0_sN-1, ch1_s0, ...]

Con 100 canali @ 1000 Hz e pacchetto ogni 100 ms → n_samples = 100,
payload = 100 * 100 * 4 = 40_000 byte (+ 24 header).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

MAGIC = b"PLCP"
VERSION = 1
HEADER_FMT = "<4sHHHHIQ"  # magic, ver, n_ch, n_samp, reserved, seq, ts_ns
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 24


@dataclass(frozen=True)
class Packet:
    sequence: int
    timestamp_ns: int
    channels: int
    samples: int
    data: np.ndarray  # shape (channels, samples), float32

    @property
    def timestamp_s(self) -> float:
        return self.timestamp_ns / 1e9

    @property
    def duration_s(self) -> float:
        return self.samples / 1000.0 if self.samples else 0.0


def packet_size(channels: int, samples: int) -> int:
    return HEADER_SIZE + channels * samples * 4


def encode_packet(
    sequence: int,
    timestamp_ns: int,
    data: np.ndarray,
) -> bytes:
    """data: array float32 shape (channels, samples)."""
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError("data deve essere 2D (channels, samples)")
    n_ch, n_samp = arr.shape
    header = struct.pack(
        HEADER_FMT,
        MAGIC,
        VERSION,
        n_ch,
        n_samp,
        0,
        sequence & 0xFFFFFFFF,
        int(timestamp_ns) & 0xFFFFFFFFFFFFFFFF,
    )
    return header + arr.tobytes(order="C")


def try_decode_header(buf: bytes) -> tuple[int, int, int, int, int] | None:
    """Ritorna (version, n_ch, n_samp, seq, ts_ns) oppure None se header incompleto/invalido."""
    if len(buf) < HEADER_SIZE:
        return None
    magic, version, n_ch, n_samp, _reserved, seq, ts_ns = struct.unpack(
        HEADER_FMT, buf[:HEADER_SIZE]
    )
    if magic != MAGIC or version != VERSION:
        return None
    if n_ch < 1 or n_samp < 1 or n_ch > 1024 or n_samp > 100_000:
        return None
    return version, n_ch, n_samp, seq, ts_ns


def decode_packet(buf: bytes) -> Packet:
    parsed = try_decode_header(buf)
    if parsed is None:
        raise ValueError("Header pacchetto non valido")
    _version, n_ch, n_samp, seq, ts_ns = parsed
    need = packet_size(n_ch, n_samp)
    if len(buf) < need:
        raise ValueError(f"Pacchetto troncato: {len(buf)} < {need}")
    payload = np.frombuffer(buf, dtype="<f4", offset=HEADER_SIZE, count=n_ch * n_samp)
    data = payload.reshape(n_ch, n_samp).copy()
    return Packet(
        sequence=seq,
        timestamp_ns=ts_ns,
        channels=n_ch,
        samples=n_samp,
        data=data,
    )


def synthesize_packet(
    sequence: int,
    timestamp_ns: int,
    channels: int = 100,
    samples: int = 100,
    sample_hz: float = 1000.0,
) -> Packet:
    """Genera un pacchetto sintetico (seni a frequenze diverse per canale)."""
    t0 = timestamp_ns / 1e9
    t = t0 + np.arange(samples, dtype=np.float64) / sample_hz
    data = np.empty((channels, samples), dtype=np.float32)
    for ch in range(channels):
        freq = 1.0 + (ch % 17) * 0.37
        amp = 1.0 + (ch % 5) * 0.2
        phase = ch * 0.11
        data[ch] = (amp * np.sin(2 * np.pi * freq * t + phase)).astype(np.float32)
    return Packet(
        sequence=sequence,
        timestamp_ns=timestamp_ns,
        channels=channels,
        samples=samples,
        data=data,
    )
