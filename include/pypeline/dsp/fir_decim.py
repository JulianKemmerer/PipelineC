# pyright: reportInvalidTypeForm=none
"""Integer-factor decimating FIR filter factory.

Same construction as dsp/fir.py's make_fir plus a phase counter in front of
the autopipelined blob: every accepted input advances the sample window, but
only every `decim`-th sample launches a computation into the pipeline, so
dropped phases never enter the core (improving on the old include/dsp/
fir_decim.h, which computed every phase and dropped outputs) and the output
stream runs at 1/decim of the accepted-input rate.
"""

from pypeline import (
    NamedTuple,
    Reg,
    _autopipeline_with_io_regs,
    hw_func,
    make_uint_t,
    struct,
    uint1_t,
)

from stream.stream import make_stream_interface, make_stream_t
from stream.stream_pipeline import make_stream_pipeline

from dsp.fir import _quantize_arg_coeffs
from dsp.fir_common import make_fir_core


def make_fir_decim(
    coeffs,
    coeff_t,
    decim,
    data_t,
    out_t=None,
    rounding="truncate",
    overflow="wrap",
    gain=1,
    symmetry="auto",
    skip_zero_taps=True,
    handshake="elastic",
):
    """Build a decimate-by-`decim` streaming FIR. Returns (fir_decim, fir_decim_t).

    Interface and parameters match dsp/fir.make_fir exactly (same stream
    types, same metadata attributes on the returned function); `decim` >= 1
    sets the integer rate reduction. Outputs fire on accepted samples
    decim-1, 2*decim-1, ... (matching dsp/fir_tb.golden_fir). Elastic mode's
    output FIFO is sized automatically from the AUTOPIPELINE'd core's
    tool-discovered .latency (see make_stream_pipeline).
    """
    if not (isinstance(decim, int) and decim >= 1):
        raise ValueError(f"make_fir_decim: decim must be an int >= 1, got {decim!r}")
    coeffs_q = _quantize_arg_coeffs(coeffs, coeff_t, gain)
    n_taps = len(coeffs_q)

    fir_core, out_t_actual, accum_t = make_fir_core(
        coeffs_q,
        data_t,
        coeff_t,
        out_t=out_t,
        rounding=rounding,
        overflow=overflow,
        symmetry=symmetry,
        skip_zero_taps=skip_zero_taps,
    )

    win_t = data_t[n_taps]
    in_intrf = make_stream_interface(data_t)
    phase_t = make_uint_t(max(1, (decim - 1).bit_length()))
    LAST_PHASE = decim - 1

    if handshake == "elastic":
        sp_func, sp_t = make_stream_pipeline(fir_core)

        @struct
        class fir_decim_t(NamedTuple):
            stream_in_if: in_intrf.fb_t  # input port's reverse half travels out
            stream_out_if: sp_func.out_intrf.fwd_t  # output port's feedforward half travels out

        @hw_func
        def fir_decim(
            stream_in_if: in_intrf.fwd_t, stream_out_if: sp_func.out_intrf.fb_t
        ) -> fir_decim_t:
            window: Reg[win_t]
            phase: Reg[phase_t]
            shifted: win_t
            shifted[0] = stream_in_if.stream.data
            for i in range(1, n_taps):
                shifted[i] = window[i - 1]

            # Only the last phase of each decim group enters the pipeline.
            sp_in: sp_func.in_intrf.stream_t
            sp_in.data = shifted
            sp_in.valid = stream_in_if.stream.valid & (phase == LAST_PHASE)
            sp_o = sp_func(sp_func.in_intrf.fwd_t(stream=sp_in), stream_out_if)

            accepted: uint1_t = stream_in_if.stream.valid & sp_o.stream_in_if.ready
            if accepted:
                window = shifted
                if phase == LAST_PHASE:
                    phase = 0
                else:
                    phase += 1

            o: fir_decim_t
            o.stream_out_if = sp_o.stream_out_if
            o.stream_in_if.ready = sp_o.stream_in_if.ready
            return o

    elif handshake == "valid_only":
        # A genuinely one-directional input type -- see dsp/fir.make_fir's
        # identical valid_only branch.
        in_stream_t = make_stream_t(data_t)
        win_stream_t = make_stream_t(win_t)
        out_stream_t = make_stream_t(out_t_actual)
        fir_decim_t = out_stream_t

        @hw_func
        def fir_core_stream(x: win_stream_t) -> out_stream_t:
            rv: out_stream_t
            rv.data = fir_core(x.data)
            rv.valid = x.valid
            return rv

        fir_core_ap, _fir_core_ap_call = _autopipeline_with_io_regs(
            fir_core_stream, has_input_reg=True, has_output_reg=True
        )

        @hw_func
        def fir_decim(stream_in_if: in_stream_t) -> out_stream_t:
            window: Reg[win_t]
            phase: Reg[phase_t]
            shifted: win_t
            shifted[0] = stream_in_if.data
            for i in range(1, n_taps):
                shifted[i] = window[i - 1]
            ws: win_stream_t
            ws.data = shifted
            ws.valid = stream_in_if.valid & (phase == LAST_PHASE)
            if stream_in_if.valid:
                window = shifted
                if phase == LAST_PHASE:
                    phase = 0
                else:
                    phase += 1
            return fir_core_ap(ws)

    else:
        raise ValueError(
            f"make_fir_decim: unsupported handshake {handshake!r}, "
            "expected 'elastic' or 'valid_only'"
        )

    fir_decim.coeffs_q = coeffs_q
    fir_decim.data_t = data_t
    fir_decim.coeff_t = coeff_t
    fir_decim.out_t = out_t_actual
    fir_decim.accum_t = accum_t
    fir_decim.full_precision = out_t is None
    fir_decim.rounding = rounding
    fir_decim.overflow = overflow
    fir_decim.decim = decim
    fir_decim.interp = 1
    fir_decim.n_taps = n_taps
    fir_decim.handshake = handshake
    fir_decim.in_fwd_t = in_intrf.fwd_t if handshake == "elastic" else None
    fir_decim.in_stream_t = in_stream_t if handshake == "valid_only" else None
    fir_decim.out_fwd_t = sp_func.out_intrf.fwd_t if handshake == "elastic" else None
    fir_decim.out_stream_t = out_stream_t if handshake == "valid_only" else None
    # Reverse halves of the two ports (elastic only -- valid_only is one-way).
    fir_decim.in_fb_t = in_intrf.fb_t if handshake == "elastic" else None
    fir_decim.out_fb_t = sp_func.out_intrf.fb_t if handshake == "elastic" else None
    fir_decim.stream_intrf = in_intrf
    fir_decim.in_intrf = in_intrf
    return fir_decim, fir_decim_t
