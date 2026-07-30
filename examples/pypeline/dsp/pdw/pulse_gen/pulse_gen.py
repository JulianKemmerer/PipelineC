# pyright: reportInvalidTypeForm=none
"""Pulse Generator for the AIR7310 PDW pipeline (see ../README.md, step 1).

Free-running PRI/width counter gating a constant-amplitude baseband I/Q
pulse onto an always-valid stream(iq_t). No carrier/DDS tone in this first
version -- a flat amplitude step is enough for the downstream detector's
I^2+Q^2 magnitude math to see a clean high/low power edge.

`pulse_gen` is a plain reusable @hw_func submodule -- no Input[T]/Output[T]
ports of its own. `pri`/`width`/`amplitude` are ordinary function args
(conceptually "as if from ctrl regs", but mechanically just args); a
top-level @MAIN (a testbench, or eventually a real synthesis top) is
responsible for supplying them, the same way fir_decim is called from
fm_radio_decim.py.
"""

from pypeline import NamedTuple, Reg, hw_func, int16_t, struct, uint1_t, uint32_t

from stream.stream import make_stream_t


@struct
class iq_t(NamedTuple):
    i: int16_t
    q: int16_t


def make_pulse_gen(pri_t=uint32_t, width_t=uint32_t, amplitude_t=int16_t):
    """Build a pulse generator. Returns (pulse_gen, out_stream_t)."""

    out_stream_t = make_stream_t(iq_t)

    @hw_func
    def pulse_gen(pri: pri_t, width: width_t, amplitude: amplitude_t) -> out_stream_t:
        pri_counter: Reg[pri_t] = 0
        pulse_active: uint1_t = pri_counter < width

        if pri_counter == (pri - 1):
            pri_counter = 0
        else:
            pri_counter = pri_counter + 1

        zero_i: amplitude_t = 0
        i: amplitude_t = amplitude if pulse_active else zero_i
        sample: iq_t = iq_t(i, 0)
        return out_stream_t(sample, 1)  # always valid: fixed-rate DAC stream

    pulse_gen.iq_t = iq_t
    pulse_gen.out_stream_t = out_stream_t
    return pulse_gen, out_stream_t
