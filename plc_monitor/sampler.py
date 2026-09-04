"""Buffer campioni, polling in background e scrittura CSV."""

from __future__ import annotations

import csv
import threading
import time
from collections import deque
from pathlib import Path

from plc_monitor.client import PlcClient, PlcReadError
from plc_monitor.config import AppConfig


class SampleBuffer:
    def __init__(self, names: tuple[str, ...], window_seconds: float) -> None:
        self.names = names
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self.times: deque[float] = deque()
        self.series: dict[str, deque[float]] = {name: deque() for name in names}
        self.last_error: str | None = None
        self.last_values: dict[str, float] = {}
        self.sample_count = 0

    def append(self, stamp: float, values: dict[str, float]) -> None:
        with self._lock:
            self.times.append(stamp)
            for name in self.names:
                self.series[name].append(float(values[name]))
            cutoff = stamp - self.window_seconds
            while self.times and self.times[0] < cutoff:
                self.times.popleft()
                for name in self.names:
                    self.series[name].popleft()
            self.last_error = None
            self.last_values = dict(values)
            self.sample_count += 1

    def mark_error(self, message: str) -> None:
        with self._lock:
            self.last_error = message

    def snapshot(self) -> tuple[list[float], dict[str, list[float]], str | None, dict[str, float]]:
        with self._lock:
            times = [t - self.times[0] for t in self.times] if self.times else []
            series = {name: list(self.series[name]) for name in self.names}
            return times, series, self.last_error, dict(self.last_values)


class CsvLogger:
    def __init__(self, path: str | Path, names: tuple[str, ...]) -> None:
        self.path = Path(path)
        self.names = names
        self._file = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(["timestamp_iso", "unix_time", *names])
        self._file.flush()

    def write(self, stamp: float, values: dict[str, float]) -> None:
        iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stamp))
        millis = int((stamp % 1) * 1000)
        self._writer.writerow(
            [f"{iso}.{millis:03d}", f"{stamp:.3f}", *[values[name] for name in self.names]]
        )
        self._file.flush()

    def close(self) -> None:
        self._file.close()


class Poller(threading.Thread):
    def __init__(
        self,
        client: PlcClient,
        config: AppConfig,
        buffer: SampleBuffer,
        csv_logger: CsvLogger | None = None,
    ) -> None:
        super().__init__(name="plc-poller", daemon=True)
        self.client = client
        self.config = config
        self.buffer = buffer
        self.csv_logger = csv_logger
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        interval = self.config.poll_interval
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                stamp, values = self.client.poll_once()
                self.buffer.append(stamp, values)
                if self.csv_logger:
                    self.csv_logger.write(stamp, values)
            except PlcReadError as exc:
                self.buffer.mark_error(str(exc))
            remaining = interval - (time.monotonic() - started)
            if remaining > 0:
                self._stop_event.wait(remaining)
