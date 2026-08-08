# pyright: reportInvalidTypeForm=none
"""Elaboration-only (--no_synth) regression for @sim_input/@sim_output: proves a
design combining both supported @sim_input call forms (direct-write and
return-value) and a bare @sim_output call nested one level inside a plain,
non-MAIN @hw_func elaborates cleanly -- no ElaborationError about writing a
read-only Input[T]/reading an Output[T], no NotImplementedError about an
unsupported statement -- with every sim-only call vanishing from the generated
hardware. Success is simply a zero exit code (pypelinec inst/
sim_input_output_elab_test.py --no_synth).

`in_return`'s body deliberately uses `itertools.count()` -- a Python-only
construct the hardware elaborator cannot represent -- and still carries a
`-> uint32_t` return annotation (the return-value form's natural signature,
matching the user-facing example in the docs). This specifically regression-
tests that @sim_input/@sim_output functions are excluded from PY_TO_LOGIC.py's
unconditional top-level "elaborate every annotated function" sweep: without
that exclusion, this function would independently fail elaboration (as an
unused, never-instantiated orphan) even though every one of its call sites is
correctly skipped -- "ignored during elaboration" must hold for the function
itself, not just its call sites.
"""

import sys, os, itertools

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

from pypeline import MAIN, hw_func, Input, Output, sim_input, sim_output, uint32_t

in0: Input[uint32_t]
_ctr = itertools.count(0)


@sim_input
def in_global():
    in0 = 0


@sim_input
def in_return() -> uint32_t:
    return next(_ctr)


@sim_output
def check_out(v):
    print(v)


@hw_func
def combine(a: uint32_t, b: uint32_t) -> uint32_t:
    check_out(a + b)  # bare @sim_output call nested inside a non-MAIN hw_func
    return a + b


in1: Input[uint32_t]
out0: Output[uint32_t]


@MAIN
def tb():
    in_global()
    in1 = in_return()
    out0 = combine(in0, in1)
