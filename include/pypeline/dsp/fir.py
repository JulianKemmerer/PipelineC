# pyright: reportInvalidTypeForm=none
"""Single-rate streaming FIR filter factory -- the pypeline equivalent of the
vendor FIR compiler IPs' basic mode (AMD FIR Compiler / Intel FIR II), built
from one autopipelined comb blob (see dsp/fir_common.py) wrapped in a
valid/ready stream. Pipeline depth is chosen by the tool per target FPGA/fmax,
never hard-coded.

Usage:
    from fixed_point import make_fixed_t
    from dsp.fir import make_fir

    data_t = make_fixed_t(1, 15)               # Q1.15 samples
    coeff_t = make_fixed_t(2, 14)              # Q2.14 coefficients
    fir, fir_t = make_fir(
        [0.25, 0.5, 0.5, 0.25], coeff_t, data_t,
        out_t=data_t, rounding="round_half_even", overflow="saturate",
    )

    @MAIN(100.0)
    def top(stream_in: fir.in_stream_t, ready_for_stream_out: uint1_t) -> fir_t:
        return fir(stream_in, ready_for_stream_out)
"""

from pypeline import (
    NamedTuple,
    Reg,
    _autopipeline_with_io_regs,
    hw_arg_types,
    hw_func,
    struct,
    uint1_t,
)

from fixed_point import quantize_coeffs
from stream.stream import make_stream_t
from stream.stream_pipeline import make_stream_pipeline

from dsp.fir_common import make_fir_core


def _quantize_arg_coeffs(coeffs, coeff_t, gain):
    """Float taps are scaled by `gain` then quantized to coeff_t (gain costs
    zero hardware -- it lives in the constants). Pre-quantized raw ints pass
    through untouched and require gain == 1."""
    if all(isinstance(c, int) and not isinstance(c, bool) for c in coeffs):
        if gain != 1:
            raise ValueError(
                "make_fir: pre-quantized integer coeffs require gain=1 "
                "(fold your gain into the integers, or pass float taps)"
            )
        return list(coeffs)
    return quantize_coeffs([float(c) * gain for c in coeffs], coeff_t)


def make_fir(
    coeffs,
    coeff_t,
    data_t,
    out_t=None,
    rounding="truncate",
    overflow="wrap",
    gain=1,
    symmetry="auto",
    skip_zero_taps=True,
    handshake="elastic",
):
    """Build a single-rate streaming FIR filter. Returns (fir, fir_t).

    coeffs:    list of float taps (quantized to coeff_t here, after scaling by
               `gain`) or already-quantized raw ints (then gain must be 1).
    coeff_t:   fixed_t coefficient format (make_fixed_t(...)).
    data_t:    fixed_t sample format of the input stream.
    out_t:     fixed_t output format; None = full-precision accumulator type
               (rounding/overflow unused in that case).
    rounding:  "truncate" | "round_half_up" | "round_half_even" | "round_half_away"
    overflow:  "wrap" | "saturate"
    symmetry:  "auto" (fold symmetric/anti-symmetric quantized coeffs into
               pre-adders, halving multipliers) | "none"
    skip_zero_taps: drop zero-coefficient taps at elaboration time (half-band).
    handshake: "elastic"    -> fir(stream_in: stream_t(data_t),
                                   ready_for_stream_out: uint1_t) -> fir_t
                               with fir_t{stream_out, ready_for_stream_in}
                               (same field names as make_stream_pipeline, so
                               filters chain like stream_pipeline instances).
               "valid_only" -> fir(stream_in: stream_t(data_t))
                                   -> stream_t(out_t)
                               vendor-style free-running mode: no FIFO or
                               in-flight counter; input must be consumable
                               downstream every cycle.
    Elastic mode's output FIFO is sized automatically from the AUTOPIPELINE'd
    core's tool-discovered .latency (see make_stream_pipeline).

    The returned `fir` carries metadata attributes for dsp/fir_tb.py:
    .coeffs_q .data_t .coeff_t .out_t .accum_t .full_precision .rounding
    .overflow .decim .interp .n_taps .handshake .in_stream_t .out_stream_t
    """
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

    if handshake == "elastic":
        sp_func, sp_t = make_stream_pipeline(fir_core)
        sp_in_stream_t = hw_arg_types(sp_func)[0]
        out_stream_t = sp_t.typeof("stream_out")

        @struct
        class fir_t(NamedTuple):
            stream_out: out_stream_t
            ready_for_stream_in: uint1_t

        @hw_func
        def fir(stream_in: in_stream_t, ready_for_stream_out: uint1_t) -> fir_t:
            # Combinational window including the current sample; the shift
            # commits only on accepted samples so backpressure freezes it.
            window: Reg[win_t]
            shifted: win_t
            shifted[0] = stream_in.data
            for i in range(1, n_taps):
                shifted[i] = window[i - 1]

            sp_in: sp_in_stream_t
            sp_in.data = shifted
            sp_in.valid = stream_in.valid
            sp_o = sp_func(sp_in, ready_for_stream_out)

            accepted: uint1_t = stream_in.valid & sp_o.ready_for_stream_in
            if accepted:
                window = shifted

            o: fir_t
            o.stream_out = sp_o.stream_out
            o.ready_for_stream_in = sp_o.ready_for_stream_in
            return o

    elif handshake == "valid_only":
        win_stream_t = make_stream_t(win_t)
        out_stream_t = make_stream_t(out_t_actual)
        fir_t = out_stream_t

        # Thread valid through the autopipeline alongside the data (the
        # stream_pipeline func_stream pattern) so retiming keeps them aligned.
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
        def fir(stream_in: in_stream_t) -> out_stream_t:
            window: Reg[win_t]
            shifted: win_t
            shifted[0] = stream_in.data
            for i in range(1, n_taps):
                shifted[i] = window[i - 1]
            if stream_in.valid:
                window = shifted
            ws: win_stream_t
            ws.data = shifted
            ws.valid = stream_in.valid
            return fir_core_ap(ws)

    else:
        raise ValueError(
            f"make_fir: unsupported handshake {handshake!r}, "
            "expected 'elastic' or 'valid_only'"
        )

    fir.coeffs_q = coeffs_q
    fir.data_t = data_t
    fir.coeff_t = coeff_t
    fir.out_t = out_t_actual
    fir.accum_t = accum_t
    fir.full_precision = out_t is None
    fir.rounding = rounding
    fir.overflow = overflow
    fir.decim = 1
    fir.interp = 1
    fir.n_taps = n_taps
    fir.handshake = handshake
    fir.in_stream_t = in_stream_t
    fir.out_stream_t = out_stream_t
    return fir, fir_t
