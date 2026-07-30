# pyright: reportInvalidTypeForm=none
"""Moving-average (boxcar) smoother example + testbench.

A step buried in white noise: the output noise spread should be materially
smaller than the input's -- the "Moving Average Smoothing" stage of
examples/pypeline/dsp/pdw/README.md, Path A: Detect & Measure.

Two @MAIN entry points exercise both handshake modes in one run: an elastic
instance under random consumer backpressure, and a valid_only (free-running)
instance.

Run the simulation:
    pypelinec examples/pypeline/dsp/moving_avg_tb.py --sim --comb --run 3000
"""

import random
from pypeline import MAIN

from fixed_point import make_fixed_t
from dsp.moving_avg import make_moving_avg
from dsp.dsp_tb import golden_moving_avg, make_block_tb, quantize_samples, step, white_noise

data_t = make_fixed_t(1, 15)  # Q1.15
N_WINDOW = 16  # power of two -> normalize=True's divide is free

N = 800
STEP_START = 300
STEP_LEVEL = 0.4
NOISE_AMPLITUDE = 0.35

STIM = quantize_samples(
    [
        (STEP_LEVEL if i >= STEP_START else 0.0) + n
        for i, n in enumerate(white_noise(N, random.Random(909), NOISE_AMPLITUDE))
    ],
    data_t,
)


def _check_noise_reduced(state):
    scale = 1 << data_t.frac_bits
    in_region = STIM[STEP_START + 64 : STEP_START + 264]
    out_region = state["out_hist"][STEP_START + 64 : STEP_START + 264]
    in_mean = sum(in_region) / len(in_region)
    out_mean = sum(out_region) / len(out_region)
    in_var = sum((v - in_mean) ** 2 for v in in_region) / len(in_region)
    out_var = sum((v - out_mean) ** 2 for v in out_region) / len(out_region)
    assert out_var < in_var / 4, (
        f"moving average did not smooth noise: input var {in_var}, output var {out_var}"
    )
    print(
        f"moving_avg: input std {in_var ** 0.5 / scale:.4f}, "
        f"output std {out_var ** 0.5 / scale:.4f}"
    )


ma_e, ma_e_t = make_moving_avg(data_t, N_WINDOW, out_t=data_t, overflow="saturate")
expected_e = golden_moving_avg(ma_e, STIM)
tb_e = make_block_tb(
    ma_e,
    STIM,
    expected_e,
    name="moving_avg_elastic",
    ready_pattern="random",
    on_done=_check_noise_reduced,
)


@MAIN(125.0)
def moving_avg_elastic_tb():
    stream_in = tb_e.drive_in()
    out_ready = tb_e.drive_ready()
    o = ma_e(stream_in, out_ready)
    tb_e.observe(o)


ma_v, ma_v_t = make_moving_avg(
    data_t, N_WINDOW, out_t=data_t, overflow="saturate", handshake="valid_only"
)
expected_v = golden_moving_avg(ma_v, STIM)
tb_v = make_block_tb(ma_v, STIM, expected_v, name="moving_avg_valid_only")


@MAIN(125.0)
def moving_avg_valid_only_tb():
    stream_in = tb_v.drive_in()
    o = ma_v(stream_in)
    tb_v.observe(o)
