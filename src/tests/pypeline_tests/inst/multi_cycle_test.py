# pyright: reportInvalidTypeForm=none
import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from typing import NamedTuple
from pypeline import (
    MAIN,
    MULTI_CYCLE,
    PART,
    struct,
    Reg,
    hw_func,
    sim_call,
    sim_reset,
    uint32_t,
)

# Arty A7-35T — multi-cycle path constraints require Vivado synthesis for now
PART("xc7a35ticsg324-1l")


@struct
class my_struct_t(NamedTuple):
    field: uint32_t


@hw_func
def big_comb_multi_cycle_func(x: my_struct_t) -> my_struct_t:
    rv: my_struct_t
    rv.field = x.field / ~x.field
    return rv


@hw_func
def my_fsm(i: my_struct_t) -> my_struct_t:
    o: my_struct_t
    MC = MULTI_CYCLE[32]
    data0: Reg[my_struct_t, MC.start]
    data1: Reg[my_struct_t, MC.end]
    o = data1
    data1 = big_comb_multi_cycle_func(data0)
    data0 = i
    return o


@MAIN(100.0)
def wrapper(x: my_struct_t) -> my_struct_t:
    rv: my_struct_t
    rv.field = x.field
    for i in range(3):
        f = my_fsm(rv)
        rv.field = rv.field | f.field
    return rv


# ── simulation tests ─────────────────────────────────────────────────────────
# Exercises the canonical `rv: my_struct_t` (bare, no initializer) then
# `rv.field = expr` idiom under pure-Python simulation (sim_call), not just the
# real AST elaborator (./src/pipelinec ... --comb).


def test_big_comb_multi_cycle_func():
    """Bare struct local + single field write, no registers: rv.field = x.field / ~x.field."""
    sim_reset()
    result = sim_call(big_comb_multi_cycle_func, my_struct_t(field=3000000000))
    assert int(result.field) == 2, f"expected 2, got {int(result.field)}"
    print(f"test_big_comb_multi_cycle_func PASS  result={int(result.field)}")


def test_wrapper_runs():
    """@MAIN function with a bare struct local (rv) calling a stateful @hw_func
    inside a Python loop: smoke test that the whole file simulates end-to-end."""
    sim_reset()
    result = sim_call(wrapper, my_struct_t(field=7))
    assert isinstance(result, my_struct_t), f"expected my_struct_t, got {type(result)}"
    assert int(result.field) == 7, f"expected 7, got {int(result.field)}"
    print(f"test_wrapper_runs PASS  result={int(result.field)}")


if __name__ == "__main__":
    test_big_comb_multi_cycle_func()
    test_wrapper_runs()
    print("All multi_cycle tests passed.")
