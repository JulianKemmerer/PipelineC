# pyright: reportInvalidTypeForm=none
"""Self-checking make_stream_pipeline design for PIPELINED native sim.

Registered in synth_tests.py as `pipelinec <this file> --sim --run all`
(no --comb): the full build runs first (throughput sweep + AUTOPIPELINE
.latency pin-and-confirm — make_stream_pipeline reads .latency to size its
FIFO), then the native simulator runs with the discovered latencies emulated
(AUTOPIPELINE call-site delay lines). The checks are latency-insensitive
elastic-handshake checks, so the same design also passes at zero latency
(plain native sim / --comb) — what the non---comb run proves is that the
whole flow (build -> harvested latencies -> native sim with delay emulation
and a .latency-sized FIFO) runs end to end and still self-checks clean.

Pass/fail = clean sim_finish() vs sim_assert abort vs never finishing.
"""

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

from pypeline import (
    MAIN,
    Reg,
    hw_func,
    sim_assert,
    sim_finish,
    uint1_t,
    uint8_t,
    uint16_t,
)

from interface.interface import make_interface_feedback_type, make_interface_type
from stream.stream import make_stream_interface
from stream.stream_pipeline import make_stream_pipeline


@hw_func
def div_inv(x: uint8_t) -> uint8_t:
    return x / ~x


uint8_stream_intrf = make_stream_interface(uint8_t)
uint8_stream_t = make_interface_type(uint8_stream_intrf)
uint8_stream_fb_t = make_interface_feedback_type(uint8_stream_intrf)
stream_pipeline, stream_pipeline_t = make_stream_pipeline(div_inv)


# Repeating 4-value input pattern (avoid x=255: ~x wraps to 0, division by
# zero) with distinct nonzero expected outputs, precomputed by a plain-Python
# model of div_inv and baked in as constants (checked via a constant mux, so
# the stateful checker MAIN never needs its own heavy comb logic).
def _model_div_inv(x):
    return (x // ((~x) & 0xFF)) & 0xFF


IN0, IN1, IN2, IN3 = 200, 170, 240, 128
EXP0, EXP1, EXP2, EXP3 = (
    _model_div_inv(IN0),
    _model_div_inv(IN1),
    _model_div_inv(IN2),
    _model_div_inv(IN3),
)

NUM_OUTPUTS = 12  # the 4-value pattern, three times over
MAX_CYCLES = 200  # generous flush bound; a stuck pipeline fails loudly


# Returns the stream output as a real top-level port: without any output,
# the sweep's per-iteration top synthesis (yosys/PYRTL timing check) prunes
# the entire design as unobserved and the timing analysis fails.
@MAIN(50.0)
def self_check_stream_pipeline() -> stream_pipeline_t:
    cycle: Reg[uint16_t]
    in_count: Reg[uint16_t]
    out_count: Reg[uint16_t]

    # Present the next input value (constant mux over the repeating pattern),
    # held until accepted per stream_in.ready.
    x: uint8_t = IN0
    in_sel: uint8_t = in_count & 3
    if in_sel == 1:
        x = IN1
    elif in_sel == 2:
        x = IN2
    elif in_sel == 3:
        x = IN3

    stream_in: uint8_stream_t
    stream_in.valid = in_count < NUM_OUTPUTS
    stream_in.data = x
    ready1: uint8_stream_fb_t
    ready1.ready = 1
    o: stream_pipeline_t = stream_pipeline(stream_in, ready1)

    if stream_in.valid & o.stream_in.ready:
        in_count += 1

    if o.stream_out.valid:
        expected: uint8_t = EXP0
        out_sel: uint8_t = out_count & 3
        if out_sel == 1:
            expected = EXP1
        elif out_sel == 2:
            expected = EXP2
        elif out_sel == 3:
            expected = EXP3
        sim_assert(
            o.stream_out.data == expected,
            f"output {out_count}: expected {expected} got {o.stream_out.data}",
        )
        sim_assert(out_count < NUM_OUTPUTS, f"too many outputs: {out_count}")
        if out_count == NUM_OUTPUTS - 1:
            sim_finish()
        out_count += 1

    sim_assert(
        cycle < MAX_CYCLES,
        f"pipeline did not flush within {MAX_CYCLES} cycles: "
        f"in={in_count} out={out_count}",
    )
    cycle += 1
    return o
