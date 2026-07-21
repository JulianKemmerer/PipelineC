# pyright: reportInvalidTypeForm=none
"""4x interpolating FIR example + testbench with matplotlib plots.

A zero-stuffer expands each input sample into 4 output beats (the sample then
3 zeros, fully backpressured), and a 27-tap windowed-sinc lowpass smooths the
result into a clean 4x-oversampled waveform. The default gain=interp
compensates the zero-stuffing energy loss at zero hardware cost (it is folded
into the coefficient constants at elaboration time).

Output rate = 4x input rate: with the consumer taking one beat per cycle, the
filter's ready naturally throttles the input to one sample per 4 cycles.

Run the simulation (writes fir_interp4_tb.png; PYPELINE_TB_SHOW=1 for a window):

    pypelinec examples/pypeline/dsp/fir_interp_tb.py --sim --comb --run 1600
"""

import math
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
from dsp.fir_interp import make_fir_interp
from dsp.fir_tb import make_fir_tb, quantize_samples, sine


def windowed_sinc_lowpass(n_taps, cutoff):
    """Hamming-windowed sinc, DC gain 1. cutoff in f/fs (output rate)."""
    m = n_taps - 1
    taps = []
    for i in range(n_taps):
        x = i - m / 2.0
        h = (
            2.0
            * cutoff
            * (
                1.0
                if x == 0
                else math.sin(2.0 * math.pi * cutoff * x) / (2.0 * math.pi * cutoff * x)
            )
        )
        w = 0.54 - 0.46 * math.cos(2.0 * math.pi * i / m)
        taps.append(h * w)
    scale = sum(taps)
    return [t / scale for t in taps]


INTERP = 4
# Anti-imaging lowpass at the OUTPUT rate: cutoff = (fs_in/2) / fs_out = 1/(2*4)
TAPS = windowed_sinc_lowpass(27, cutoff=1.0 / (2 * INTERP))

data_t = make_fixed_t(1, 15)  # Q1.15
# gain=interp=4 is folded into the taps before quantization, so give the
# coefficient format the integer headroom for 4 * max|tap| (~1.0).
coeff_t = make_fixed_t(2, 14)

fir_interp4, fir_interp4_t = make_fir_interp(
    TAPS,
    coeff_t,
    INTERP,
    data_t,
    out_t=data_t,
    rounding="round_half_even",
    overflow="saturate",
)

# A low-rate sine: 64 input samples -> 256 smooth output samples.
stim = quantize_samples(sine(64, cycles=3, amplitude=0.7), data_t)
tb = make_fir_tb(fir_interp4, stim, name="fir_interp4", plot=True)


@MAIN
def fir_interp4_tb():
    stream_in = tb.drive_in()
    out_ready = tb.drive_ready()
    o = fir_interp4(stream_in, out_ready)
    tb.observe(o)
