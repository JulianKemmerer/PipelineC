# pyright: reportInvalidTypeForm=none
"""In-design performance probes: called from inside a design's OWN hardware
functions, they pass a block's handshake, FSM-state, arbitration and buffer
signals straight out to the plain-Python taps in stream_perf.py.

Boundary measurement (stream_perf.StreamMeter) answers "how fast is the
design". These probes answer "which block is holding it up".

WHY THIS COSTS NO HARDWARE
--------------------------
Every probe here is `@sim_output`-decorated, and the hardware elaborator
DELETES calls to those, argument expressions included (PY_TO_LOGIC's
_elab_stmt turns the whole statement into `pass`). So the elaborated logic is
identical with or without probes, and a probe may be handed anything -- a
`keep` array to popcount, a Python tuple of state names -- without it becoming
logic. The one visible effect: generated VHDL embeds source line numbers, so
ADDING or MOVING a probe line renames signals in its enclosing hierarchy and
costs one re-synthesis. Once probes are in place, stimulus-only changes
re-measure in sim time alone.

WHERE PROBES MAY GO
-------------------
1. Plain `@hw_func`/`@MAIN` bodies only. An `@interface_func` body cannot
   host them (only calls may consume interface values there); probe a plain
   hw_func it calls instead.
2. Stateful, zero-latency contexts only -- never inside an AUTO_PIPELINE core
   or a pipelined pure MAIN, where native sim's delay-line model would hand
   the probe a stage-0 sample and the cycle alignment vs real VHDL would be
   wrong. FSMs and other Reg-holding functions are the natural sites.
3. State probes at the TOP of an FSM body (a `Reg` reads back its next value
   once assigned), handshake probes at the BOTTOM (every `o.*` field final).

NAMING
------
During each cycle's final (converged) pass, the native simulator records the
MAIN being executed, so a probe qualifies its name with that MAIN:
`<label>/<name>`. `MAIN_LABELS` maps MAIN function names to shorter labels
(e.g. two direction-specific MAINs instantiating the same probed FSM ->
`encrypt/`, `decrypt/`); an unlisted MAIN uses its own name. Outside the
native simulator (a plain `sim_call` loop) names are left bare.

A tap name identifies ONE call site per MAIN: two calls of the same probed
function inside one MAIN would share a name, and only one of them would be
counted. Give such instances distinct names (a factory `tap_name` argument,
as `make_probed_stream_fifo` takes) or put them under different MAINs.

ENABLEMENT
----------
`REGISTRY.enable([...])` selects live taps: exact names, a `<label>/` or
`<block>` prefix, or "all". Everything else is a NullTap, so an unused probe
is one no-op call per cycle. `REGISTRY` and `MAIN_LABELS` are created once and
must only be mutated in place (`.enable(...)`, `.update(...)`): a
`@sim_output` body executes against a detached copy of its module's globals,
so rebinding either name would leave the probes writing into orphans.

See pypeline_stream_perf_guide.md for the metrics these feed.
"""

import pypeline
from pypeline import hw_func, sim_input, sim_output

from stream.skid_buffer import make_skid_buffer
from stream.stream_fifo import make_stream_fifo
from stream.stream_perf import (
    ArbTap,
    BufferTap,
    HandshakeTap,
    StateTap,
    TapRegistry,
)

# The one registry per process. Never rebind; see ENABLEMENT above.
REGISTRY = TapRegistry()

# MAIN function name -> short label qualifying tap names. Never rebind.
MAIN_LABELS = {}


def _qualified(name):
    """`<label>/<name>`, from whichever MAIN is currently executing."""
    main = getattr(pypeline, "_sim_current_main", None)
    if main is None:
        return name
    label = getattr(main, "__name__", "")
    return (MAIN_LABELS.get(label, label) or "?") + "/" + name


# --- the per-cycle epoch --------------------------------------------------
# @sim_output bodies run only in each cycle's final, converged pass (also
# inside Feedback[T] convergence loops), so a probe normally fires once per
# cycle. Every tap still buffers one sample and commits it when the epoch
# changes (stream_perf._EpochTap), so a cycle is never counted twice whatever
# the evaluation order. @sim_input is the right clock: its result cache is
# cleared exactly once per simulated cycle (once per outermost sim_call), so
# this body runs exactly once per cycle no matter which MAIN reaches a probe
# first. Mutated IN PLACE, for the same detached-globals reason REGISTRY is
# never rebound.
_EPOCH = [0]


@sim_input
def _epoch_tick():
    _EPOCH[0] = _EPOCH[0] + 1
    return 0


def _keep_count(keep):
    """Popcount of a `keep` array, as bytes. None if it is not an array (so a
    probe can pass `None` to mean 'no byte accounting on this edge')."""
    if keep is None:
        return None
    try:
        n = len(keep)
    except TypeError:
        return None
    return sum(1 for i in range(n) if keep[i])


def _data_keep(data):
    """A stream word's `keep`: an AXIS fragment's `.frag.keep`, a bare
    kept-data bus's `.keep`, or None for a scalar word (counted in beats)."""
    frag = getattr(data, "frag", None)
    if frag is not None:
        return getattr(frag, "keep", None)
    return getattr(data, "keep", None)


# --- plain-Python workers (kept out of the @sim_output bodies, which are
# --- AST-rewritten; a one-line body keeps that rewriting trivial) ----------
def _note_hs(name, valid, ready, keep, epoch):
    if not REGISTRY.any_enabled():
        return
    tap = REGISTRY.tap(_qualified(name), HandshakeTap)
    tap.sample(epoch, (valid, ready, _keep_count(keep) if valid and ready else None))


def _note_state(name, value, names, epoch):
    if not REGISTRY.any_enabled():
        return
    REGISTRY.tap(_qualified(name), StateTap).sample(epoch, (value, names))


def _note_occupancy(name, in_valid, in_ready, out_valid, out_ready, capacity, epoch):
    if not REGISTRY.any_enabled():
        return
    REGISTRY.tap(_qualified(name), BufferTap).sample(
        epoch, (bool(in_valid and in_ready), bool(out_valid and out_ready), capacity)
    )


def _note_arb(name, sel, reqs, granted, labels, epoch):
    if not REGISTRY.any_enabled():
        return
    tap = REGISTRY.tap(_qualified(name), ArbTap, tuple(labels))
    tap.sample(epoch, (sel, tuple(reqs), granted))


# --- the probes -----------------------------------------------------------
@sim_output
def hs(name, valid, ready, keep=None):
    """Sample one valid/ready handshake for this cycle.

    `keep` is optional: pass a beat's keep array for exact byte accounting on
    that edge, or omit it where beats are the natural unit (a key, a tag, a
    compute launch).
    """
    _epoch_tick()
    _note_hs(name, valid, ready, keep, _EPOCH[0])


@sim_output
def stream_hs(name, valid, ready, data):
    """Sample a handshake given the stream word: bytes from its keep (AXIS
    fragment or kept-data bus), beats for a scalar word."""
    _epoch_tick()
    _note_hs(name, valid, ready, _data_keep(data), _EPOCH[0])


@sim_output
def occupancy(name, in_valid, in_ready, out_valid, out_ready, capacity_beats):
    """Track a buffer's occupancy from its input and output handshakes,
    against its total storage capacity in beats."""
    _epoch_tick()
    _note_occupancy(
        name, in_valid, in_ready, out_valid, out_ready, capacity_beats, _EPOCH[0]
    )


@sim_output
def state(name, value, names=None):
    """Sample one FSM state register for this cycle.

    `names` is a module-level tuple of member names in DECLARATION order --
    pypeline `@enum` with auto() numbers members 0..n-1 in that order, so the
    state value indexes it directly.
    """
    _epoch_tick()
    _note_state(name, value, names, _EPOCH[0])


@sim_output
def arb(name, sel_a, req_a, req_b, granted, label_a="a", label_b="b"):
    """Sample a two-way arbitrated resource for this cycle.

    `sel_a` is true when the mux points at requester A; `granted` is the
    resource's ready. See `arb_n` for more than two requesters.
    """
    _epoch_tick()
    _note_arb(
        name, 0 if sel_a else 1, (req_a, req_b), granted, (label_a, label_b), _EPOCH[0]
    )


@sim_output
def arb_n(name, sel, reqs, granted, labels):
    """Sample an N-way arbitrated resource: `sel` is the selected requester's
    index, `reqs` a tuple of request bits, `labels` their names."""
    _epoch_tick()
    _note_arb(name, sel, reqs, granted, labels, _EPOCH[0])


# --- probed buffers -------------------------------------------------------
def make_probed_stream_fifo(data_t, depth: int, tap_name: str, mode: str = "fwft"):
    """`make_stream_fifo` with probes on both handshakes and its occupancy:
    taps `<tap_name>.in`, `<tap_name>.out` and `<tap_name>.occupancy`. Same
    ports, result type and attributes as `make_stream_fifo`, plus
    `.capacity_beats` (memory rounded to a power of two + the FWFT output
    register) and `.tap_name`. The probes add no hardware.
    """
    fifo, result_t = make_stream_fifo(data_t, depth, mode)
    intrf = fifo.stream_intrf
    capacity = fifo.capacity_beats

    @hw_func
    def probed_stream_fifo(
        in_stream_if: intrf.fwd_t, out_stream_if: intrf.fb_t
    ) -> result_t:
        result = fifo(in_stream_if=in_stream_if, out_stream_if=out_stream_if)
        stream_hs(tap_name + ".in", in_stream_if.stream.valid,
                  result.in_stream_if.ready, in_stream_if.stream.data)
        stream_hs(tap_name + ".out", result.out_stream_if.stream.valid,
                  out_stream_if.ready, result.out_stream_if.stream.data)
        occupancy(tap_name + ".occupancy", in_stream_if.stream.valid,
                  result.in_stream_if.ready, result.out_stream_if.stream.valid,
                  out_stream_if.ready, capacity)
        return result

    probed_stream_fifo.stream_intrf = intrf
    probed_stream_fifo.fwd_t = fifo.fwd_t
    probed_stream_fifo.fb_t = fifo.fb_t
    probed_stream_fifo.depth = depth
    probed_stream_fifo.capacity_beats = capacity
    probed_stream_fifo.tap_name = tap_name
    return probed_stream_fifo, result_t


def make_probed_skid_buffer(data_t_or_intrf, tap_name: str, mode: str = "full"):
    """`make_skid_buffer` with probes on both handshakes and its occupancy
    (taps `<tap_name>.in`/`.out`/`.occupancy`, capacity = its slot count).
    Same ports, result type and attributes as `make_skid_buffer`, plus
    `.capacity_beats` and `.tap_name`. The probes add no hardware.
    """
    skid, result_t = make_skid_buffer(data_t_or_intrf, mode)
    intrf = skid.stream_intrf
    capacity = skid.n_slots

    @hw_func
    def probed_skid_buffer(
        stream_in_if: intrf.fwd_t, stream_out_if: intrf.fb_t
    ) -> result_t:
        result = skid(stream_in_if=stream_in_if, stream_out_if=stream_out_if)
        stream_hs(tap_name + ".in", stream_in_if.stream.valid,
                  result.stream_in_if.ready, stream_in_if.stream.data)
        stream_hs(tap_name + ".out", result.stream_out_if.stream.valid,
                  stream_out_if.ready, result.stream_out_if.stream.data)
        occupancy(tap_name + ".occupancy", stream_in_if.stream.valid,
                  result.stream_in_if.ready, result.stream_out_if.stream.valid,
                  stream_out_if.ready, capacity)
        return result

    for attr in ("stream_intrf", "fwd_t", "fb_t", "data_t", "mode", "n_slots", "latency"):
        setattr(probed_skid_buffer, attr, getattr(skid, attr))
    probed_skid_buffer.capacity_beats = capacity
    probed_skid_buffer.tap_name = tap_name
    return probed_skid_buffer, result_t
