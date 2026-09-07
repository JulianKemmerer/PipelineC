# pyright: reportInvalidTypeForm=none
"""Software-side type <-> bytes conversion: pypeline.type_to_bytes /
type_from_bytes and the @struct T.to_bytes / T.from_bytes classmethods.

The point of these functions is that a software author with plain byte arrays
(a readStream/writeStream pair, a socket, a file) can build and decode the same
structs the hardware moves, without elaborating anything. So the load-bearing
assertions here are not the round trips -- those would pass for any
self-consistent layout -- but `test_sw_matches_hw`, which pins the software
layout to what the generated hardware function actually produces, for every
fixture and both endians.
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from enum import auto
from typing import NamedTuple

from pypeline import (
    MAIN,
    PypelineEnum,
    byte_length,
    char_t,
    enum,
    int8_t,
    int16_t,
    make_type_from_bytes,
    make_type_to_bytes,
    sim_call,
    struct,
    type_from_bytes,
    type_to_bytes,
    uint3_t,
    uint8_t,
    uint12_t,
    uint16_t,
    uint32_t,
)

# ── fixtures ──────────────────────────────────


@enum
class mode_t(PypelineEnum):
    # NB: not `ON` -- enum member names are emitted verbatim into the VHDL
    # enumeration type, and `on` is a VHDL reserved word, so `ON` produces
    # uncompilable VHDL. Native simulation cannot see this; only a synth or
    # GHDL run can. See the guide's limitations table.
    OFF = auto()
    ACTIVE = auto()
    STANDBY = auto()


@struct
class inner_t(NamedTuple):
    lo: uint8_t
    hi: uint16_t


@struct
class rec_t(NamedTuple):
    m: mode_t  # 2 bits -> 1 byte
    r: uint3_t  # 3 bits -> 1 byte
    sg: int8_t  # signed, 1 byte
    ragged: uint12_t  # 12 bits -> 2 bytes, top nibble unused
    arr: uint16_t[3]
    nest: inner_t


@struct
class pt_t(NamedTuple):
    x: int16_t
    y: int16_t


# Typed-array values in sim mode come from struct-field construction; see the
# same trick in type_bytes_test.py.
@struct
class _u16x4_wrap(NamedTuple):
    v: uint16_t[4]


@struct
class _ptx2_wrap(NamedTuple):
    v: pt_t[2]


REC = rec_t(
    m=mode_t.STANDBY,
    r=5,
    sg=-3,
    ragged=0xABC,
    arr=[0x1111, 0x2222, 0x3333],
    nest=inner_t(lo=0x44, hi=0x5566),
)
PTS = _ptx2_wrap(v=[pt_t(x=-1, y=2), pt_t(x=3, y=-4)]).v
U16X4 = _u16x4_wrap(v=[1, 2, 3, 4]).v

# (type, value) pairs driven through every generic check below.
FIXTURES = [
    (uint32_t, 0xDEADBEEF),
    (uint3_t, 5),
    (int8_t, -3),
    (mode_t, mode_t.STANDBY),
    (inner_t, inner_t(lo=0x44, hi=0x5566)),
    (rec_t, REC),
    (pt_t[2], PTS),
    (uint16_t[4], U16X4),
]

# ── @MAIN wrappers, so the same generated hardware functions this file
#    cross-checks against also elaborate (native sim never emits VHDL) ────

rec_to_bytes = make_type_to_bytes(rec_t)
rec_from_bytes = make_type_from_bytes(rec_t)
REC_NBYTES = byte_length(rec_t)


@MAIN
def elab_sw_rec_to_bytes(x: rec_t) -> uint8_t[REC_NBYTES]:
    return rec_to_bytes(x)


@MAIN
def elab_sw_rec_from_bytes(src: uint8_t[REC_NBYTES]) -> rec_t:
    return rec_from_bytes(src)


# ── tests ─────────────────────────────────────


def test_scalar_endianness():
    assert type_to_bytes(uint32_t, 0xDEADBEEF) == b"\xef\xbe\xad\xde"
    assert type_to_bytes(uint32_t, 0xDEADBEEF, "big") == b"\xde\xad\xbe\xef"
    assert int(type_from_bytes(uint32_t, b"\xef\xbe\xad\xde")) == 0xDEADBEEF
    assert int(type_from_bytes(uint32_t, b"\xde\xad\xbe\xef", "big")) == 0xDEADBEEF
    print("test_scalar_endianness PASS")


def test_length_always_byte_length():
    for t, v in FIXTURES:
        for endian in ("little", "big"):
            assert len(type_to_bytes(t, v, endian)) == byte_length(t), t
    print("test_length_always_byte_length PASS")


def test_roundtrip_all_fixtures():
    for t, v in FIXTURES:
        for endian in ("little", "big"):
            raw = type_to_bytes(t, v, endian)
            back = type_from_bytes(t, raw, endian)
            # Re-packing the decoded value must reproduce the same bytes; this
            # compares structurally without needing per-type field walks here.
            assert type_to_bytes(t, back, endian) == raw, (t, endian)
    print("test_roundtrip_all_fixtures PASS")


def test_struct_layout_explicit():
    """Spell the packed/unpadded layout out byte by byte, so a change in field
    order, leaf rounding, or ragged-width handling fails loudly rather than
    staying self-consistent."""
    raw = type_to_bytes(rec_t, REC)
    assert list(raw) == [
        2,  # m: STANDBY, 2 bits -> its own byte
        5,  # r: uint3_t -> its own byte
        0xFD,  # sg: -3 two's complement
        0xBC,
        0x0A,  # ragged: uint12_t, LE, top nibble of the high byte zero
        0x11,
        0x11,
        0x22,
        0x22,
        0x33,
        0x33,  # arr
        0x44,  # nest.lo
        0x66,
        0x55,  # nest.hi
    ], list(raw)
    assert byte_length(rec_t) == 14
    print("test_struct_layout_explicit PASS")


def test_signed_leaves_come_back_negative():
    back = type_from_bytes(rec_t, type_to_bytes(rec_t, REC))
    assert int(back.sg) == -3, int(back.sg)
    pts = type_from_bytes(pt_t[2], type_to_bytes(pt_t[2], PTS))
    assert [int(pts[0].x), int(pts[0].y)] == [-1, 2]
    assert [int(pts[1].x), int(pts[1].y)] == [3, -4]
    print("test_signed_leaves_come_back_negative PASS")


def test_enum_leaf():
    back = type_from_bytes(rec_t, type_to_bytes(rec_t, REC))
    # Native sim holds an enum field as a SimVal of the carrier uint (@struct's
    # _typed_new casts it), so compare by value, not identity.
    assert back.m == mode_t.STANDBY, back.m
    assert type_to_bytes(mode_t, mode_t.ACTIVE) == b"\x01"
    assert type_from_bytes(mode_t, b"\x02") == mode_t.STANDBY
    print("test_enum_leaf PASS")


def test_ragged_leaf_masks_high_bits():
    """A uint12_t leaf occupies 2 bytes but only 12 bits are significant --
    packing must zero the top nibble and unpacking must ignore it, matching
    the hardware's tmp[hi:lo] slicing."""
    assert type_to_bytes(uint12_t, 0xFFF) == b"\xff\x0f"
    assert type_to_bytes(uint12_t, 0x1ABC) == b"\xbc\x0a"  # input over-wide: masked
    assert int(type_from_bytes(uint12_t, b"\xbc\xfa")) == 0xABC
    print("test_ragged_leaf_masks_high_bits PASS")


def test_accepted_input_shapes():
    """Every value shape native sim produces or accepts must pack identically."""
    expect = type_to_bytes(uint16_t[4], U16X4)
    assert type_to_bytes(uint16_t[4], [1, 2, 3, 4]) == expect  # plain list
    assert type_to_bytes(uint16_t[4], (1, 2, 3, 4)) == expect  # tuple
    assert type_to_bytes(uint8_t[3], b"\x01\x02\x03") == b"\x01\x02\x03"
    assert type_to_bytes(uint8_t[3], bytearray(b"\x01\x02\x03")) == b"\x01\x02\x03"
    assert type_to_bytes(uint8_t, True) == b"\x01"  # bool
    # a SimVal (what sim_call returns) round-trips as an input too
    sv = type_from_bytes(uint32_t, b"\x01\x02\x03\x04")
    assert type_to_bytes(uint32_t, sv) == b"\x01\x02\x03\x04"
    print("test_accepted_input_shapes PASS")


def test_bytes_like_and_iterable_input():
    raw = type_to_bytes(rec_t, REC)
    for form in (raw, bytearray(raw), memoryview(raw), list(raw)):
        back = type_from_bytes(rec_t, form)
        assert type_to_bytes(rec_t, back) == raw
    # a uint8_t[N] sim value straight out of sim_call
    hw_raw = sim_call(rec_to_bytes, x=REC)
    assert type_to_bytes(rec_t, type_from_bytes(rec_t, hw_raw)) == raw
    print("test_bytes_like_and_iterable_input PASS")


def test_char_array_returns_charray():
    ca = type_from_bytes(char_t[6], b"hi\x00\x00\x00\x00")
    assert str(ca) == "hi", repr(str(ca))
    assert type_to_bytes(char_t[6], ca) == b"hi\x00\x00\x00\x00"
    print("test_char_array_returns_charray PASS")


def test_classmethods_agree_with_module_functions():
    for endian in ("little", "big"):
        raw = type_to_bytes(rec_t, REC, endian)
        assert rec_t.to_bytes(REC, endian) == raw
        assert type_to_bytes(rec_t, rec_t.from_bytes(raw, endian), endian) == raw
    assert inner_t.to_bytes(inner_t(lo=1, hi=2)) == b"\x01\x02\x00"
    print("test_classmethods_agree_with_module_functions PASS")


def test_struct_field_named_to_bytes_rejected():
    try:

        @struct
        class collides_t(NamedTuple):
            to_bytes: uint8_t

        raise AssertionError("expected TypeError for a field named to_bytes")
    except TypeError as e:
        assert "collides" in str(e), str(e)
    print("test_struct_field_named_to_bytes_rejected PASS")


def test_errors():
    try:
        type_from_bytes(uint32_t, b"\x01\x02")
        raise AssertionError("expected ValueError for wrong length")
    except ValueError as e:
        assert "expected 4 bytes" in str(e), str(e)
    for fn in (
        lambda: type_to_bytes(uint32_t, 1, "middle"),
        lambda: type_from_bytes(uint32_t, b"\x00" * 4, "middle"),
    ):
        try:
            fn()
            raise AssertionError("expected ValueError for bad endian")
        except ValueError:
            pass
    for fn in (
        lambda: type_to_bytes(int, 1),
        lambda: type_from_bytes(int, b"\x00"),
    ):
        try:
            fn()
            raise AssertionError("expected TypeError for a non-pypeline type")
        except TypeError:
            pass
    print("test_errors PASS")


def test_sw_matches_hw():
    """The contract: software and hardware are one layout, not two.

    Both walk _enumerate_leaves(t), so this pins that they stay one walk --
    if a future change touched only make_type_to_bytes, this fails.
    """
    for t, v in FIXTURES:
        for endian in ("little", "big"):
            hw_raw = bytes(int(b) for b in sim_call(make_type_to_bytes(t, endian), x=v))
            sw_raw = type_to_bytes(t, v, endian)
            assert hw_raw == sw_raw, (t, endian, hw_raw.hex(), sw_raw.hex())

            hw_back = sim_call(make_type_from_bytes(t, endian), src=list(hw_raw))
            sw_back = type_from_bytes(t, hw_raw, endian)
            # Compare by re-packing: sim_call's return and type_from_bytes'
            # return are the same value shape, but comparing nested
            # NamedTuple/list values directly is fragile across SimVal types.
            assert type_to_bytes(t, hw_back, endian) == type_to_bytes(
                t, sw_back, endian
            ), (t, endian)
    print("test_sw_matches_hw PASS")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
