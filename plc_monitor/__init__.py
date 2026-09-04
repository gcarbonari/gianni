"""Lettura e grafico di segnali PLC via Modbus TCP."""

from plc_monitor.decoder import REG_COUNT, decode_registers, encode_value

__all__ = ["REG_COUNT", "decode_registers", "encode_value"]
