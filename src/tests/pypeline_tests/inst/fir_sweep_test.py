# pyright: reportInvalidTypeForm=none
"""Full autopipelining throughput-sweep coverage for one dsp/fir.py filter:
proves the FIR comb blob (pre-adders + const multiplies + adder tree + resize)
actually retimes to meet a @MAIN frequency goal, rather than only elaborating
under --comb. Kept to a single small filter so the sweep stays fast; broad
per-mode elaboration coverage lives in fir_test.py (--comb)."""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)

from pypeline import MAIN, uint1_t

from fixed_point import make_fixed_t
from dsp.fir import make_fir

data_t = make_fixed_t(1, 7)
coeff_t = make_fixed_t(2, 6)

fir_sweep, fir_sweep_t = make_fir(
    [0.0625, 0.25, 0.375, 0.25, 0.0625],  # symmetric 5-tap
    coeff_t,
    data_t,
    out_t=data_t,
    rounding="round_half_even",
    overflow="saturate",
)


@MAIN(100.0)
def fir_sweep_main(
    stream_in_if: fir_sweep.in_fwd_t, stream_out_if: fir_sweep.out_fb_t
) -> fir_sweep_t:
    return fir_sweep(stream_in_if, stream_out_if)
