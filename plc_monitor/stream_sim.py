"""Simulatore TCP: emette pacchetti 100 ch @ 1000 Hz ogni 100 ms (come un PLC)."""

from __future__ import annotations

import logging
import socket
import threading
import time

from plc_monitor.packet_proto import encode_packet, synthesize_packet

log = logging.getLogger("plc_monitor.stream_sim")


class PacketStreamServer(threading.Thread):
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 2000,
        *,
        channels: int = 100,
        samples: int = 100,
        sample_hz: float = 1000.0,
        packet_ms: float = 100.0,
    ) -> None:
        super().__init__(name="plc-stream-sim", daemon=True)
        self.host = host
        self.port = port
        self.channels = channels
        self.samples = samples
        self.sample_hz = sample_hz
        self.packet_ms = packet_ms
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._server: socket.socket | None = None

    def start_ready(self) -> None:
        self.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("Simulatore stream non partito")
        if self._error:
            raise RuntimeError(f"Simulatore stream in errore: {self._error}") from self._error

    def stop(self) -> None:
        self._stop_event.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        self.join(timeout=3)

    def run(self) -> None:
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(1)
            server.settimeout(0.5)
            self._server = server
            self._ready.set()
            log.info(
                "Simulatore stream in ascolto su %s:%s (%d ch, %d samp/pkt, ogni %.0f ms)",
                self.host,
                self.port,
                self.channels,
                self.samples,
                self.packet_ms,
            )
            while not self._stop_event.is_set():
                try:
                    conn, addr = server.accept()
                except socket.timeout:
                    continue
                log.info("Client connesso: %s", addr)
                try:
                    self._serve_client(conn)
                finally:
                    conn.close()
                    log.info("Client disconnesso: %s", addr)
        except Exception as exc:  # pragma: no cover
            self._error = exc
            self._ready.set()
        finally:
            if self._server is not None:
                try:
                    self._server.close()
                except OSError:
                    pass

    def _serve_client(self, conn: socket.socket) -> None:
        conn.settimeout(1.0)
        seq = 0
        interval = self.packet_ms / 1000.0
        # timestamp di stream coerente con 1000 Hz
        t0_ns = time.time_ns()
        next_deadline = time.monotonic()
        while not self._stop_event.is_set():
            packet = synthesize_packet(
                sequence=seq,
                timestamp_ns=t0_ns + int(seq * self.samples * 1e9 / self.sample_hz),
                channels=self.channels,
                samples=self.samples,
                sample_hz=self.sample_hz,
            )
            raw = encode_packet(packet.sequence, packet.timestamp_ns, packet.data)
            try:
                conn.sendall(raw)
            except OSError:
                return
            seq += 1
            next_deadline += interval
            sleep_for = next_deadline - time.monotonic()
            if sleep_for > 0:
                if self._stop_event.wait(sleep_for):
                    return
            else:
                # in ritardo: non dormire, continua
                next_deadline = time.monotonic()
