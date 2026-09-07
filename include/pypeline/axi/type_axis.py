# pyright: reportInvalidTypeForm=none
"""Struct/value stream <-> AXI-Stream frames. The pypeline replacement for old
PipelineC's `axis_packet_to_type`, `axis_to_type`, `type_to_axis` and
`axis_max_len_limiter` (`include/axi/axis.h:515-655`).

This is the thin framing layer over `stream/type_byte_stream.py`: that module
already turns values into keep-tagged byte beats and back, and an AXIS stream
*is* that beat stream (`make_axis_interface` composes the same
kept_data_bus -> ndarray_fragment -> stream types, with `eod[0]` as tlast). So
what is left here is packet policy -- how many values live in one frame, and
what happens at a frame boundary.

Two framing modes, both of which the old code wanted and only one of which it
actually shipped:

  frame="one_per_packet"   One value per frame, with a length limiter that
      drops anything a frame carries past `byte_length(t)`. This is old
      `axis_packet_to_type`, and the limiter is there for a real reason:
      Ethernet pads frames to a 60-byte minimum, so without it a struct smaller
      than the minimum frame leaves trailing pad bytes in the deserializer and
      desyncs every value after it.

  frame="many_per_packet"  Values packed back-to-back inside one frame, tlast
      only at the end. This is old `axis_to_type`, which shipped `#if 0`'d out
      (`axis.h:598`) because its signature was never updated in the stream
      refactor -- it declared `axis##axis_bits##_t payload` while its body read
      `payload.data.tdata[i]`/`payload.valid`. Here it is a first-class mode.

Defects in `axis.h` fixed here, each with a named regression test in
`src/tests/pypeline_tests/inst/axis_max_len_limiter_test.py` or
`type_axis_test.py`:

  L527  `max_byte_len - (axis_bits/8)` on an unsigned counter UNDERFLOWS when
        the type is smaller than one bus word, wrapping to ~65534 so the
        limiter silently never limits. This module never computes that
        subtraction -- it compares forward, `counter + n_kept >= max_bytes`.
  L527  the same expression assumed `max_byte_len` was a whole multiple of the
        bus width, since it tested `counter == last_word_limit`; a non-multiple
        stepped straight over it. Fixed by comparing with `>=`.
  L539  forced tlast was not qualified by valid, so tlast could appear on an
        invalid beat (and did, via `type_to_axis` at L653).
  L539  tkeep was left untouched when truncating, so the beat that hit the
        limit still claimed every byte was real. Fixed per lane.
  L587  `axis_packet_to_type` ignored tkeep entirely for data, shifting all
        bus bytes in regardless. Handled in `stream/deserializer.py`.
  L650  `type_to_axis` hardcoded tkeep all-ones, making a partial final beat
        inexpressible. Now it comes from the serializer's real fill count.
"""
from pypeline import (
    Feedback,
    NamedTuple,
    Reg,
    hw_func,
    make_uint_t,
    struct,
    uint1_t,
    uint8_t,
    byte_length,
)

from axi.axis import make_axis_interface
from ndarray import make_ndarray_fragment_t
from stream.serdes_common import check_choice
from stream.stream import make_stream_interface
from stream.type_byte_stream import (
    make_byte_stream_to_type,
    make_type_to_byte_stream,
)

FRAME_MODES = ("one_per_packet", "many_per_packet")


def make_axis_max_len_limiter(axis_intrf, n, max_bytes):
    """Truncate every frame to at most `max_bytes` bytes, forcing eod there.

    Purely combinational passthrough plus a byte counter -- no buffering, no
    latency, and `ready` passes straight through while below the limit. Bytes
    above the limit are dropped (accepted and discarded, so the producer is
    never stalled by them) and the counter resets on both a real and a forced
    end-of-frame, so the next frame is limited identically.

    Returns (axis_max_len_limiter, axis_max_len_limiter_t):
        axis_max_len_limiter(axis_in_if: axis_intrf.fwd_t,
                             axis_out_if: axis_intrf.fb_t) -> ..._t
        fields: .axis_out_if (fwd), .axis_in_if (fb)
    """
    if not (isinstance(max_bytes, int) and max_bytes >= 1):
        raise ValueError(
            f"make_axis_max_len_limiter: max_bytes must be a positive int, got {max_bytes!r}"
        )
    # Wide enough for the counter to reach max_bytes + one whole beat without
    # wrapping (sized from the real bound, not the old hardcoded uint16_t).
    count_t = make_uint_t(max(1, (max_bytes + n).bit_length()))

    @struct
    class axis_max_len_limiter_t(NamedTuple):
        axis_out_if: axis_intrf.fwd_t
        axis_in_if: axis_intrf.fb_t

    @hw_func
    def axis_max_len_limiter(
        axis_in_if: axis_intrf.fwd_t, axis_out_if: axis_intrf.fb_t
    ) -> axis_max_len_limiter_t:
        o: axis_max_len_limiter_t
        counter: Reg[count_t]  # bytes of this frame already passed through

        below: uint1_t = counter < max_bytes

        outw: axis_intrf.stream_t = axis_in_if.stream
        n_kept: count_t = 0
        for i in range(n):
            # Lane i sits at frame offset counter + i, because keep is a
            # contiguous prefix. Data on dropped lanes is zeroed so an
            # unwritten value can never leak (and so GHDL's 'U' and native
            # sim's 0 agree in a cycle-by-cycle diff).
            keep_i: uint1_t = axis_in_if.stream.data.frag.keep[i] & (
                (counter + i) < max_bytes
            )
            outw.data.frag.keep[i] = keep_i
            outw.data.frag.data[i] = 0
            if keep_i:
                outw.data.frag.data[i] = axis_in_if.stream.data.frag.data[i]
            n_kept = n_kept + keep_i

        at_limit: uint1_t = (counter + n_kept) >= max_bytes
        outw.data.eod[0] = axis_in_if.stream.data.eod[0] | at_limit
        # eod is only ever observable under valid -- axis.h:539 forced it
        # unconditionally, so it could sit high on an invalid beat.
        outw.valid = axis_in_if.stream.valid & below
        o.axis_out_if.stream = outw

        # Above the limit, accept-and-drop rather than backpressure.
        o.axis_in_if.ready = 1
        if below:
            o.axis_in_if.ready = axis_out_if.ready

        if axis_in_if.stream.valid & o.axis_in_if.ready:
            counter = counter + n_kept
            # Reset ONLY at the real end of the frame, never on the forced eod:
            # once the limit is hit the counter must STAY at/above max_bytes so
            # `below` keeps dropping the rest of this frame. Resetting here
            # would re-arm the limiter mid-frame, and the trailing padding
            # would be decoded as a whole second value -- which is precisely
            # the Ethernet-min-frame case the limiter exists to prevent.
            if axis_in_if.stream.data.eod[0]:
                counter = 0
        return o

    axis_max_len_limiter.axis_intrf = axis_intrf
    axis_max_len_limiter.n = n
    axis_max_len_limiter.max_bytes = max_bytes
    return axis_max_len_limiter, axis_max_len_limiter_t


def make_axis_to_type(
    out_t,
    n,
    frame="one_per_packet",
    on_runt="discard",
    endian="little",
    registered_ready=False,
    check_keep=True,
):
    """AXI-Stream frames -> a stream of `out_t` values.

    frame="one_per_packet" (default): exactly one value per frame; a length
        limiter drops anything past byte_length(out_t) (Ethernet min-frame
        padding, the original motivation for old axis_packet_to_type).
    frame="many_per_packet": values packed back-to-back within a frame, tlast
        only at the end -- old axis_to_type, which never shipped working.

    on_runt: what a frame that ends mid-value does -- "discard" (default,
        resync and pulse .runt), "zero_pad" (emit it zero-filled, pulse .runt),
        or "ignore" (carry the residue, reproducing the old permanent desync).

    Returns (axis_to_type, axis_to_type_t):
        axis_to_type(axis_in_if: axis_intrf.fwd_t,
                     stream_out_if: out_intrf.fb_t) -> axis_to_type_t
        fields: .stream_out_if (values), .axis_in_if (reverse half of the AXIS
                port), .runt (uint1_t)
        attrs: .axis_intrf .out_intrf .axis_fb_t .out_fb_t .t .n_bytes .n
    """
    check_choice("make_axis_to_type", "frame", frame, FRAME_MODES)
    n_bytes = byte_length(out_t)
    limited = frame == "one_per_packet"

    rx, rx_t = make_byte_stream_to_type(
        out_t,
        n,
        endian=endian,
        align="beat" if limited else "packed",
        on_eod=on_runt,
        registered_ready=registered_ready,
        check_keep=check_keep,
    )
    axis_intrf = rx.in_intrf  # already an AXIS interface: n lanes of uint8_t
    out_intrf = rx.out_intrf
    if limited:
        limiter, limiter_t = make_axis_max_len_limiter(axis_intrf, n, n_bytes)

    @struct
    class axis_to_type_t(NamedTuple):
        stream_out_if: out_intrf.fwd_t
        axis_in_if: axis_intrf.fb_t
        runt: uint1_t

    # Two whole function bodies rather than one with a factory-time `if`:
    # the limited path declares a Feedback[uint1_t], and Reg[T]/Feedback[T]
    # declarations are only picked up as state when they are TOP-LEVEL
    # statements of the function body (pypeline._build_reg_sim_func scans
    # `func_def.body`, not nested blocks). Same shape as dsp/fir.py's
    # elastic/valid-only split.
    if limited:

        @hw_func
        def axis_to_type(
            axis_in_if: axis_intrf.fwd_t, stream_out_if: out_intrf.fb_t
        ) -> axis_to_type_t:
            o: axis_to_type_t
            # The limiter's forward output feeds the deserializer, whose ready
            # feeds the limiter's ready -- a genuine circular reference between
            # two call results, and exactly what axis.h:571 needed
            # FEEDBACK(ready_for_limter_out) for. The feedback carries the bare
            # ready bit (an interface half may not be a plain local), wrapped
            # with .fb_t() at the call site.
            ready_for_limiter: Feedback[uint1_t]
            lim = limiter(axis_in_if, axis_intrf.fb_t(ready_for_limiter))
            r = rx(axis_intrf.fwd_t(lim.axis_out_if.stream), stream_out_if)
            ready_for_limiter = r.stream_in_if.ready
            o.stream_out_if = r.stream_out_if
            o.axis_in_if.ready = lim.axis_in_if.ready
            o.runt = r.runt
            return o

    else:

        @hw_func
        def axis_to_type(
            axis_in_if: axis_intrf.fwd_t, stream_out_if: out_intrf.fb_t
        ) -> axis_to_type_t:
            o: axis_to_type_t
            r = rx(axis_in_if, stream_out_if)
            o.stream_out_if = r.stream_out_if
            o.axis_in_if.ready = r.stream_in_if.ready
            o.runt = r.runt
            return o

    axis_to_type.axis_intrf = axis_intrf
    axis_to_type.out_intrf = out_intrf
    axis_to_type.axis_fb_t = axis_intrf.fb_t
    axis_to_type.out_fb_t = out_intrf.fb_t
    axis_to_type.t = out_t
    axis_to_type.n_bytes = n_bytes
    axis_to_type.n = n
    return axis_to_type, axis_to_type_t


def make_type_to_axis(
    in_t, n, frame="one_per_packet", endian="little", structs_per_packet=None
):
    """A stream of `in_t` values -> AXI-Stream frames.

    frame="one_per_packet" (default): every value gets its own frame; tlast
        lands on that value's final beat, whose tkeep carries the real byte
        count (byte_length(in_t) % n, or n) rather than the hardcoded all-ones
        of axis.h:650.
    frame="many_per_packet": values concatenate into one frame. End it either
        by driving `stream_in_if.stream.data.eod[0]` on the last value, or by
        passing structs_per_packet=k to have an internal mod-k counter do it.

    Returns (type_to_axis, type_to_axis_t):
        type_to_axis(stream_in_if: in_intrf.fwd_t,
                     axis_out_if: axis_intrf.fb_t) -> type_to_axis_t
        fields: .axis_out_if (fwd), .stream_in_if (fb)
        attrs: .in_intrf .axis_intrf .in_fb_t .axis_fb_t .t .n_bytes .n
    """
    check_choice("make_type_to_axis", "frame", frame, FRAME_MODES)
    per_value = frame == "one_per_packet"
    if structs_per_packet is not None:
        if per_value:
            raise ValueError(
                "make_type_to_axis: structs_per_packet only applies to "
                "frame='many_per_packet' (one_per_packet is one struct by definition)"
            )
        if not (isinstance(structs_per_packet, int) and structs_per_packet >= 1):
            raise ValueError(
                "make_type_to_axis: structs_per_packet must be a positive int, "
                f"got {structs_per_packet!r}"
            )

    tx, tx_t = make_type_to_byte_stream(
        in_t, n, endian=endian, align="beat" if per_value else "packed"
    )
    in_intrf = make_stream_interface(make_ndarray_fragment_t(in_t, 1))
    axis_intrf = tx.out_intrf
    counted = structs_per_packet is not None
    count_t = make_uint_t(max(1, (structs_per_packet or 1).bit_length()))

    @struct
    class type_to_axis_t(NamedTuple):
        axis_out_if: axis_intrf.fwd_t
        stream_in_if: in_intrf.fb_t

    @hw_func
    def type_to_axis(
        stream_in_if: in_intrf.fwd_t, axis_out_if: axis_intrf.fb_t
    ) -> type_to_axis_t:
        o: type_to_axis_t
        n_in_packet: Reg[count_t]

        tx_in: tx.in_intrf.stream_t
        tx_in.data.frag = stream_in_if.stream.data.frag
        tx_in.valid = stream_in_if.stream.valid
        if per_value:
            # align="beat" ends a packet per value regardless, but say so
            # explicitly rather than relying on the layer below.
            tx_in.data.eod[0] = 1
        else:
            if counted:
                tx_in.data.eod[0] = n_in_packet == (structs_per_packet - 1)
            else:
                tx_in.data.eod[0] = stream_in_if.stream.data.eod[0]

        r = tx(tx.in_intrf.fwd_t(tx_in), axis_out_if)
        o.axis_out_if = r.stream_out_if
        o.stream_in_if.ready = r.stream_in_if.ready

        if counted:
            if stream_in_if.stream.valid & r.stream_in_if.ready:
                if n_in_packet == (structs_per_packet - 1):
                    n_in_packet = 0
                else:
                    n_in_packet = n_in_packet + 1
        return o

    type_to_axis.in_intrf = in_intrf
    type_to_axis.axis_intrf = axis_intrf
    type_to_axis.in_fb_t = in_intrf.fb_t
    type_to_axis.axis_fb_t = axis_intrf.fb_t
    type_to_axis.t = in_t
    type_to_axis.n_bytes = byte_length(in_t)
    type_to_axis.n = n
    return type_to_axis, type_to_axis_t
