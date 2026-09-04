"""Client TCP che riceve lo stream di pacchetti dal PLC."""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from plc_monitor.packet_proto import (
    HEADER_SIZE,
    Packet,
    decode_packet,
    packet_size,
    try_decode_header,
)

log = logging.getLogger("plc_monitor.stream")


@dataclass
class StreamStats:
    packets: int = 0
    bytes_rx: int = 0
    gaps: int = 0
    last_seq: int | None = None
    last_timestamp_ns: int | None = None
    last_error: str | None = None
    rate_hz: float = 0.0
    _rate_times: deque[float] = field(default_factory=lambda: deque(maxlen=50))


class PacketBuffer:
    """Coda thread-safe degli ultimi N pacchetti + stats."""

    def __init__(self, maxlen: int = 200) -> None:
        self._packets: deque[Packet] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self.stats = StreamStats()

    def append(self, packet: Packet) -> None:
        now = time.monotonic()
        with self._lock:
            stats = self.stats
            if stats.last_seq is not None and packet.sequence != (stats.last_seq + 1) & 0xFFFFFFFF:
                stats.gaps += 1
            stats.last_seq = packet.sequence
            stats.last_timestamp_ns = packet.timestamp_ns
            stats.packets += 1
            stats.bytes_rx += HEADER_SIZE + packet.channels * packet.samples * 4
            stats.last_error = None
            stats._rate_times.append(now)
            if len(stats._rate_times) >= 2:
                dt = stats._rate_times[-1] - stats._rate_times[0]
                if dt > 0:
                    stats.rate_hz = (len(stats._rate_times) - 1) / dt
            self._packets.append(packet)

    def mark_error(self, message: str) -> None:
        with self._lock:
            self.stats.last_error = message

    def latest(self) -> Packet | None:
        with self._lock:
            return self._packets[-1] if self._packets else None

    def snapshot(self) -> tuple[list[Packet], StreamStats]:
        with self._lock:
            stats = StreamStats(
                packets=self.stats.packets,
                bytes_rx=self.stats.bytes_rx,
                gaps=self.stats.gaps,
                last_seq=self.stats.last_seq,
                last_timestamp_ns=self.stats.last_timestamp_ns,
                last_error=self.stats.last_error,
                rate_hz=self.stats.rate_hz,
            )
            return list(self._packets), stats


class StreamClient(threading.Thread):
    """Connette al PLC e riempie il PacketBuffer."""

    def __init__(
        self,
        host: str,
        port: int,
        buffer: PacketBuffer,
        *,
        timeout: float = 3.0,
        expected_channels: int = 100,
        expected_samples: int = 100,
    ) -> None:
        super().__init__(name="plc-stream", daemon=True)
        self.host = host
        self.port = port
        self.buffer = buffer
        self.timeout = timeout
        self.expected_channels = expected_channels
        self.expected_samples = expected_samples
        self._stop_event = threading.Event()
        self._sock: socket.socket | None = None

    def stop(self) -> None:
        self._stop_event.set()
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._session()
            except OSError as exc:
                self.buffer.mark_error(f"Connessione: {exc}")
                log.warning("Stream interrotto: %s", exc)
            if self._stop_event.is_set():
                break
            time.sleep(1.0)

    def _session(self) -> None:
        log.info("Connessione stream a %s:%s ...", self.host, self.port)
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock = sock
        sock.settimeout(1.0)
        log.info("Stream connesso a %s:%s", self.host, self.port)
        pending = bytearray()
        expected = packet_size(self.expected_channels, self.expected_samples)
        try:
            while not self._stop_event.is_set():
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    raise OSError("PLC ha chiuso la connessione")
                pending.extend(chunk)
                while True:
                    if len(pending) < HEADER_SIZE:
                        break
                    hdr = try_decode_header(bytes(pending[:HEADER_SIZE]))
                    if hdr is None:
                        # risincronizza cercando il magic
                        idx = bytes(pending).find(b"PLCP", 1)
                        if idx < 0:
                            pending.clear()
                            self.buffer.mark_error("Sync perso sullo stream")
                            break
                        del pending[:idx]
                        continue
                    _ver, n_ch, n_samp, _seq, _ts = hdr
                    need = packet_size(n_ch, n_samp)
                    if len(pending) < need:
                        expected = need
                        break
                    raw = bytes(pending[:need])
                    del pending[:need]
                    try:
                        packet = decode_packet(raw)
                    except ValueError as exc:
                        self.buffer.mark_error(str(exc))
                        continue
                    self.buffer.append(packet)
        finally:
            try:
                sock.close()
            except OSError:
                pass
            self._sock = None
