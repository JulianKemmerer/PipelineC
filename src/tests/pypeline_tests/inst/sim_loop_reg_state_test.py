# pyright: reportInvalidTypeForm=none
"""Native-simulation loop-instance regression tests.

PY_TO_LOGIC unrolls each source-loop iteration into a separate hardware
instance.  Native simulation must give a stateful call from one source line
the same structural identity: loop source span plus zero-based iteration
ordinal, rather than the iterator value or the number of calls that happened
to execute at runtime.

The @MAIN below is used by native-vs-VHDL simulation.  The direct sim_call
tests cover for/while, duplicate iterator values, nested loops, a pure helper
between the loop and the stateful call, and runtime-gated iterations.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

import pypeline
from pypeline import (
    MAIN,
    Reg,
    hw_func,
    sim_assert,
    sim_call,
    sim_finish,
    sim_print,
    sim_reset,
    uint1_t,
    uint8_t,
)


@hw_func
def acc_step(x: uint8_t) -> uint8_t:
    c: Reg[uint8_t]
    old: uint8_t = c
    c = old + x
    return old


@hw_func
def for_loop_chain() -> uint8_t:
    y: uint8_t = 10
    # Duplicate values prove the identity is the ordinal, never the value.
    for _ in (0, 0):
        y = acc_step(y)
    return y


@hw_func
def while_loop_chain() -> uint8_t:
    y: uint8_t = 10
    i = 0
    while i < 2:
        y = acc_step(y)
        i += 1
    return y


@hw_func
def nested_loop_chain() -> uint8_t:
    y: uint8_t = 10
    for _outer in (0, 0):
        for _inner in (0, 0):
            y = acc_step(y)
    return y


@hw_func
def pure_step_helper(x: uint8_t) -> uint8_t:
    # This is deliberately stateless, so its wrapper keeps the fast path and
    # acc_step sees only the caller's loop frames plus its own call site.
    return acc_step(x)


@hw_func
def two_pure_helper_loops() -> uint8_t:
    y: uint8_t = 10
    for _ in (0, 0):
        y = pure_step_helper(y)
    for _ in (0, 0):
        y = pure_step_helper(y)
    return y


@hw_func
def runtime_gated_loop(mask: uint1_t[2]) -> uint8_t:
    y: uint8_t = 10
    for i in range(2):
        if mask[i]:
            y = acc_step(y)
    return y


@MAIN
def sim_loop_reg_state():
    n: Reg[uint8_t]
    y: uint8_t = for_loop_chain()

    # Four clock-edge observations of independent loop instances: 0, 0, 10,
    # 30.  The former shared-bank native simulation instead stayed at zero.
    if n == 0:
        sim_assert(y == 0)
    elif n == 1:
        sim_assert(y == 0)
    elif n == 2:
        sim_assert(y == 10)
    else:
        sim_assert(y == 30)

    # No debug print on the sim_finish cycle: GHDL's output flush ordering is
    # intentionally not part of the native-vs-VHDL comparison contract.
    if n < 3:
        sim_print(f"sim_loop_reg_state y={y}", debug=True)
    if n == 3:
        sim_finish()
    n += 1


def _observe(func, cycles):
    return [int(sim_call(func)) for _ in range(cycles)]


def _assert_stack_clean():
    assert not pypeline._sim_inst_stack, pypeline._sim_inst_stack


def test_for_and_while_loop_instances_are_independent():
    sim_reset()
    assert _observe(for_loop_chain, 4) == [0, 0, 10, 30]
    _assert_stack_clean()

    sim_reset()
    assert _observe(while_loop_chain, 4) == [0, 0, 10, 30]
    _assert_stack_clean()


def test_nested_and_pure_helper_loop_instances_are_independent():
    sim_reset()
    assert _observe(nested_loop_chain, 5) == [0, 0, 0, 0, 10]
    _assert_stack_clean()

    sim_reset()
    assert _observe(two_pure_helper_loops, 5) == [0, 0, 0, 0, 10]
    _assert_stack_clean()


def test_runtime_gated_iterations_keep_their_own_state():
    sim_reset()
    assert int(sim_call(runtime_gated_loop, [1, 0])) == 0
    assert int(sim_call(runtime_gated_loop, [0, 1])) == 0
    assert int(sim_call(runtime_gated_loop, [1, 0])) == 10
    assert int(sim_call(runtime_gated_loop, [0, 1])) == 10
    _assert_stack_clean()


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
