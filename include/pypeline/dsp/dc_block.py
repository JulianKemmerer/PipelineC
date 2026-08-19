# pyright: reportInvalidTypeForm=none
"""DC blocker (leaky-integrator mean subtraction) -- the "DC Blocking /
Removal" stage of an RF pulse detector (see
examples/pypeline/dsp/pdw/README.md, Path A: Detect & Measure).

y[n] = x[n] - mean[n]
mean[n] = mean[n-1] + (x_ext[n] - mean[n-1]) >> k

`mean` is kept with `k` EXTRA fractional bits beyond `data_t` -- the standard
trick that lets the `>> k` update step extract a real (if small) increment
every cycle instead of getting stuck at 0 once `|x - mean|` drops below one
`data_t` LSB (the classic integer-leaky-integrator dead-zone/limit-cycle).
Passband is flat (no ~2x Nyquist gain, unlike the classic `y = x - x_prev +
R*y_prev` pole/zero blocker), at the cost of one Reg of state instead of two.
`.mean` is also a directly useful noise-floor estimate on its own.

The recursive mean update is inherently stateful (an IIR loop), so it cannot
itself be autopipelined into an II=1 pipeline -- only the feedforward output
resize stage is. `k` sets the pole at 1 - 2^-k, i.e. a settling time constant
of roughly 2^k samples.
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

from dsp.fir_common import data_range, signed_bits_for


def make_dc_block(
    data_t,
    k=10,
    out_t=None,
    rounding="truncate",
    overflow="wrap",
    handshake="elastic",
):
    """Build a DC blocker. Returns (dc_block, dc_block_t).

    data_t:    fixed_t sample format.
    k:         extra fractional bits carried by the internal mean estimate
               (also the shift in the leaky-integrator update); pole at
               1 - 2^-k, settling time constant ~= 2^k samples. Must be >= 1.
    out_t:     fixed_t output format; None = full-precision highpassed sample
               (same frac_bits as the internal diff, i.e. data_t.frac_bits + k;
               rounding/overflow are then unused).
    rounding:  "truncate" | "round_half_up" | "round_half_even" | "round_half_away"
    overflow:  "wrap" | "saturate"
    handshake: "elastic"    -> dc_block(stream_in_if: in_intrf.fwd_t,
                                         stream_out_if: out_intrf.fb_t) -> dc_block_t
               "valid_only" -> dc_block(stream_in_if: make_stream_t(data_t))
                                   -> make_stream_t(out_t)

    The returned `dc_block` carries metadata attributes:
    .data_t .out_t .k .mean_t .diff_t .full_precision .rounding .overflow
    .handshake .in_fwd_t/.out_fwd_t (elastic) .in_stream_t/.out_stream_t
    (valid_only) .in_fb_t/.out_fb_t .in_intrf/.out_intrf
    """
    if not (isinstance(k, int) and k >= 1):
        raise ValueError(f"make_dc_block: k must be an int >= 1, got {k!r}")

    xlo, xhi = data_range(data_t)
    mean_frac = data_t.frac_bits + k
    # One guard integer bit above data_t's own range: the leaky-integrator
    # mean is a convex running estimate that tracks toward x_ext, so it
    # should never need more headroom than this under normal operation.
    mean_t = make_fixed_t(data_t.int_bits + 1, mean_frac, signed=True)
    mean_val_t = mean_t.typeof("val")
    mlo, mhi = data_range(mean_t)

    x_ext_lo, x_ext_hi = xlo << k, xhi << k
    diff_bits = signed_bits_for(x_ext_lo - mhi, x_ext_hi - mlo)
    diff_t = make_fixed_t(diff_bits - mean_frac, mean_frac, signed=True)
    diff_val_t = diff_t.typeof("val")

    if out_t is None:
        out_t_actual = diff_t

        @hw_func
        def dc_block_core(d: diff_t) -> out_t_actual:
            return d

    else:
        out_t_actual = out_t
        resize_fn = make_fixed_resize(diff_t, out_t, rounding, overflow)

        @hw_func
        def dc_block_core(d: diff_t) -> out_t_actual:
            return resize_fn(d)

    if handshake == "elastic":
        sp_func, _sp_t = make_stream_pipeline(dc_block_core)
        in_intrf = make_stream_interface(data_t)
        out_intrf = sp_func.out_intrf

        @struct
        class dc_block_t(NamedTuple):
            stream_in_if: in_intrf.fb_t
            stream_out_if: out_intrf.fwd_t

        @hw_func
        def dc_block(
            stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t
        ) -> dc_block_t:
            mean: Reg[mean_t]
            x_wide: mean_val_t = stream_in_if.stream.data.val
            x_ext: mean_val_t = x_wide << k
            diff_val: diff_val_t = x_ext - mean.val
            diff: diff_t = diff_t(val=diff_val)

            sp_in: sp_func.in_intrf.stream_t
            sp_in.data = diff
            sp_in.valid = stream_in_if.stream.valid
            sp_o = sp_func(sp_func.in_intrf.fwd_t(sp_in), stream_out_if)

            accepted: uint1_t = stream_in_if.stream.valid & sp_o.stream_in_if.ready
            if accepted:
                mean = mean_t(val=mean.val + (diff_val >> k))

            o: dc_block_t
            o.stream_out_if = sp_o.stream_out_if
            o.stream_in_if.ready = sp_o.stream_in_if.ready
            return o

        _core_ap = None  # no AUTOPIPELINE core in elastic mode (make_stream_pipeline)

    elif handshake == "valid_only":
        in_stream_t = make_stream_t(data_t)
        diff_stream_t = make_stream_t(diff_t)
        out_stream_t = make_stream_t(out_t_actual)
        dc_block_t = out_stream_t

        @hw_func
        def dc_block_core_stream(x: diff_stream_t) -> out_stream_t:
            rv: out_stream_t
            rv.data = dc_block_core(x.data)
            rv.valid = x.valid
            return rv

        dc_block_core_ap, _dc_block_core_ap_call = _autopipeline_with_io_regs(
            dc_block_core_stream, has_input_reg=True, has_output_reg=True
        )
        _core_ap = _dc_block_core_ap_call

        @hw_func
        def dc_block(stream_in_if: in_stream_t) -> out_stream_t:
            mean: Reg[mean_t]
            x_wide: mean_val_t = stream_in_if.data.val
            x_ext: mean_val_t = x_wide << k
            diff_val: diff_val_t = x_ext - mean.val
            diff: diff_t = diff_t(val=diff_val)
            if stream_in_if.valid:
                mean = mean_t(val=mean.val + (diff_val >> k))
            ds: diff_stream_t
            ds.data = diff
            ds.valid = stream_in_if.valid
            return dc_block_core_ap(ds)

    else:
        raise ValueError(
            f"make_dc_block: unsupported handshake {handshake!r}, "
            "expected 'elastic' or 'valid_only'"
        )

    dc_block.data_t = data_t
    dc_block.out_t = out_t_actual
    dc_block.k = k
    dc_block.mean_t = mean_t
    dc_block.diff_t = diff_t
    dc_block.full_precision = out_t is None
    dc_block.rounding = rounding
    dc_block.overflow = overflow
    dc_block.handshake = handshake
    dc_block.in_fwd_t = in_intrf.fwd_t if handshake == "elastic" else None
    dc_block.in_stream_t = in_stream_t if handshake == "valid_only" else None
    dc_block.out_fwd_t = out_intrf.fwd_t if handshake == "elastic" else None
    dc_block.out_stream_t = out_stream_t if handshake == "valid_only" else None
    dc_block.in_fb_t = in_intrf.fb_t if handshake == "elastic" else None
    dc_block.out_fb_t = out_intrf.fb_t if handshake == "elastic" else None
    dc_block.in_intrf = in_intrf if handshake == "elastic" else None
    dc_block.out_intrf = out_intrf if handshake == "elastic" else None

    # Latency metadata (valid_only mode only -- see magnitude.py's identical
    # comment for why this is a lazy accessor rather than an eager attribute).
    # Note: the IIR mean update itself is purely combinational-in (reads the
    # committed Reg, no pipeline stages of its own), so it adds no latency
    # beyond the io-reg-wrapped output resize's AUTOPIPELINE core.
    dc_block.core_ap = _core_ap
    dc_block.io_reg_latency = 2 if handshake == "valid_only" else None  # in + out reg
    dc_block.get_latency = (
        (lambda: dc_block.io_reg_latency + dc_block.core_ap.latency)
        if handshake == "valid_only"
        else None
    )
    return dc_block, dc_block_t
