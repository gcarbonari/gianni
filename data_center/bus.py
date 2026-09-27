"""Bus in-process: last-value, storico, burst analogici, pub/sub verso i client."""

from __future__ import annotations

import fnmatch
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from queue import Empty, Queue
from typing import Callable, Iterator

from data_center.models import DataBlock, Quality, TagUpdate


@dataclass
class Subscription:
    pattern: str
    min_interval_s: float = 0.0
    maxsize: int = 1024
    _queue: Queue = field(default_factory=Queue)
    _last_sent: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    closed: bool = False

    def __post_init__(self) -> None:
        self._queue = Queue(maxsize=self.maxsize)

    def matches(self, name: str) -> bool:
        return fnmatch.fnmatchcase(name, self.pattern)

    def offer(self, update: TagUpdate) -> None:
        if self.closed or not self.matches(update.name):
            return
        now = time.monotonic()
        if self.min_interval_s > 0:
            with self._lock:
                last = self._last_sent.get(update.name, 0.0)
                if now - last < self.min_interval_s:
                    return
                self._last_sent[update.name] = now
        try:
            self._queue.put_nowait(update)
        except Exception:
            try:
                self._queue.get_nowait()
            except Empty:
                pass
            try:
                self._queue.put_nowait(update)
            except Exception:
                pass

    def get(self, timeout: float | None = None) -> TagUpdate | None:
        try:
            return self._queue.get(timeout=timeout)
        except Empty:
            return None

    def close(self) -> None:
        self.closed = True


class TagBus:
    """Accentratore: gli adapter pubblicano, i client si iscrivono."""

    def __init__(self, history: int = 256) -> None:
        self.history = history
        self._lock = threading.RLock()
        self._latest: dict[str, TagUpdate] = {}
        self._history: dict[str, deque[TagUpdate]] = {}
        self._blocks: dict[str, DataBlock] = {}
        self._subs: list[Subscription] = []
        self._on_publish: list[Callable[[TagUpdate], None]] = []

    def publish(self, update: TagUpdate) -> None:
        with self._lock:
            self._latest[update.name] = update
            hist = self._history.get(update.name)
            if hist is None:
                hist = deque(maxlen=self.history)
                self._history[update.name] = hist
            hist.append(update)
            subs = list(self._subs)
            callbacks = list(self._on_publish)
        for sub in subs:
            sub.offer(update)
        for cb in callbacks:
            cb(update)

    def publish_block(self, block: DataBlock) -> None:
        with self._lock:
            self._blocks[block.name] = block

    def snapshot(self, pattern: str = "*") -> dict[str, TagUpdate]:
        with self._lock:
            return {
                name: upd
                for name, upd in self._latest.items()
                if fnmatch.fnmatchcase(name, pattern)
            }

    def get(self, name: str) -> TagUpdate | None:
        with self._lock:
            return self._latest.get(name)

    def history_of(self, name: str) -> list[TagUpdate]:
        with self._lock:
            hist = self._history.get(name)
            return list(hist) if hist else []

    def fetch_block(self, name: str) -> DataBlock | None:
        with self._lock:
            return self._blocks.get(name)

    def names(self, pattern: str = "*") -> list[str]:
        with self._lock:
            return sorted(n for n in self._latest if fnmatch.fnmatchcase(n, pattern))

    def subscribe(self, pattern: str = "*", *, min_interval_ms: int = 0) -> Subscription:
        sub = Subscription(pattern=pattern, min_interval_s=max(min_interval_ms, 0) / 1000.0)
        with self._lock:
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        sub.close()
        with self._lock:
            self._subs = [item for item in self._subs if item is not sub]

    def mark_stale(self, older_than_ns: int, now_ns: int | None = None) -> int:
        """Segna UNCERTAIN→STALE i tag fermi da too long. Ritorna quanti ne ha marcati."""
        now_ns = now_ns if now_ns is not None else time.time_ns()
        marked = 0
        with self._lock:
            items = list(self._latest.items())
        for name, upd in items:
            if upd.quality is Quality.STALE:
                continue
            if now_ns - upd.timestamp_ns >= older_than_ns:
                self.publish(
                    TagUpdate(
                        name=upd.name,
                        value=upd.value,
                        timestamp_ns=upd.timestamp_ns,
                        source=upd.source,
                        quality=Quality.STALE,
                        unit=upd.unit,
                        raw=upd.raw,
                        meta=upd.meta,
                    )
                )
                marked += 1
        return marked

    def iter_updates(self, sub: Subscription, timeout: float = 0.2) -> Iterator[TagUpdate]:
        while not sub.closed:
            item = sub.get(timeout=timeout)
            if item is not None:
                yield item
