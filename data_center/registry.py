"""Registro dei moduli innestabili. Aggiungere un protocollo = una classe + una voce qui."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data_center.adapter import ProtocolAdapter

_ALIASES = {
    "can_j1939": "can_j1939",
    "can": "can_j1939",
    "j1939": "can_j1939",
    "arinc429": "arinc429",
    "arinc": "arinc429",
    "plc_modbus": "plc_modbus",
    "modbus": "plc_modbus",
    "plc_stream": "plc_stream",
    "siemens_stream": "plc_stream",
}


def get_adapter_class(type_name: str) -> type[ProtocolAdapter]:
    key = _ALIASES.get(type_name.strip().lower())
    if key == "can_j1939":
        from data_center.adapters.can_j1939 import CanJ1939Adapter

        return CanJ1939Adapter
    if key == "arinc429":
        from data_center.adapters.arinc429 import Arinc429Adapter

        return Arinc429Adapter
    if key == "plc_modbus":
        from data_center.adapters.plc_modbus import PlcModbusAdapter

        return PlcModbusAdapter
    if key == "plc_stream":
        from data_center.adapters.plc_stream import PlcStreamAdapter

        return PlcStreamAdapter
    known = ", ".join(sorted(set(_ALIASES)))
    raise KeyError(f"Tipo adapter sconosciuto '{type_name}'. Disponibili: {known}")
