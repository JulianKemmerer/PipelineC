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
    hw_arg_types,
    hw_func,
    make_autopipeline,
    make_uint_t,
    struct,
    uint1_t,
)

from stream.stream import make_stream_t
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
    max_in_flight=4,
):
    """Build a decimate-by-`decim` streaming FIR. Returns (fir_decim, fir_decim_t).

    Interface and parameters match dsp/fir.make_fir exactly (same stream
    types, same metadata attributes on the returned function); `decim` >= 1
    sets the integer rate reduction. Outputs fire on accepted samples
    decim-1, 2*decim-1, ... (matching dsp/fir_tb.golden_fir). max_in_flight
    can be small since only 1-in-decim samples enter the pipeline.
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
    in_stream_t = make_stream_t(data_t)
    phase_t = make_uint_t(max(1, (decim - 1).bit_length()))
    LAST_PHASE = decim - 1

    if handshake == "elastic":
        sp_func, sp_t = make_stream_pipeline(fir_core, max_in_flight)
        sp_in_stream_t = hw_arg_types(sp_func)[0]
        out_stream_t = sp_t.typeof("stream_out")

        @struct
        class fir_decim_t(NamedTuple):
            stream_out: out_stream_t
            ready_for_stream_in: uint1_t

        @hw_func
        def fir_decim(
            stream_in: in_stream_t, ready_for_stream_out: uint1_t
        ) -> fir_decim_t:
            window: Reg[win_t]
            phase: Reg[phase_t]
            shifted: win_t
            shifted[0] = stream_in.data
            for i in range(1, n_taps):
                shifted[i] = window[i - 1]

            # Only the last phase of each decim group enters the pipeline.
            sp_in: sp_in_stream_t
            sp_in.data = shifted
            sp_in.valid = stream_in.valid & (phase == LAST_PHASE)
            sp_o = sp_func(sp_in, ready_for_stream_out)

            accepted: uint1_t = stream_in.valid & sp_o.ready_for_stream_in
            if accepted:
                window = shifted
                if phase == LAST_PHASE:
                    phase = 0
                else:
                    phase += 1

            o: fir_decim_t
            o.stream_out = sp_o.stream_out
            o.ready_for_stream_in = sp_o.ready_for_stream_in
            return o

    elif handshake == "valid_only":
        win_stream_t = make_stream_t(win_t)
        out_stream_t = make_stream_t(out_t_actual)
        fir_decim_t = out_stream_t

        @hw_func
        def fir_core_stream(x: win_stream_t) -> out_stream_t:
            rv: out_stream_t
            rv.data = fir_core(x.data)
            rv.valid = x.valid
            return rv

        fir_core_ap = make_autopipeline(
            fir_core_stream, has_input_reg=True, has_output_reg=True
        )

        @hw_func
        def fir_decim(stream_in: in_stream_t) -> out_stream_t:
            window: Reg[win_t]
            phase: Reg[phase_t]
            shifted: win_t
            shifted[0] = stream_in.data
            for i in range(1, n_taps):
                shifted[i] = window[i - 1]
            ws: win_stream_t
            ws.data = shifted
            ws.valid = stream_in.valid & (phase == LAST_PHASE)
            if stream_in.valid:
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
    fir_decim.in_stream_t = in_stream_t
    fir_decim.out_stream_t = out_stream_t
    return fir_decim, fir_decim_t
