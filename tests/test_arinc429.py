from __future__ import annotations

from data_center.arinc429 import (
    ArincWord,
    decode_bnr,
    encode_bnr,
    load_icd,
    pack_word,
    parse_arinc_label,
    unpack_word,
)


def test_label_octal_and_parity() -> None:
    word = pack_word(label_octal=parse_arinc_label("206"), sdi=0, data=123, ssm=0b11)
    fields = unpack_word(word)
    assert fields["label_octal"] == 0o206
    assert fields["data"] == 123
    assert fields["ssm"] == 0b11
    assert fields["parity_ok"] is True


def test_bnr_roundtrip() -> None:
    raw = encode_bnr(-12.5, bits=15, resolution=0.01)
    assert decode_bnr(raw, bits=15, resolution=0.01) == -12.5


def test_icd_encode_decode() -> None:
    icd = load_icd("databases/arinc429.yaml")
    heading = icd.get_by_name("heading")
    assert heading is not None
    word = ArincWord(word=icd.encode(heading, 180.0))
    spec, value, fields = icd.decode(word)
    assert spec.name == "heading"
    assert value == 180.0
    assert fields["parity_ok"] is True
