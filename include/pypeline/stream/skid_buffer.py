# pyright: reportInvalidTypeForm=none
"""Skid buffers / register slices for a valid-ready stream.

The pypeline answer to old PipelineC's `SKID_BUF(type, name)` macro
(`include/stream/stream.h:41-101`), whose own comment states the purpose:
"to skid to a stop while avoiding a comb. path from `ready_for_stream_out` ->
`ready_for_stream_in`". There was no pypeline equivalent, so a design needing
to cut a timing path on a stream had to drop in a whole `make_stream_fifo` or
hand-roll registers.

A skid buffer is not a FIFO. Its job is to break combinational paths through a
stream port while still sustaining one beat per cycle -- which is exactly why
it needs *two* storage slots when both directions are cut: one slot to present
downstream, one to catch the beat already accepted upstream when the consumer
stalls. `mode` picks which paths get cut, using the same vocabulary as Xilinx's
AXI Register Slice `REG_CONFIG`:

    mode        slots  latency  throughput                   cuts
    "full"        2       1     100%                         data/valid AND ready
    "forward"     1       1     100%                         data/valid only
    "reverse"     1       0     100% steady, 1 stall bubble   ready only
    "bypass"      0       0     100%                         nothing (pure wires)

The one-slot modes each leave one path combinational, and that is the whole
trade: with a single slot, `ready` can only be a pure function of registers if
the buffer refuses input while draining, which costs one bubble to recover from
a stall. Full throughput with *both* paths cut needs two slots -- `"full"`.

Note what `"full"` is NOT: `axi/axis.py`'s `dwidth_widen`/`dwidth_narrow` are
also two-register 100%-throughput buffers, but they clear registers *before*
deriving `o.<in>_if.ready`, so `stream_out_if.ready` still reaches
`o.stream_in_if.ready` combinationally. They are elastic buffers, not register
slices. `"full"` here deliberately derives both outputs from registers only,
before any clear or write, which is what makes it fully registered in both
directions -- see the comment in its body.
"""
from pypeline import NamedTuple, Reg, hw_func, struct, uint1_t

from interface.interface import is_interface
from stream.serdes_common import check_choice
from stream.stream import make_stream_interface

# Which combinational paths through the stream port the slice cuts.
SKID_MODES = ("full", "forward", "reverse", "bypass")

# Storage slots and added (unstalled) latency per mode -- exposed on the
# returned function so a caller sizing a pipeline never has to re-derive them.
_MODE_SLOTS = {"full": 2, "forward": 1, "reverse": 1, "bypass": 0}
_MODE_LATENCY = {"full": 1, "forward": 1, "reverse": 0, "bypass": 0}


def make_skid_buffer(data_t_or_intrf, mode: str = "full"):
    """A skid buffer / register slice over one valid-ready stream.

    `data_t_or_intrf` is either a plain payload type -- in which case the stream
    interface is built here, the `stream/` house style (cf. `make_stream_fifo`)
    -- or an already-built `@interface`, the `axi/` house style (cf.
    `make_axis_broadcast_interlock`). Accepting an interface is not just
    convenience: `interface_func.callee_ports` compares interfaces by Python
    identity, so a caller who already built an `axis_intrf` must be able to hand
    in *that object* rather than a canonically-equal twin.

    Known limitation, in the compiler rather than here: passing an *interface*
    for two different payload widths in one design makes VHDL writing fail with
    "Cant support this assignment in vhdl?", because the result struct resolves
    to two different canonical names for the same Python class. It is not
    specific to this module -- `make_axis_broadcast_interlock` at two widths in
    one design fails identically. Passing the payload TYPE instead (the
    `data_t` form above) is unaffected, and is the workaround if a design needs
    several widths and does not need `@interface_func` port identity. Reproducer
    and full write-up:
    `src/tests/pypeline_tests/inst/interface_factory_two_widths_known_issue.py`.

    `mode` is one of "full" (the default), "forward", "reverse" or "bypass" --
    see this module's docstring for what each cuts and costs. "full" is the
    default because it is the one that cuts every path in both directions at
    full throughput: a caller who reaches for a skid buffer because of a timing
    problem gets the thing that actually fixes it.

    Returns (skid_buffer, skid_buffer_t):
        skid_buffer(stream_in_if: stream_intrf.fwd_t, stream_out_if: stream_intrf.fb_t)
            -> skid_buffer_t
        skid_buffer_t fields: .stream_out_if (stream_intrf.fwd_t),
                              .stream_in_if  (stream_intrf.fb_t)
    attrs: .stream_intrf .fwd_t .fb_t .data_t .mode .n_slots .latency
    """
    check_choice("make_skid_buffer", "mode", mode, SKID_MODES)

    if is_interface(data_t_or_intrf):
        stream_intrf = data_t_or_intrf
    else:
        stream_intrf = make_stream_interface(data_t_or_intrf)
    data_t = stream_intrf.stream_t.typeof("data")

    @struct
    class skid_buffer_t(NamedTuple):
        stream_out_if: stream_intrf.fwd_t
        stream_in_if: stream_intrf.fb_t

    # One whole @hw_func body per mode, under a factory-time `if` -- not one
    # body with internal branching. Required, not stylistic: Reg[T]
    # declarations are only picked up as state when they are top-level
    # statements of the function body, so the register set cannot vary inside
    # a single body. Same reason as `type_axis.py`'s registered_ready split.
    if mode == "full":

        @hw_func
        def skid_buffer(
            stream_in_if: stream_intrf.fwd_t, stream_out_if: stream_intrf.fb_t
        ) -> skid_buffer_t:
            o: skid_buffer_t
            buf: Reg[stream_intrf.stream_t]
            skid: Reg[stream_intrf.stream_t]
            out_is_skid: Reg[uint1_t]

            # Both outputs are derived from REGISTERS ONLY, before any clear or
            # write below. That ordering is the whole point of this mode: it is
            # what keeps stream_out_if.ready out of o.stream_in_if.ready, and
            # stream_in_if out of o.stream_out_if. (dwidth_widen/dwidth_narrow
            # deliberately do the opposite and are not register slices.)
            outw: stream_intrf.stream_t = buf
            ready_in: uint1_t = ~skid.valid
            if out_is_skid:
                outw = skid
                ready_in = ~buf.valid
            o.stream_out_if.stream = outw
            o.stream_in_if.ready = ready_in

            # An accepted input fills whichever buffer is NOT being presented...
            if stream_in_if.stream.valid & ready_in:
                if out_is_skid:
                    buf = stream_in_if.stream
                else:
                    skid = stream_in_if.stream

            # ...and the presented one is cleared and swapped away from once
            # drained (or if it was empty anyway), so the two `if`s never touch
            # the same register in the same cycle.
            if ~outw.valid | stream_out_if.ready:
                if out_is_skid:
                    skid.valid = 0
                else:
                    buf.valid = 0
                out_is_skid = ~out_is_skid

            return o

    elif mode == "forward":

        @hw_func
        def skid_buffer(
            stream_in_if: stream_intrf.fwd_t, stream_out_if: stream_intrf.fb_t
        ) -> skid_buffer_t:
            o: skid_buffer_t
            buf: Reg[stream_intrf.stream_t]

            o.stream_out_if.stream = buf
            # Combinational from the downstream ready: this mode cuts the
            # data/valid paths only, in exchange for a single slot.
            o.stream_in_if.ready = ~buf.valid | stream_out_if.ready
            if o.stream_in_if.ready:
                # An invalid input just clears buf -- no separate empty case.
                buf = stream_in_if.stream

            return o

    elif mode == "reverse":

        @hw_func
        def skid_buffer(
            stream_in_if: stream_intrf.fwd_t, stream_out_if: stream_intrf.fb_t
        ) -> skid_buffer_t:
            o: skid_buffer_t
            skid: Reg[stream_intrf.stream_t]

            # A pure function of the register -- the cut this mode makes. It is
            # also why one bubble is needed to recover from a stall: while skid
            # drains, ready is already low for this cycle.
            o.stream_in_if.ready = ~skid.valid

            # Data/valid bypass combinationally whenever the slot is empty.
            outw: stream_intrf.stream_t = stream_in_if.stream
            if skid.valid:
                outw = skid
            o.stream_out_if.stream = outw

            if outw.valid & stream_out_if.ready:
                skid.valid = 0
            elif stream_in_if.stream.valid & o.stream_in_if.ready:
                # Stalled downstream, but ready was already asserted upstream --
                # catch the beat that was accepted anyway. This is the "skid".
                skid = stream_in_if.stream

            return o

    else:  # "bypass"

        @hw_func
        def skid_buffer(
            stream_in_if: stream_intrf.fwd_t, stream_out_if: stream_intrf.fb_t
        ) -> skid_buffer_t:
            o: skid_buffer_t
            o.stream_out_if.stream = stream_in_if.stream
            o.stream_in_if.ready = stream_out_if.ready
            return o

    skid_buffer.stream_intrf = stream_intrf
    skid_buffer.fwd_t = stream_intrf.fwd_t
    skid_buffer.fb_t = stream_intrf.fb_t
    skid_buffer.data_t = data_t
    skid_buffer.mode = mode
    skid_buffer.n_slots = _MODE_SLOTS[mode]
    skid_buffer.latency = _MODE_LATENCY[mode]
    return skid_buffer, skid_buffer_t
