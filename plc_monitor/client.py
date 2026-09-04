"""Client Modbus TCP con riconnessione e letture raggruppate."""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

from plc_monitor.config import AppConfig, Signal
from plc_monitor.decoder import REG_COUNT, decode_registers

log = logging.getLogger("plc_monitor")

_READERS = {
    "holding": "read_holding_registers",
    "input": "read_input_registers",
    "coil": "read_coils",
    "discrete": "read_discrete_inputs",
}


class PlcReadError(RuntimeError):
    """Lettura Modbus fallita."""


def _group_signals(signals: tuple[Signal, ...]) -> list[tuple[str, int, int, list[Signal]]]:
    """Raggruppa segnali contigui della stessa tabella in un'unica lettura."""
    by_table: dict[str, list[Signal]] = defaultdict(list)
    for signal in signals:
        by_table[signal.table].append(signal)

    groups: list[tuple[str, int, int, list[Signal]]] = []
    for table, items in by_table.items():
        items = sorted(items, key=lambda s: s.address)
        start = items[0].address
        end = start + REG_COUNT[items[0].dtype]
        current = [items[0]]
        for signal in items[1:]:
            signal_end = signal.address + REG_COUNT[signal.dtype]
            if signal.address <= end + 4:
                current.append(signal)
                end = max(end, signal_end)
            else:
                groups.append((table, start, end - start, current))
                start = signal.address
                end = signal_end
                current = [signal]
        groups.append((table, start, end - start, current))
    return groups


class PlcClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._groups = _group_signals(config.signals)
        self._client = ModbusTcpClient(
            host=config.plc.host,
            port=config.plc.port,
            timeout=config.plc.timeout,
        )

    def connect(self) -> None:
        if not self._client.connect():
            raise PlcReadError(
                f"Impossibile connettersi a {self.config.plc.host}:{self.config.plc.port}"
            )
        log.info("Connesso a %s:%s", self.config.plc.host, self.config.plc.port)

    def close(self) -> None:
        self._client.close()

    def _ensure_connected(self) -> None:
        if self._client.connected:
            return
        log.warning("Connessione persa, tentativo di riconnessione...")
        if not self._client.connect():
            raise PlcReadError("Riconnessione al PLC fallita")

    def read_all(self) -> dict[str, float]:
        """Legge tutti i segnali configurati. Chiavi = nomi segnale."""
        self._ensure_connected()
        values: dict[str, float] = {}
        unit = self.config.plc.unit_id
        for table, address, count, signals in self._groups:
            reader = getattr(self._client, _READERS[table])
            try:
                response = reader(address=address, count=count, device_id=unit)
            except ModbusException as exc:
                raise PlcReadError(str(exc)) from exc
            if response.isError():
                raise PlcReadError(f"Errore Modbus su {table}@{address}: {response}")

            if table in ("coil", "discrete"):
                bits = list(response.bits[:count])
                payload: list[int] = [1 if bit else 0 for bit in bits]
            else:
                payload = list(response.registers)

            for signal in signals:
                offset = signal.address - address
                nregs = REG_COUNT[signal.dtype]
                chunk = payload[offset : offset + nregs]
                values[signal.name] = decode_registers(
                    chunk,
                    dtype=signal.dtype,
                    word_order=signal.word_order,
                    scale=signal.scale,
                    offset=signal.offset,
                )
        return values

    def poll_once(self) -> tuple[float, dict[str, float]]:
        stamp = time.time()
        return stamp, self.read_all()
