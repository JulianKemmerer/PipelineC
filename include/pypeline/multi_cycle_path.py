# pyright: reportInvalidTypeForm=none
from pypeline import (
    struct,
    NamedTuple,
    uint1_t,
    uint8_t,
    hw_func,
    Reg,
    MULTI_CYCLE,
    hw_arg_types,
    hw_return_type,
    is_hw_func,
)

from interface.interface import make_interface_feedback_type, make_interface_type
from stream.stream import make_stream_interface


def make_valid_ready_mcp(func, ncycles: int):
    """Wraps a combinational hardware function in a multi-cycle-path FSM
    exposing a valid/ready stream interface — pypeline equivalent of
    PipelineC's DECL_VALID_READY_MCP_FUNC(out_type, func_name, in_type, NCYCLES).

    `func` must already be @hw_func-decorated, with a single annotated parameter and
    an annotated return type, e.g.:
        @hw_func
        def divider(i: my_struct_t) -> uint32_t: ...

    Returns (func_mcp, func_mcp_t):
        func_mcp(stream_in: in_stream_t, stream_out: out_fb_t) -> func_mcp_t
        func_mcp_t fields: .stream_in (in_fb_t), .stream_out (out_stream_t)
    """
    if not is_hw_func(func):
        raise TypeError(
            f"make_valid_ready_mcp(func, ...): {func.__qualname__!r} must be "
            f"@hw_func-decorated before being passed in"
        )
    (in_type,) = hw_arg_types(func)
    out_type = hw_return_type(func)

    in_intrf = make_stream_interface(in_type)
    out_intrf = make_stream_interface(out_type)
    in_stream_t = make_interface_type(in_intrf)
    in_fb_t = make_interface_feedback_type(in_intrf)
    out_stream_t = make_interface_type(out_intrf)
    out_fb_t = make_interface_feedback_type(out_intrf)

    @struct
    class func_mcp_t(NamedTuple):
        stream_in: in_fb_t  # input port's reverse half travels out
        stream_out: out_stream_t  # output port's feedforward half travels out

    @hw_func
    def func_mcp(stream_in: in_stream_t, stream_out: out_fb_t) -> func_mcp_t:
        # Start/capture regs spanning the multi-cycle path
        MC = MULTI_CYCLE[ncycles]
        launch: Reg[in_type, MC.start]
        capture: Reg[out_type, MC.end]
        capture_next = func(launch)

        o: func_mcp_t
        o.stream_out.data = capture

        # FSM logic exposing the valid/ready interface
        cycles_since_launch: Reg[uint8_t]
        # Output side first, for same-cycle output/input handshake
        if cycles_since_launch == (ncycles + 1):
            o.stream_out.valid = 1
            if o.stream_out.valid & stream_out.ready:
                cycles_since_launch = 0
        elif cycles_since_launch > 0:
            cycles_since_launch += 1

        if cycles_since_launch == 0:
            o.stream_in.ready = 1
            if stream_in.valid & o.stream_in.ready:
                launch = stream_in.data
                cycles_since_launch = 1

        capture = capture_next
        return o

    func_mcp.in_intrf = in_intrf
    func_mcp.out_intrf = out_intrf
    func_mcp.in_stream_t = in_stream_t
    func_mcp.in_fb_t = in_fb_t
    func_mcp.out_stream_t = out_stream_t
    func_mcp.out_fb_t = out_fb_t
    return func_mcp, func_mcp_t
