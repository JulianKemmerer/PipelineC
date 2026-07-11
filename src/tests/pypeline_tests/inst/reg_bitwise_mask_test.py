import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from typing import NamedTuple

from pypeline import MAIN, Reg, SimVal, sim_call, sim_reset, struct, uint1_t


@struct
class s_t(NamedTuple):
    a: uint1_t
    b: uint1_t


@MAIN
def g(set_have: uint1_t, y: uint1_t) -> s_t:
    """Repro: struct field written from `~reg_var | operand` must be masked to
    uint1_t on every cycle, not just power-on (cycle 1)."""
    have: Reg[uint1_t]
    o: s_t
    o.a = ~have | y  # compound bitwise expr through a Reg[uint1_t]
    o.b = ~have  # control: bare complement, already correct pre-fix
    if set_have:
        have = 1
    return o


@MAIN
def h() -> s_t:
    """Reg[uint1_t] with a scalar literal power-on init, read via bitwise ops
    on cycle 0 before any reassignment."""
    have: Reg[uint1_t] = 1
    o: s_t
    o.a = ~have | 0
    o.b = ~have
    return o


def test_bitwise_mask_across_cycles():
    """Cycle-by-cycle repro from the bug report: a/b must stay in {0, 1}."""
    sim_reset()
    r1 = sim_call(g, 1, 0)  # cycle 1: have reads power-on 0, then set_have=1 -> have=1
    assert (int(r1.a), int(r1.b)) == (
        1,
        1,
    ), f"cycle1 expected (1,1), got {(int(r1.a), int(r1.b))}"

    r2 = sim_call(g, 0, 0)  # cycle 2: have reads back 1 (written last cycle)
    assert (int(r2.a), int(r2.b)) == (
        0,
        0,
    ), f"cycle2 expected (0,0), got {(int(r2.a), int(r2.b))}"

    r3 = sim_call(g, 0, 1)  # cycle 3: have still 1, y=1
    assert (int(r3.a), int(r3.b)) == (
        1,
        0,
    ), f"cycle3 expected (1,0), got {(int(r3.a), int(r3.b))}"
    print("test_bitwise_mask_across_cycles PASS")


def test_reg_literal_init_bitwise():
    """Reg[uint1_t] = 1 literal init must be typed/masked from cycle 0."""
    sim_reset()
    r = sim_call(h)
    assert (int(r.a), int(r.b)) == (0, 0), f"expected (0,0), got {(int(r.a), int(r.b))}"
    print("test_reg_literal_init_bitwise PASS")


def test_or_masks_raw_negative_operand():
    """Bitwise dunders in isolation: OR-ing an out-of-range-but-typed SimVal
    against another typed SimVal must mask to the ctype's width, not leak the
    raw value through _bitwise_ctype's ctype-adoption."""
    v = SimVal(-2, uint1_t) | SimVal(1, uint1_t)
    assert int(v) in (0, 1), f"__or__ left unmasked value: {int(v)}"
    v = SimVal(1, uint1_t) | SimVal(-2, uint1_t)
    assert int(v) in (0, 1), f"__ror__ left unmasked value: {int(v)}"
    v = -2 | SimVal(1, uint1_t)
    assert int(v) in (0, 1), f"plain-int __ror__ left unmasked value: {int(v)}"
    print("test_or_masks_raw_negative_operand PASS")


if __name__ == "__main__":
    test_bitwise_mask_across_cycles()
    test_reg_literal_init_bitwise()
    test_or_masks_raw_negative_operand()
    print("All reg_bitwise_mask tests passed.")
