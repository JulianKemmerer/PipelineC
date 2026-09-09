# pyright: reportInvalidTypeForm=none
"""Standalone synthesis check for pulse_detect (see pulse_detect.py).

pulse_detect itself has no top-level ports -- it's a plain submodule meant
to be called from inside a larger design. This file exists purely to prove
it closes timing on its own, on real hardware ports, at the README's
125 MHz system clock. It is not used by the native-sim testbench
(pulse_detect_tb.py).

Elastic handshake only: valid_only shares the same FSM core (see
pulse_detect.py), and elastic is the heavier of the two paths (adds the
1-deep output-slot backpressure logic on the input side), so it's the more
representative timing-closure check.

Synthesize (requires Vivado):
    pypelinec examples/pypeline/dsp/pdw/pulse_detect_synth_top.py
"""

import pdw_paths  # noqa: F401  (puts include/pypeline on sys.path)

from pypeline import MAIN, PART, Input, uint1_t, uint32_t

from pulse_detect import make_pulse_detect_fsm

from fixed_point import make_fixed_t

PART("xc7a100tcsg324-1")  # Artix-7 100T, same part as board/arty/part100t.py

power_t = make_fixed_t(32, 0, signed=False)  # README's uint32_t power format

pulse_detect_fsm, pulse_detect_fsm_t = make_pulse_detect_fsm(power_t)

# Runtime-configurable knobs (the README's control registers, as if from config
# regs -- see pulse_gen_synth_top.py for the same convention).
threshold_high: Input[uint32_t]
threshold_low: Input[uint32_t]
max_width: Input[uint32_t]
# A real port rather than a tied 0: the reset fans out to the whole state
# machine, so its routing is part of what this check should be measuring.
rst: Input[uint1_t]


@MAIN(125.0)
def pulse_detect_fsm_top(
    stream_in_if: pulse_detect_fsm.in_fwd_t, pdw_out_if: pulse_detect_fsm.out_fb_t
) -> pulse_detect_fsm_t:
    return pulse_detect_fsm(
        stream_in_if,
        pdw_out_if,
        power_t(val=threshold_high),
        power_t(val=threshold_low),
        max_width,
        rst,
    )
