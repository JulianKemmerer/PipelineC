# pyright: reportInvalidTypeForm=none
"""dsp/fir_tb.py testbench-library end-to-end test: two filters (elastic with
random consumer backpressure + valid_only) each driven cycle-by-cycle through
@sim_input and checked against the exact golden model by a @sim_output.

@sim_input/@sim_output only exist in the native simulator, so run this via
the multi-MAIN runner (never plain python3, never --comb):

    python3 src/pypeline_sim.py fir_sim_tb_test.py --run 1400

The run count must exceed both tbs' deadlines (see tb.min_cycles; the
@sim_output checker asserts if a tb hasn't finished by its deadline, and
asserts on any output mismatch)."""

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
import random

from pypeline import MAIN

from fixed_point import make_fixed_t
from dsp.fir import make_fir
from dsp.fir_tb import make_fir_tb, quantize_samples, sine, white_noise

data_t = make_fixed_t(1, 7)
coeff_t = make_fixed_t(2, 6)

fir_e, fir_e_t = make_fir(
    [0.25, 0.5, 0.5, 0.25],
    coeff_t,
    data_t,
    out_t=data_t,
    rounding="round_half_even",
    overflow="saturate",
)
stim_e = quantize_samples(sine(80, 4), data_t)
tb_e = make_fir_tb(fir_e, stim_e, ready_pattern="random", name="fir_elastic")

fir_v, fir_v_t = make_fir(
    [-0.03125, 0.0, 0.28125, 0.5, 0.28125, 0.0, -0.03125],
    coeff_t,
    data_t,
    out_t=data_t,
    rounding="round_half_up",
    overflow="saturate",
    handshake="valid_only",
)
stim_v = quantize_samples(white_noise(80, random.Random(42)), data_t)
tb_v = make_fir_tb(fir_v, stim_v, name="fir_valid_only")


@MAIN
def fir_elastic_tb():
    stream_in = tb_e.drive_in()
    out_ready = tb_e.drive_ready()
    o = fir_e(stream_in, out_ready)
    tb_e.observe(o)


@MAIN
def fir_valid_only_tb():
    stream_in = tb_v.drive_in()
    out_stream = fir_v(stream_in)
    tb_v.observe(out_stream)
