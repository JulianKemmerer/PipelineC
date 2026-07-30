# pyright: reportInvalidTypeForm=none
"""Top-level synthesis entry point for the AIR7310 PDW project (see README.md).

Only the Pulse Generator (step 1, pulse_gen/pulse_gen.py) is implemented so
far -- the rest of the pipeline (Time-Aligned Detect & Delay Module,
Qualified Storage & PDW Engine) isn't built yet. This wires pulse_gen up
to real top-level ports:

  * flat Input[T] control registers for pri/width/amplitude (as if from
    host config regs -- see README.md section 2), matching how pulse_gen
    is meant to be driven once the rest of the design exists;
  * a flattened AXI-Stream-style master output (tx0_m_axis_tdata/
    tx0_m_axis_tvalid) -- plain uintN_t at the port boundary, not the
    iq_t/stream(iq_t) structs used internally, per the project's
    convention that AXI-Stream is only the top-level interface shape (see
    README.md section 1: "Raw I/Q format"). iq_t's i/q fields are packed
    into tdata per the project-wide convention I = tdata[15:0],
    Q = tdata[31:16]. Named `tx0_` since this drives the first TX port
    (TX1 in the README's diagram, i.e. TX RF Out index 0).

As more of the PDW pipeline gets built, this file is where subsequent
stages get wired in and where TX2/RX1/host-DMA ports will eventually live.
"""

import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulse_gen"),
)

from pypeline import MAIN, PART, Input, Output, concat, int16_t, uint1_t, uint16_t, uint32_t

from pulse_gen import make_pulse_gen

PART("xc7a100tcsg324-1")  # Artix-7 100T, same part as board/arty/part100t.py

pulse_gen, out_stream_t = make_pulse_gen()

# Pulse generator control registers (as if from host config regs).
pulse_gen_pri: Input[uint32_t]
pulse_gen_width: Input[uint32_t]
pulse_gen_amplitude: Input[int16_t]

# Flattened AXI-Stream master output, TX1/TX0 (first TX port).
tx0_m_axis_tdata: Output[uint32_t]
tx0_m_axis_tvalid: Output[uint1_t]


@MAIN(125.0)
def pdw_top():
    o = pulse_gen(pulse_gen_pri, pulse_gen_width, pulse_gen_amplitude)
    # concat() requires unsigned args -- full-width bit-slice reinterprets
    # each int16_t field's raw bits as uint16_t. concat()'s first arg is
    # MSBs, so Q (tdata[31:16]) goes first, I (tdata[15:0]) second, per
    # the project-wide I/Q packing convention.
    i_bits: uint16_t = o.data.i[15:0]
    q_bits: uint16_t = o.data.q[15:0]
    tx0_m_axis_tdata = concat(q_bits, i_bits)
    tx0_m_axis_tvalid = o.valid
