from __future__ import annotations

from data_center.dbc import CanFrame, load_dbc, parse_dbc
from data_center.j1939 import id_from_pgn, pgn_from_id, source_address


SAMPLE = """
BO_ 256 Lights: 8 BCM
 SG_ LowBeam : 0|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ HighBeam : 1|1@1+ (1,0) [0|1] "" Vector__XXX

BO_ 217056256 EEC1: 8 ECM
 SG_ EngineSpeed : 24|16@1+ (0.125,0) [0|8031.875] "rpm" Vector__XXX
 SG_ EngineTorque : 8|8@1+ (1,-125) [-125|125] "%" Vector__XXX
"""


def test_pgn_layout() -> None:
    can_id = id_from_pgn(61444, source=0x21, priority_value=3)
    assert pgn_from_id(can_id) == 61444
    assert source_address(can_id) == 0x21
    assert can_id == 0x0CF00421


def test_parse_and_roundtrip_engine_speed() -> None:
    db = parse_dbc(SAMPLE)
    eec1 = next(m for m in db.messages if m.name == "EEC1")
    assert eec1.is_extended
    assert eec1.pgn == 61444
    frame = db.encode(eec1, {"EngineSpeed": 1000.0, "EngineTorque": 10.0})
    decoded = {sig.name: value for _m, sig, value, _raw in db.decode(frame, j1939=True)}
    assert decoded["EngineSpeed"] == 1000.0
    assert decoded["EngineTorque"] == 10.0


def test_j1939_matches_any_source_address() -> None:
    db = parse_dbc(SAMPLE)
    eec1 = next(m for m in db.messages if m.name == "EEC1")
    frame = db.encode(eec1, {"EngineSpeed": 800.0, "EngineTorque": 0.0})
    other_sa = CanFrame(
        arbitration_id=id_from_pgn(61444, source=0xAA, priority_value=3),
        data=frame.data,
        is_extended=True,
    )
    decoded = db.decode(other_sa, j1939=True)
    assert decoded
    speeds = [value for _m, sig, value, _raw in decoded if sig.name == "EngineSpeed"]
    assert speeds[0] == 800.0


def test_load_repo_dbc() -> None:
    db = load_dbc("databases/vehicle.dbc")
    names = {m.name for m in db.messages}
    assert {"EEC1", "CCVS", "Lights"} <= names
