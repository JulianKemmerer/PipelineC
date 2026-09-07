# pyright: reportInvalidTypeForm=none
"""Struct/value stream <-> byte stream. The pypeline replacement for old
PipelineC's `type_byte_serializer` / `type_byte_deserializer`
(`include/stream/serializer.h:60`, `include/stream/deserializer.h:51`).

Each direction is the corresponding base module from `stream/serializer.py` /
`stream/deserializer.py` with `make_type_to_bytes(t)` / `make_type_from_bytes(t)`
bolted on the value side -- exactly how the old macros were built, except that
the layout functions here are the same ones `pypeline.type_to_bytes()` uses in
software, so a host program and the hardware agree by construction rather than
by a separately generated C header staying in sync.

Sizing comes from `byte_length(t)`, the pypeline equivalent of the old flow's
`sizeof(out_t)` (`C_TO_LOGIC.C_TYPE_SIZE`): a packed, unpadded struct where
each leaf scalar rounds up to a whole byte. When that length is not a multiple
of the bus width the final beat is partial and its `keep` says so; nothing is
padded into the data. `padding="exact"` rejects the case up front instead.
"""
from pypeline import (
    NamedTuple,
    byte_length,
    hw_func,
    make_type_from_bytes,
    make_type_to_bytes,
    struct,
    uint1_t,
    uint8_t,
)

from ndarray import make_ndarray_fragment_t
from stream.deserializer import make_deserializer
from stream.serializer import make_serializer
from stream.stream import make_stream_interface


def make_type_to_byte_stream(
    t, out_n, endian="little", align="beat", padding="pad"
):
    """Stream of `t` values -> keep-tagged byte stream, `out_n` bytes per beat.

    align="beat" (default) ends a packet on every value's final beat;
    align="packed" concatenates values into one packet that the caller ends by
    driving eod[0] on the last value. See `stream/serializer.py`.

    Returns (type_to_byte_stream, type_to_byte_stream_t):
        type_to_byte_stream(stream_in_if: in_intrf.fwd_t,
                            stream_out_if: out_intrf.fb_t) -> ..._t
        in_intrf  = make_stream_interface(make_ndarray_fragment_t(t, 1))
                    -- .stream.data.frag is the value, .stream.data.eod[0]
                       marks the last value of a packet (align="packed")
        out_intrf = the serializer's byte-stream interface (an AXIS interface
                    when the element type is uint8_t, which it is here)
        attrs: .in_intrf .out_intrf .in_fb_t .out_fb_t .t .n_bytes .out_n
    """
    n_bytes = byte_length(t)
    t_to_bytes = make_type_to_bytes(t, endian)
    ser, ser_t = make_serializer(
        uint8_t, n_bytes, out_n, align=align, padding=padding
    )

    in_intrf = make_stream_interface(make_ndarray_fragment_t(t, 1))
    out_intrf = ser.out_intrf

    @struct
    class type_to_byte_stream_t(NamedTuple):
        stream_out_if: out_intrf.fwd_t
        stream_in_if: in_intrf.fb_t

    @hw_func
    def type_to_byte_stream(
        stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t
    ) -> type_to_byte_stream_t:
        o: type_to_byte_stream_t
        # .fwd_t/.fb_t may not be plain locals, so build the payload as the
        # interface's plain .stream_t and wrap it inline at the call site.
        ser_in: ser.in_intrf.stream_t
        ser_in.data.frag = t_to_bytes(stream_in_if.stream.data.frag)
        ser_in.data.eod[0] = stream_in_if.stream.data.eod[0]
        ser_in.valid = stream_in_if.stream.valid
        r = ser(ser.in_intrf.fwd_t(ser_in), stream_out_if)
        o.stream_out_if = r.stream_out_if
        o.stream_in_if.ready = r.stream_in_if.ready
        return o

    type_to_byte_stream.in_intrf = in_intrf
    type_to_byte_stream.out_intrf = out_intrf
    type_to_byte_stream.in_fb_t = in_intrf.fb_t
    type_to_byte_stream.out_fb_t = out_intrf.fb_t
    type_to_byte_stream.t = t
    type_to_byte_stream.n_bytes = n_bytes
    type_to_byte_stream.out_n = out_n
    return type_to_byte_stream, type_to_byte_stream_t


def make_byte_stream_to_type(
    t,
    in_n,
    endian="little",
    align="beat",
    on_eod="discard",
    padding="pad",
    registered_ready=False,
    check_keep=True,
):
    """Keep-tagged byte stream, `in_n` bytes per beat -> stream of `t` values.

    `on_eod` decides what happens to a partial value when the byte stream ends
    mid-value: "discard" (default) drops it and resyncs, pulsing `.runt`;
    "zero_pad" emits it zero-filled, also pulsing `.runt`; "ignore" carries the
    residue forward, reproducing the old desync. See `stream/deserializer.py`.

    Returns (byte_stream_to_type, byte_stream_to_type_t):
        byte_stream_to_type(stream_in_if: in_intrf.fwd_t,
                            stream_out_if: out_intrf.fb_t) -> ..._t
        result fields: .stream_out_if (values), .stream_in_if (reverse half),
                       .runt (uint1_t)
        attrs: .in_intrf .out_intrf .in_fb_t .out_fb_t .t .n_bytes .in_n
    """
    n_bytes = byte_length(t)
    t_from_bytes = make_type_from_bytes(t, endian)
    deser, deser_t = make_deserializer(
        uint8_t,
        in_n,
        n_bytes,
        align=align,
        on_eod=on_eod,
        padding=padding,
        registered_ready=registered_ready,
        check_keep=check_keep,
    )

    in_intrf = deser.in_intrf
    out_intrf = make_stream_interface(make_ndarray_fragment_t(t, 1))

    @struct
    class byte_stream_to_type_t(NamedTuple):
        stream_out_if: out_intrf.fwd_t
        stream_in_if: in_intrf.fb_t
        runt: uint1_t

    @hw_func
    def byte_stream_to_type(
        stream_in_if: in_intrf.fwd_t, stream_out_if: out_intrf.fb_t
    ) -> byte_stream_to_type_t:
        o: byte_stream_to_type_t
        r = deser(stream_in_if, deser.out_fb_t(stream_out_if.ready))
        outw: out_intrf.stream_t
        outw.data.frag = t_from_bytes(r.stream_out_if.stream.data.frag)
        outw.data.eod[0] = r.stream_out_if.stream.data.eod[0]
        outw.valid = r.stream_out_if.stream.valid
        o.stream_out_if.stream = outw
        o.stream_in_if.ready = r.stream_in_if.ready
        o.runt = r.runt
        return o

    byte_stream_to_type.in_intrf = in_intrf
    byte_stream_to_type.out_intrf = out_intrf
    byte_stream_to_type.in_fb_t = in_intrf.fb_t
    byte_stream_to_type.out_fb_t = out_intrf.fb_t
    byte_stream_to_type.t = t
    byte_stream_to_type.n_bytes = n_bytes
    byte_stream_to_type.in_n = in_n
    return byte_stream_to_type, byte_stream_to_type_t
