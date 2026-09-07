# pyright: reportInvalidTypeForm=none
"""Base-layer element-stream serializer/deserializer (stream/serializer.py,
stream/deserializer.py).

These are the modules every type/AXIS layer above them is built from, so the
coverage here is deliberately about the *mechanism* -- sizing, handshake,
keep, end-of-data -- rather than about structs. Several tests are named
regressions for defects in the old PipelineC macros these replace; each says
which one.
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
from pypeline import MAIN, sim_call, sim_reset, uint8_t

from stream.deserializer import make_deserializer
from stream.serializer import make_serializer

# ── instances under test ──────────────────────
# 13 elements on a 4-lane bus: deliberately NOT divisible, the case the old
# macros deadlocked on.
ser_13_4, ser_13_4_t = make_serializer(uint8_t, 13, 4)
deser_4_13, deser_4_13_t = make_deserializer(uint8_t, 4, 13)

# divisible, both directions
ser_8_4, ser_8_4_t = make_serializer(uint8_t, 8, 4)
deser_4_4, deser_4_4_t = make_deserializer(uint8_t, 4, 4)
deser_4_4_reg, deser_4_4_reg_t = make_deserializer(uint8_t, 4, 4, registered_ready=True)

# widening (2 lanes in -> 8-element value) and packed/eod policy variants
deser_2_8, deser_2_8_t = make_deserializer(uint8_t, 2, 8)
deser_packed, deser_packed_t = make_deserializer(uint8_t, 4, 6, align="packed")
deser_zero_pad, deser_zero_pad_t = make_deserializer(uint8_t, 4, 6, on_eod="zero_pad")
deser_ignore, deser_ignore_t = make_deserializer(uint8_t, 4, 6, on_eod="ignore")
ser_packed, ser_packed_t = make_serializer(uint8_t, 6, 4, align="packed")


@MAIN
def ser_13_4_main(
    stream_in_if: ser_13_4.in_intrf.fwd_t, stream_out_if: ser_13_4.out_fb_t
) -> ser_13_4_t:
    return ser_13_4(stream_in_if, stream_out_if)


@MAIN
def deser_4_13_main(
    stream_in_if: deser_4_13.in_intrf.fwd_t, stream_out_if: deser_4_13.out_fb_t
) -> deser_4_13_t:
    return deser_4_13(stream_in_if, stream_out_if)


@MAIN
def deser_2_8_main(
    stream_in_if: deser_2_8.in_intrf.fwd_t, stream_out_if: deser_2_8.out_fb_t
) -> deser_2_8_t:
    return deser_2_8(stream_in_if, stream_out_if)


@MAIN
def deser_packed_main(
    stream_in_if: deser_packed.in_intrf.fwd_t, stream_out_if: deser_packed.out_fb_t
) -> deser_packed_t:
    return deser_packed(stream_in_if, stream_out_if)


@MAIN
def ser_packed_main(
    stream_in_if: ser_packed.in_intrf.fwd_t, stream_out_if: ser_packed.out_fb_t
) -> ser_packed_t:
    return ser_packed(stream_in_if, stream_out_if)


@MAIN
def deser_4_4_reg_main(
    stream_in_if: deser_4_4_reg.in_intrf.fwd_t, stream_out_if: deser_4_4_reg.out_fb_t
) -> deser_4_4_reg_t:
    return deser_4_4_reg(stream_in_if, stream_out_if)


@MAIN
def deser_4_4_main(
    stream_in_if: deser_4_4.in_intrf.fwd_t, stream_out_if: deser_4_4.out_fb_t
) -> deser_4_4_t:
    return deser_4_4(stream_in_if, stream_out_if)


@MAIN
def deser_zero_pad_main(
    stream_in_if: deser_zero_pad.in_intrf.fwd_t, stream_out_if: deser_zero_pad.out_fb_t
) -> deser_zero_pad_t:
    return deser_zero_pad(stream_in_if, stream_out_if)


@MAIN
def deser_ignore_main(
    stream_in_if: deser_ignore.in_intrf.fwd_t, stream_out_if: deser_ignore.out_fb_t
) -> deser_ignore_t:
    return deser_ignore(stream_in_if, stream_out_if)


@MAIN
def ser_8_4_main(
    stream_in_if: ser_8_4.in_intrf.fwd_t, stream_out_if: ser_8_4.out_fb_t
) -> ser_8_4_t:
    return ser_8_4(stream_in_if, stream_out_if)


# ── driving helpers ───────────────────────────


def _in_beat(mod, data, keep, eod, valid=1):
    """Hand-craft one keep-tagged input beat for a deserializer."""
    n = mod.in_n
    st = mod.in_intrf.stream_t
    frag_t = st.typeof("data")
    bus_t = frag_t.typeof("frag")
    data = list(data) + [0] * (n - len(data))
    keep = list(keep) + [0] * (n - len(keep))
    return mod.in_intrf.fwd_t(
        st(data=frag_t(frag=bus_t(data=data, keep=keep), eod=[eod]), valid=valid)
    )


def _in_idle(mod):
    return _in_beat(mod, [0] * mod.in_n, [0] * mod.in_n, 0, valid=0)


def _in_value(mod, payload, eod=1, valid=1):
    """Hand-craft one whole-value input word for a serializer."""
    st = mod.in_intrf.stream_t
    frag_t = st.typeof("data")
    return mod.in_intrf.fwd_t(
        st(data=frag_t(frag=list(payload), eod=[eod]), valid=valid)
    )


def _beats_for(payload, n, eod_on_last=True):
    """Split payload into n-wide (data, keep, eod) beats, the last one partial."""
    out = []
    for i in range(0, len(payload), n):
        chunk = payload[i : i + n]
        last = (i + n) >= len(payload)
        out.append(
            (
                chunk + [0] * (n - len(chunk)),
                [1] * len(chunk) + [0] * (n - len(chunk)),
                1 if (last and eod_on_last) else 0,
            )
        )
    return out


def _run_deser(top, mod, beats, max_cycles=200, out_ready=1):
    """Feed beats into a deserializer, collecting (payload, eod, runt) outputs."""
    sim_reset()
    outs = []
    runts = 0
    bi = 0
    for _ in range(max_cycles):
        inp = _in_beat(mod, *beats[bi]) if bi < len(beats) else _in_idle(mod)
        r = sim_call(top, inp, mod.out_fb_t(ready=out_ready))
        s = r.stream_out_if.stream
        if int(s.valid) and out_ready:
            outs.append(([int(x) for x in s.data.frag], int(s.data.eod[0])))
        runts += int(r.runt)
        if bi < len(beats) and int(r.stream_in_if.ready):
            bi += 1
    return outs, runts


def _run_ser(top, mod, values, max_cycles=200):
    """Feed whole values into a serializer, collecting (data, keep, eod) beats."""
    sim_reset()
    beats = []
    vi = 0
    for _ in range(max_cycles):
        inp = (
            _in_value(mod, values[vi][0], eod=values[vi][1])
            if vi < len(values)
            else _in_value(mod, [0] * mod.in_n, valid=0)
        )
        r = sim_call(top, inp, mod.out_fb_t(ready=1))
        s = r.stream_out_if.stream
        if int(s.valid):
            beats.append(
                (
                    [int(x) for x in s.data.frag.data],
                    [int(x) for x in s.data.frag.keep],
                    int(s.data.eod[0]),
                )
            )
        if vi < len(values) and int(r.stream_in_if.ready):
            vi += 1
    return beats


def _kept(beats):
    """Flatten beats down to the kept elements only."""
    return [d for (data, keep, _) in beats for d, k in zip(data, keep) if k]


# ── tests ─────────────────────────────────────


def test_serialize_non_divisible_partial_final_beat():
    """13 elements on a 4-lane bus. The old serializer_in_to_out deadlocked
    outright here (serializer.h:42's `out_counter==IN_SIZE` never fires when
    IN_SIZE % OUT_SIZE != 0); the final beat must instead carry keep == 1."""
    payload = list(range(1, 14))
    beats = _run_ser(ser_13_4_main, ser_13_4, [(payload, 1)])
    assert len(beats) == 4, beats
    assert _kept(beats) == payload, _kept(beats)
    assert sum(beats[-1][1]) == 1, beats[-1]
    assert beats[-1][2] == 1, "eod must be on the final beat"
    assert all(e == 0 for (_, _, e) in beats[:-1]), "eod must not be early"
    print("test_serialize_non_divisible_partial_final_beat PASS")


def test_serialize_zeroes_unkept_lanes():
    """Unkept lanes carry 0, not stale buffer contents -- an unwritten register
    reads 'U' in GHDL but 0 in native sim, so stale data would show up as a
    spurious mismatch in a native-vs-VHDL cycle diff."""
    beats = _run_ser(ser_13_4_main, ser_13_4, [(list(range(1, 14)), 1)])
    data, keep, _ = beats[-1]
    for i in range(len(keep)):
        if not keep[i]:
            assert data[i] == 0, (i, data)
    print("test_serialize_zeroes_unkept_lanes PASS")


def test_deserialize_non_divisible():
    """The mirror: gather 13 elements from 4-lane beats. Old deserializer.h:41
    (`out_counter==OUT_SIZE`) stepped over the target and wedged forever."""
    payload = list(range(1, 14))
    outs, _ = _run_deser(deser_4_13_main, deser_4_13, _beats_for(payload, 4))
    assert len(outs) == 1, outs
    assert outs[0][0] == payload, outs[0][0]
    assert outs[0][1] == 1, "eod must propagate to the gathered value"
    print("test_deserialize_non_divisible PASS")


def test_deserialize_widening():
    """2 lanes in, 8-element value out."""
    payload = list(range(10, 18))
    outs, _ = _run_deser(deser_2_8_main, deser_2_8, _beats_for(payload, 2))
    assert len(outs) == 1 and outs[0][0] == payload, outs
    print("test_deserialize_widening PASS")


def test_deserialize_equal_width():
    """1 beat per value, the case the old registered-ready deserializer
    halved the throughput of."""
    beats = [([1, 2, 3, 4], [1] * 4, 0), ([5, 6, 7, 8], [1] * 4, 1)]
    outs, _ = _run_deser(deser_4_4_main, deser_4_4, beats)
    assert [o[0] for o in outs] == [[1, 2, 3, 4], [5, 6, 7, 8]], outs
    print("test_deserialize_equal_width PASS")


def test_deserializer_is_bubble_free():
    """THE regression for changing the old macro's handshake.

    `deserializer.h:22`'s `in_data_ready = !out_buffer_valid` forbids accepting
    a beat on the cycle an output drains, so N one-beat values take 2N cycles.
    Bubble-free (the default) must take N cycles plus the initial fill; the
    registered_ready=True escape hatch must reproduce the old 2N.
    """
    n_values = 5
    beat = ([1, 2, 3, 4], [1] * 4, 0)

    def cycles_to_collect(top, mod):
        sim_reset()
        got = 0
        for c in range(1, 100):
            r = sim_call(top, _in_beat(mod, *beat), mod.out_fb_t(ready=1))
            if int(r.stream_out_if.stream.valid):
                got += 1
            if got == n_values:
                return c
        raise AssertionError("never collected all values")

    fast = cycles_to_collect(deser_4_4_main, deser_4_4)
    slow = cycles_to_collect(deser_4_4_reg_main, deser_4_4_reg)
    assert fast == n_values + 1, fast  # one fill cycle, then full rate
    assert slow == 2 * n_values, slow  # the old bubble, one per value
    print(f"test_deserializer_is_bubble_free PASS ({fast} vs {slow} cycles)")


def test_serializer_is_bubble_free():
    """The serializer's combinational ready path (kept from serializer.h:32)
    means back-to-back values stream with no gap: N values of 2 beats each
    take 2N beats in 2N+1 cycles."""
    sim_reset()
    n_values, accepted, beats = 4, 0, 0
    payload = list(range(8))
    for c in range(1, 100):
        r = sim_call(
            ser_8_4_main, _in_value(ser_8_4, payload), ser_8_4.out_fb_t(ready=1)
        )
        if int(r.stream_in_if.ready) and accepted < n_values:
            accepted += 1
        if int(r.stream_out_if.stream.valid):
            beats += 1
        if accepted == n_values and beats == 2 * n_values:
            assert c == 2 * n_values + 1, c
            print(f"test_serializer_is_bubble_free PASS ({c} cycles)")
            return
    raise AssertionError(f"never streamed cleanly: accepted={accepted} beats={beats}")


def test_backpressure_stall_and_resume():
    """With the sink not ready, nothing is emitted and no state is lost; once
    ready returns the whole value comes out intact."""
    payload = list(range(1, 14))
    beats = _beats_for(payload, 4)
    sim_reset()
    bi = 0
    # 12 cycles with out_ready=0: the input beats are absorbed, no output.
    for _ in range(12):
        inp = _in_beat(deser_4_13, *beats[bi]) if bi < len(beats) else _in_idle(deser_4_13)
        r = sim_call(deser_4_13_main, inp, deser_4_13.out_fb_t(ready=0))
        if bi < len(beats) and int(r.stream_in_if.ready):
            bi += 1
    assert bi == len(beats), f"stalled sink blocked input intake at {bi}"
    # ...but nothing is consumed until ready, so the value is still there.
    r = sim_call(deser_4_13_main, _in_idle(deser_4_13), deser_4_13.out_fb_t(ready=1))
    assert int(r.stream_out_if.stream.valid) == 1
    assert [int(x) for x in r.stream_out_if.stream.data.frag] == payload
    print("test_backpressure_stall_and_resume PASS")


def test_padding_exact_raises_at_factory_time():
    """The replacement for the old silent deadlock: a design that asks for
    exact sizing and does not have it fails while the module is being
    imported, with both sizes in the message."""
    for kwargs, factory in (
        (dict(elem_t=uint8_t, in_n=4, out_n=13, padding="exact"), make_deserializer),
        (dict(elem_t=uint8_t, in_n=13, out_n=4, padding="exact"), make_serializer),
    ):
        try:
            factory(**kwargs)
            raise AssertionError(f"expected ValueError from {factory.__name__}")
        except ValueError as e:
            msg = str(e)
            assert "13" in msg and "4" in msg, msg
            assert "padding='pad'" in msg, msg
    # ...and the divisible case is accepted.
    make_deserializer(uint8_t, 4, 12, padding="exact")
    make_serializer(uint8_t, 12, 4, padding="exact")
    print("test_padding_exact_raises_at_factory_time PASS")


def test_bad_options_rejected():
    for kwargs in (
        dict(align="middle"),
        dict(on_eod="explode"),
        dict(padding="maybe"),
    ):
        try:
            make_deserializer(uint8_t, 4, 8, **kwargs)
            raise AssertionError(f"expected ValueError for {kwargs}")
        except ValueError:
            pass
    print("test_bad_options_rejected PASS")


def test_on_eod_discard_resyncs_after_runt():
    """Default policy. A packet that ends mid-value drops the residue and
    pulses .runt, so the NEXT packet decodes correctly -- the fix for
    axis.h:561-595, where the deserializer was never flushed on tlast and one
    runt permanently desynced every value after it."""
    runt = [([9, 9, 0, 0], [1, 1, 0, 0], 1)]  # 2 elements, then eod: value needs 6
    good = _beats_for([1, 2, 3, 4, 5, 6], 4)
    outs, runts = _run_deser(deser_packed_main, deser_packed, runt + good)
    assert runts >= 1, "runt was not signalled"
    assert len(outs) == 1, outs
    assert outs[0][0] == [1, 2, 3, 4, 5, 6], outs[0][0]
    print("test_on_eod_discard_resyncs_after_runt PASS")


def test_on_eod_zero_pad_emits_padded_value():
    """The alternative policy: emit the partial value zero-filled, still
    pulsing .runt so a consumer can tell."""
    runt = [([7, 8, 0, 0], [1, 1, 0, 0], 1)]
    outs, runts = _run_deser(deser_zero_pad_main, deser_zero_pad, runt)
    assert runts >= 1
    assert len(outs) == 1, outs
    assert outs[0][0] == [7, 8, 0, 0, 0, 0], outs[0][0]
    print("test_on_eod_zero_pad_emits_padded_value PASS")


def test_on_eod_ignore_reproduces_old_desync():
    """Documents the behaviour this library deliberately no longer defaults to.

    With on_eod="ignore" the residue of a runt packet is carried forward, so
    the next packet's elements complete the previous value and every value
    after it is shifted -- exactly what old axis_packet_to_type did to any
    stream that ever saw a short packet.
    """
    runt = [([9, 9, 0, 0], [1, 1, 0, 0], 1)]
    good = _beats_for([1, 2, 3, 4, 5, 6], 4)
    outs, _ = _run_deser(deser_ignore_main, deser_ignore, runt + good)
    assert len(outs) >= 1, outs
    # The first value emitted is the runt's leftovers followed by the good
    # packet's opening elements -- corrupted, and offset from then on.
    assert outs[0][0] == [9, 9, 1, 2, 3, 4], outs[0][0]
    print("test_on_eod_ignore_reproduces_old_desync PASS")


def test_packed_carries_residue_across_values():
    """align="packed": two 6-element values arriving as 4-lane beats straddle
    beat boundaries and both come out whole."""
    payload = list(range(1, 13))  # two 6-element values, back to back
    beats = _beats_for(payload, 4)
    outs, _ = _run_deser(deser_packed_main, deser_packed, beats)
    assert [o[0] for o in outs] == [[1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12]], outs
    print("test_packed_carries_residue_across_values PASS")


def test_packed_serializer_concatenates_into_one_packet():
    """The send-side mirror: two 6-element values become one packet whose eod
    lands only on the caller-flagged final value."""
    beats = _run_ser(
        ser_packed_main,
        ser_packed,
        [(list(range(1, 7)), 0), (list(range(7, 13)), 1)],
    )
    assert _kept(beats) == list(range(1, 13)), _kept(beats)
    eods = [e for (_, _, e) in beats]
    assert sum(eods) == 1 and eods[-1] == 1, eods
    print("test_packed_serializer_concatenates_into_one_packet PASS")


def test_serializer_eod_never_on_invalid_beat():
    """serializer.h:29 computed out_last from the counter alone, so tlast could
    sit high while tvalid was low (and axis.h:653 copied it straight through).
    Here eod is only ever observable on a valid beat."""
    sim_reset()
    for _ in range(6):
        r = sim_call(
            ser_13_4_main,
            _in_value(ser_13_4, [0] * 13, valid=0),
            ser_13_4.out_fb_t(ready=1),
        )
        s = r.stream_out_if.stream
        if not int(s.valid):
            assert int(s.data.eod[0]) == 0, "eod asserted on an invalid beat"
    print("test_serializer_eod_never_on_invalid_beat PASS")


def test_round_trip_through_both():
    """serializer -> deserializer recovers the original 13 elements."""
    payload = list(range(1, 14))
    beats = _run_ser(ser_13_4_main, ser_13_4, [(payload, 1)])
    outs, _ = _run_deser(deser_4_13_main, deser_4_13, beats)
    assert len(outs) == 1 and outs[0][0] == payload, outs
    print("test_round_trip_through_both PASS")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
