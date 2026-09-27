"""PGN / ID J1939 (CAN 29 bit).

Layout ID esteso:
  28-26  priority
  25     reserved
  24     data page
  23-16  PDU format (PF)
  15-8   PDU specific (PS) — destinazione se PDU1, gruppo se PDU2
  7-0    source address
"""

from __future__ import annotations

J1939_PGN_MASK = 0x3FFFF


def pgn_from_id(can_id: int) -> int:
    pf = (can_id >> 16) & 0xFF
    ps = (can_id >> 8) & 0xFF
    dp = (can_id >> 24) & 0x1
    if pf < 240:
        pgn = (dp << 16) | (pf << 8)
    else:
        pgn = (dp << 16) | (pf << 8) | ps
    return pgn & J1939_PGN_MASK


def source_address(can_id: int) -> int:
    return can_id & 0xFF


def priority(can_id: int) -> int:
    return (can_id >> 26) & 0x7


def id_from_pgn(
    pgn: int,
    source: int = 0,
    *,
    priority_value: int = 6,
    destination: int = 0,
) -> int:
    """Ricostruisce un ID 29 bit da PGN (PDU1 usa destination)."""
    pgn &= J1939_PGN_MASK
    dp = (pgn >> 16) & 0x1
    pf = (pgn >> 8) & 0xFF
    ps = destination if pf < 240 else (pgn & 0xFF)
    return (
        ((priority_value & 0x7) << 26)
        | (dp << 24)
        | (pf << 16)
        | (ps << 8)
        | (source & 0xFF)
    )
