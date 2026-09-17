"""An area-optimized combinational core between two elastic registers."""
from pypeline import (
    AUTO_COMB_AREA_OPT, NamedTuple, Reg, hw_arg_types, hw_return_type, hw_func,
    struct, uint1_t,
)
from stream.stream import make_stream_interface


def make_stream_auto_comb_area_opt(func):
    """Return (stream function, return type); latency 2, unstalled II 1.

    Both boundaries are registered. The ready path is combinational through
    occupancy logic, and never through the computation. Each boundary holds
    its data and valid bit until the following stage can accept it.
    """
    tag = func if type(func) is AUTO_COMB_AREA_OPT else AUTO_COMB_AREA_OPT(func)
    return _make_stream_auto_comb(tag)


def _make_stream_auto_comb(tag):
    """Shared elastic shell; the passed tag determines the optimization."""
    (in_type,) = hw_arg_types(tag)
    out_type = hw_return_type(tag)
    in_intrf = make_stream_interface(in_type)
    out_intrf = make_stream_interface(out_type)

    @struct
    class stream_auto_comb_opt_t(NamedTuple):
        stream_in_if: in_intrf.fb_t
        stream_out_if: out_intrf.fwd_t

    @hw_func
    def stream_auto_comb_opt(
        stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t
    ) -> stream_auto_comb_opt_t:
        o: stream_auto_comb_opt_t
        input_data: Reg[in_type]
        input_valid: Reg[uint1_t]
        output_data: Reg[out_type]
        output_valid: Reg[uint1_t]
        o.stream_out_if.stream.data = output_data
        o.stream_out_if.stream.valid = output_valid
        output_ready: uint1_t = ~output_valid | stream_out_if.ready
        input_ready: uint1_t = ~input_valid | output_ready
        o.stream_in_if.ready = input_ready
        computed: out_type = tag(input_data)
        if output_ready:
            output_valid = input_valid
            if input_valid:
                output_data = computed
        if input_ready:
            input_valid = stream_in_if.stream.valid
            if stream_in_if.stream.valid:
                input_data = stream_in_if.stream.data
        return o

    stream_auto_comb_opt.comb_opt = tag
    stream_auto_comb_opt.latency = 2
    stream_auto_comb_opt.in_intrf = in_intrf
    stream_auto_comb_opt.out_intrf = out_intrf
    stream_auto_comb_opt.in_fwd_t = in_intrf.fwd_t
    stream_auto_comb_opt.in_fb_t = in_intrf.fb_t
    stream_auto_comb_opt.out_fwd_t = out_intrf.fwd_t
    stream_auto_comb_opt.out_fb_t = out_intrf.fb_t
    return stream_auto_comb_opt, stream_auto_comb_opt_t
