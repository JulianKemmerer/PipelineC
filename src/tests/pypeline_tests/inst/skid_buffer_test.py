# pyright: reportInvalidTypeForm=none
import sys, os

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
import random

from pypeline import MAIN, uint32_t, sim_call, sim_reset

from axi.axis import make_axis_interface, make_axis_skid_buffer
from stream.skid_buffer import make_skid_buffer

# One instance per mode. Each mode is a whole separate @hw_func body, and
# `mode` is an enclosing-factory arg so each gets its own entity name -- these
# do not collapse into one another.
full_skid, full_skid_t = make_skid_buffer(uint32_t, mode="full")
fwd_skid, fwd_skid_t = make_skid_buffer(uint32_t, mode="forward")
rev_skid, rev_skid_t = make_skid_buffer(uint32_t, mode="reverse")
byp_skid, byp_skid_t = make_skid_buffer(uint32_t, mode="bypass")

N = 4
axis_intrf = make_axis_interface(N)
axis_skid, axis_skid_t = make_axis_skid_buffer(axis_intrf)


@MAIN
def full_skid_top(
    stream_in_if: full_skid.fwd_t, stream_out_if: full_skid.fb_t
) -> full_skid_t:
    return full_skid(stream_in_if, stream_out_if)


@MAIN
def fwd_skid_top(
    stream_in_if: fwd_skid.fwd_t, stream_out_if: fwd_skid.fb_t
) -> fwd_skid_t:
    return fwd_skid(stream_in_if, stream_out_if)


@MAIN
def rev_skid_top(
    stream_in_if: rev_skid.fwd_t, stream_out_if: rev_skid.fb_t
) -> rev_skid_t:
    return rev_skid(stream_in_if, stream_out_if)


@MAIN
def byp_skid_top(
    stream_in_if: byp_skid.fwd_t, stream_out_if: byp_skid.fb_t
) -> byp_skid_t:
    return byp_skid(stream_in_if, stream_out_if)


@MAIN
def axis_skid_top(
    stream_in_if: axis_skid.fwd_t, stream_out_if: axis_skid.fb_t
) -> axis_skid_t:
    return axis_skid(stream_in_if, stream_out_if)


# (top, factory-returned func) per mode, so every test below runs against all
# four without repeating the table.
MODES = [
    (full_skid_top, full_skid),
    (fwd_skid_top, fwd_skid),
    (rev_skid_top, rev_skid),
    (byp_skid_top, byp_skid),
]


def _beat(skid, data, valid, ready):
    """The (fwd_t, fb_t) argument pair for one sim_call on a uint32_t skid."""
    plain_t = skid.stream_intrf.stream_t
    return (
        skid.fwd_t(stream=plain_t(data=data, valid=valid)),
        skid.fb_t(ready=ready),
    )


def _cycle(top, skid, data, valid, ready):
    a, b = _beat(skid, data, valid, ready)
    return sim_call(top, a, b)


# ── Data integrity ───────────────────────────────────────────────────────────


def test_order_preserved_under_random_handshake():
    """No beat lost, duplicated or reordered, for any mode, under pseudo-random
    valid gaps and pseudo-random backpressure."""
    n_values = 200
    values = [((i * 2654435761) & 0xFFFFFFFF) for i in range(1, n_values + 1)]
    for top, skid in MODES:
        rng = random.Random(0xC0FFEE)
        sim_reset()
        sent_i = 0
        got = []
        for _ in range(n_values * 20 + 200):
            offering = sent_i < n_values
            valid = 1 if (offering and rng.random() < 0.7) else 0
            data = values[sent_i] if offering else 0
            ready = 1 if rng.random() < 0.6 else 0
            r = _cycle(top, skid, data, valid, ready)
            if valid and int(r.stream_in_if.ready):
                sent_i += 1
            if int(r.stream_out_if.stream.valid) and ready:
                got.append(int(r.stream_out_if.stream.data))
            if len(got) == n_values:
                break
        assert got == values, (
            f"mode={skid.mode}: stream corrupted -- sent {n_values} values, "
            f"got {len(got)}; first mismatch at index "
            f"{next((i for i, (a, b) in enumerate(zip(got, values)) if a != b), len(got))}"
        )


def test_output_held_stable_while_consumer_stalled():
    """AXI stability rule: once a beat is presented it must not change while
    ready is low. Input is held constant so the combinational-bypass modes are
    being asked a fair question."""
    for top, skid in MODES:
        sim_reset()
        seen = None
        for _ in range(8):
            r = _cycle(top, skid, 0xA5A5A5A5, 1, 0)
            if int(r.stream_out_if.stream.valid):
                cur = int(r.stream_out_if.stream.data)
                if seen is None:
                    seen = cur
                assert cur == seen, (
                    f"mode={skid.mode}: presented beat changed from {seen:#x} to "
                    f"{cur:#x} while the consumer held ready low"
                )
        assert seen == 0xA5A5A5A5, (
            f"mode={skid.mode}: expected the offered beat to be presented, got {seen!r}"
        )


# ── Handshake / capacity ─────────────────────────────────────────────────────


def test_backpressure_propagates_after_exactly_n_slots():
    """With the consumer stalled forever and the producer always offering, a
    slice absorbs exactly `n_slots` beats and then holds ready low. This is the
    property that says how much storage each mode really has."""
    for top, skid in MODES:
        sim_reset()
        accepted = 0
        for cyc in range(12):
            r = _cycle(top, skid, cyc + 1, 1, 0)
            if int(r.stream_in_if.ready):
                accepted += 1
        assert accepted == skid.n_slots, (
            f"mode={skid.mode}: expected exactly n_slots={skid.n_slots} beats "
            f"absorbed while stalled, got {accepted}"
        )


def test_full_throughput_and_fill_latency():
    """One beat per cycle sustained once filled -- the reason a skid buffer
    exists rather than a plain register -- and the exact advertised latency."""
    n = 50
    for top, skid in MODES:
        sim_reset()
        sent = 0
        got = []
        first_out_cycle = None
        last_out_cycle = None
        for cyc in range(n + 20):
            offering = sent < n
            r = _cycle(top, skid, sent + 1, 1 if offering else 0, 1)
            if offering and int(r.stream_in_if.ready):
                sent += 1
            if int(r.stream_out_if.stream.valid):
                if first_out_cycle is None:
                    first_out_cycle = cyc
                last_out_cycle = cyc
                got.append(int(r.stream_out_if.stream.data))
            if len(got) == n:
                break
        assert got == list(range(1, n + 1)), f"mode={skid.mode}: wrong data out"
        assert first_out_cycle == skid.latency, (
            f"mode={skid.mode}: advertised latency {skid.latency}, but the first "
            f"beat appeared on cycle {first_out_cycle}"
        )
        assert last_out_cycle == skid.latency + n - 1, (
            f"mode={skid.mode}: {n} beats should drain in {n} cycles after a "
            f"{skid.latency}-cycle fill (last on cycle {skid.latency + n - 1}), "
            f"but the last beat appeared on cycle {last_out_cycle} -- there is a bubble"
        )


# ── Which combinational paths each mode actually cuts ────────────────────────
#
# The whole point of the module, tested behaviourally at the port rather than by
# reading generated VHDL: replay an identical prefix, then probe the same
# register state twice with one input changed, and see whether an output moves.

_PREFIXES = [
    [],
    [(1, 0xDEADBEEF, 0)],
    [(1, 0xDEADBEEF, 0), (1, 0xFEEDFACE, 0)],
    [(1, 0xDEADBEEF, 1)],
    [(1, 0xDEADBEEF, 1), (1, 0xFEEDFACE, 0)],
]


def _probe(top, skid, prefix, valid, data, ready):
    sim_reset()
    for pv, pd, pr in prefix:
        _cycle(top, skid, pd, pv, pr)
    return _cycle(top, skid, data, valid, ready)


def _ready_moves_with_downstream_ready(top, skid):
    """True if o.stream_in_if.ready is a function of stream_out_if.ready."""
    for prefix in _PREFIXES:
        a = _probe(top, skid, prefix, 1, 0x11111111, 0)
        b = _probe(top, skid, prefix, 1, 0x11111111, 1)
        if int(a.stream_in_if.ready) != int(b.stream_in_if.ready):
            return True
    return False


def _output_moves_with_upstream(top, skid):
    """True if o.stream_out_if.stream is a function of stream_in_if."""
    for prefix in _PREFIXES:
        a = _probe(top, skid, prefix, 0, 0, 1)
        b = _probe(top, skid, prefix, 1, 0x22222222, 1)
        if int(a.stream_out_if.stream.valid) != int(b.stream_out_if.stream.valid):
            return True
        if int(a.stream_out_if.stream.data) != int(b.stream_out_if.stream.data):
            return True
    return False


def test_modes_cut_the_paths_they_claim():
    # (mode, ready depends on downstream ready, output depends on upstream)
    expected = {
        "full": (False, False),
        "forward": (True, False),
        "reverse": (False, True),
        "bypass": (True, True),
    }
    for top, skid in MODES:
        want_ready_dep, want_out_dep = expected[skid.mode]
        got_ready_dep = _ready_moves_with_downstream_ready(top, skid)
        got_out_dep = _output_moves_with_upstream(top, skid)
        assert got_ready_dep == want_ready_dep, (
            f"mode={skid.mode}: o.stream_in_if.ready "
            f"{'does' if got_ready_dep else 'does not'} depend on "
            f"stream_out_if.ready, expected it "
            f"{'to' if want_ready_dep else 'not to'} -- the reverse path is "
            f"{'not ' if want_ready_dep else ''}cut"
        )
        assert got_out_dep == want_out_dep, (
            f"mode={skid.mode}: o.stream_out_if.stream "
            f"{'does' if got_out_dep else 'does not'} depend on stream_in_if, "
            f"expected it {'to' if want_out_dep else 'not to'} -- the forward "
            f"path is {'not ' if want_out_dep else ''}cut"
        )


# ── AXIS face ────────────────────────────────────────────────────────────────


def test_axis_frame_passes_through_byte_identical():
    """data/keep/eod are carried opaquely: a partial-keep eod beat comes out
    exactly as it went in."""
    frag_t = axis_intrf.stream_t.typeof("data")
    bus_t = frag_t.typeof("frag")

    def axis_args(data, keep, eod, valid, ready):
        return (
            axis_intrf.fwd_t(
                axis_intrf.stream_t(
                    data=frag_t(frag=bus_t(data=data, keep=keep), eod=[eod]),
                    valid=valid,
                )
            ),
            axis_intrf.fb_t(ready=ready),
        )

    frame = [
        ([1, 2, 3, 4], [1, 1, 1, 1], 0),
        ([5, 6, 0, 0], [1, 1, 0, 0], 1),
    ]
    sim_reset()
    sent = 0
    got = []
    for _ in range(20):
        offering = sent < len(frame)
        data, keep, eod = frame[sent] if offering else ([0] * N, [0] * N, 0)
        a, b = axis_args(data, keep, eod, 1 if offering else 0, 1)
        r = sim_call(axis_skid_top, a, b)
        if offering and int(r.stream_in_if.ready):
            sent += 1
        w = r.stream_out_if.stream
        if int(w.valid):
            got.append(
                (
                    [int(w.data.frag.data[i]) for i in range(N)],
                    [int(w.data.frag.keep[i]) for i in range(N)],
                    int(w.data.eod[0]),
                )
            )
        if len(got) == len(frame):
            break
    assert got == frame, f"AXIS frame not passed through unchanged: {got} != {frame}"


# ── Factory validation ───────────────────────────────────────────────────────


def test_bad_mode_rejected_at_factory_call_time():
    try:
        make_skid_buffer(uint32_t, mode="nope")
    except ValueError as e:
        msg = str(e)
        assert "mode" in msg and "nope" in msg, f"unhelpful message: {msg}"
        for m in ("full", "forward", "reverse", "bypass"):
            assert m in msg, f"message should name the legal set, missing {m!r}: {msg}"
    else:
        raise AssertionError("make_skid_buffer accepted mode='nope'")


def test_advertised_slots_and_latency():
    assert (full_skid.n_slots, full_skid.latency) == (2, 1)
    assert (fwd_skid.n_slots, fwd_skid.latency) == (1, 1)
    assert (rev_skid.n_slots, rev_skid.latency) == (1, 0)
    assert (byp_skid.n_slots, byp_skid.latency) == (0, 0)
    # The AXIS face must reuse the caller's interface object identically --
    # interface ports are matched by Python identity, not just canonical name.
    assert axis_skid.stream_intrf is axis_intrf
    assert axis_skid.axis_intrf is axis_intrf


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
