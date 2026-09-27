"""Gateway JSON-lines TCP: i client HMI / TestStand / script si collegano qui."""

from __future__ import annotations

import json
import socket
import threading
from typing import Any

from data_center.bus import TagBus
from data_center.models import DataBlock, Health, TagUpdate


class JsonLinesGateway(threading.Thread):
    """Una riga JSON per messaggio. Non blocca gli adapter se un client è lento."""

    def __init__(self, bus: TagBus, host: str = "127.0.0.1", port: int = 8765) -> None:
        super().__init__(name="dc-gateway", daemon=True)
        self.bus = bus
        self.host = host
        self.port = port
        self._halt = threading.Event()
        self._server: socket.socket | None = None
        self._ready = threading.Event()
        self._health_fn = None
        self._write_fn = None
        self._catalog_fn = None

    def bind_handlers(self, *, health, write, catalog=None) -> None:
        self._health_fn = health
        self._write_fn = write
        self._catalog_fn = catalog

    def start_ready(self) -> None:
        self.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("Gateway JSON non partito")

    def stop(self) -> None:
        self._halt.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        self.join(timeout=3)

    def run(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        bound_host, bound_port = server.getsockname()[:2]
        self.host = bound_host
        self.port = int(bound_port)
        server.listen(16)
        server.settimeout(0.5)
        self._server = server
        self._ready.set()
        try:
            while not self._halt.is_set():
                try:
                    conn, _addr = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                threading.Thread(
                    target=self._client, args=(conn,), name="dc-gw-client", daemon=True
                ).start()
        finally:
            try:
                server.close()
            except OSError:
                pass

    def _client(self, conn: socket.socket) -> None:
        conn.settimeout(0.5)
        buf = b""
        sub = None
        try:
            while not self._halt.is_set():
                if sub is not None:
                    update = sub.get(timeout=0.05)
                    if update is not None:
                        _send(conn, {"op": "update", **update.as_dict()})
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        _send(conn, {"op": "error", "message": "JSON non valido"})
                        continue
                    sub = self._handle(conn, msg, sub)
        finally:
            if sub is not None:
                self.bus.unsubscribe(sub)
            try:
                conn.close()
            except OSError:
                pass

    def _handle(self, conn: socket.socket, msg: dict[str, Any], sub):
        op = str(msg.get("op") or "")
        if op == "snapshot":
            pattern = str(msg.get("pattern") or "*")
            tags = [upd.as_dict() for upd in self.bus.snapshot(pattern).values()]
            _send(conn, {"op": "snapshot", "tags": tags})
            return sub
        if op == "subscribe":
            if sub is not None:
                self.bus.unsubscribe(sub)
            sub = self.bus.subscribe(
                str(msg.get("pattern") or "*"),
                min_interval_ms=int(msg.get("min_interval_ms") or 0),
            )
            _send(conn, {"op": "subscribed", "pattern": sub.pattern})
            return sub
        if op == "unsubscribe":
            if sub is not None:
                self.bus.unsubscribe(sub)
            _send(conn, {"op": "unsubscribed"})
            return None
        if op == "write":
            if self._write_fn is None:
                _send(conn, {"op": "error", "message": "write non disponibile"})
                return sub
            try:
                self._write_fn(str(msg["tag"]), msg.get("value"))
                _send(conn, {"op": "written", "tag": msg.get("tag")})
            except Exception as exc:  # noqa: BLE001
                _send(conn, {"op": "error", "message": str(exc)})
            return sub
        if op == "health":
            adapters = []
            if self._health_fn is not None:
                adapters = [_health_dict(item) for item in self._health_fn()]
            _send(conn, {"op": "health", "adapters": adapters})
            return sub
        if op == "fetch_block":
            block = self.bus.fetch_block(str(msg.get("name") or ""))
            _send(conn, _block_dict(block))
            return sub
        if op == "catalog":
            tags = self._catalog_fn() if self._catalog_fn is not None else []
            _send(conn, {"op": "catalog", "tags": tags})
            return sub
        _send(conn, {"op": "error", "message": f"op sconosciuta: {op}"})
        return sub


def _send(conn: socket.socket, payload: dict[str, Any]) -> None:
    data = (json.dumps(payload, default=str) + "\n").encode("utf-8")
    conn.sendall(data)


def _health_dict(item: Health) -> dict[str, Any]:
    return {
        "id": item.adapter_id,
        "type": item.type_name,
        "running": item.running,
        "ok": item.ok,
        "error": item.error,
        "frames": item.frames,
        "publishes": item.publishes,
    }


def _block_dict(block: DataBlock | None) -> dict[str, Any]:
    if block is None:
        return {"op": "block", "name": None, "samples": []}
    return {
        "op": "block",
        "name": block.name,
        "timestamp_ns": block.timestamp_ns,
        "sample_hz": block.sample_hz,
        "source": block.source,
        "samples": [float(x) for x in block.samples.tolist()],
    }
