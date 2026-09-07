# pyright: reportInvalidTypeForm=none
"""Byte/element-stream -> value deserializer: gathers `out_n` elements out of a
keep-tagged `in_n`-lane input stream. The pypeline replacement for old
PipelineC's `deserializer_in_to_out` / `deserializer` (`include/stream/
deserializer.h`).

Structure -- a fill-index elastic buffer, not the old shift register:

    buf:  Reg[elem_t[buf_n]]   buf_n = in_n + out_n - 1
    fill: Reg[count_t]         elements currently held

    output = the bottom out_n elements       valid <=> fill >= out_n
    input  lands at buf[fill + i]            ready <=> next_fill < out_n

Three things that differ from the old macro, all deliberate:

1. **Bubble-free.** The old `in_data_ready = !out_buffer_valid`
   (`deserializer.h:22`) forbids accepting a beat on the same cycle an output
   drains, costing one cycle per output word -- throughput n/(n+1), which
   *halves* throughput when a value is one beat wide (a 4-byte struct on a
   4-byte bus, a very common case for this library). Nothing requires it: the
   output is a combinational read of the *current* register while the input
   write is next-state, so both can happen in one cycle. That is the same
   elastic idiom `axi/axis.py`'s `make_dwidth_narrow` and `dsp/fir.py` already
   use. The cost is a combinational `stream_out_if.ready -> stream_in_if.ready`
   path -- the very path the old *serializer* had, and what made it, but not the
   deserializer, bubble-free. `registered_ready=True` restores the old
   behaviour for a design that needs that path broken.

2. **Non-divisible sizes work.** `out_n % in_n != 0` silently deadlocked the old
   macro (`deserializer.h:41` tests `out_counter==OUT_SIZE`, which the counter
   steps straight over). Here a partial beat is just a beat whose `keep` says
   how many lanes are real. `padding="exact"` rejects the case at factory-call
   time instead, for a design that wants the constraint enforced.

3. **End-of-data is handled.** The old `axis_packet_to_type` never touched the
   deserializer on `tlast`, so a runt packet left partial elements in the buffer
   and the *next* packet completed them -- permanently desyncing the value
   boundary with no error. `on_eod` makes that an explicit choice.

Why the lane writes are unconditional
-------------------------------------
`keep` is a contiguous prefix (Xilinx-style AXIS -- full keep on every beat but
the last, and a prefix on that one; `make_axis_byte_sink` already asserts this,
and so does this module). Under that invariant kept lane `i` sits at buffer
offset `nbase + i` regardless of how many lanes are kept, so the write needs no
per-lane mux -- only the *count* is conditional. That is what avoids an
in_n-way barrel shifter.

The `in_n - n_kept` garbage elements written above `nbase + n_kept` are never
read: if another beat follows, it writes over the whole garbage region (its
`in_n` lanes start at `nbase + n_kept`); if none follows, the value completed,
so `nbase + n_kept >= out_n` and every garbage element sits at an index at or
above out_n -- outside the `buf[0:out_n]` output window. This is precisely why
`buf_n` is `in_n + out_n - 1` and not `out_n`.
"""
from pypeline import (
    NamedTuple,
    Reg,
    hw_func,
    sim_assert,
    struct,
    uint1_t,
)

from axi.axis import make_axis_interface
from ndarray import make_ndarray_fragment_t
from stream.serdes_common import (
    ALIGN_MODES,
    ON_EOD_MODES,
    buffer_len,
    check_choice,
    check_padding,
    check_sizes,
    counter_t,
)
from stream.stream import make_stream_interface


def make_deserializer(
    elem_t,
    in_n,
    out_n,
    align="beat",
    on_eod="discard",
    padding="pad",
    registered_ready=False,
    check_keep=True,
):
    """Gather `out_n` elements of `elem_t` from an `in_n`-lane keep-tagged stream.

    align:
      "beat"    each value starts on a fresh beat boundary; elements left over
                in the buffer after a value drains are dropped. This is what a
                sender that pads each value out to whole beats produces, and
                the mode `make_axis_to_type(frame="one_per_packet")` uses.
      "packed"  values run back-to-back through the byte stream; leftover
                elements are shifted down and start the next value. Needed when
                several values share one packet.

    on_eod: what to do with a partial value when the input asserts eod[0]:
      "discard"   drop the residue, resync to a value boundary, pulse `.runt`
                  (default -- a truncated packet must not corrupt the next one)
      "zero_pad"  zero-fill the partial value, emit it, and pulse `.runt`
      "ignore"    carry the residue into the next packet. Reproduces the old
                  `axis_packet_to_type` behaviour, where one runt packet
                  permanently desyncs the value boundary; here only so a test
                  can demonstrate it.

    padding:  "pad" (default) allows out_n % in_n != 0, with the final beat's
              `keep` carrying the true element count; "exact" rejects it at
              factory-call time.
    registered_ready: break the combinational ready path, at one bubble cycle
              per output value (the old macro's behaviour).
    check_keep: emit the contiguous-prefix `keep` assertions (see the module
              docstring -- the correctness of the unconditional lane writes
              rests on that invariant). Costs nothing in synthesis.

    Returns (deserializer, deserializer_t):
        deserializer(stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t)
            -> deserializer_t
        deserializer_t fields:
          .stream_out_if (out_intrf.fwd_t) - gathered values, eod[0] marking the
             value that ended a packet
          .stream_in_if  (in_intrf.fb_t)   - reverse half of the input port
          .runt (uint1_t) - pulses when eod[0] arrived mid-value
        attrs: .in_intrf .out_intrf .in_fb_t .out_fb_t .elem_t .in_n .out_n
    """
    check_sizes("make_deserializer", in_n, out_n)
    check_choice("make_deserializer", "align", align, ALIGN_MODES)
    check_choice("make_deserializer", "on_eod", on_eod, ON_EOD_MODES)
    check_padding("make_deserializer", padding, in_n, out_n, "out_n")

    in_intrf = make_axis_interface(in_n, elem_t)
    out_intrf = make_stream_interface(make_ndarray_fragment_t(elem_t[out_n], 1))

    buf_n = buffer_len(in_n, out_n)
    buf_t = elem_t[buf_n]
    count_t = counter_t(in_n, out_n)
    packed = align == "packed"
    # How far a completed value can leave the buffer filled, in packed mode.
    max_values_held = buf_n // out_n

    @struct
    class deserializer_t(NamedTuple):
        stream_out_if: out_intrf.fwd_t
        stream_in_if: in_intrf.fb_t
        runt: uint1_t

    @hw_func
    def deserializer(
        stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t
    ) -> deserializer_t:
        o: deserializer_t
        buf: Reg[buf_t]
        fill: Reg[count_t]
        eod_held: Reg[uint1_t]

        # Outputs are read from the CURRENT register state, before any
        # next-state write below -- that is what lets a drain and an accept
        # share a cycle.
        cur_fill: count_t = fill
        outw: out_intrf.stream_t
        for i in range(out_n):
            outw.data.frag[i] = buf[i]
        outw.data.eod[0] = eod_held
        outw.valid = cur_fill >= out_n
        o.stream_out_if.stream = outw
        o.runt = 0

        drained: uint1_t = outw.valid & stream_out_if.ready
        nbase: count_t = cur_fill
        if drained:
            if packed:
                for i in range(buf_n - out_n):
                    buf[i] = buf[i + out_n]
                nbase = cur_fill - out_n
            else:
                # "beat": whatever is left over belonged to the padding of the
                # value just emitted, so the next value starts clean.
                nbase = 0
            eod_held = 0

        if registered_ready:
            o.stream_in_if.ready = cur_fill < out_n
        else:
            o.stream_in_if.ready = nbase < out_n

        if stream_in_if.stream.valid & o.stream_in_if.ready:
            n_kept: count_t = 0
            for i in range(in_n):
                # Unconditional: contiguous-prefix keep puts kept lane i at
                # nbase + i, and the unkept remainder is provably never read.
                buf[nbase + i] = stream_in_if.stream.data.frag.data[i]
                n_kept = n_kept + stream_in_if.stream.data.frag.keep[i]
            if check_keep:
                sim_assert(
                    (n_kept == in_n) | stream_in_if.stream.data.eod[0],
                    "deserializer: partial-keep beat without eod (embedded holes)",
                )
                for i in range(in_n):
                    sim_assert(
                        stream_in_if.stream.data.frag.keep[i] == (i < n_kept),
                        "deserializer: keep is not a contiguous prefix",
                    )
            nbase = nbase + n_kept
            if stream_in_if.stream.data.eod[0]:
                if on_eod == "discard":
                    if nbase < out_n:
                        nbase = 0
                        o.runt = 1
                    else:
                        if packed:
                            # Keep only whole values; drop any trailing residue
                            # so the next packet starts on a value boundary.
                            kept: count_t = 0
                            for k in range(1, max_values_held + 1):
                                if nbase >= (k * out_n):
                                    kept = k * out_n
                            nbase = kept
                elif on_eod == "zero_pad":
                    if (nbase < out_n) & (nbase > 0):
                        for i in range(out_n):
                            if i >= nbase:
                                buf[i] = 0
                        nbase = out_n
                        o.runt = 1
                eod_held = 1
        fill = nbase
        return o

    deserializer.in_intrf = in_intrf
    deserializer.out_intrf = out_intrf
    deserializer.in_fb_t = in_intrf.fb_t
    deserializer.out_fb_t = out_intrf.fb_t
    deserializer.elem_t = elem_t
    deserializer.in_n = in_n
    deserializer.out_n = out_n
    return deserializer, deserializer_t
