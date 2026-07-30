# pyright: reportInvalidTypeForm=none
"""Streaming lowpass FIR example + testbench with matplotlib plots.

A 31-tap windowed-sinc lowpass (designed in plain Python at elaboration time)
filters a two-tone signal: the in-band tone passes, the stopband tone is
removed. The filter is one autopipelined combinational blob wrapped in a
valid/ready stream -- pipeline depth is chosen by the tool for the target
FPGA/fmax, never hard-coded (see docs/pypeline_guide.md "DSP: FIR filters").

Run the simulation (writes fir_lowpass_tb.png in the current directory;
set PYPELINE_TB_SHOW=1 to also open a window):

    pypelinec examples/pypeline/dsp/fir_lowpass_tb.py --sim --comb --run 2400

The @sim_input/@sim_output testbench pieces are native-sim-only; the filter
itself is real synthesizable hardware.
"""

import math
from pypeline import MAIN

from fixed_point import make_fixed_t
from dsp.fir import make_fir
from dsp.fir_tb import make_fir_tb, quantize_samples, two_tone


# ── Filter design (plain Python, runs at elaboration time) ─
def windowed_sinc_lowpass(n_taps, cutoff):
    """Hamming-windowed sinc, DC gain normalized to 1. cutoff in f/fs."""
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


TAPS = windowed_sinc_lowpass(31, cutoff=0.125)

data_t = make_fixed_t(1, 15)  # Q1.15 samples
coeff_t = make_fixed_t(1, 15)  # Q1.15 coefficients

# Symmetric taps fold automatically (16 multipliers, not 31); output is
# rounded convergently and saturated back to Q1.15 like the vendor cores.
fir, fir_t = make_fir(
    TAPS,
    coeff_t,
    data_t,
    out_t=data_t,
    rounding="round_half_even",
    overflow="saturate",
)

# ── Stimulus + testbench ─
# 8 cycles/256 samples = 0.031 f/fs (passband) + 96/256 = 0.375 f/fs (stopband)
stim = quantize_samples(two_tone(256, cycles_a=8, cycles_b=96, amplitude=0.4), data_t)
tb = make_fir_tb(fir, stim, name="fir_lowpass", plot=True)


@MAIN
def fir_lowpass_tb():
    stream_in = tb.drive_in()
    out_ready = tb.drive_ready()
    o = fir(stream_in, out_ready)
    tb.observe(o)
