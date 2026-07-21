# pyright: reportInvalidTypeForm=none
"""5x decimating FIR example + testbench with matplotlib plots.

Uses the exact 49-tap Q1.15 coefficient set of the SDR FM radio's `decim_5x`
front-end filter (examples/sdr/fm_radio.h) -- passed as pre-quantized raw
integers -- decimating by 5 with the same truncating output scaling as the
old macro library. Only every 5th sample launches a computation into the
autopipelined blob; the output stream runs at 1/5 the input rate, and
backpressure freezes the sample window exactly.

Run the simulation (writes fir_decim5_tb.png; PYPELINE_TB_SHOW=1 for a window):

    pypelinec examples/pypeline/dsp/fir_decim_tb.py --sim --comb --run 1800
"""

import sys, os

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)

from pypeline import MAIN

from fixed_point import make_fixed_t
from dsp.fir_decim import make_fir_decim
from dsp.fir_tb import make_fir_tb, quantize_samples, two_tone

# 49-tap lowpass, Q1.15, symmetric -- identical values to fm_radio.h's
# decim_5x FIR_DECIM_COEFFS (the old preprocessor-macro library this
# pypeline library replaces).
# fmt: off
DECIM_5X_COEFFS_Q15 = [
    -165, -284, -219, -303, -190, -102, 98, 268, 430, 482, 420, 207,
    -117, -498, -835, -1022, -957, -576, 135, 1122, 2272, 3429, 4419,
    5086, 5321, 5086, 4419, 3429, 2272, 1122, 135, -576, -957, -1022,
    -835, -498, -117, 207, 420, 482, 430, 268, 98, -102, -190, -303,
    -219, -284, -165,
]
# fmt: on

data_t = make_fixed_t(1, 15)  # int16 Q1.15, same as the SDR datapath
coeff_t = make_fixed_t(1, 15)

# rounding="truncate", overflow="wrap" reproduce the old library's plain
# `accum >> FIR_DECIM_POW2_DN_SCALE` output stage bit-for-bit.
fir_decim5, fir_decim5_t = make_fir_decim(
    DECIM_5X_COEFFS_Q15,
    coeff_t,
    5,
    data_t,
    out_t=data_t,
    rounding="truncate",
    overflow="wrap",
)

# Two tones: 0.02 f/fs survives 5x decimation; 0.30 f/fs sits in the filter's
# stopband (above the post-decimation Nyquist of 0.1 f/fs) and is removed.
stim = quantize_samples(two_tone(300, cycles_a=6, cycles_b=90, amplitude=0.35), data_t)
tb = make_fir_tb(fir_decim5, stim, name="fir_decim5", plot=True)


@MAIN
def fir_decim5_tb():
    stream_in = tb.drive_in()
    out_ready = tb.drive_ready()
    o = fir_decim5(stream_in, out_ready)
    tb.observe(o)
