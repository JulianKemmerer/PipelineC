# pyright: reportInvalidTypeForm=none
from pypeline import (
    struct,
    NamedTuple,
    uint1_t,
    hw_func,
    Reg,
    make_uint_t,
    _autopipeline_with_io_regs,
    hw_arg_types,
    hw_return_type,
    is_hw_func,
)

from fifo import make_fifo
from stream.stream import make_stream_t


def make_stream_pipeline(func):
    """Wraps a combinational hardware function in an AUTOPIPELINE'd instance (with
    registered input/output) plus a free-running output FIFO, exposing a single
    valid/ready stream interface around it — pypeline equivalent of PipelineC's
    GLOBAL_VALID_READY_PIPELINE_INST macro, minus the global wires: this is one
    locally-instantiated function instead of two MAIN funcs joined by globals.

    The FIFO and in-flight counter are sized automatically from the
    AUTOPIPELINE'd instance's .latency — the tool-discovered pipeline depth —
    so there is no MAX_IN_FLIGHT parameter to guess. .latency reads 0 until
    the pipelinec driver's pin-and-confirm pass installs the real value
    (native sim / --comb builds stay at 0, where the effective pipeline
    latency really is just the 2 boundary registers and the FIFO floor of 2
    matches it exactly). Because make_stream_pipeline runs as plain factory
    Python, the AUTOPIPELINE object is constructed eagerly here and captured
    by closure, which is what makes its .latency readable for sizing.

    `func` must already be @hw_func-decorated, with a single annotated parameter and an
    annotated return type, e.g.:
        @hw_func
        def fft_2pt_w_omega_lut(i: fft_2pt_w_omega_lut_in_t) -> fft_2pt_out_t: ...

    Returns (stream_pipeline_func, stream_pipeline_t):
        stream_pipeline_func(stream_in: stream_t(in_type), ready_for_stream_out: uint1_t) -> stream_pipeline_t
        stream_pipeline_t fields: .stream_out (stream_t(out_type)), .ready_for_stream_in (uint1_t)
    """
    if not is_hw_func(func):
        raise TypeError(
            f"make_stream_pipeline(func): {func.__qualname__!r} must be "
            f"@hw_func-decorated before being passed in"
        )
    (in_type,) = hw_arg_types(func)
    out_type = hw_return_type(func)

    in_stream_t = make_stream_t(in_type)
    out_stream_t = make_stream_t(out_type)

    # Thread .valid alongside .data so the AUTOPIPELINE retiming balances
    # valid through the same number of stages it picks for func's data path.
    @hw_func
    def func_stream(x: in_stream_t) -> out_stream_t:
        rv: out_stream_t
        rv.data = func(x.data)
        rv.valid = x.valid
        return rv

    autopipelined_func, autopipeline_call = _autopipeline_with_io_regs(
        func_stream, has_input_reg=True, has_output_reg=True
    )

    # Total words that can be in flight at once = input reg + AUTOPIPELINE'd
    # core stages + output reg; the FIFO must hold all of them if downstream
    # stalls, and allowing exactly that many in flight sustains 1 word/cycle.
    # make_fifo requires depth >= 2 (also the 0-latency native-sim/comb floor).
    fifo_depth = max(2, 1 + autopipeline_call.latency + 1)

    fifo_func, fifo_t = make_fifo(out_type, fifo_depth)

    counter_t = make_uint_t(fifo_depth.bit_length())

    @struct
    class stream_pipeline_t(NamedTuple):
        stream_out: out_stream_t
        ready_for_stream_in: uint1_t

    @hw_func
    def stream_pipeline(
        stream_in: in_stream_t, ready_for_stream_out: uint1_t
    ) -> stream_pipeline_t:
        o: stream_pipeline_t

        # Count of words accepted into the pipeline but not yet read out of the FIFO.
        in_flight: Reg[counter_t]
        # Registered ready (matches the macro's static in_ready_reg): read old value,
        # written for next cycle further down.
        ready_reg: Reg[uint1_t]
        o.ready_for_stream_in = ready_reg

        # Free-flowing pipeline input, gated by ready.
        no_handshake_in: in_stream_t
        no_handshake_in.valid = stream_in.valid & o.ready_for_stream_in
        no_handshake_in.data = stream_in.data
        no_handshake_out: out_stream_t = autopipelined_func(no_handshake_in)

        # Free-flowing pipeline output into the FIFO; FIFO never overflows because
        # ready already accounted for in_flight < fifo_depth.
        f = fifo_func(
            ready_for_stream_out, no_handshake_out.data, no_handshake_out.valid
        )
        o.stream_out = out_stream_t(data=f.data_out, valid=f.data_out_valid)

        # Update in-flight count / next-cycle ready from accept/retire this cycle.
        accepted: uint1_t = stream_in.valid & o.ready_for_stream_in
        retired: uint1_t = o.stream_out.valid & ready_for_stream_out

        ready_reg = in_flight < fifo_depth
        if accepted & ~retired:
            ready_reg = in_flight < (fifo_depth - 1)
            in_flight += 1
        elif retired & ~accepted:
            ready_reg = 1
            in_flight -= 1

        return o

    return stream_pipeline, stream_pipeline_t
