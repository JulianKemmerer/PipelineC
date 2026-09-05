# pyright: reportInvalidTypeForm=none
"""Standalone synthesis check for pdw_engine (see pdw_engine.py).

pdw_engine has no top-level ports of its own -- it's a plain submodule called
from top.py. This file exists purely to prove it builds and closes timing in
isolation, on real hardware ports, at the README's 125 MHz system clock. It is
not used by either testbench (pdw_engine_tb.py, ../pdw_tb.py). Same convention
and purpose as pulse_detect/pulse_detect_synth_top.py.

The two FIFO depths are the README's real ones (16,384-beat data FIFO), not
the small ones pdw_engine_tb.py uses -- the point of this file is to check
what actually gets built, including that the data FIFO infers block RAM rather
than a wall of flops.

Synthesize (requires Vivado):
    pypelinec examples/pypeline/dsp/pdw/pdw_engine/pdw_engine_synth_top.py
"""

import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pulse_detect"),
)

from pypeline import MAIN, PART, Input, uint1_t, uint32_t

from pulse_detect import make_detect_pulses
from pdw_engine import make_pdw_engine

PART("xc7a100tcsg324-1")  # Artix-7 100T, same part as board/arty/part100t.py

# Built against a detect_pulses instance for its types only (complex_t /
# gated_sample_t / candidate_pdw_t / width_t); no detector logic is
# synthesized here -- detect_pulses is never called.
detect_pulses, _detect_pulses_t = make_detect_pulses()
pdw_engine, pdw_engine_t = make_pdw_engine(detect_pulses)

# Runtime-configurable knobs (README section 2's host regs, as if from config
# regs -- same convention as pulse_detect_synth_top.py).
min_width: Input[uint32_t]
max_width: Input[uint32_t]

# Consumer backpressure, real ports so the release path's timing is real.
pkt_out_ready: Input[uint1_t]
pdw_out_ready: Input[uint1_t]

dsp_overflow: Input[uint1_t]


@MAIN(125.0)
def pdw_engine_top(
    gated_in: detect_pulses.gated_sample_t, pdw_in_if: detect_pulses.out_fwd_t
) -> pdw_engine_t:
    return pdw_engine(
        gated_in,
        pdw_in_if,
        dsp_overflow,
        min_width,
        max_width,
        pkt_out_ready,
        pdw_out_ready,
    )
