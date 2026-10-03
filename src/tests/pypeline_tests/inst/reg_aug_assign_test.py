# pyright: reportInvalidTypeForm=none
"""Augmented assignment (`t op= rhs`) native-simulation regression tests.

PY_TO_LOGIC elaborates `t op= rhs` as `t = t op rhs`, and native simulation
must do the same.  Before this was fixed, `_TypedAnnAssignRewriter` had no
AugAssign rule, so `reg_arr[i] += 1` ran as plain Python and edited the
committed register list in place.  pypeline_sim evaluates every MAIN at least
twice per clock (convergence loop + final pass) and Feedback convergence
re-runs a body until it settles, so the later evaluations saw the register
change before the clock edge.  The same gap left scalar `x += 1` unwrapped at
the declared width, crashed `reg_struct.field += 1`, and let a cycle-0
increment leak through the shared power-on zero object into a second
instance.  Writes to an array/struct/scalar *parameter* had the plain-`=`
version of the problem: an array write edited the caller's register.

The @MAIN below is used by pypeline_sim (--run all, the multi-evaluation
runner) and by the native-vs-VHDL compare.  The direct sim_call tests cover
the rest, using _clock() to evaluate each body more than once per clock the
way pypeline_sim does.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

from typing import NamedTuple

import pypeline
from pypeline import (
    MAIN,
    Feedback,
    Reg,
    hw_func,
    int8_t,
    int16_t,
    sim_assert,
    sim_call,
    sim_finish,
    sim_print,
    sim_reset,
    struct,
    uint1_t,
    uint8_t,
    uint32_t,
)


@struct
class aug_pair_t(NamedTuple):
    a: uint8_t
    arr: uint8_t[2]


@struct
class aug_obs_t(NamedTuple):
    a: uint32_t
    b: uint32_t
    c: uint32_t
    d: uint32_t


@MAIN
def reg_aug_assign():
    cycle: Reg[uint32_t]
    aug: Reg[uint32_t[2]]
    plain: Reg[uint32_t[2]]
    wrap: Reg[uint8_t[2]]
    small: Reg[uint8_t] = 250
    sgn: Reg[int8_t] = -127
    s: Reg[aug_pair_t]
    s_plain: Reg[aug_pair_t]

    # The handoff repro: a register changes only at the clock edge, and the
    # augmented form tracks the plain form cycle for cycle.
    sim_assert(aug[0] == cycle, "augmented Reg array changed before clock edge")
    sim_assert(plain[0] == cycle, "plain Reg array changed before clock edge")
    sim_assert(s.a == s_plain.a, "Reg struct field += diverged from plain")
    sim_assert(s.arr[0] == s_plain.arr[0], "Reg nested [0] += diverged")
    sim_assert(s.arr[1] == s_plain.arr[1], "Reg nested [1] += diverged")
    if cycle == 2:
        sim_assert(small == 0, "uint8_t += must wrap")  # 250, 253, 0
        sim_assert(sgn == 127, "int8_t -= must wrap")  # -127, -128, 127
    if cycle == 3:
        sim_assert(wrap[1] == 44, "uint8_t element += must wrap")  # 0, 100, 200, 44

    # No debug print on the sim_finish cycle: GHDL's output flush ordering is
    # intentionally not part of the native-vs-VHDL comparison contract.
    if cycle < 5:
        sim_print(
            f"reg_aug_assign cycle={cycle} aug={aug[0]} wrap={wrap[1]} small={small} "
            f"sgn={sgn} a={s.a} arr0={s.arr[0]} arr1={s.arr[1]}",
            debug=True,
        )
    if cycle == 5:
        sim_finish()

    idx: uint1_t = cycle
    aug[0] += 1
    plain[0] = plain[0] + 1
    wrap[1] += 100
    small += 3
    sgn -= 1
    s.a += 1
    s.arr[idx] += 3
    s_plain.a = s_plain.a + 1
    s_plain.arr[idx] = s_plain.arr[idx] + 3
    cycle += 1


def _clock(func, *args, evals=2):
    """One simulated clock, the way pypeline_sim.py runs it: the body is
    evaluated `evals` times against the same committed register state, then
    every register write commits together.  Every evaluation must return the
    same value -- a body that changes committed state fails here."""
    prev_active = pypeline._sim_active
    pypeline._sim_active = True
    pypeline._sim_reg_begin_buffer()
    try:
        outs = [sim_call(func, *args) for _ in range(evals)]
    finally:
        pypeline._sim_reg_flush_buffer()
        pypeline._sim_active = prev_active
    assert all(o == outs[0] for o in outs), f"evaluations disagree within one clock: {outs}"
    return outs[0]


def _run(func, cycles, *args, evals=2):
    sim_reset()
    return [_clock(func, *args, evals=evals) for _ in range(cycles)]


def _ints(values):
    return [int(v) for v in values]


def _obs(values):
    return [tuple(int(f) for f in v) for v in values]


# -- The handoff repro, both variants ----------------------------------------


@hw_func
def repro_augmented() -> uint32_t:
    counters: Reg[uint32_t[2]]
    old: uint32_t = counters[0]
    counters[0] += 1
    return old


@hw_func
def repro_plain() -> uint32_t:
    counters: Reg[uint32_t[2]]
    old: uint32_t = counters[0]
    counters[0] = counters[0] + 1
    return old


def test_handoff_repro_matches_plain_assignment():
    for evals in (1, 2, 3):
        aug = _ints(_run(repro_augmented, 5, evals=evals))
        plain = _ints(_run(repro_plain, 5, evals=evals))
        assert aug == plain == [0, 1, 2, 3, 4], (evals, aug, plain)


def test_power_on_value_survives_sim_reset():
    # The first read of a never-written register returns the shared power-on
    # object; an in-place write used to corrupt it for every later reset.
    for _ in range(2):
        assert _ints(_run(repro_augmented, 3)) == [0, 1, 2]
        assert _ints(_run(scalar_wrap, 4)) == [254, 255, 0, 1]


# -- Width truncation ----------------------------------------------------------


@hw_func
def scalar_wrap() -> uint32_t:
    x: Reg[uint8_t] = 254
    old: uint32_t = x
    x += 1
    return old


@hw_func
def signed_wrap() -> int16_t:
    y: Reg[int8_t] = -127
    old: int16_t = y
    y -= 1
    return old


@hw_func
def leaf_wrap() -> aug_obs_t:
    arr: Reg[uint8_t[2]]
    s: Reg[aug_pair_t]
    o: aug_obs_t
    o.a = arr[1]
    o.b = s.a
    o.c = s.arr[0]
    arr[1] += 100
    s.a += 100
    s.arr[0] += 100
    return o


def test_scalar_targets_wrap_at_declared_width():
    assert _ints(_run(scalar_wrap, 4)) == [254, 255, 0, 1]
    assert _ints(_run(signed_wrap, 4)) == [-127, -128, 127, 126]


def test_compound_leaves_wrap_at_declared_width():
    seq = [0, 100, 200, 44, 144]
    assert _obs(_run(leaf_wrap, 5)) == [(v, v, v, 0) for v in seq]


# -- Struct fields, nested paths, variable index, read-after-write ------------


@hw_func
def struct_fields() -> aug_obs_t:
    s: Reg[aug_pair_t]
    n: Reg[uint8_t]
    o: aug_obs_t
    o.a = s.a
    o.b = s.arr[0]
    o.c = s.arr[1]
    idx: uint1_t = n
    s.a += 1
    s.arr[idx] += 3
    n += 1
    return o


@hw_func
def read_after_write() -> aug_obs_t:
    c: Reg[uint8_t[2]]
    o: aug_obs_t
    o.a = c[0]
    c[0] += 1
    o.b = c[0]
    c[0] += 1
    o.c = c[0]
    return o


def test_struct_field_and_variable_index_nested_path():
    assert _obs(_run(struct_fields, 5)) == [
        (0, 0, 0, 0),
        (1, 3, 0, 0),
        (2, 3, 3, 0),
        (3, 6, 3, 0),
        (4, 6, 6, 0),
    ]


def test_sequential_read_after_write():
    assert _obs(_run(read_after_write, 4)) == [(2 * k, 2 * k + 1, 2 * k + 2, 0) for k in range(4)]


# -- Every supported operator, against the plain-assignment form --------------


@hw_func
def ops_augmented(v: uint8_t) -> uint8_t[9]:
    acc: Reg[uint8_t[8]]
    o: uint8_t[9]
    for i in range(8):
        o[i] = acc[i]
    acc[0] += v
    acc[1] -= v
    acc[2] += 3
    acc[2] *= v
    acc[3] += v
    acc[3] >>= 1
    acc[4] += v
    acc[4] <<= 1
    acc[5] |= 0x5A
    acc[5] &= v
    acc[6] |= v
    acc[7] ^= v
    t: uint8_t = acc[0]
    t += v
    t -= 3
    t *= v
    t >>= 1
    t <<= 2
    t &= 0xFE
    t |= 1
    t ^= v
    o[8] = t
    return o


@hw_func
def ops_plain(v: uint8_t) -> uint8_t[9]:
    acc: Reg[uint8_t[8]]
    o: uint8_t[9]
    for i in range(8):
        o[i] = acc[i]
    acc[0] = acc[0] + v
    acc[1] = acc[1] - v
    acc[2] = acc[2] + 3
    acc[2] = acc[2] * v
    acc[3] = acc[3] + v
    acc[3] = acc[3] >> 1
    acc[4] = acc[4] + v
    acc[4] = acc[4] << 1
    acc[5] = acc[5] | 0x5A
    acc[5] = acc[5] & v
    acc[6] = acc[6] | v
    acc[7] = acc[7] ^ v
    t: uint8_t = acc[0]
    t = t + v
    t = t - 3
    t = t * v
    t = t >> 1
    t = t << 2
    t = t & 0xFE
    t = t | 1
    t = t ^ v
    o[8] = t
    return o


def test_all_operators_match_plain_assignment():
    vs = [3, 250, 17, 0, 255, 129, 64]

    def run(func):
        sim_reset()
        return [_ints(_clock(func, v)) for v in vs]

    aug, plain = run(ops_augmented), run(ops_plain)
    assert aug == plain, (aug, plain)
    assert all(0 <= x <= 255 for row in aug for x in row), aug
    assert any(row != [0] * 9 for row in aug)


# -- Feedback convergence re-runs the body -------------------------------------


@hw_func
def feedback_counter(x: uint8_t) -> uint32_t:
    fb: Feedback[uint8_t]
    counts: Reg[uint32_t[2]]
    old: uint32_t = counts[0]
    seen: uint8_t = fb
    counts[0] += 1
    fb = x
    return old


def test_feedback_convergence_advances_once_per_clock():
    # Each call converges over several passes (fb starts at 0, settles at x,
    # then one unsuppressed final pass); the register must advance once.
    sim_reset()
    assert [int(sim_call(feedback_counter, 5)) for _ in range(4)] == [0, 1, 2, 3]
    assert _ints(_run(feedback_counter, 4, 5)) == [0, 1, 2, 3]


# -- Instance isolation through the shared power-on object --------------------


@hw_func
def step_counter(step: uint8_t) -> uint8_t:
    c: Reg[uint8_t[2]]
    old: uint8_t = c[0]
    c[0] += step
    return old


@hw_func
def two_counters() -> aug_obs_t:
    o: aug_obs_t
    o.a = step_counter(1)
    o.b = step_counter(10)
    return o


def test_two_instances_do_not_share_state():
    for evals in (1, 2):
        assert _obs(_run(two_counters, 4, evals=evals)) == [(k, 10 * k, 0, 0) for k in range(4)]


# -- Typed local copies and parameters are values, not aliases ----------------


@hw_func
def typed_copy() -> aug_obs_t:
    counters: Reg[uint32_t[2]]
    o: aug_obs_t
    o.a = counters[0]
    snap: uint32_t[2] = counters
    snap[0] += 5
    o.b = snap[0]
    return o


@hw_func
def bump_param_array(a: uint8_t[2]) -> uint8_t:
    a[0] += 7
    a[1] = 9
    return a[0]


@hw_func
def bump_param_struct(p: aug_pair_t) -> uint8_t:
    p.a += 1
    p.arr[1] += 2
    return p.a


@hw_func
def bump_param_scalar(x: uint8_t) -> uint32_t:
    x += 10
    return x


@hw_func
def param_caller() -> aug_obs_t:
    r: Reg[uint8_t[2]]
    s: Reg[aug_pair_t]
    o: aug_obs_t
    o.a = r[0]
    o.b = r[1]
    o.c = s.a
    o.d = s.arr[1]
    got_r: uint8_t = bump_param_array(r)
    got_s: uint8_t = bump_param_struct(s)
    sim_assert(got_r == 7, "array parameter += lost")
    sim_assert(got_s == 1, "struct parameter += lost")
    return o


def test_typed_local_copy_does_not_alias_register():
    assert _obs(_run(typed_copy, 3)) == [(0, 5, 0, 0)] * 3


def test_parameter_writes_do_not_reach_the_caller():
    # Hardware ports are pass-by-value: the callee's writes never reach the
    # caller's registers.
    assert _obs(_run(param_caller, 3)) == [(0, 0, 0, 0)] * 3
    arg = [1, 2]
    assert int(sim_call(bump_param_array, arg)) == 8
    assert arg == [1, 2]
    assert int(sim_call(bump_param_scalar, 250)) == 4


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
