import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from enum import IntEnum
from typing import NamedTuple

from pypeline import (
    MAIN,
    Reg,
    enum,
    enum_bit_width,
    enum_uint_type,
    hw_func,
    sim_call,
    sim_reset,
    struct,
    uint1_t,
    uint2_t,
    uint8_t,
    uint32_t,
)


# ── static enum definition via @enum on an IntEnum subclass ─────────────────


@enum
class state_t(IntEnum):
    IDLE = 0
    RUNNING = 1
    DONE = 2


# ── parameterizable factory using enum(IntEnum(...)) ─────────────────────────


def make_color_t(include_alpha=True):
    members = {"RED": 0, "GREEN": 1, "BLUE": 2}
    if include_alpha:
        members["ALPHA"] = 3
    return enum(IntEnum("color_t", members))


color_t = make_color_t(include_alpha=True)  # 4 states, needs 2 bits
color3_t = make_color_t(include_alpha=False)  # 3 states, needs 2 bits


# ── @enum on a plain class (auto-converted to IntEnum) ───────────────────────


@enum
class direction_t:
    NORTH = 0
    EAST = 1
    SOUTH = 2
    WEST = 3


# ── struct with an enum field ────────────────────────────────────────────────


@struct
class packet_t(NamedTuple):
    state: state_t
    data: uint8_t


# ── hardware functions ───────────────────────────────────────────────────────


@MAIN
def passthrough_state(s: state_t) -> state_t:
    return s


@MAIN
def is_idle(s: state_t) -> uint1_t:
    rv: uint1_t = 0
    if s == state_t.IDLE:
        rv = 1
    return rv


@MAIN
def simple_fsm(trigger: uint1_t) -> state_t:
    st: Reg[state_t]
    if st == state_t.IDLE and trigger:
        st = state_t.RUNNING
    elif st == state_t.RUNNING:
        st = state_t.DONE
    return st


@MAIN
def make_packet(s: state_t, d: uint8_t) -> packet_t:
    p: packet_t
    p.state = s
    p.data = d
    return p


@MAIN
def read_packet_state(p: packet_t) -> state_t:
    return p.state


@MAIN
def passthrough_color(c: color_t) -> color_t:
    return c


@MAIN
def passthrough_direction(d: direction_t) -> direction_t:
    return d


# ── simulation tests ─────────────────────────────────────────────────────────


def test_passthrough():
    sim_reset()
    for member in state_t:
        r = sim_call(passthrough_state, s=member)
        assert int(r) == member.value, f"expected {member.value}, got {int(r)}"
    print("test_passthrough PASS")


def test_is_idle():
    sim_reset()
    assert int(sim_call(is_idle, s=state_t.IDLE)) == 1
    assert int(sim_call(is_idle, s=state_t.RUNNING)) == 0
    assert int(sim_call(is_idle, s=state_t.DONE)) == 0
    print("test_is_idle PASS")


def test_simple_fsm():
    sim_reset()
    r0 = sim_call(simple_fsm, trigger=0)
    assert int(r0) == state_t.IDLE.value, f"expected IDLE, got {r0}"
    r1 = sim_call(simple_fsm, trigger=1)
    assert int(r1) == state_t.RUNNING.value, f"expected RUNNING, got {r1}"
    r2 = sim_call(simple_fsm, trigger=0)
    assert int(r2) == state_t.DONE.value, f"expected DONE, got {r2}"
    r3 = sim_call(simple_fsm, trigger=0)
    assert int(r3) == state_t.DONE.value, f"expected DONE (stuck), got {r3}"
    print("test_simple_fsm PASS")


def test_packet_field():
    sim_reset()
    p = sim_call(make_packet, s=state_t.RUNNING, d=42)
    assert int(p.state) == state_t.RUNNING.value, f"expected RUNNING, got {p.state}"
    assert int(p.data) == 42, f"expected 42, got {p.data}"
    s = sim_call(read_packet_state, p=p)
    assert int(s) == state_t.RUNNING.value, f"expected RUNNING, got {s}"
    print("test_packet_field PASS")


def test_factory_enum():
    sim_reset()
    for member in color_t:
        r = sim_call(passthrough_color, c=member)
        assert int(r) == member.value, f"expected {member.value}, got {int(r)}"
    print("test_factory_enum PASS")


def test_plain_class_enum():
    sim_reset()
    for member in direction_t:
        r = sim_call(passthrough_direction, d=member)
        assert int(r) == member.value, f"expected {member.value}, got {int(r)}"
    print("test_plain_class_enum PASS")


def test_introspection():
    assert enum_bit_width(state_t) == 2, f"expected 2, got {enum_bit_width(state_t)}"
    u = enum_uint_type(state_t)
    assert str(u) == str(uint2_t), f"expected uint2_t, got {u}"
    assert enum_bit_width(color_t) == 2
    assert enum_bit_width(color3_t) == 2
    print("test_introspection PASS")


def test_parameterizable():
    full = make_color_t(include_alpha=True)
    slim = make_color_t(include_alpha=False)
    assert enum_bit_width(full) == 2
    assert enum_bit_width(slim) == 2
    assert len(list(full)) == 4
    assert len(list(slim)) == 3
    print("test_parameterizable PASS")


if __name__ == "__main__":
    test_passthrough()
    test_is_idle()
    test_simple_fsm()
    test_packet_field()
    test_factory_enum()
    test_plain_class_enum()
    test_introspection()
    test_parameterizable()
    print("All enum tests passed.")
