# pyright: reportInvalidTypeForm=none
"""AUTOFSM basics: a pure function with several same-kind operations, wrapped
so the tool implements it as a resource-shared FSM instead of a wide blob of
combinational logic.

Registered three ways, each proving something different:
  native_sim  plain `python3 autofsm_test.py` -- the tag behaves as an
              identity passthrough when no schedule is installed, so the
              function's own semantics are checkable with sim_call.
  elab        `pypelinec --no_synth` -- the bootstrap (no-schedule) call site
              elaborates: the combinational passthrough wrapper that puts the
              real function into the design for delay measurement.
  synth       driven by the autofsm_latency_test wrapper, which runs the full
              build and asserts on the scheduling that comes out of it.

The clock goal is deliberately low enough that several operations could fit in
one state, so the schedule is a real scheduling decision rather than a forced
one-operation-per-state fallback.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    AUTOFSM,
    MAIN,
    NamedTuple,
    Reg,
    hw_func,
    int16_t,
    sim_call,
    struct,
    uint1_t,
)


@struct
class blob_in_t(NamedTuple):
    a: int16_t
    b: int16_t
    c: int16_t
    d: int16_t


@hw_func
def blob(x: blob_in_t) -> int16_t:
    """Four adds and a subtract of one type, plus a constant shift, a compare
    and a conditional -- i.e. several instances of the SAME operation, which is
    what AUTOFSM folds onto shared hardware, plus enough variety to exercise
    the shift/compare/mux paths of the code generator."""
    t0: int16_t = x.a + x.b
    t1: int16_t = t0 + x.c
    t2: int16_t = t1 - x.d
    t3: int16_t = t2 + t0
    half: int16_t = t3 >> 1
    rv: int16_t = half
    if t3 > 100:
        rv = half + x.a
    return rv


BLOB_FSM = AUTOFSM(blob)


@MAIN(25.0)
def autofsm_top(start: uint1_t, x: blob_in_t) -> int16_t:
    s: BLOB_FSM.in_stream_t
    s.data = x
    s.valid = start
    o = BLOB_FSM(s)
    result: Reg[int16_t]
    if o.valid:
        result = o.data
    return result


def _model(a, b, c, d):
    """Python reference for blob(), in plain ints (values chosen to stay well
    inside int16 so no wrapping is involved)."""
    t0 = a + b
    t1 = t0 + c
    t2 = t1 - d
    t3 = t2 + t0
    half = t3 >> 1
    return half + a if t3 > 100 else half


if __name__ == "__main__":
    for a, b, c, d in [(1, 2, 3, 4), (10, 20, 30, 40), (100, 7, 5, 3), (0, 0, 0, 1)]:
        got = sim_call(blob, blob_in_t(a=a, b=b, c=c, d=d))
        want = _model(a, b, c, d)
        assert got == want, f"blob({a},{b},{c},{d}) = {got}, expected {want}"
    # With no schedule installed (plain native sim), the tag is a zero-latency
    # passthrough that carries valid through unchanged.
    assert BLOB_FSM.latency == 0, "unscheduled AUTOFSM should report latency 0"
    s = BLOB_FSM.in_stream_t(data=blob_in_t(a=1, b=2, c=3, d=4), valid=1)
    o = BLOB_FSM(s)
    assert o.valid == 1 and o.data == _model(1, 2, 3, 4), f"passthrough gave {o}"
    print("autofsm_test PASS")
