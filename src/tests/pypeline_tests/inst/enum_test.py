import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from enum import IntEnum, auto
from typing import NamedTuple

from pypeline import (
    MAIN,
    PypelineEnum,
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


# ── auto() enums: plain-class form (0-based) ────────────────────────────────


@enum
class auto_state_t:
    IDLE = auto()
    RUNNING = auto()
    DONE = auto()


# ── auto() enums: PypelineEnum base class form (0-based) ─────────────────────


@enum
class auto_color_t(PypelineEnum):
    RED = auto()
    GREEN = auto()
    BLUE = auto()


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


@MAIN
def passthrough_auto_state(s: auto_state_t) -> auto_state_t:
    return s


@MAIN
def passthrough_auto_color(c: auto_color_t) -> auto_color_t:
    return c


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


def test_auto_plain_class_enum():
    """auto() in a plain class assigns 0-based values (IDLE=0, RUNNING=1, DONE=2)."""
    assert auto_state_t.IDLE.value == 0, f"expected 0, got {auto_state_t.IDLE.value}"
    assert (
        auto_state_t.RUNNING.value == 1
    ), f"expected 1, got {auto_state_t.RUNNING.value}"
    assert auto_state_t.DONE.value == 2, f"expected 2, got {auto_state_t.DONE.value}"
    sim_reset()
    for member in auto_state_t:
        r = sim_call(passthrough_auto_state, s=member)
        assert int(r) == member.value, f"expected {member.value}, got {int(r)}"
    print("test_auto_plain_class_enum PASS")


def test_pypeline_enum_base():
    """PypelineEnum base class gives 0-based auto() for the IntEnum-subclass form."""
    assert auto_color_t.RED.value == 0, f"expected 0, got {auto_color_t.RED.value}"
    assert auto_color_t.GREEN.value == 1, f"expected 1, got {auto_color_t.GREEN.value}"
    assert auto_color_t.BLUE.value == 2, f"expected 2, got {auto_color_t.BLUE.value}"
    sim_reset()
    for member in auto_color_t:
        r = sim_call(passthrough_auto_color, c=member)
        assert int(r) == member.value, f"expected {member.value}, got {int(r)}"
    print("test_pypeline_enum_base PASS")


def test_auto_introspection():
    """Bit-width introspection is correct for auto() enums."""
    assert (
        enum_bit_width(auto_state_t) == 2
    ), f"expected 2, got {enum_bit_width(auto_state_t)}"
    assert (
        enum_bit_width(auto_color_t) == 2
    ), f"expected 2, got {enum_bit_width(auto_color_t)}"
    print("test_auto_introspection PASS")


if __name__ == "__main__":
    test_passthrough()
    test_is_idle()
    test_simple_fsm()
    test_packet_field()
    test_factory_enum()
    test_plain_class_enum()
    test_introspection()
    test_parameterizable()
    test_auto_plain_class_enum()
    test_pypeline_enum_base()
    test_auto_introspection()
    print("All enum tests passed.")
