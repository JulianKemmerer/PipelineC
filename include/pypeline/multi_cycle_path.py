# pyright: reportInvalidTypeForm=none
from pypeline import (
    struct,
    NamedTuple,
    uint1_t,
    uint8_t,
    hw_func,
    Reg,
    MULTI_CYCLE,
    AUTOMCP,
    hw_arg_types,
    hw_return_type,
    is_hw_func,
)

from stream.stream import make_stream_interface

# Both factories' handshake count cycles_since_launch in a uint8_t that must
# reach latency + 1.
_MAX_MCP_LATENCY = 254


def _mcp_stream_types(func, factory_name):
    """(in_type, out_type, in_intrf, out_intrf) for a single-argument
    @hw_func wrapped in a multi-cycle-path FSM."""
    if not is_hw_func(func):
        raise TypeError(
            f"{factory_name}(func, ...): {func.__qualname__!r} must be "
            f"@hw_func-decorated before being passed in"
        )
    (in_type,) = hw_arg_types(func)
    out_type = hw_return_type(func)
    return in_type, out_type, make_stream_interface(in_type), make_stream_interface(out_type)


def _check_mcp_latency(factory_name, latency):
    if latency > _MAX_MCP_LATENCY:
        raise ValueError(
            f"{factory_name}: {latency} cycles exceeds the handshake counter's "
            f"limit of {_MAX_MCP_LATENCY}"
        )


def _attach_stream_attrs(func_mcp, in_intrf, out_intrf):
    func_mcp.in_intrf = in_intrf
    func_mcp.out_intrf = out_intrf
    func_mcp.in_fwd_t = in_intrf.fwd_t
    func_mcp.in_fb_t = in_intrf.fb_t
    func_mcp.out_fwd_t = out_intrf.fwd_t
    func_mcp.out_fb_t = out_intrf.fb_t


def make_stream_interface_mcp(func, latency: int):
    """Wraps a combinational hardware function in a multi-cycle-path FSM
    exposing a valid/ready stream interface, with a fixed `latency`-cycle
    MULTI_CYCLE[...] constraint on it -- pypeline equivalent of PipelineC's
    DECL_VALID_READY_MCP_FUNC(out_type, func_name, in_type, NCYCLES). See
    make_stream_interface_automcp for a cycle count the build picks.

    `func` must already be @hw_func-decorated, with a single annotated parameter and
    an annotated return type, e.g.:
        @hw_func
        def divider(i: my_struct_t) -> uint32_t: ...

    Returns (func_mcp, func_mcp_t):
        func_mcp(stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t) -> func_mcp_t
        func_mcp_t fields: .stream_in_if (in_intrf.fb_t), .stream_out_if (out_intrf.fwd_t)
    A result is valid latency + 1 cycles after its input is accepted.
    """
    if not isinstance(latency, int) or isinstance(latency, bool) or latency < 1:
        raise ValueError(
            f"make_stream_interface_mcp(func, latency={latency!r}): latency must "
            "be an int >= 1"
        )
    _check_mcp_latency("make_stream_interface_mcp", latency)
    in_type, out_type, in_intrf, out_intrf = _mcp_stream_types(
        func, "make_stream_interface_mcp"
    )

    @struct
    class func_mcp_t(NamedTuple):
        stream_in_if: in_intrf.fb_t  # input port's reverse half travels out
        stream_out_if: out_intrf.fwd_t  # output port's feedforward half travels out

    @hw_func
    def func_mcp(stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t) -> func_mcp_t:
        # Start/capture regs spanning the multi-cycle path
        MC = MULTI_CYCLE[latency]
        launch: Reg[in_type, MC.start]
        capture: Reg[out_type, MC.end]
        capture_next = func(launch)

        o: func_mcp_t
        o.stream_out_if.stream.data = capture

        # FSM logic exposing the valid/ready interface
        cycles_since_launch: Reg[uint8_t]
        # Output side first, for same-cycle output/input handshake
        if cycles_since_launch == (latency + 1):
            o.stream_out_if.stream.valid = 1
            if o.stream_out_if.stream.valid & stream_out_if.ready:
                cycles_since_launch = 0
        elif cycles_since_launch > 0:
            cycles_since_launch += 1

        if cycles_since_launch == 0:
            o.stream_in_if.ready = 1
            if stream_in_if.stream.valid & o.stream_in_if.ready:
                launch = stream_in_if.stream.data
                cycles_since_launch = 1

        capture = capture_next
        return o

    _attach_stream_attrs(func_mcp, in_intrf, out_intrf)
    return func_mcp, func_mcp_t


def make_stream_interface_automcp(
    func, *, latency=None, start_latency=None, max_latency=None
):
    """make_stream_interface_mcp whose multi-cycle count the pypelinec
    throughput sweep picks: an AUTOMCP(latency=, start_latency=,
    max_latency=) tag replaces the fixed MULTI_CYCLE[...] (see
    pypeline.AUTOMCP). The sweep starts at start_latency (default 1) and
    raises the count when the launch->capture path fails timing, never above
    max_latency; latency=N fixes it. The handshake is written in terms of the
    tag's .latency, so the final design always waits exactly as many cycles as
    the path is constrained for.

    Returns (func_mcp, func_mcp_t), like make_stream_interface_mcp;
    func_mcp.mcp is the AUTOMCP tag (read func_mcp.mcp.latency for the count).
    A result is valid mcp.latency + 1 cycles after its input is accepted.
    """
    MC = AUTOMCP(latency=latency, start_latency=start_latency, max_latency=max_latency)
    _check_mcp_latency("make_stream_interface_automcp", MC._ncycles_for_compiler())
    in_type, out_type, in_intrf, out_intrf = _mcp_stream_types(
        func, "make_stream_interface_automcp"
    )

    @struct
    class func_mcp_t(NamedTuple):
        stream_in_if: in_intrf.fb_t  # input port's reverse half travels out
        stream_out_if: out_intrf.fwd_t  # output port's feedforward half travels out

    @hw_func
    def func_mcp(stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t) -> func_mcp_t:
        # Start/capture regs spanning the multi-cycle path
        launch: Reg[in_type, MC.start]
        capture: Reg[out_type, MC.end]
        capture_next = func(launch)

        o: func_mcp_t
        o.stream_out_if.stream.data = capture

        # FSM logic exposing the valid/ready interface
        cycles_since_launch: Reg[uint8_t]
        # Output side first, for same-cycle output/input handshake
        if cycles_since_launch == (MC.latency + 1):
            o.stream_out_if.stream.valid = 1
            if o.stream_out_if.stream.valid & stream_out_if.ready:
                cycles_since_launch = 0
        elif cycles_since_launch > 0:
            cycles_since_launch += 1

        if cycles_since_launch == 0:
            o.stream_in_if.ready = 1
            if stream_in_if.stream.valid & o.stream_in_if.ready:
                launch = stream_in_if.stream.data
                cycles_since_launch = 1

        capture = capture_next
        return o

    _attach_stream_attrs(func_mcp, in_intrf, out_intrf)
    func_mcp.mcp = MC
    return func_mcp, func_mcp_t
