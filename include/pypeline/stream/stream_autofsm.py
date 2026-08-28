# pyright: reportInvalidTypeForm=none
from pypeline import (
    struct,
    NamedTuple,
    uint1_t,
    hw_func,
    Reg,
    AUTOFSM,
    is_hw_func,
)

from stream.stream import make_stream_interface


def make_stream_autofsm(func, max_latency=None):
    """Wraps a pure combinational hardware function in an AUTOFSM instance plus a
    registered-output valid/ready handshake, exposing it as a stream interface --
    the AUTOFSM equivalent of make_stream_pipeline (AUTOPIPELINE) and
    make_valid_ready_mcp (MULTI_CYCLE[...]).

    AUTOFSM's own call-site contract has no backpressure: a `valid` pulse
    asserted while the FSM is busy is IGNORED, and the result itself is only a
    ONE-CYCLE `valid` pulse -- callers must hand-roll a `busy` register and
    space requests at least `.latency` cycles apart (see the AUTOFSM class
    docstring in pypeline.py). This wrapper does that bookkeeping once: a
    holding register latches the FSM's pulse and a `busy` register tracks
    in-flight state, so `stream_in_if.ready` and `stream_out_if.stream.valid`
    behave like any other stream port -- including real backpressure (a result
    is held, not dropped, while the downstream `ready` is low).

    The wrapper disables AUTOFSM's own optional result bank because the
    backpressure holding register below already provides that boundary. This
    leaves exactly one full-width output bank instead of registering every
    result twice.

    `func` must already be @hw_func-decorated, with a single annotated parameter and
    an annotated return type, e.g.:
        @hw_func
        def blob(x: blob_in_t) -> int16_t: ...

    Returns (func_autofsm, func_autofsm_t):
        func_autofsm(stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t) -> func_autofsm_t
        func_autofsm_t fields: .stream_in_if (in_intrf.fb_t), .stream_out_if (out_intrf.fwd_t)

    Latency (input accepted -> `stream_out_if.stream.valid` pulse) and
    initiation interval are both `FSM.latency + 1` -- one cycle more than the
    raw AUTOFSM FSM, spent latching its pulse into the holding register. The
    body never reads `.latency` (unlike the raw call site's manual spacing):
    it degrades to a correct 1-cycle-latency, 1-cycle-II stream when no
    schedule is installed (.latency == 0, i.e. --comb / native sim / bootstrap
    pass), and is exactly the same generated RTL in every mode -- which keeps
    canonical entity-name hashing stable across passes exactly as it must for
    AUTOPIPELINE/AUTOFSM call sites elsewhere (see docs/AUTOFSM_DESIGN.md and
    the "CONSTRUCTION TIMING MATTERS" note on AUTOFSM itself).
    """
    if not is_hw_func(func):
        raise TypeError(
            f"make_stream_autofsm(func, ...): {func.__qualname__!r} must be "
            f"@hw_func-decorated before being passed in"
        )
    # The holding register below is already the stream's output boundary.
    # Asking raw AUTOFSM for another full-width output register would only
    # duplicate storage and add muxing; expose its final-state value directly.
    fsm = AUTOFSM(func, max_latency=max_latency, register_output=False)

    in_intrf = make_stream_interface(fsm.in_type)
    out_intrf = make_stream_interface(fsm.out_type)

    @struct
    class func_autofsm_t(NamedTuple):
        stream_in_if: in_intrf.fb_t  # input port's reverse half travels out
        stream_out_if: out_intrf.fwd_t  # output port's feedforward half travels out

    @hw_func
    def func_autofsm(
        stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t
    ) -> func_autofsm_t:
        o: func_autofsm_t

        result: Reg[fsm.out_type]  # holds the FSM's one-cycle valid pulse
        result_valid: Reg[uint1_t]
        busy: Reg[uint1_t]

        # Output side first, for the same-cycle output/input handshake (the
        # make_valid_ready_mcp trick): clearing result_valid here is visible
        # to the accept decision below in the same cycle.
        o.stream_out_if.stream.data = result
        o.stream_out_if.stream.valid = result_valid
        if result_valid & stream_out_if.ready:
            result_valid = 0

        # Accept only when the FSM is idle AND the output slot is free.
        o.stream_in_if.ready = ~busy & ~result_valid
        s: fsm.in_stream_t
        s.data = stream_in_if.stream.data
        s.valid = stream_in_if.stream.valid & o.stream_in_if.ready
        f = fsm(s)
        if s.valid:
            busy = 1

        # Written after the accept block, so at latency 0 (passthrough) this
        # clear -- driven by f.valid, itself combinationally s.valid there --
        # wins over the `busy = 1` write above in the same cycle.
        if f.valid:
            result = f.data
            result_valid = 1
            busy = 0

        return o

    func_autofsm.fsm = fsm
    func_autofsm.latency = fsm.latency + 1
    func_autofsm.in_intrf = in_intrf
    func_autofsm.out_intrf = out_intrf
    func_autofsm.in_fwd_t = in_intrf.fwd_t
    func_autofsm.in_fb_t = in_intrf.fb_t
    func_autofsm.out_fwd_t = out_intrf.fwd_t
    func_autofsm.out_fb_t = out_intrf.fb_t
    return func_autofsm, func_autofsm_t
