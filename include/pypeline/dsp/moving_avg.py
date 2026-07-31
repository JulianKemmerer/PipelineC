# pyright: reportInvalidTypeForm=none
"""Moving-average (boxcar) smoother -- the "Moving Average Smoothing" stage of
an RF pulse detector (see examples/pypeline/dsp/pdw/README.md, Path A: Detect &
Measure). Window of the last `n` samples (including the current one, matching
dsp/fir_tb.golden_fir's convention) kept as a running sum -- O(1) adders
instead of the O(n) an equivalent all-ones make_fir would pay -- so the sum is
exact, with no accumulated rounding drift.

`normalize=True` (default) divides by `n` for free: since `n` is a power of
two, the division is just a binary-point relabelling (log2(n) extra
fractional bits), fused into the same output resize stage every other dsp/
block uses. Non-power-of-two `n` needs a real reciprocal multiply and isn't
implemented (pass `normalize=False` for the raw running sum instead).

The delay line is registers, not BRAM -- there's no RAM primitive in this
codebase yet (the same limitation blocking the FIR library's coefficient-bank
roadmap item) -- so a large `n` x wide `data_t` costs flops accordingly, and
the running sum's single-cycle add/subtract is this block's fmax limiter for
very wide accumulators.
"""

from pypeline import (
    NamedTuple,
    Reg,
    _autopipeline_with_io_regs,
    hw_func,
    struct,
    uint1_t,
)

from fixed_point import make_fixed_t, make_fixed_resize
from stream.stream import make_stream_interface, make_stream_t
from stream.stream_pipeline import make_stream_pipeline

from dsp.fir_common import data_range, signed_bits_for, unsigned_bits_for


def make_moving_avg(
    data_t,
    n,
    out_t=None,
    normalize=True,
    rounding="truncate",
    overflow="wrap",
    handshake="elastic",
):
    """Build an n-sample moving average. Returns (moving_avg, moving_avg_t).

    data_t:    fixed_t sample format.
    n:         window length (>= 1), including the current sample. Must be a
               power of two when normalize=True.
    normalize: True  -> output is the actual mean (sum / n, exact, via a
                         binary-point relabel -- requires n a power of two).
               False -> output is the raw running sum (boxcar integrator);
                        n need not be a power of two.
    out_t:     fixed_t output format; None = full-precision (the exact sum,
               or the exact mean when normalize=True; rounding/overflow are
               then unused).
    rounding:  "truncate" | "round_half_up" | "round_half_even" | "round_half_away"
    overflow:  "wrap" | "saturate"
    handshake: "elastic"    -> moving_avg(stream_in_if: in_intrf.fwd_t,
                                           stream_out_if: out_intrf.fb_t) -> moving_avg_t
               "valid_only" -> moving_avg(stream_in_if: make_stream_t(data_t))
                                   -> make_stream_t(out_t)

    The returned `moving_avg` carries metadata attributes:
    .data_t .out_t .n .normalize .sum_t .avg_t .full_precision .rounding
    .overflow .handshake .in_fwd_t/.out_fwd_t (elastic) .in_stream_t/
    .out_stream_t (valid_only) .in_fb_t/.out_fb_t .in_intrf/.out_intrf
    """
    if not (isinstance(n, int) and n >= 1):
        raise ValueError(f"make_moving_avg: n must be an int >= 1, got {n!r}")
    log2n = 0
    if normalize:
        log2n = (n - 1).bit_length() if n > 1 else 0
        if (1 << log2n) != n:
            raise ValueError(
                f"make_moving_avg: normalize=True requires n to be a power of "
                f"two, got n={n!r} -- use a power-of-two window, or pass "
                "normalize=False for a raw running-sum boxcar instead"
            )

    xlo, xhi = data_range(data_t)
    data_val_t = data_t.typeof("val")

    if data_t.signed:
        sum_bits = signed_bits_for(n * xlo, n * xhi)
        sum_t = make_fixed_t(sum_bits - data_t.frac_bits, data_t.frac_bits, signed=True)
    else:
        sum_bits = unsigned_bits_for(n * xhi)
        sum_t = make_fixed_t(sum_bits - data_t.frac_bits, data_t.frac_bits, signed=False)
    sum_val_t = sum_t.typeof("val")

    if normalize:
        avg_t = make_fixed_t(
            sum_t.int_bits - log2n, sum_t.frac_bits + log2n, signed=data_t.signed
        )
    else:
        avg_t = sum_t
    if out_t is None:
        out_t_actual = avg_t

        @hw_func
        def moving_avg_core(s: avg_t) -> out_t_actual:
            return s

    else:
        out_t_actual = out_t
        resize_fn = make_fixed_resize(avg_t, out_t, rounding, overflow)

        @hw_func
        def moving_avg_core(s: avg_t) -> out_t_actual:
            return resize_fn(s)

    if handshake == "elastic":
        sp_func, _sp_t = make_stream_pipeline(moving_avg_core)
        in_intrf = make_stream_interface(data_t)
        out_intrf = sp_func.out_intrf

        @struct
        class moving_avg_t(NamedTuple):
            stream_in_if: in_intrf.fb_t
            stream_out_if: out_intrf.fwd_t

        @hw_func
        def moving_avg(
            stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t
        ) -> moving_avg_t:
            window: Reg[data_val_t[n]]
            sum_reg: Reg[sum_val_t]
            new_sum: sum_val_t = sum_reg + stream_in_if.stream.data.val - window[n - 1]
            avg: avg_t = avg_t(val=new_sum)

            sp_in: sp_func.in_intrf.stream_t
            sp_in.data = avg
            sp_in.valid = stream_in_if.stream.valid
            sp_o = sp_func(sp_func.in_intrf.fwd_t(stream=sp_in), stream_out_if)

            accepted: uint1_t = stream_in_if.stream.valid & sp_o.stream_in_if.ready
            if accepted:
                shifted: data_val_t[n]
                shifted[0] = stream_in_if.stream.data.val
                for i in range(1, n):
                    shifted[i] = window[i - 1]
                window = shifted
                sum_reg = new_sum

            o: moving_avg_t
            o.stream_out_if = sp_o.stream_out_if
            o.stream_in_if.ready = sp_o.stream_in_if.ready
            return o

        _core_ap = None  # no AUTOPIPELINE core in elastic mode (make_stream_pipeline)

    elif handshake == "valid_only":
        in_stream_t = make_stream_t(data_t)
        avg_stream_t = make_stream_t(avg_t)
        out_stream_t = make_stream_t(out_t_actual)
        moving_avg_t = out_stream_t

        @hw_func
        def moving_avg_core_stream(x: avg_stream_t) -> out_stream_t:
            rv: out_stream_t
            rv.data = moving_avg_core(x.data)
            rv.valid = x.valid
            return rv

        moving_avg_core_ap, _moving_avg_core_ap_call = _autopipeline_with_io_regs(
            moving_avg_core_stream, has_input_reg=True, has_output_reg=True
        )
        _core_ap = _moving_avg_core_ap_call

        @hw_func
        def moving_avg(stream_in_if: in_stream_t) -> out_stream_t:
            window: Reg[data_val_t[n]]
            sum_reg: Reg[sum_val_t]
            new_sum: sum_val_t = sum_reg + stream_in_if.data.val - window[n - 1]
            avg: avg_t = avg_t(val=new_sum)
            if stream_in_if.valid:
                shifted: data_val_t[n]
                shifted[0] = stream_in_if.data.val
                for i in range(1, n):
                    shifted[i] = window[i - 1]
                window = shifted
                sum_reg = new_sum
            avs: avg_stream_t
            avs.data = avg
            avs.valid = stream_in_if.valid
            return moving_avg_core_ap(avs)

    else:
        raise ValueError(
            f"make_moving_avg: unsupported handshake {handshake!r}, "
            "expected 'elastic' or 'valid_only'"
        )

    moving_avg.data_t = data_t
    moving_avg.out_t = out_t_actual
    moving_avg.n = n
    moving_avg.normalize = normalize
    moving_avg.sum_t = sum_t
    moving_avg.avg_t = avg_t
    moving_avg.full_precision = out_t is None
    moving_avg.rounding = rounding
    moving_avg.overflow = overflow
    moving_avg.handshake = handshake
    moving_avg.in_fwd_t = in_intrf.fwd_t if handshake == "elastic" else None
    moving_avg.in_stream_t = in_stream_t if handshake == "valid_only" else None
    moving_avg.out_fwd_t = out_intrf.fwd_t if handshake == "elastic" else None
    moving_avg.out_stream_t = out_stream_t if handshake == "valid_only" else None
    moving_avg.in_fb_t = in_intrf.fb_t if handshake == "elastic" else None
    moving_avg.out_fb_t = out_intrf.fb_t if handshake == "elastic" else None
    moving_avg.in_intrf = in_intrf if handshake == "elastic" else None
    moving_avg.out_intrf = out_intrf if handshake == "elastic" else None

    # Latency metadata (valid_only mode only -- see magnitude.py's identical
    # comment for why this is a lazy accessor rather than an eager attribute).
    # The window shift-register update is combinational-in (reads committed
    # Reg state, no pipeline stages of its own), so it adds no latency beyond
    # the io-reg-wrapped output resize's AUTOPIPELINE core.
    moving_avg.core_ap = _core_ap
    moving_avg.io_reg_latency = 2 if handshake == "valid_only" else None  # in + out reg
    moving_avg.get_latency = (
        (lambda: moving_avg.io_reg_latency + moving_avg.core_ap.latency)
        if handshake == "valid_only"
        else None
    )
    return moving_avg, moving_avg_t
