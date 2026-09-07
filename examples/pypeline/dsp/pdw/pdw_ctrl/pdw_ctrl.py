# pyright: reportInvalidTypeForm=none
"""Control register file for the AIR7310 PDW pipeline (see ../README.md).

Every runtime knob of this design -- the pulse generator's PRI/width/carrier,
the detector's thresholds, the engine's glitch/CW limits, the loopback select
-- lives in one `pdw_ctrl_t` struct, written by a host over a 32-bit AXI-Stream
slave port. The block holds a local copy with power-on defaults and replaces it
wholesale whenever a well-formed frame arrives.

WHY A STRUCT AND NOT WIRES. The previous version exposed eleven flat `Input[T]`
ports. That is fine in simulation and unbuildable in a real system: nothing on
an AXI-Stream fabric can drive eleven parallel register wires. One framed struct
is one DMA descriptor.

FRAMING POLICY -- exactly sized, no runts, no padding. `make_axis_to_type` is
instantiated with `frame="one_per_packet"` and `on_runt="discard"`, which is
precisely the requested behaviour and needs no code here:

  * a frame LONGER than `byte_length(pdw_ctrl_t)` has its excess dropped by the
    built-in `make_axis_max_len_limiter` -- so Ethernet-style minimum-frame
    padding cannot be decoded as struct content, and cannot desync the frames
    that follow it;
  * a frame SHORTER than that is discarded and the deserializer resyncs, so a
    truncated write leaves the registers untouched rather than half-applied.

TIMING. The register file is the consumer, and a register file is never busy:
`stream_out_if.ready` is tied high, so `tx0_s_axis_tready` is always 1 and a
host is never back-pressured. Two register stages then separate the frame from
the registers -- the deserializer presents its assembled value one cycle after
the final byte is shifted in ("bubble-free" is about throughput, not latency),
and this block latches that value on the next edge:

    pdw_ctrl.latency == 2   -- new values are readable two cycles after the
                              frame's last beat is accepted.

That number is MEASURED, not assumed: `pdw_ctrl_test.py` derives it from a real
run and asserts this attribute matches, so a change in the deserializer cannot
silently shift it. `../pdw_tb.py` reads the attribute rather than hardcoding a
number -- see this project's `.latency` discipline generally.
"""

import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "..", "..", "include", "pypeline",
    ),
)

from pypeline import (
    NamedTuple,
    Reg,
    byte_length,
    hw_func,
    int16_t,
    int32_t,
    struct,
    uint1_t,
    uint16_t,
    uint32_t,
)

from axi.type_axis import make_axis_to_type

# `flags` bit assignments. Same style as pdw_engine.py's STATUS_* constants:
# named module constants, so a testbench and a host program refer to the bit by
# name rather than repeating a shift.
CTRL_FLAG_LOOPBACK_EN = 1 << 0  # 1 = feed the detector from pulse_gen, not RX0


@struct
class pdw_ctrl_t(NamedTuple):
    """40 bytes / 320 bits -- ten 32-bit AXIS beats, deliberately the same size
    as `valid_pdw_t` so both directions are one clean DMA burst.

    Field widths are chosen to total exactly 40 bytes with no padding field;
    adding a knob means taking the space from `flags` or growing the struct by a
    whole beat. `byte_length()` is asserted below so that can never drift
    silently."""

    # -- pulse generator (see pulse_gen/pulse_gen.py) --
    pulse_gen_pri: uint32_t  # 32   PRI in samples
    pulse_gen_width: uint32_t  # 32   pulse width in samples
    pulse_gen_freq: int32_t  # 32   phase increment/sample, turns x 2^32
    pulse_gen_chirp_rate: int32_t  # 32   added to that increment each pulse sample
    pulse_gen_amplitude: int16_t  # 16   peak I/Q amplitude
    pulse_gen_noise_amp: uint16_t  # 16   LFSR noise scale, 0 = off
    # -- detector Path A (see pulse_detect/pulse_detect.py) --
    threshold_high: uint32_t  # 32   hysteresis SM upper threshold
    threshold_low: uint32_t  # 32   hysteresis SM lower threshold
    # -- qualification (see pdw_engine/pdw_engine.py) --
    max_width: uint32_t  # 32   Path A force-close cap AND CW rejection
    min_width: uint32_t  # 32   glitch rejection
    # -- misc --
    flags: uint32_t  # 32   CTRL_FLAG_* above


CTRL_N_BYTES = byte_length(pdw_ctrl_t)
assert CTRL_N_BYTES == 40, (
    f"pdw_ctrl_t must stay 40 bytes / ten 32-bit beats, got {CTRL_N_BYTES}"
)


# Power-on defaults. Chosen so an unconfigured device is QUIET and in a KNOWN
# state rather than merely zeroed:
#
#   * pri=1, width=0, amplitude=0, noise_amp=0 -- the generator emits pure
#     zeros. pri=1 additionally pins its PRI counter at 0 on every cycle
#     (`pri_counter == pri - 1` is true immediately), so the instant a real PRI
#     is written the generator starts from a defined phase instead of from
#     wherever a free-running counter happened to be. That property is what lets
#     ../pdw_tb.py's pre-roll window be modelled exactly.
#   * thresholds at their maximum -- the hysteresis SM cannot leave IDLE, so an
#     unconfigured device never emits a PDW rather than emitting garbage ones.
#     (Zero thresholds would declare one continuous pulse forever.)
#   * loopback off -- the real RX0 input is the default source.
CTRL_DEFAULTS = pdw_ctrl_t(
    pulse_gen_pri=1,
    pulse_gen_width=0,
    pulse_gen_freq=0,
    pulse_gen_chirp_rate=0,
    pulse_gen_amplitude=0,
    pulse_gen_noise_amp=0,
    threshold_high=0xFFFFFFFF,
    threshold_low=0xFFFFFFFF,
    max_width=0xFFFFFFFF,
    min_width=0,
    flags=0,
)


def make_pdw_ctrl(n=4, registered_ready=False):
    """Build the control register file. Returns (pdw_ctrl, pdw_ctrl_out_t).

        pdw_ctrl(axis_in_if: pdw_ctrl.axis_intrf.fwd_t) -> pdw_ctrl_out_t

    Result fields:
        .regs        (pdw_ctrl_t) the live register values
        .axis_in_if  (axis_intrf.fb_t) reverse half of the AXIS slave port
        .updated     (uint1_t) pulses the cycle a frame's last beat is accepted
        .runt        (uint1_t) pulses when a short frame was discarded

    `registered_ready` is passed through to the deserializer. It is False here
    -- the point of this block is that control never stalls -- but it is the
    documented escape hatch if the combinational ready path ever becomes a
    timing problem, at the cost of one bubble cycle per value. It does NOT
    change `.latency` (measured identical both ways in pdw_ctrl_test.py), and
    nothing downstream hardcodes that number anyway.
    """
    rx, _rx_t = make_axis_to_type(
        pdw_ctrl_t,
        n,
        frame="one_per_packet",
        on_runt="discard",
        registered_ready=registered_ready,
    )

    @struct
    class pdw_ctrl_out_t(NamedTuple):
        axis_in_if: rx.axis_intrf.fb_t
        regs: pdw_ctrl_t
        updated: uint1_t
        runt: uint1_t

    @hw_func
    def pdw_ctrl(axis_in_if: rx.axis_intrf.fwd_t) -> pdw_ctrl_out_t:
        o: pdw_ctrl_out_t
        regs: Reg[pdw_ctrl_t] = CTRL_DEFAULTS

        # Ready tied high: a register file is never busy, and this is what makes
        # the apply moment a pure function of when the last beat lands.
        r = rx(axis_in_if, rx.out_fb_t(1))

        # Present the CURRENT register contents, THEN latch the new ones. That
        # ordering is the second of the two cycles in `.latency`: consumers see
        # the old configuration until the edge on which the decoded struct is
        # latched. Reversing these two would make the update combinational and
        # put the deserializer's 40-byte output straight into the detector's
        # threshold comparators.
        o.regs = regs
        o.axis_in_if = r.axis_in_if
        o.updated = r.stream_out_if.stream.valid
        o.runt = r.runt

        if r.stream_out_if.stream.valid:
            regs = r.stream_out_if.stream.data.frag
        return o

    pdw_ctrl.ctrl_t = pdw_ctrl_t
    pdw_ctrl.defaults = CTRL_DEFAULTS
    pdw_ctrl.axis_intrf = rx.axis_intrf
    pdw_ctrl.n = n
    pdw_ctrl.n_bytes = CTRL_N_BYTES
    pdw_ctrl.n_beats = (CTRL_N_BYTES + n - 1) // n
    # Cycles from "frame's last beat accepted" to "new values readable": one for
    # the deserializer's output register, one for `regs` itself. Pinned by
    # pdw_ctrl_test.py against a real run, for both registered_ready settings.
    pdw_ctrl.latency = 2
    return pdw_ctrl, pdw_ctrl_out_t
