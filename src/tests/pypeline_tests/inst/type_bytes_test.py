# pyright: reportInvalidTypeForm=none
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
    enum,
    make_type_from_bytes,
    make_type_to_bytes,
    sim_call,
    struct,
    uint3_t,
    uint8_t,
    uint16_t,
    uint32_t,
    uint64_t,
)

# ── fixtures ──────────────────────────────────


@struct
class mixed_t(NamedTuple):
    a: uint3_t  # 3 bits -> rounds up to 1 byte
    b: uint32_t  # 4 bytes
    c: uint8_t  # 1 byte


@struct
class inner_t(NamedTuple):
    a: uint8_t
    b: uint16_t


@struct
class outer_t(NamedTuple):
    x: inner_t
    y: uint32_t


@struct
class pt_t(NamedTuple):
    x: uint8_t
    y: uint8_t


# A throwaway wrapper used only to get a *typed* uint16_t[4] value in sim mode:
# struct-field construction is the sanctioned path for producing a properly
# typed array-of-scalar value (see pypeline.py's _typed_new); bare array
# locals/args assigned from a plain Python list are not auto-cast at sim_call
# boundaries, an existing, unrelated framework characteristic.
@struct
class _u16x4_wrap(NamedTuple):
    v: uint16_t[4]


# Regression fixtures mirroring wireguard-fpga's chacha20_state/u320_t shapes
# (single field wrapping a uniform-element array) -- proves byte_length()
# replaces their hand-maintained CHACHA20_BLOCK_SIZE/U320_NBYTES constants.
CHACHA20_STATE_NWORDS = 16
CHACHA20_BLOCK_SIZE = 64


@struct
class chacha20_state(NamedTuple):
    state: uint32_t[CHACHA20_STATE_NWORDS]


U320_NLIMBS = 5
U320_NBYTES = 40


@struct
class u320_t(NamedTuple):
    limbs: uint64_t[U320_NLIMBS]


@enum
class small_state_t(PypelineEnum):
    IDLE = auto()
    RUNNING = auto()


@struct
class has_enum_t(NamedTuple):
    s: small_state_t
    x: uint8_t


# ── generated functions (module scope, so @MAIN wrappers below can call them
#    by name -- factory-produced closures aren't themselves recognized as
#    @MAIN entry points by PARSE_FILE's static AST scan) ──────────────────

u32_to_bytes_le = make_type_to_bytes(uint32_t)
u32_from_bytes_le = make_type_from_bytes(uint32_t)
u32_to_bytes_be = make_type_to_bytes(uint32_t, endian="big")
u32_from_bytes_be = make_type_from_bytes(uint32_t, endian="big")

u16x4_to_bytes = make_type_to_bytes(uint16_t[4])
u16x4_from_bytes = make_type_from_bytes(uint16_t[4])

mixed_to_bytes = make_type_to_bytes(mixed_t)
mixed_from_bytes = make_type_from_bytes(mixed_t)

outer_to_bytes = make_type_to_bytes(outer_t)
outer_from_bytes = make_type_from_bytes(outer_t)

pt3_to_bytes = make_type_to_bytes(pt_t[3])
pt3_from_bytes = make_type_from_bytes(pt_t[3])

chacha20_state_to_bytes = make_type_to_bytes(chacha20_state)
chacha20_state_from_bytes = make_type_from_bytes(chacha20_state)

u320_to_bytes = make_type_to_bytes(u320_t)
u320_from_bytes = make_type_from_bytes(u320_t)


# ── @MAIN wrappers: elaboration (--no_synth) coverage ────────────────────


@MAIN
def elab_u32_to_bytes_le(x: uint32_t) -> uint8_t[4]:
    return u32_to_bytes_le(x)


@MAIN
def elab_u32_from_bytes_le(src: uint8_t[4]) -> uint32_t:
    return u32_from_bytes_le(src)


@MAIN
def elab_u32_to_bytes_be(x: uint32_t) -> uint8_t[4]:
    return u32_to_bytes_be(x)


@MAIN
def elab_u32_from_bytes_be(src: uint8_t[4]) -> uint32_t:
    return u32_from_bytes_be(src)


@MAIN
def elab_u16x4_to_bytes(x: uint16_t[4]) -> uint8_t[8]:
    return u16x4_to_bytes(x)


@MAIN
def elab_u16x4_from_bytes(src: uint8_t[8]) -> uint16_t[4]:
    return u16x4_from_bytes(src)


@MAIN
def elab_mixed_to_bytes(x: mixed_t) -> uint8_t[6]:
    return mixed_to_bytes(x)


@MAIN
def elab_mixed_from_bytes(src: uint8_t[6]) -> mixed_t:
    return mixed_from_bytes(src)


@MAIN
def elab_outer_to_bytes(x: outer_t) -> uint8_t[7]:
    return outer_to_bytes(x)


@MAIN
def elab_outer_from_bytes(src: uint8_t[7]) -> outer_t:
    return outer_from_bytes(src)


@MAIN
def elab_pt3_to_bytes(x: pt_t[3]) -> uint8_t[6]:
    return pt3_to_bytes(x)


@MAIN
def elab_pt3_from_bytes(src: uint8_t[6]) -> pt_t[3]:
    return pt3_from_bytes(src)


@MAIN
def elab_chacha20_state_to_bytes(x: chacha20_state) -> uint8_t[CHACHA20_BLOCK_SIZE]:
    return chacha20_state_to_bytes(x)


@MAIN
def elab_chacha20_state_from_bytes(src: uint8_t[CHACHA20_BLOCK_SIZE]) -> chacha20_state:
    return chacha20_state_from_bytes(src)


@MAIN
def elab_u320_to_bytes(x: u320_t) -> uint8_t[U320_NBYTES]:
    return u320_to_bytes(x)


@MAIN
def elab_u320_from_bytes(src: uint8_t[U320_NBYTES]) -> u320_t:
    return u320_from_bytes(src)


# ── sim_call tests ────────────────────────────


def test_byte_length():
    assert byte_length(uint32_t) == 4
    assert byte_length(uint3_t) == 1
    assert byte_length(uint16_t) == 2
    assert byte_length(uint32_t[3]) == 12
    assert byte_length(mixed_t) == 6  # 1 (uint3_t rounded up) + 4 + 1
    assert byte_length(outer_t) == 7  # (1 + 2) + 4
    assert byte_length(pt_t[3]) == 6  # (1 + 1) * 3
    assert byte_length(chacha20_state) == CHACHA20_BLOCK_SIZE
    assert byte_length(u320_t) == U320_NBYTES
    print("test_byte_length PASS")


def test_byte_length_enum_rejected():
    try:
        byte_length(small_state_t)
        raise AssertionError("expected NotImplementedError for bare enum type")
    except NotImplementedError:
        pass
    try:
        byte_length(has_enum_t)
        raise AssertionError("expected NotImplementedError for enum nested in struct")
    except NotImplementedError:
        pass
    try:
        make_type_to_bytes(has_enum_t)
        raise AssertionError("expected NotImplementedError from make_type_to_bytes")
    except NotImplementedError:
        pass
    print("test_byte_length_enum_rejected PASS")


def test_wires_tagged():
    for fn in (u32_to_bytes_le, u32_from_bytes_le, mixed_to_bytes, outer_from_bytes):
        assert (
            getattr(fn, "_is_func_wires_pragma", False) is True
        ), f"{fn.__name__} not tagged @wires"
    print("test_wires_tagged PASS")


def test_scalar_roundtrip_le():
    for val in (0, 1, 0x11223344, 0xFFFFFFFF):
        raw = sim_call(u32_to_bytes_le, x=val)
        raw_ints = [int(b) for b in raw]
        assert raw_ints == list(val.to_bytes(4, "little")), raw_ints
        back = sim_call(u32_from_bytes_le, src=raw)
        assert int(back) == val, (val, int(back))
    print("test_scalar_roundtrip_le PASS")


def test_scalar_roundtrip_be():
    for val in (0, 1, 0x11223344, 0xFFFFFFFF):
        raw = sim_call(u32_to_bytes_be, x=val)
        raw_ints = [int(b) for b in raw]
        assert raw_ints == list(val.to_bytes(4, "big")), raw_ints
        back = sim_call(u32_from_bytes_be, src=raw)
        assert int(back) == val, (val, int(back))
    print("test_scalar_roundtrip_be PASS")


def test_array_of_scalar_roundtrip():
    vals = [1, 0x2233, 0xFFFF, 0]
    typed = _u16x4_wrap(v=vals).v
    raw = sim_call(u16x4_to_bytes, x=typed)
    back = sim_call(u16x4_from_bytes, src=raw)
    assert [int(v) for v in back] == vals
    print("test_array_of_scalar_roundtrip PASS")


def test_struct_roundtrip_byte_rounding():
    x = mixed_t(a=5, b=0xDEADBEEF, c=0x7A)
    raw = sim_call(mixed_to_bytes, x=x)
    assert len(raw) == 6
    assert int(raw[0]) == 5  # uint3_t rounded up, zero-extended into its own byte
    back = sim_call(mixed_from_bytes, src=raw)
    assert int(back.a) == 5 and int(back.b) == 0xDEADBEEF and int(back.c) == 0x7A
    print("test_struct_roundtrip_byte_rounding PASS")


def test_nested_struct_roundtrip():
    x = outer_t(x=inner_t(a=7, b=0x1234), y=0xDEADBEEF)
    raw = sim_call(outer_to_bytes, x=x)
    back = sim_call(outer_from_bytes, src=raw)
    assert int(back.x.a) == 7 and int(back.x.b) == 0x1234 and int(back.y) == 0xDEADBEEF
    print("test_nested_struct_roundtrip PASS")


def test_array_of_struct_roundtrip():
    pts = [pt_t(x=i, y=i + 100) for i in range(3)]
    raw = sim_call(pt3_to_bytes, x=pts)
    back = sim_call(pt3_from_bytes, src=raw)
    for i in range(3):
        assert int(back[i].x) == i and int(back[i].y) == i + 100
    print("test_array_of_struct_roundtrip PASS")


def test_chacha20_state_regression():
    """Regression proof for the wireguard-fpga migration this feature enables:
    byte_length() replaces the hand-maintained CHACHA20_BLOCK_SIZE constant,
    and the generated from_bytes function reproduces the same little-endian
    per-word byte layout chacha20_init() currently builds manually via
    nested concat() calls."""
    state_vals = [(i * 0x01010101) & 0xFFFFFFFF for i in range(CHACHA20_STATE_NWORDS)]
    x = chacha20_state(state=state_vals)
    raw = sim_call(chacha20_state_to_bytes, x=x)
    assert len(raw) == CHACHA20_BLOCK_SIZE
    expected = b"".join(v.to_bytes(4, "little") for v in state_vals)
    assert bytes(int(b) for b in raw) == expected
    back = sim_call(chacha20_state_from_bytes, src=raw)
    assert [int(v) for v in back.state] == state_vals
    print("test_chacha20_state_regression PASS")


def test_u320_regression():
    limb_vals = [
        i * 0x0102030405060708 & (2**64 - 1) for i in range(1, U320_NLIMBS + 1)
    ]
    x = u320_t(limbs=limb_vals)
    raw = sim_call(u320_to_bytes, x=x)
    assert len(raw) == U320_NBYTES
    expected = b"".join(v.to_bytes(8, "little") for v in limb_vals)
    assert bytes(int(b) for b in raw) == expected
    back = sim_call(u320_from_bytes, src=raw)
    assert [int(v) for v in back.limbs] == limb_vals
    print("test_u320_regression PASS")


if __name__ == "__main__":
    test_byte_length()
    test_byte_length_enum_rejected()
    test_wires_tagged()
    test_scalar_roundtrip_le()
    test_scalar_roundtrip_be()
    test_array_of_scalar_roundtrip()
    test_struct_roundtrip_byte_rounding()
    test_nested_struct_roundtrip()
    test_array_of_struct_roundtrip()
    test_chacha20_state_regression()
    test_u320_regression()
