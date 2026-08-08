# pyright: reportInvalidTypeForm=none
"""AUTOFSM example: the sine polynomial from float_sine.py, folded onto shared
floating-point hardware.

examples/pypeline/float_sine.py evaluates a degree-5 minimax polynomial in
double precision -- roughly ten float64 multiplies and seven float64 adds -- as
one enormous slab of parallel combinational logic. A float64 multiplier is a
53x53 array multiplier; ten of them is a lot of FPGA.

The polynomial is a Horner chain, so most of those multiplies happen one after
another anyway and there is no throughput to lose by giving them one shared
multiplier:

    poly = c0 + x2*(c1 + x2*(c2 + x2*(c3 + x2*(c4 + x2*c5))))

AUTOFSM schedules exactly that: one float64 multiplier and one float64 adder,
reused across as many states as the clock goal requires.

    $ pypelinec examples/pypeline/float_sine_autofsm.py

Compare the `AUTOFSM ...: N ops -> M shared unit(s)` line and the yosys cell
count against a `--comb` build of the same file.

Scope note: this deliberately wraps `sinf_poly` ALONE rather than the whole of
float_sine.py's `hw_sinf`. The full function instantiates three range-reduction
paths and four separate copies of this polynomial, and is large enough that
synthesizing it does not complete in reasonable time -- which is a statement
about the size of the combinational blob, not about AUTOFSM. The polynomial is
where the folding win is anyway.

AUTOFSM takes exactly one argument, so the polynomial's four inputs are bundled
into one struct here.
"""

from typing import NamedTuple

from pypeline import (
    AUTOFSM,
    MAIN,
    Reg,
    hw_func,
    struct,
    uint1_t,
)
from floating_point import float32_t, float64_t, float64_to_float32

# No PART, so timing comes from PYRTL's software model. A float64 multiply is
# enormous under any model -- it is indivisible as far as AUTOFSM is concerned
# (nothing inside it is Python to reschedule), so it sets the floor on the
# clock. This goal leaves it comfortable room; the point of the example is the
# area, not the fmax.
CLOCK_MHZ = 4.0


@struct
class sincos_t(NamedTuple):
    """Minimax polynomial coefficients (same shape as float_sine.py's)."""

    c0: float64_t
    c1: float64_t
    c2: float64_t
    c3: float64_t
    c4: float64_t
    c5: float64_t


@struct
class poly_in_t(NamedTuple):
    """All of sinf_poly's inputs in one struct: AUTOFSM wraps single-argument
    functions, so multiple inputs get bundled (the same rule
    make_stream_pipeline and make_valid_ready_mcp follow)."""

    x: float64_t
    s_sign: float64_t
    p: sincos_t
    is_odd_quadrant: uint1_t


@hw_func
def sinf_poly(i: poly_in_t) -> float32_t:
    """Degree-5 minimax polynomial, evaluated by Horner's method.

    Ten float64 multiplies and seven float64 adds. As combinational logic that
    is ten multipliers; as an FSM it is one, because the Horner chain is
    sequential -- each multiply needs the previous one's result, so they could
    never have run at the same time anyway. This is the shape where resource
    sharing is nearly free.
    """
    x2: float64_t = i.x * i.x
    poly: float64_t = i.p.c0 + x2 * (
        i.p.c1 + x2 * (i.p.c2 + x2 * (i.p.c3 + x2 * (i.p.c4 + x2 * i.p.c5)))
    )

    result_f64: float64_t
    if i.is_odd_quadrant:
        # Cosine: s_sign * cos(x) = s_sign + (s_sign * x^2) * poly
        result_f64 = i.s_sign + (i.s_sign * x2) * poly
    else:
        # Sine: s_sign * sin(x), where x already carries the sign
        result_f64 = i.x + (i.x * x2) * poly

    return float64_to_float32(result_f64)


POLY_FSM = AUTOFSM(sinf_poly)


@MAIN(CLOCK_MHZ)
def float_sine_autofsm(start: uint1_t, i: poly_in_t) -> float32_t:
    req: POLY_FSM.in_stream_t
    req.data = i
    req.valid = start
    resp = POLY_FSM(req)
    result: Reg[float32_t]
    if resp.valid:
        result = resp.data
    return result
