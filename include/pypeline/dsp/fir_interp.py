# pyright: reportInvalidTypeForm=none
"""Integer-factor interpolating FIR filter factory (zero-stuffing
architecture, port of include/dsp/fir_interp.h with real backpressure).

A small zero-stuffer FSM expands each accepted input sample into `interp`
output beats (the sample, then interp-1 zeros), each beat gated by downstream
ready -- unlike the old header's open-loop period counters, pacing is exact
and composable. The stuffed stream feeds a full-rate elastic make_fir core;
the default gain=interp compensates the zero-stuffing energy loss and costs
zero hardware (it is folded into the coefficient constants).

Output rate = interp x accepted-input rate: with a consumer taking one beat
per cycle, upstream ready throttles input to one sample per interp cycles
naturally. Under a stalling consumer the interp beats of one input emerge as
a burst -- same tvalid behavior as the vendor cores.

(A polyphase variant that avoids the interp-1 wasted zero multiplies is a
planned later phase; this zero-stuffed version is the faithful, simple port.)
"""

from pypeline import (
    Feedback,
    NamedTuple,
    Reg,
    hw_func,
    make_uint_t,
    struct,
    uint1_t,
)

from interface.interface import interface
from interface.interface_func import make_hw_func_from_interface_func
from stream.stream import make_stream_interface

from dsp.fir import make_fir


def make_zero_stuffer(data_t, factor):
    """1-to-`factor` sample expander with valid/ready on both sides:
    each accepted input emits the sample then factor-1 zeros, one beat per
    downstream-ready cycle. Registered (one-sample buffer); accepts a new
    input on the same cycle its last beat is consumed, so sustained
    throughput is exactly factor cycles per input.

    Returns (zero_stuffer, zero_stuffer_t):
        zero_stuffer(stream_in_if: stream_intrf.fwd_t, stream_out_if: stream_intrf.fb_t)
            -> zero_stuffer_t{stream_in_if: stream_intrf.fb_t, stream_out_if: stream_intrf.fwd_t}
    i.e. one stream `@interface` per port, split into its two halves.
    """
    if not (isinstance(factor, int) and factor >= 1):
        raise ValueError(
            f"make_zero_stuffer: factor must be an int >= 1, got {factor!r}"
        )
    stream_intrf = make_stream_interface(data_t)
    count_t = make_uint_t(max(1, (factor - 1).bit_length()))
    LAST = factor - 1

    @struct
    class zero_stuffer_t(NamedTuple):
        stream_in_if: stream_intrf.fb_t  # input port's reverse half travels out
        stream_out_if: stream_intrf.fwd_t  # output port's feedforward half travels out

    @hw_func
    def zero_stuffer(
        stream_in_if: stream_intrf.fwd_t, stream_out_if: stream_intrf.fb_t
    ) -> zero_stuffer_t:
        held: Reg[data_t]
        have: Reg[uint1_t]
        count: Reg[count_t]

        o: zero_stuffer_t
        o.stream_out_if.stream.valid = have
        zero: data_t = data_t(val=0)
        if count == 0:
            o.stream_out_if.stream.data = held
        else:
            o.stream_out_if.stream.data = zero

        beat: uint1_t = have & stream_out_if.ready
        last_beat: uint1_t = beat & (count == LAST)
        o.stream_in_if.ready = ~have | last_beat

        if beat:
            if count == LAST:
                have = 0
                count = 0
            else:
                count += 1
        accepted: uint1_t = stream_in_if.stream.valid & o.stream_in_if.ready
        if accepted:
            held = stream_in_if.stream.data
            have = 1
            count = 0
        return o

    zero_stuffer.stream_intrf = stream_intrf
    zero_stuffer.in_fwd_t = stream_intrf.fwd_t
    zero_stuffer.in_fb_t = stream_intrf.fb_t
    return zero_stuffer, zero_stuffer_t


def make_fir_interp(
    coeffs,
    coeff_t,
    interp,
    data_t,
    out_t=None,
    rounding="truncate",
    overflow="wrap",
    gain=None,
    symmetry="auto",
    skip_zero_taps=True,
):
    """Build an interpolate-by-`interp` streaming FIR. Returns
    (fir_interp, fir_interp_t) with the same elastic stream interface and
    metadata attributes as dsp/fir.make_fir (elastic only -- a 1-to-interp
    expansion cannot run open-loop, so there is no valid_only mode).

    gain=None defaults to `interp` (zero-stuffing compensation), applied by
    scaling the float taps before quantization -- make sure coeff_t has the
    integer headroom for gain * max|tap|.
    """
    if not (isinstance(interp, int) and interp >= 1):
        raise ValueError(f"make_fir_interp: interp must be an int >= 1, got {interp!r}")
    if gain is None:
        gain = interp

    stuffer, _stuffer_t = make_zero_stuffer(data_t, interp)
    fir, _fir_t = make_fir(
        coeffs,
        coeff_t,
        data_t,
        out_t=out_t,
        rounding=rounding,
        overflow=overflow,
        gain=gain,
        symmetry=symmetry,
        skip_zero_taps=skip_zero_taps,
        handshake="elastic",
    )

    # Name the single output port `stream_out_if`, so the generated module's
    # ports read the same as its hand-written siblings (fir, fir_decim).
    @interface
    class fir_interp_ports(NamedTuple):
        stream_out_if: fir.out_intrf

    # An interface function: only the feedforward direction is written, and the
    # reverse (`ready`) wiring between stuffer and fir -- previously a hand-held
    # Feedback[uint1_t] -- is generated.
    def fir_interp_wiring(stream_in_if: stuffer.stream_intrf) -> fir_interp_ports:
        st = stuffer(stream_in_if)
        f = fir(st.stream_out_if)
        return fir_interp_ports(stream_out_if=f.stream_out_if)

    fir_interp, fir_interp_t = make_hw_func_from_interface_func(fir_interp_wiring)

    fir_interp.coeffs_q = fir.coeffs_q
    fir_interp.data_t = data_t
    fir_interp.coeff_t = coeff_t
    fir_interp.out_t = fir.out_t
    fir_interp.accum_t = fir.accum_t
    fir_interp.full_precision = fir.full_precision
    fir_interp.rounding = rounding
    fir_interp.overflow = overflow
    fir_interp.decim = 1
    fir_interp.interp = interp
    fir_interp.n_taps = fir.n_taps
    fir_interp.handshake = "elastic"
    fir_interp.in_fwd_t = fir.in_fwd_t
    fir_interp.out_fwd_t = fir.out_fwd_t
    fir_interp.in_fb_t = stuffer.in_fb_t
    fir_interp.out_fb_t = fir.out_fb_t
    fir_interp.in_intrf = stuffer.stream_intrf
    fir_interp.out_intrf = fir.out_intrf
    return fir_interp, fir_interp_t
