"""Manual Vivado area probe: native `*` vs the Karatsuba hybrid with inferred
leaves (operators/soft_mult.py make_mult_karatsuba_inferred_leaves), on the
WireGuard part. Not registered in run_all; results and the run recipe are in
docs/SYN_DESIGN.md#karatsuba-with-inferred-leaves.

    pypelinec karatsuba_inferred_leaves.py -D VARIANT=hybrid -D WIDTH=130 \\
        --out_dir <new dir>

VARIANT: inferred (plain `*`), hybrid (exact-type registration of the
threshold-34 hybrid), soft (register_soft_mult_karatsuba, all-fabric).
Registered inputs and output, no internal registers, no clock goal: an
area probe only. Read DSP48E1 / Slice LUTs / Slice Registers from the
report_utilization section of the Vivado log.
"""
from pypeline import MAIN, PART, Reg, hw_func, make_uint_t, param, register_operator

from operators.soft import register_soft_mult_karatsuba
from operators.soft_mult import make_mult_karatsuba_inferred_leaves

PART("xc7a200tffg1156-2")
VARIANT = param("VARIANT", "hybrid", choices=("inferred", "hybrid", "soft"))
WIDTH = param("WIDTH", 130)
in_t = make_uint_t(WIDTH)
out_t = make_uint_t(2 * WIDTH)

if VARIANT == "hybrid":
    register_operator(
        "INFERRED_MULT", in_t, in_t, make_mult_karatsuba_inferred_leaves(in_t, in_t)
    )
elif VARIANT == "soft":
    register_soft_mult_karatsuba()


@hw_func
def product(a: in_t, b: in_t) -> out_t:
    result: out_t = a * b
    return result


@MAIN
def probe(a: in_t, b: in_t) -> out_t:
    ar: Reg[in_t]
    br: Reg[in_t]
    result: Reg[out_t]
    previous: out_t = result
    result = product(ar, br)
    ar = a
    br = b
    return previous
