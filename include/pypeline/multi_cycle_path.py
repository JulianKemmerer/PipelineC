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

from stream.stream import make_stream_t


def make_valid_ready_mcp(func, ncycles: int):
    """Wraps a combinational hardware function in a multi-cycle-path FSM
    exposing a valid/ready stream interface — pypeline equivalent of
    PipelineC's DECL_VALID_READY_MCP_FUNC(out_type, func_name, in_type, NCYCLES).

    `func` must already be @hw_func-decorated, with a single annotated parameter and
    an annotated return type, e.g.:
        @hw_func
        def divider(i: my_struct_t) -> uint32_t: ...

    Returns (func_mcp, func_mcp_t):
        func_mcp(stream_in: stream_t(in_type), ready_for_stream_out: uint1_t) -> func_mcp_t
        func_mcp_t fields: .stream_out (stream_t(out_type)), .ready_for_stream_in (uint1_t)
    """
    if not is_hw_func(func):
        raise TypeError(
            f"make_valid_ready_mcp(func, ...): {func.__qualname__!r} must be "
            f"@hw_func-decorated before being passed in"
        )
    (in_type,) = hw_arg_types(func)
    out_type = hw_return_type(func)

    in_stream_t = make_stream_t(in_type)
    out_stream_t = make_stream_t(out_type)

    @struct
    class func_mcp_t(NamedTuple):
        stream_out: out_stream_t
        ready_for_stream_in: uint1_t

    @hw_func
    def func_mcp(stream_in: in_stream_t, ready_for_stream_out: uint1_t) -> func_mcp_t:
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
            if o.stream_out.valid & ready_for_stream_out:
                cycles_since_launch = 0
        elif cycles_since_launch > 0:
            cycles_since_launch += 1

        if cycles_since_launch == 0:
            o.ready_for_stream_in = 1
            if stream_in.valid & o.ready_for_stream_in:
                launch = stream_in.data
                cycles_since_launch = 1

        capture = capture_next
        return o

    return func_mcp, func_mcp_t
