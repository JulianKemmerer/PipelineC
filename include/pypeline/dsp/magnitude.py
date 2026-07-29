# pyright: reportInvalidTypeForm=none
"""Complex-sample power (I^2+Q^2) -- the "instantaneous power" stage of an
RF pulse detector (see examples/pypeline/dsp/pdw/README.md, Path A: Detect &
Measure). One pure feedforward `@hw_func` blob (two squares, an add, and a
fused output resize), autopipelined the same way as dsp/fir.py's core, wrapped
in a valid/ready stream.
"""

from pypeline import (
    NamedTuple,
    _autopipeline_with_io_regs,
    hw_func,
    struct,
    uint1_t,
)

from fixed_point import make_fixed_t, make_fixed_resize
from stream.stream import make_stream_t
from stream.stream_pipeline import make_stream_pipeline

from dsp.fir_common import data_range, signed_bits_for, unsigned_bits_for


def make_complex_t(data_t):
    """A plain `{i, q}` struct over a shared fixed_t sample type. Lives here
    (rather than its own module) because magnitude is its only consumer today;
    promote it if a complex FIR/mixer needs it later."""

    @struct
    class complex_t(NamedTuple):
        i: data_t
        q: data_t

    return complex_t


def make_magnitude(
    data_t,
    out_t=None,
    rounding="truncate",
    overflow="wrap",
    handshake="elastic",
):
    """Build a power (I^2+Q^2) stage. Returns (magnitude, magnitude_t).

    data_t:    fixed_t sample format of each I/Q rail (e.g. make_fixed_t(16, 0)
               for a plain int16_t rail -- the PDW's raw ADC format).
    out_t:     fixed_t output format; None = full-precision exact power type
               (unsigned, `2*data_t.frac_bits` frac_bits; rounding/overflow are
               then unused -- the value is provably >= 0, so the signed exact
               accumulator's bits are reinterpreted into the unsigned output
               losslessly, not rounded/saturated).
    rounding:  "truncate" | "round_half_up" | "round_half_even" | "round_half_away"
    overflow:  "wrap" | "saturate"
    handshake: "elastic"    -> magnitude(stream_in_if: in_intrf.fwd_t,
                                          stream_out_if: out_intrf.fb_t) -> magnitude_t
                               (in_intrf built over make_complex_t(data_t))
               "valid_only" -> magnitude(stream_in_if: make_stream_t(complex_t))
                                   -> make_stream_t(out_t)

    The returned `magnitude` carries metadata attributes:
    .data_t .complex_t .out_t .acc_t .full_precision .rounding .overflow
    .handshake .in_fwd_t/.out_fwd_t (elastic) .in_stream_t/.out_stream_t
    (valid_only) .in_fb_t/.out_fb_t .in_intrf/.out_intrf
    """
    complex_t = make_complex_t(data_t)

    xlo, xhi = data_range(data_t)
    sq_max = max(xlo * xlo, xhi * xhi)
    sum_max = 2 * sq_max
    acc_frac = 2 * data_t.frac_bits
    acc_bits = signed_bits_for(0, sum_max)
    acc_t = make_fixed_t(acc_bits - acc_frac, acc_frac, signed=True)
    acc_val_t = acc_t.typeof("val")

    if out_t is None:
        power_bits = unsigned_bits_for(sum_max)
        out_t_actual = make_fixed_t(power_bits - acc_frac, acc_frac, signed=False)
    else:
        out_t_actual = out_t
    out_t_actual_full_precision = out_t is None

    resize_fn = make_fixed_resize(acc_t, out_t_actual, rounding, overflow)

    @hw_func
    def magnitude_core(x: complex_t) -> out_t_actual:
        sq_i: acc_val_t = x.i.val * x.i.val
        sq_q: acc_val_t = x.q.val * x.q.val
        s: acc_val_t = sq_i + sq_q
        acc: acc_t = acc_t(val=s)
        return resize_fn(acc)

    if handshake == "elastic":
        sp_func, _sp_t = make_stream_pipeline(magnitude_core)
        in_intrf = sp_func.in_intrf
        out_intrf = sp_func.out_intrf

        @struct
        class magnitude_t(NamedTuple):
            stream_in_if: in_intrf.fb_t
            stream_out_if: out_intrf.fwd_t

        @hw_func
        def magnitude(
            stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t
        ) -> magnitude_t:
            o: magnitude_t
            sp_o = sp_func(stream_in_if, stream_out_if)
            o.stream_out_if = sp_o.stream_out_if
            o.stream_in_if.ready = sp_o.stream_in_if.ready
            return o

    elif handshake == "valid_only":
        in_stream_t = make_stream_t(complex_t)
        out_stream_t = make_stream_t(out_t_actual)
        magnitude_t = out_stream_t

        @hw_func
        def magnitude_core_stream(x: in_stream_t) -> out_stream_t:
            rv: out_stream_t
            rv.data = magnitude_core(x.data)
            rv.valid = x.valid
            return rv

        magnitude_core_ap, _magnitude_core_ap_call = _autopipeline_with_io_regs(
            magnitude_core_stream, has_input_reg=True, has_output_reg=True
        )

        @hw_func
        def magnitude(stream_in_if: in_stream_t) -> out_stream_t:
            return magnitude_core_ap(stream_in_if)

    else:
        raise ValueError(
            f"make_magnitude: unsupported handshake {handshake!r}, "
            "expected 'elastic' or 'valid_only'"
        )

    magnitude.data_t = data_t
    magnitude.complex_t = complex_t
    magnitude.in_data_t = complex_t
    magnitude.acc_t = acc_t
    magnitude.out_t = out_t_actual
    magnitude.full_precision = out_t_actual_full_precision
    magnitude.rounding = rounding
    magnitude.overflow = overflow
    magnitude.handshake = handshake
    magnitude.in_fwd_t = in_intrf.fwd_t if handshake == "elastic" else None
    magnitude.in_stream_t = in_stream_t if handshake == "valid_only" else None
    magnitude.out_fwd_t = out_intrf.fwd_t if handshake == "elastic" else None
    magnitude.out_stream_t = out_stream_t if handshake == "valid_only" else None
    magnitude.in_fb_t = in_intrf.fb_t if handshake == "elastic" else None
    magnitude.out_fb_t = out_intrf.fb_t if handshake == "elastic" else None
    magnitude.in_intrf = in_intrf if handshake == "elastic" else None
    magnitude.out_intrf = out_intrf if handshake == "elastic" else None
    return magnitude, magnitude_t
