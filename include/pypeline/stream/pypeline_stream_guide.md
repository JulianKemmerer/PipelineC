# Pypeline Byte-Stream & Struct Framing Library

The library source lives in `include/pypeline/stream/` (same directory as this guide)
and `include/pypeline/axi/type_axis.py`.

This is the pypeline answer to "I have a `@struct` on one side and bytes on the other."
It replaces old PipelineC's `include/stream/serializer.h`,
`include/stream/deserializer.h` and the conversion macros in `include/axi/axis.h`
(`type_byte_serializer`, `type_byte_deserializer`, `axis_packet_to_type`,
`axis_to_type`, `type_to_axis`, `axis_max_len_limiter`).

Four layers, each usable on its own:

| Layer | Module | Converts |
|---|---|---|
| Layout | `pypeline.make_type_to_bytes` / `make_type_from_bytes` | a value ↔ a fixed `uint8_t[N]`, combinationally |
| Element streams | `stream/serializer.py`, `stream/deserializer.py` | a value ↔ keep-tagged beats, with valid/ready |
| Typed streams | `stream/type_byte_stream.py` | a struct stream ↔ a byte stream |
| Framing | `axi/type_axis.py` | a struct stream ↔ AXI-Stream frames |

And the software side — `pypeline.type_to_bytes` / `type_from_bytes` — produces the
*same* bytes in plain Python, so a host program with `readStream`/`writeStream`
functions can build and parse whatever the hardware sends.

## The shortest useful example

```python
from typing import NamedTuple
from pypeline import MAIN, struct, uint8_t, uint16_t, uint32_t, type_to_bytes
from axi.type_axis import make_axis_to_type, make_type_to_axis

@struct
class hdr_t(NamedTuple):
    version: uint8_t
    length:  uint16_t
    flags:   uint32_t          # 7 bytes -- deliberately not a multiple of 4

rx, rx_t = make_axis_to_type(hdr_t, 4)    # AXIS frames -> hdr_t values
tx, tx_t = make_type_to_axis(hdr_t, 4)    # hdr_t values -> AXIS frames

@MAIN
def rx_top(axis_in_if: rx.axis_intrf.fwd_t, stream_out_if: rx.out_fb_t) -> rx_t:
    return rx(axis_in_if, stream_out_if)

@MAIN
def tx_top(stream_in_if: tx.in_intrf.fwd_t, axis_out_if: tx.axis_fb_t) -> tx_t:
    return tx(stream_in_if, axis_out_if)
```

On the software side, the exact bytes that design puts on the wire:

```python
raw = type_to_bytes(hdr_t, hdr_t(version=0xAB, length=0x1234, flags=0xDEADBEEF))
# b'\xab\x34\x12\xef\xbe\xad\xde'   -- 7 bytes, packed little-endian
```

## Layout

Packed and unpadded — **not** C's natural alignment. Each leaf scalar rounds up to a
whole byte (a `uint3_t` field takes one byte), fields and array elements pack
back-to-back in declaration order, and `endian` (default `"little"`) sets the byte order
*within* each multi-byte leaf. `byte_length(t)` is the "sizeof". `@enum` leaves are
supported; arrays *of* enums are not expressible in pypeline (wrap the enum in a struct).

This is the same layout old PipelineC's `SW_LIB.py` generated C headers for, so a design
ported from there stays wire-compatible.

## Choosing options

`align`, `padding` and `on_eod`/`on_runt` are the three knobs that matter. Short version:

| If you are... | Use |
|---|---|
| Sending one struct per Ethernet frame / packet | `frame="one_per_packet"` (the default) — the built-in length limiter drops the frame's min-size padding for you |
| Batching several structs into one frame | `frame="many_per_packet"`, plus either `structs_per_packet=k` or your own `eod[0]` on the last value |
| Worried about truncated/corrupt frames | leave `on_runt="discard"` (the default) and watch the `.runt` output |
| Sure your struct divides the bus width, and want that enforced | `padding="exact"` — it fails at build time if it ever stops being true |
| Hitting a combinational-loop problem through the ready path | `registered_ready=True` on the deserializer, at one bubble cycle per value |

`on_runt="ignore"` exists only to reproduce the old PipelineC behaviour, where a single
short frame permanently desynced the struct boundary for every frame after it. Do not
use it in new designs.

## Padding, and why nothing deadlocks any more

A struct whose byte length is not a multiple of the bus width ends in a **partial beat**,
whose `keep` gives the real byte count. Padding is expressed in `keep`, never written
into the data. So `byte_length(t) == 7` on a 4-byte bus is two beats, the second with
`keep == [1, 1, 1, 0]`.

The old macros had no such path: `deserializer.h:41` and `serializer.h:42` compared their
counters for *equality* with the target, so a non-divisible size stepped straight over it
and the stream wedged forever, silently. Here that case either works (`padding="pad"`,
the default) or raises `ValueError` while the design is being imported
(`padding="exact"`), naming both sizes and how to fix it.

## Throughput

Both the serializer and the deserializer are bubble-free: an output drains and an input
beat is accepted on the same cycle, so N values of B beats each stream in N·B cycles plus
one to fill. Worth knowing because the old deserializer was *not* — its `ready` was gated
on the output register being empty, costing one cycle per value, which halves throughput
whenever a value is a single beat wide (a 4-byte struct on a 4-byte bus, say).
`registered_ready=True` restores the old behaviour if a design needs the combinational
`ready` path broken.

## Handshaking and ports

Everything here uses the standard pypeline conventions: `@interface` port halves paired
by name (`stream_in_if`/`stream_out_if`, or `axis_in_if`/`axis_out_if`), `.fwd_t` on the
argument side and `.fb_t` as a return-struct field, and `(hw_func, struct_t)` from every
factory. Each returned function carries its interfaces as attributes
(`.in_intrf`, `.out_intrf`, `.axis_intrf`, `.in_fb_t`, `.out_fb_t`, `.axis_fb_t`, plus
`.t`, `.n_bytes` and the sizes), so a caller never has to rebuild a type to declare a
port.

## Tests

| File | Covers |
|---|---|
| `src/tests/pypeline_tests/inst/serdes_test.py` | base serializer/deserializer: sizing, handshake, keep, all three `on_eod` policies, bubble-free throughput |
| `type_byte_stream_test.py` | struct ↔ byte stream, and that the wire bytes equal `type_to_bytes` |
| `axis_max_len_limiter_test.py` | the length limiter, one named regression per old `axis.h` defect |
| `type_axis_test.py` | all four AXIS variants |
| `self_check_type_axis_test.py` | the whole path through real GHDL, cycle-diffed against native sim |
| `type_bytes_sw_test.py` | the software helpers, cross-checked against the generated hardware |
| `host_types_test.py`, `host_types_build_test.py` | the generated standalone host module, run where Pypeline cannot be imported |

**See also:** [the main guide's Byte-Stream Serialization section](../../../docs/pypeline_guide.md#byte-stream-serialization-make_serializer--make_deserializer) ·
[Struct ↔ AXI-Stream](../../../docs/pypeline_guide.md#struct--axi-stream-make_axis_to_type--make_type_to_axis) ·
[Struct/type ↔ bytes conversion](../../../docs/pypeline_guide.md#structtype--bytes-conversion)

One thing that falls out of using any of these factories: because they all reach
`make_type_to_bytes`/`make_type_from_bytes` underneath, a design that streams a struct
also gets a standalone Python module for the host on the other end of the wire, written
to `<out_dir>/host/pypeline_host_types.py` by every build — no design change needed. See
[Host-Side Generated Types](../../../docs/pypeline_guide.md#host-side-generated-types).
