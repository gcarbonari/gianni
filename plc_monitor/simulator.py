"""Simulatore Modbus TCP con segnali sintetici (seno, rampa, allarme)."""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from typing import Any

from pymodbus.datastore import (
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.server import ModbusTcpServer

from plc_monitor.decoder import encode_value

log = logging.getLogger("plc_monitor.sim")

HOLDING_SIZE = 32
COIL_SIZE = 8


def _block(size: int, fill: int = 0) -> ModbusSequentialDataBlock:
    return ModbusSequentialDataBlock(0, [fill] * size)


def build_context() -> ModbusServerContext:
    device = ModbusDeviceContext(
        di=_block(COIL_SIZE),
        co=_block(COIL_SIZE),
        hr=_block(HOLDING_SIZE),
        ir=_block(HOLDING_SIZE),
    )
    return ModbusServerContext(devices=device, single=True)


def synthetic_values(elapsed: float) -> dict[str, Any]:
    """Valori di processo fittizi, allineati a config.yaml di default."""
    return {
        "Temperatura": 22.0 + 6.0 * math.sin(elapsed / 4.0),
        "Pressione": 1.8 + 0.4 * math.sin(elapsed / 2.5 + 0.6),
        "Velocita": int(800 + 400 * math.sin(elapsed / 3.0)),
        "Allarme": elapsed % 12.0 > 9.0,
    }


def write_process_image(context: ModbusServerContext, elapsed: float) -> None:
    values = synthetic_values(elapsed)
    holding = (
        encode_value(values["Temperatura"], "float32")
        + encode_value(values["Pressione"], "float32")
        + encode_value(values["Velocita"], "uint16")
    )
    context[0].setValues(3, 0, holding)
    context[0].setValues(1, 0, [1 if values["Allarme"] else 0])


async def _updater(context: ModbusServerContext, started: float, stop: asyncio.Event) -> None:
    while not stop.is_set():
        write_process_image(context, time.monotonic() - started)
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.1)
        except TimeoutError:
            continue


class SimulatorThread:
    """Esegue il simulatore in un thread dedicato (utile per demo e test)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5020) -> None:
        self.host = host
        self.port = port
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="plc-simulator", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("Il simulatore non è partito")
        if self._error:
            raise RuntimeError(f"Simulatore in errore: {self._error}") from self._error

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._stop = asyncio.Event()

        async def boot() -> None:
            await self._serve()

        try:
            loop.run_until_complete(boot())
        except Exception as exc:  # pragma: no cover - errore di avvio
            self._error = exc
            self._ready.set()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    async def _serve(self) -> None:
        assert self._stop is not None
        context = build_context()
        write_process_image(context, 0.0)
        server = ModbusTcpServer(context=context, address=(self.host, self.port))
        await server.serve_forever(background=True)
        updater = asyncio.create_task(_updater(context, time.monotonic(), self._stop))
        log.info("Simulatore PLC in ascolto su %s:%s", self.host, self.port)
        self._ready.set()
        try:
            await self._stop.wait()
        finally:
            updater.cancel()
            await server.shutdown()

    def stop(self) -> None:
        if self._loop and self._stop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread:
            self._thread.join(timeout=3)


def run_simulator(host: str, port: int) -> None:
    """Avvio bloccante da riga di comando."""
    sim = SimulatorThread(host=host, port=port)
    sim.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Arresto simulatore")
    finally:
        sim.stop()
