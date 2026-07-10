# pyright: reportInvalidTypeForm=none
"""@sim_input + Input[T] test: exercises both supported call forms in the same
design, per-cycle-varying Python-side counters (not Reg[T], to keep the driving
value purely simulation-side), and a downstream @sim_output checker that
asserts the exact expected combined value every cycle. A broken once-per-cycle
cache would advance a counter more than once per cycle (multiple @sim_input
calls happen every cycle: once during delta-cycle convergence, once more in
the unconditional final pass) or serve a stale value -- either way the checker
assertion would fail. Run only via the multi-MAIN runner
(pypeline_sim.py sim_input_test.py --run N).
"""

import sys, os, itertools

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Input, Output, sim_input, sim_output, uint32_t

_ctr_a = itertools.count(0)  # drives in0 via the direct-write form
_ctr_b = itertools.count(1000)  # drives in1 via the return-value form

in0: Input[uint32_t]


@sim_input
def in_global():
    # Direct-write form: the function's own body assigns directly to the
    # global Input[T] by bare name.
    in0 = next(_ctr_a)


@sim_input
def in_return() -> uint32_t:
    # Return-value form: no wire reference at all -- the caller captures the
    # return value via its own (already AST-rewritten) assignment.
    return next(_ctr_b)


in1: Input[uint32_t]
out0: Output[uint32_t]


@MAIN
def tb_inputs():
    in_global()
    in1 = in_return()


@MAIN
def combine_main():
    out0 = in0 + in1


_expected = [0]  # mutable container -- see sim_output_direct_wire_test.py for why


@sim_output
def check_out():
    v = int(out0)
    expected = _expected[0] + (1000 + _expected[0])
    assert v == expected, (
        f"cycle {_expected[0]}: out0={v} expected={expected} "
        f"(sim_input ran more than once per cycle, or served a stale value?)"
    )
    _expected[0] += 1


@MAIN
def checker_main():
    check_out()
