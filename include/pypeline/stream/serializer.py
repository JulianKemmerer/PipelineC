# pyright: reportInvalidTypeForm=none
"""Value -> byte/element-stream serializer: emits an `in_n`-element value as
keep-tagged `out_n`-lane beats. The pypeline replacement for old PipelineC's
`serializer_in_to_out` / `serializer` (`include/stream/serializer.h`).

The exact mirror of `stream/deserializer.py` -- same fill-index elastic buffer,
same `buf_n = in_n + out_n - 1` sizing identity, same one-comparison `ready`.
Read that module's docstring for the structure; what follows is only what is
specific to the send direction.

Output beats carry `keep[i] = i < fill`, so a value whose length is not a
multiple of the bus width ends in a partial beat instead of deadlocking
(`serializer.h:42`'s `if(out_counter==IN_SIZE)` never fires when `IN_SIZE %
OUT_SIZE != 0`). **Padding lives in `keep`, never in the data** -- and the
unkept lanes' data is explicitly zeroed rather than left holding stale buffer
contents, because an unwritten register reads `'U'` in GHDL but `0` in native
simulation, which would show up as a spurious mismatch in any cycle-by-cycle
native-vs-VHDL diff.

Bugs in `serializer.h` fixed here, each covered by a named test in
`src/tests/pypeline_tests/inst/serdes_test.py`:

  L29  `out_last` computed from the counter alone, unqualified by validity, so
       `tlast` could sit high on an invalid beat (and did, once `type_to_axis`
       copied it straight to `tlast` at `axis.h:653`). Here `eod[0]` is only
       ever observable under `outw.valid`, and every state update is gated on
       `accepted_out` (= valid & ready).
  L35  `if(out_data_ready)` shifted the buffer and advanced the counter even
       with no data present -- masked only by an accident of the input block
       re-zeroing the counter in the same cycle.
  L51  `in_buffer = in_data` ran unconditionally whenever ready, clobbering the
       just-shifted buffer with whatever was on the input port.
  L42  non-divisible sizes deadlocked silently; see above.

One thing deliberately *kept* from the old macro: `ready` depends
combinationally on `stream_out_if.ready`, so the last beat of one value and the
load of the next happen in the same cycle. That is what makes the stream
bubble-free, and it is why the old serializer was fast while the old
deserializer (which lacked it) was not.
"""
from pypeline import (
    NamedTuple,
    Reg,
    hw_func,
    struct,
    uint1_t,
)

from axi.axis import make_axis_interface
from ndarray import make_ndarray_fragment_t
from stream.serdes_common import (
    ALIGN_MODES,
    buffer_len,
    check_choice,
    check_padding,
    check_sizes,
    counter_t,
)
from stream.stream import make_stream_interface


def make_serializer(elem_t, in_n, out_n, align="beat", padding="pad"):
    """Emit an `in_n`-element value as `out_n`-lane keep-tagged beats.

    align:
      "beat"    every accepted value ends its own packet: eod[0] is asserted on
                that value's final beat regardless of what the caller drives.
      "packed"  values concatenate into one packet; the caller ends it by
                driving eod[0] on the last value.

    padding:  "pad" (default) allows in_n % out_n != 0, the final beat's `keep`
              carrying the true element count; "exact" rejects it at
              factory-call time.

    Returns (serializer, serializer_t):
        serializer(stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t)
            -> serializer_t
        serializer_t fields:
          .stream_out_if (out_intrf.fwd_t) - the keep-tagged beat stream
          .stream_in_if  (in_intrf.fb_t)   - reverse half of the input port
        attrs: .in_intrf .out_intrf .in_fb_t .out_fb_t .elem_t .in_n .out_n
    """
    check_sizes("make_serializer", in_n, out_n)
    check_choice("make_serializer", "align", align, ALIGN_MODES)
    check_padding("make_serializer", padding, in_n, out_n, "in_n")

    in_intrf = make_stream_interface(make_ndarray_fragment_t(elem_t[in_n], 1))
    out_intrf = make_axis_interface(out_n, elem_t)

    buf_n = buffer_len(in_n, out_n)
    buf_t = elem_t[buf_n]
    count_t = counter_t(in_n, out_n)
    per_value_eod = align == "beat"

    @struct
    class serializer_t(NamedTuple):
        stream_out_if: out_intrf.fwd_t
        stream_in_if: in_intrf.fb_t

    @hw_func
    def serializer(
        stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t
    ) -> serializer_t:
        o: serializer_t
        buf: Reg[buf_t]
        fill: Reg[count_t]
        flush: Reg[uint1_t]  # an eod is owed once the buffer drains

        cur_fill: count_t = fill
        outw: out_intrf.stream_t
        for i in range(out_n):
            # Zero first, then overwrite the kept prefix: unkept lanes must
            # carry a defined value, not stale buffer contents (see docstring).
            outw.data.frag.data[i] = 0
            outw.data.frag.keep[i] = 0
            if i < cur_fill:
                outw.data.frag.data[i] = buf[i]
                outw.data.frag.keep[i] = 1
        outw.data.eod[0] = flush & (cur_fill <= out_n)
        outw.valid = (cur_fill >= out_n) | (flush & (cur_fill > 0))
        o.stream_out_if.stream = outw

        accepted_out: uint1_t = outw.valid & stream_out_if.ready
        nfill: count_t = cur_fill
        if accepted_out:
            for i in range(buf_n - out_n):
                buf[i] = buf[i + out_n]
            if cur_fill <= out_n:
                nfill = 0
                flush = 0
            else:
                nfill = cur_fill - out_n

        # Combinational on stream_out_if.ready via nfill -- deliberately; see
        # the module docstring. `& ~flush` stops a value being appended to a
        # packet that has already been told to end.
        o.stream_in_if.ready = (nfill < out_n) & ~flush
        if stream_in_if.stream.valid & o.stream_in_if.ready:
            for i in range(in_n):
                buf[nfill + i] = stream_in_if.stream.data.frag[i]
            nfill = nfill + in_n
            if per_value_eod:
                flush = 1
            else:
                if stream_in_if.stream.data.eod[0]:
                    flush = 1
        fill = nfill
        return o

    serializer.in_intrf = in_intrf
    serializer.out_intrf = out_intrf
    serializer.in_fb_t = in_intrf.fb_t
    serializer.out_fb_t = out_intrf.fb_t
    serializer.elem_t = elem_t
    serializer.in_n = in_n
    serializer.out_n = out_n
    return serializer, serializer_t
