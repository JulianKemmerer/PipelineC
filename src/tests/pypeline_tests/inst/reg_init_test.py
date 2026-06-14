import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from typing import NamedTuple

from pypeline import (
    MAIN,
    Reg,
    hw_func,
    int32_t,
    sim_call,
    sim_reset,
    struct,
    uint8_t,
    uint32_t,
)


# ── inline struct for struct-init tests ─────────────────────────────────────
@struct
class reg_point_t(NamedTuple):
    x: uint32_t
    y: uint32_t


# ── hardware functions ───────────────────────────────────────────────────────


@MAIN
def counter_from_10() -> uint32_t:
    """Scalar register initialised to 10; first return value is 11."""
    cnt: Reg[uint32_t] = 10
    cnt = cnt + 1
    return cnt


@MAIN
def counter_default() -> uint32_t:
    """Scalar register with no initializer; starts at 0 (unchanged behaviour)."""
    cnt: Reg[uint32_t]
    cnt = cnt + 1
    return cnt


@MAIN
def signed_counter() -> int32_t:
    """Signed register initialised to -5; first return value is -4."""
    n: Reg[int32_t] = -5
    n = n + 1
    return n


@MAIN
def array_reg_read_init() -> uint8_t:
    """Array register initialised to [10, 20, 30, 40]; returns buf[0] unmodified."""
    buf: Reg[uint8_t[4]] = [10, 20, 30, 40]
    return buf[0]


@MAIN
def struct_reg_init_dict() -> uint32_t:
    """Struct register dict style {x:3, y:7}; first return is 10."""
    pt: Reg[reg_point_t] = {"x": 3, "y": 7}
    return pt.x + pt.y


@MAIN
def struct_reg_init_ctor() -> uint32_t:
    """Struct register constructor style reg_point_t(x=5, y=2); first return is 7."""
    pt: Reg[reg_point_t] = reg_point_t(x=5, y=2)
    return pt.x + pt.y


# ── simulation tests ─────────────────────────────────────────────────────────


def test_scalar_init():
    """First call returns init+1 (10+1=11), not 0+1=1."""
    sim_reset()
    first = sim_call(counter_from_10)
    second = sim_call(counter_from_10)
    assert int(first) == 11, f"expected 11, got {int(first)}"
    assert int(second) == 12, f"expected 12, got {int(second)}"
    print(f"test_scalar_init PASS  first={int(first)} second={int(second)}")


def test_default_init_unchanged():
    """No initializer: first call still returns 0+1=1."""
    sim_reset()
    first = sim_call(counter_default)
    assert int(first) == 1, f"expected 1, got {int(first)}"
    print(f"test_default_init_unchanged PASS  first={int(first)}")


def test_signed_init():
    """Signed register init -5: first call returns -5+1=-4."""
    sim_reset()
    first = sim_call(signed_counter)
    second = sim_call(signed_counter)
    assert int(first) == -4, f"expected -4, got {int(first)}"
    assert int(second) == -3, f"expected -3, got {int(second)}"
    print(f"test_signed_init PASS  first={int(first)} second={int(second)}")


def test_array_init():
    """Array register init [10,20,30,40]: first read of buf[0] is 10."""
    sim_reset()
    first = sim_call(array_reg_read_init)
    assert int(first) == 10, f"expected 10 (init buf[0]=10), got {int(first)}"
    print(f"test_array_init PASS  first={int(first)}")


def test_struct_init_dict():
    """Struct register dict style {x:3, y:7}: first return is 3+7=10."""
    sim_reset()
    first = sim_call(struct_reg_init_dict)
    assert int(first) == 10, f"expected 10 (x=3, y=7), got {int(first)}"
    print(f"test_struct_init_dict PASS  result={int(first)}")


def test_struct_init_ctor():
    """Struct register constructor style reg_point_t(x=5, y=2): first return is 5+2=7."""
    sim_reset()
    first = sim_call(struct_reg_init_ctor)
    assert int(first) == 7, f"expected 7 (x=5, y=2), got {int(first)}"
    print(f"test_struct_init_ctor PASS  result={int(first)}")


def test_sim_reset_restores_init():
    """After sim_reset(), register returns to init value, not accumulated state."""
    sim_reset()
    sim_call(counter_from_10)  # state → 11
    sim_call(counter_from_10)  # state → 12
    sim_reset()
    after_reset = sim_call(counter_from_10)  # should restart from 10 → 11
    assert int(after_reset) == 11, f"expected 11 after reset, got {int(after_reset)}"
    print(f"test_sim_reset_restores_init PASS  after_reset={int(after_reset)}")


if __name__ == "__main__":
    test_scalar_init()
    test_default_init_unchanged()
    test_signed_init()
    test_array_init()
    test_struct_init_dict()
    test_struct_init_ctor()
    test_sim_reset_restores_init()
    print("All reg_init tests passed.")
