# pyright: reportInvalidTypeForm=none
"""stream/type_byte_stream.py -- struct stream <-> byte stream.

The headline property, asserted in several shapes below: the bytes this
hardware puts on the wire are byte-for-byte what `pypeline.type_to_bytes()`
produces in software. That is what lets someone with a readStream/writeStream
byte API talk to a pypeline design without a hand-maintained struct format.
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)
from enum import auto
from typing import NamedTuple

from pypeline import (
    MAIN,
    PypelineEnum,
    byte_length,
    enum,
    sim_call,
    sim_reset,
    struct,
    type_from_bytes,
    type_to_bytes,
    uint8_t,
    uint16_t,
    uint32_t,
)

from stream.type_byte_stream import (
    make_byte_stream_to_type,
    make_type_to_byte_stream,
)

N = 4


@enum
class mode_t(PypelineEnum):
    # NB: not `ON` -- enum member names are emitted verbatim into the VHDL
    # enumeration type, and `on` is a VHDL reserved word, so `ON` produces
    # uncompilable VHDL. Native simulation cannot see this; only a synth or
    # GHDL run can. See the guide's limitations table.
    OFF = auto()
    ACTIVE = auto()
    STANDBY = auto()


@struct
class inner_t(NamedTuple):
    lo: uint8_t
    hi: uint16_t


# 7 bytes: deliberately NOT a multiple of the 4-byte bus.
@struct
class hdr_t(NamedTuple):
    version: uint8_t
    length: uint16_t
    flags: uint32_t


# 8 bytes: an exact multiple, so no partial beat is ever produced.
@struct
class aligned_t(NamedTuple):
    a: uint32_t
    b: uint32_t


# nested + an enum leaf
@struct
class nested_t(NamedTuple):
    m: mode_t
    inner: inner_t
    tail: uint16_t


tx_hdr, tx_hdr_t = make_type_to_byte_stream(hdr_t, N)
rx_hdr, rx_hdr_t = make_byte_stream_to_type(hdr_t, N)
tx_al, tx_al_t = make_type_to_byte_stream(aligned_t, N)
rx_al, rx_al_t = make_byte_stream_to_type(aligned_t, N)
tx_nest, tx_nest_t = make_type_to_byte_stream(nested_t, N)
rx_nest, rx_nest_t = make_byte_stream_to_type(nested_t, N)
tx_arr, tx_arr_t = make_type_to_byte_stream(uint16_t[4], N)
rx_arr, rx_arr_t = make_byte_stream_to_type(uint16_t[4], N)


@MAIN
def tx_hdr_main(
    stream_in_if: tx_hdr.in_intrf.fwd_t, stream_out_if: tx_hdr.out_fb_t
) -> tx_hdr_t:
    return tx_hdr(stream_in_if, stream_out_if)


@MAIN
def rx_hdr_main(
    stream_in_if: rx_hdr.in_intrf.fwd_t, stream_out_if: rx_hdr.out_fb_t
) -> rx_hdr_t:
    return rx_hdr(stream_in_if, stream_out_if)


@MAIN
def tx_al_main(
    stream_in_if: tx_al.in_intrf.fwd_t, stream_out_if: tx_al.out_fb_t
) -> tx_al_t:
    return tx_al(stream_in_if, stream_out_if)


@MAIN
def rx_al_main(
    stream_in_if: rx_al.in_intrf.fwd_t, stream_out_if: rx_al.out_fb_t
) -> rx_al_t:
    return rx_al(stream_in_if, stream_out_if)


@MAIN
def tx_nest_main(
    stream_in_if: tx_nest.in_intrf.fwd_t, stream_out_if: tx_nest.out_fb_t
) -> tx_nest_t:
    return tx_nest(stream_in_if, stream_out_if)


@MAIN
def rx_nest_main(
    stream_in_if: rx_nest.in_intrf.fwd_t, stream_out_if: rx_nest.out_fb_t
) -> rx_nest_t:
    return rx_nest(stream_in_if, stream_out_if)


@MAIN
def tx_arr_main(
    stream_in_if: tx_arr.in_intrf.fwd_t, stream_out_if: tx_arr.out_fb_t
) -> tx_arr_t:
    return tx_arr(stream_in_if, stream_out_if)


@MAIN
def rx_arr_main(
    stream_in_if: rx_arr.in_intrf.fwd_t, stream_out_if: rx_arr.out_fb_t
) -> rx_arr_t:
    return rx_arr(stream_in_if, stream_out_if)


# ── driving helpers ───────────────────────────


def _send(top, mod, value, cycles=30):
    """Push one value through a type_to_byte_stream; return its beats."""
    frag_t = mod.in_intrf.stream_t.typeof("data")

    def word(valid):
        return mod.in_intrf.fwd_t(
            mod.in_intrf.stream_t(
                data=frag_t(frag=value, eod=[1]), valid=valid
            )
        )

    sim_reset()
    sent = False
    beats = []
    for _ in range(cycles):
        r = sim_call(top, word(0 if sent else 1), mod.out_fb_t(ready=1))
        if not sent and int(r.stream_in_if.ready):
            sent = True
        s = r.stream_out_if.stream
        if int(s.valid):
            beats.append(
                (
                    [int(d) for d in s.data.frag.data],
                    [int(k) for k in s.data.frag.keep],
                    int(s.data.eod[0]),
                )
            )
    return beats


def _recv(top, mod, beats, cycles=30):
    """Push beats through a byte_stream_to_type; return the recovered values
    as bytes (re-packed, so comparison needs no per-type field walk)."""
    st = mod.in_intrf.stream_t
    frag_t = st.typeof("data")
    bus_t = frag_t.typeof("frag")

    def word(data, keep, eod, valid=1):
        return mod.in_intrf.fwd_t(
            st(
                data=frag_t(frag=bus_t(data=list(data), keep=list(keep)), eod=[eod]),
                valid=valid,
            )
        )

    sim_reset()
    bi = 0
    got = []
    for _ in range(cycles):
        inp = word(*beats[bi]) if bi < len(beats) else word([0] * N, [0] * N, 0, 0)
        r = sim_call(top, inp, mod.out_fb_t(ready=1))
        if int(r.stream_out_if.stream.valid):
            got.append(type_to_bytes(mod.t, r.stream_out_if.stream.data.frag))
        if bi < len(beats) and int(r.stream_in_if.ready):
            bi += 1
    return got


def _wire(beats):
    return bytes(d for (dat, keep, _) in beats for d, k in zip(dat, keep) if k)


HDR = hdr_t(version=0xAB, length=0x1234, flags=0xDEADBEEF)
ALIGNED = aligned_t(a=0x01020304, b=0x05060708)
NESTED = nested_t(m=mode_t.STANDBY, inner=inner_t(lo=0x11, hi=0x2233), tail=0x4455)


@struct
class _u16x4_wrap(NamedTuple):
    v: uint16_t[4]


ARR = _u16x4_wrap(v=[0x1111, 0x2222, 0x3333, 0x4444]).v


# ── tests ─────────────────────────────────────


def test_wire_bytes_match_software_layout():
    """THE contract. Whatever the hardware puts on the wire is exactly what a
    software author gets from pypeline.type_to_bytes for the same value."""
    for top, mod, value in (
        (tx_hdr_main, tx_hdr, HDR),
        (tx_al_main, tx_al, ALIGNED),
        (tx_nest_main, tx_nest, NESTED),
        (tx_arr_main, tx_arr, ARR),
    ):
        wire = _wire(_send(top, mod, value))
        assert wire == type_to_bytes(mod.t, value), (
            mod.t,
            wire.hex(),
            type_to_bytes(mod.t, value).hex(),
        )
    print("test_wire_bytes_match_software_layout PASS")


def test_partial_final_beat_keep():
    """A 7-byte struct on a 4-byte bus: 2 beats, the last carrying 3 bytes.
    Old type_to_axis hardcoded tkeep all-ones (axis.h:650), making this
    inexpressible -- and the underlying serializer deadlocked outright."""
    beats = _send(tx_hdr_main, tx_hdr, HDR)
    assert byte_length(hdr_t) == 7
    assert len(beats) == 2, beats
    assert sum(beats[-1][1]) == byte_length(hdr_t) % N == 3
    assert beats[-1][2] == 1 and beats[0][2] == 0
    print("test_partial_final_beat_keep PASS")


def test_aligned_type_has_no_partial_beat():
    beats = _send(tx_al_main, tx_al, ALIGNED)
    assert byte_length(aligned_t) == 8
    assert len(beats) == 2 and all(sum(b[1]) == N for b in beats)
    assert [b[2] for b in beats] == [0, 1]
    print("test_aligned_type_has_no_partial_beat PASS")


def test_eod_exactly_once_per_value():
    for top, mod, value in (
        (tx_hdr_main, tx_hdr, HDR),
        (tx_al_main, tx_al, ALIGNED),
        (tx_nest_main, tx_nest, NESTED),
    ):
        beats = _send(top, mod, value)
        eods = [e for (_, _, e) in beats]
        assert sum(eods) == 1 and eods[-1] == 1, (mod.t, eods)
    print("test_eod_exactly_once_per_value PASS")


def test_loopback_all_shapes():
    """tx -> rx recovers each value, including the enum-bearing nested struct
    and a bare array type."""
    for tx_top, tx_mod, rx_top, rx_mod, value in (
        (tx_hdr_main, tx_hdr, rx_hdr_main, rx_hdr, HDR),
        (tx_al_main, tx_al, rx_al_main, rx_al, ALIGNED),
        (tx_nest_main, tx_nest, rx_nest_main, rx_nest, NESTED),
        (tx_arr_main, tx_arr, rx_arr_main, rx_arr, ARR),
    ):
        beats = _send(tx_top, tx_mod, value)
        got = _recv(rx_top, rx_mod, beats)
        assert got == [type_to_bytes(rx_mod.t, value)], (rx_mod.t, got)
    print("test_loopback_all_shapes PASS")


def test_software_built_frame_decodes_in_hardware():
    """The direction a software author actually cares about: build the bytes in
    Python with type_to_bytes, feed them in as beats, get the struct out."""
    raw = type_to_bytes(hdr_t, HDR)
    beats = []
    for i in range(0, len(raw), N):
        chunk = list(raw[i : i + N])
        beats.append(
            (
                chunk + [0] * (N - len(chunk)),
                [1] * len(chunk) + [0] * (N - len(chunk)),
                1 if i + N >= len(raw) else 0,
            )
        )
    got = _recv(rx_hdr_main, rx_hdr, beats)
    assert got == [raw], got
    # ...and the inverse: what came out of hardware decodes in software.
    assert type_from_bytes(hdr_t, got[0]).flags == HDR.flags
    print("test_software_built_frame_decodes_in_hardware PASS")


def test_padding_exact_propagates_type_level_message():
    """A non-divisible struct with padding='exact' must name the byte length,
    the bus width and the way out -- not deadlock like the old macros."""
    try:
        make_byte_stream_to_type(hdr_t, N, padding="exact")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        msg = str(e)
        assert "7" in msg and "4" in msg and "padding='pad'" in msg, msg
    try:
        make_type_to_byte_stream(hdr_t, N, padding="exact")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "padding='pad'" in str(e)
    # the aligned struct is fine
    make_byte_stream_to_type(aligned_t, N, padding="exact")
    print("test_padding_exact_propagates_type_level_message PASS")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
