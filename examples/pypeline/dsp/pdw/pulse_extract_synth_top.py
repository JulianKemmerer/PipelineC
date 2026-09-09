# pyright: reportInvalidTypeForm=none
"""Standalone synthesis check for pulse_extract (see pulse_extract.py).

pulse_extract has no top-level ports of its own -- it's a plain submodule called
from top.py. This file exists purely to prove it builds and closes timing in
isolation, on real hardware ports, at the README's 125 MHz system clock. It is
not used by either testbench (pulse_extract_tb.py, ../pdw_tb.py). Same convention
and purpose as pulse_detect_synth_top.py.

The two FIFO depths are the README's real ones (16,384-beat data FIFO), not
the small ones pulse_extract_tb.py uses -- the point of this file is to check
what actually gets built, including that the data FIFO infers block RAM rather
than a wall of flops.

This is also the only place the per-pulse measurement engine
(pulse_measure.py) gets a real timing check: its 14-iteration
CORDIC and its two logarithm converters are instantiated inside pulse_extract.

Synthesize (requires Vivado):
    pypelinec examples/pypeline/dsp/pdw/pulse_extract_synth_top.py
"""

import pdw_paths  # noqa: F401  (puts include/pypeline on sys.path)

from pypeline import MAIN, PART, Input, uint1_t, uint32_t

from pulse_detect import make_pulse_detect
from pulse_extract import make_pulse_extract

PART("xc7a100tcsg324-1")  # Artix-7 100T, same part as board/arty/part100t.py

# Built against a pulse_detect instance for its types only (complex_t /
# gated_sample_t / candidate_pdw_t / width_t); no detector logic is
# synthesized here -- pulse_detect is never called.
pulse_detect, _pulse_detect_t = make_pulse_detect()
pulse_extract, pulse_extract_t = make_pulse_extract(pulse_detect)

# Runtime-configurable knobs (the README's control registers, as if from config
# regs -- same convention as pulse_detect_synth_top.py).
min_width: Input[uint32_t]
max_width: Input[uint32_t]

dsp_overflow: Input[uint1_t]

# A real port rather than a tied 0. Reset drives the three FIFO read enables as
# well as the store FSM's clears, so it sits directly in the release path this
# file exists to measure.
rst: Input[uint1_t]


@MAIN(125.0)
def pulse_extract_top(
    gated_in: pulse_detect.gated_sample_t,
    pdw_in_if: pulse_detect.out_fwd_t,
    freq_acc: pulse_detect.freq_accum_t,
    noise_est: pulse_detect.noise_t,
    # Consumer backpressure. Both release ports are stream interfaces, so the
    # reverse half of each is a real port here -- paired by name with the
    # feedforward half `pulse_extract_t` returns, which is what keeps the
    # release path's timing real rather than tied off.
    pkt_out_if: pulse_extract.pkt_out_intrf.fb_t,
    pdw_out_if: pulse_extract.pdw_out_intrf.fb_t,
) -> pulse_extract_t:
    return pulse_extract(
        gated_in=gated_in,
        pdw_in_if=pdw_in_if,
        dsp_overflow=dsp_overflow,
        min_width=min_width,
        max_width=max_width,
        freq_acc=freq_acc,
        noise_est=noise_est,
        pkt_out_if=pkt_out_if,
        pdw_out_if=pdw_out_if,
        rst=rst,
    )
