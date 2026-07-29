# pyright: reportInvalidTypeForm=none
"""Standalone synthesis check for pulse_gen (see pulse_gen.py).

pulse_gen itself has no top-level ports -- it's a plain submodule meant to
be called from inside a larger design. This file exists purely to prove it
closes timing on its own, on real hardware ports, at the README's 125 MHz
system clock. It is not used by the native-sim testbench (pulse_gen_tb.py).

Synthesize (requires Vivado):
    pypelinec examples/pypeline/dsp/pdw/pulse_gen/pulse_gen_synth_top.py
"""

from pypeline import MAIN, PART, Input, int16_t, uint32_t

from pulse_gen import make_pulse_gen

PART("xc7a100tcsg324-1")  # Artix-7 100T, same part as board/arty/part100t.py

pulse_gen, out_stream_t = make_pulse_gen()

pri: Input[uint32_t]
width: Input[uint32_t]
amplitude: Input[int16_t]


@MAIN(125.0)
def pulse_gen_top() -> out_stream_t:
    return pulse_gen(pri, width, amplitude)
