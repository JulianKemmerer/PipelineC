# pyright: reportInvalidTypeForm=none
"""axi/type_axis.make_axis_max_len_limiter.

The limiter exists because Ethernet pads frames to a 60-byte minimum: without
it, a struct smaller than the minimum frame leaves trailing pad bytes in the
deserializer and desyncs every value after it. Old PipelineC had one
(`axis.h:515-553`) but it was broken in four separate ways, and every test here
is a named regression for one of them.
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
from pypeline import MAIN, sim_call, sim_reset

from axi.axis import make_axis_interface
from axi.type_axis import make_axis_max_len_limiter

N = 4
axis_intrf = make_axis_interface(N)

# max_bytes < one bus word: the case axis.h:527's `max_byte_len - (axis_bits/8)`
# underflowed on, silently disabling the limiter entirely.
lim_3, lim_3_t = make_axis_max_len_limiter(axis_intrf, N, 3)
# max_bytes not a multiple of the bus width: axis.h tested `counter ==
# last_word_limit`, which such a value steps straight over.
lim_6, lim_6_t = make_axis_max_len_limiter(axis_intrf, N, 6)
# exact multiple, the only case the old code actually handled
lim_8, lim_8_t = make_axis_max_len_limiter(axis_intrf, N, 8)


@MAIN
def lim_3_main(
    axis_in_if: axis_intrf.fwd_t, axis_out_if: axis_intrf.fb_t
) -> lim_3_t:
    return lim_3(axis_in_if, axis_out_if)


@MAIN
def lim_6_main(
    axis_in_if: axis_intrf.fwd_t, axis_out_if: axis_intrf.fb_t
) -> lim_6_t:
    return lim_6(axis_in_if, axis_out_if)


@MAIN
def lim_8_main(
    axis_in_if: axis_intrf.fwd_t, axis_out_if: axis_intrf.fb_t
) -> lim_8_t:
    return lim_8(axis_in_if, axis_out_if)


def _beat(data, keep, eod, valid=1):
    st = axis_intrf.stream_t
    frag_t = st.typeof("data")
    bus_t = frag_t.typeof("frag")
    data = list(data) + [0] * (N - len(data))
    keep = list(keep) + [0] * (N - len(keep))
    return axis_intrf.fwd_t(
        st(data=frag_t(frag=bus_t(data=data, keep=keep), eod=[eod]), valid=valid)
    )


def _idle():
    return _beat([0] * N, [0] * N, 0, valid=0)


def _frame_beats(payload):
    """Split a payload into full-keep beats, eod on the last."""
    out = []
    for i in range(0, len(payload), N):
        chunk = payload[i : i + N]
        out.append(
            (
                chunk + [0] * (N - len(chunk)),
                [1] * len(chunk) + [0] * (N - len(chunk)),
                1 if i + N >= len(payload) else 0,
            )
        )
    return out


def _run(top, beats, cycles=40):
    """Push beats through a limiter; return the (data, keep, eod) beats that
    came out, plus the kept payload bytes."""
    sim_reset()
    out = []
    bi = 0
    for _ in range(cycles):
        r = sim_call(top, _beat(*beats[bi]) if bi < len(beats) else _idle(),
                     axis_intrf.fb_t(ready=1))
        s = r.axis_out_if.stream
        if int(s.valid):
            out.append(
                (
                    [int(d) for d in s.data.frag.data],
                    [int(k) for k in s.data.frag.keep],
                    int(s.data.eod[0]),
                )
            )
        if bi < len(beats) and int(r.axis_in_if.ready):
            bi += 1
    kept = [d for (dat, keep, _) in out for d, k in zip(dat, keep) if k]
    return out, kept


def test_sub_word_limit_actually_limits():
    """REGRESSION for axis.h:527. `max_byte_len - (axis_bits/8)` on an unsigned
    counter underflows to ~65534 when the type is smaller than one bus word,
    so `below` was always true and the limiter silently did nothing. With
    max_bytes=3 on a 4-byte bus, a 12-byte frame must yield exactly 3 bytes."""
    out, kept = _run(lim_3_main, _frame_beats(list(range(1, 13))))
    assert kept == [1, 2, 3], kept
    assert out[0][1] == [1, 1, 1, 0], out[0][1]
    assert out[0][2] == 1, "eod must be forced at the limit"
    print("test_sub_word_limit_actually_limits PASS")


def test_non_multiple_limit():
    """REGRESSION for axis.h:527's `counter == last_word_limit`, which never
    fires when max_byte_len is not a whole number of bus words. max_bytes=6 on
    a 4-byte bus must cut mid-beat."""
    out, kept = _run(lim_6_main, _frame_beats(list(range(1, 13))))
    assert kept == [1, 2, 3, 4, 5, 6], kept
    assert out[-1][2] == 1
    print("test_non_multiple_limit PASS")


def test_keep_adjusted_on_truncating_beat():
    """REGRESSION for axis.h:539-541: the old limiter forced tlast but left
    tkeep untouched, so the beat that hit the limit still claimed all its bytes
    were real. Here keep must be a prefix of exactly the remaining length, and
    the dropped lanes' data must be zeroed."""
    out, _ = _run(lim_6_main, _frame_beats(list(range(1, 13))))
    data, keep, eod = out[-1]
    assert keep == [1, 1, 0, 0], keep  # 6 - 4 already passed == 2 bytes left
    assert eod == 1
    for i in range(N):
        if not keep[i]:
            assert data[i] == 0, (i, data)
    print("test_keep_adjusted_on_truncating_beat PASS")


def test_exact_multiple_limit():
    out, kept = _run(lim_8_main, _frame_beats(list(range(1, 13))))
    assert kept == list(range(1, 9)), kept
    assert out[-1][1] == [1, 1, 1, 1] and out[-1][2] == 1
    print("test_exact_multiple_limit PASS")


def test_eod_never_forced_on_invalid_beat():
    """REGRESSION for axis.h:539-541, which forced tlast without checking
    validity, so tlast could sit high on an invalid beat."""
    sim_reset()
    for _ in range(6):
        r = sim_call(lim_3_main, _idle(), axis_intrf.fb_t(ready=1))
        s = r.axis_out_if.stream
        assert int(s.valid) == 0
        assert int(s.data.eod[0]) == 0, "eod asserted while invalid"
    print("test_eod_never_forced_on_invalid_beat PASS")


def test_counter_resets_so_next_frame_is_limited_too():
    """REGRESSION for the framing half of the same bug: the counter must reset
    at the real end of a frame -- but NOT at the forced one, or the trailing
    padding re-arms the limiter and comes through as a second value."""
    frame = _frame_beats(list(range(1, 13)))
    out, kept = _run(lim_6_main, frame + frame, cycles=60)
    assert kept == [1, 2, 3, 4, 5, 6] * 2, kept
    eods = [e for (_, _, e) in out]
    assert sum(eods) == 2, eods  # exactly one per frame, not one per limit hit
    print("test_counter_resets_so_next_frame_is_limited_too PASS")


def test_short_frame_passes_through_untouched():
    """A frame already under the limit must be unmodified -- same data, same
    keep, its own eod, no forced one."""
    out, kept = _run(lim_8_main, _frame_beats([7, 8, 9]))
    assert kept == [7, 8, 9], kept
    assert len(out) == 1 and out[0][1] == [1, 1, 1, 0] and out[0][2] == 1
    print("test_short_frame_passes_through_untouched PASS")


def test_bad_max_bytes_rejected():
    for bad in (0, -1, "8", None):
        try:
            make_axis_max_len_limiter(axis_intrf, N, bad)
            raise AssertionError(f"expected ValueError for max_bytes={bad!r}")
        except ValueError:
            pass
    print("test_bad_max_bytes_rejected PASS")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
