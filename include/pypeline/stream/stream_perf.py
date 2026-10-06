"""Plain-Python (no pypeline import) throughput/latency measurement for
valid/ready streams in native simulation.

Everything here is cycle-domain only -- cycles, beats, bytes. Nothing is
converted to MHz or Gb/s, so a measured run can be re-expressed at any fmax
later without re-simulating (stream_perf_report.derive_throughput does that).

Two halves, usable separately:

- Internal taps. `HandshakeTap`/`StateTap`/`ArbTap`/`BufferTap` (owned by a
  `TapRegistry`) count one handshake, FSM state register, two-way arbiter or
  buffer occupancy per cycle. They are fed from probe calls placed inside a
  design's own hardware functions -- see stream_perf_probe.py, the only part
  that imports pypeline -- or from a plain `sim_call` loop calling `note(...)`
  directly. stream_bottleneck.py turns their snapshots into per-block
  throughput and a bottleneck verdict.

- Boundary measurement. `StreamMeter` accounts one input/output stream pair
  per cycle (beats, bytes, per-packet latency, sustained rate);
  `PhaseRunner` drives a phase plan of back-to-back packets through it, with a
  `PhaseBarrier` keeping several concurrent streams in the same phase and a
  `PerfRecorder` (re)writing the JSON after every phase.

See pypeline_stream_perf_guide.md (same directory) for the metric
definitions and a worked example.
"""

import json
import os
import random
import statistics


class _EpochTap:
    """Common sampling discipline for every tap.

    `note(...)` commits a sample immediately. `sample(epoch, ...)` buffers one
    and commits the PREVIOUS one when the epoch changes, so however many times
    a probe fires within one cycle, exactly one (the last) sample counts.
    In-design probes use the latter. Pypeline already runs `@sim_output` only
    in each cycle's final, converged pass -- including inside a `Feedback[T]`
    body's convergence loop -- so a probe normally fires once per cycle; the
    epoch keeps that invariant even if a body were evaluated twice, and
    stream_bottleneck.check_taps reports any tap whose cycle count disagrees.

    stream_perf_probe.py derives the epoch from a `@sim_input`, whose cache
    pypeline clears exactly once per simulated cycle, so it is independent of
    MAIN ordering and of how many convergence passes ran.
    """

    def __init__(self, name):
        self.name = name
        self._epoch = None
        self._pending = None
        self.reset()

    def sample(self, epoch, args):
        if self._pending is not None and epoch != self._epoch:
            self._commit(self._pending)
        self._epoch = epoch
        self._pending = args

    def flush(self):
        """Commit the buffered sample -- called before every snapshot, so the
        last cycle of a phase is not silently dropped at the phase boundary."""
        if self._pending is not None:
            self._commit(self._pending)
            self._pending = None
            self._epoch = None

    def _commit(self, args):
        raise NotImplementedError


class HandshakeTap(_EpochTap):
    """Per-cycle valid/ready accounting for ONE handshake -- the unit of
    internal bottleneck analysis.

    Every cycle is exactly one of four classes, which is what makes
    attribution automatic:

        xfer     valid &  ready   a beat moved
        stall    valid & ~ready   CONSUMER backpressured the producer
        starved ~valid &  ready   consumer was ready, PRODUCER had nothing
        idle    ~valid & ~ready   neither side had anything to do

    A block that is the bottleneck shows high `stall` on its own input while
    everything downstream of it shows high `starved`. The two derived numbers
    that matter most:

      `service_period_cycles` = offered/xfer -- cycles per accepted beat *while
        work is being offered*. This is the block's throughput ceiling in
        situ, independent of how often it is fed: a multi-cycle block that
        re-arms every 6 cycles reads 6.0, an II=1 pipeline reads 1.0.
      `accept_rate` = xfer/offered -- the same thing as a fraction (1/period).

    Deliberately an offered/accepted ratio rather than a trimmed steady-state
    window: accepts are usually bursty, so a windowed rate would describe the
    burst, not the block.
    """

    kind = "handshake"

    def _commit(self, args):
        if args[0] and args[1] and self._epoch is not None:
            cycle = self._epoch - 1  # the probe epoch is 1 on simulation cycle 0
            if self.first_transfer_cycle is None:
                self.first_transfer_cycle = cycle
            self.last_transfer_cycle = cycle
        self.note(*args)

    def reset(self):
        self.cycles = 0
        self.valid_cycles = 0
        self.ready_cycles = 0
        self.xfer_cycles = 0
        self.stall_cycles = 0  # valid & ~ready: consumer backpressures producer
        self.starved_cycles = 0  # ~valid & ready: consumer idle, producer dry
        self.idle_cycles = 0  # ~valid & ~ready
        self.bytes = 0
        self.has_bytes = False
        self.first_transfer_cycle = None
        self.last_transfer_cycle = None

    def note(self, valid, ready, nbytes=None):
        valid = 1 if valid else 0
        ready = 1 if ready else 0
        self.cycles += 1
        self.valid_cycles += valid
        self.ready_cycles += ready
        if valid and ready:
            self.xfer_cycles += 1
            if nbytes is not None:
                self.has_bytes = True
                self.bytes += int(nbytes)
        elif valid:
            self.stall_cycles += 1
        elif ready:
            self.starved_cycles += 1
        else:
            self.idle_cycles += 1

    def snapshot(self):
        window = self.cycles or 1
        offered = self.xfer_cycles + self.stall_cycles
        snap = {
            "kind": self.kind,
            "cycles": self.cycles,
            "valid_cycles": self.valid_cycles,
            "ready_cycles": self.ready_cycles,
            "xfer_cycles": self.xfer_cycles,
            "stall_cycles": self.stall_cycles,
            "starved_cycles": self.starved_cycles,
            "idle_cycles": self.idle_cycles,
            "first_transfer_cycle": self.first_transfer_cycle,
            "last_transfer_cycle": self.last_transfer_cycle,
            "offered_cycles": offered,
            # The block's in-situ ceiling: how it serves work that IS offered.
            "accept_rate": (self.xfer_cycles / offered) if offered else None,
            "service_period_cycles": (
                (offered / self.xfer_cycles) if self.xfer_cycles else None
            ),
            "beats_per_cycle": self.xfer_cycles / window,
            "duty": self.xfer_cycles / window,
            "stall_frac": self.stall_cycles / window,
            "starve_frac": self.starved_cycles / window,
            "idle_frac": self.idle_cycles / window,
        }
        if self.has_bytes:
            snap["bytes"] = self.bytes
            snap["bytes_per_cycle"] = self.bytes / window
            snap["bytes_per_beat"] = (
                (self.bytes / self.xfer_cycles) if self.xfer_cycles else None
            )
        return snap


class BufferTap(_EpochTap):
    """Occupancy reconstructed from converged input/output transfers of a
    FIFO or register slice, against its total storage capacity (for
    `make_stream_fifo`, the power-of-two memory plus the FWFT output register:
    see `stream_fifo_capacity_beats`).

    Occupancy survives a phase reset; counters do not, so a phase boundary
    cannot silently invent an empty buffer. No hardware occupancy counter or
    extra registers are introduced.
    """

    kind = "buffer"

    def __init__(self, name):
        self.occupancy = 0
        self.capacity = None
        super().__init__(name)

    def _commit(self, args):
        self.note(*args)

    def reset(self):
        self.cycles = 0
        self.start_occupancy = self.occupancy
        self.high_water = self.occupancy
        self.accepted = 0
        self.retired = 0
        self.simultaneous_cycles = 0
        self.full_cycles = 0
        self.empty_cycles = 0

    def note(self, accepted, retired, capacity):
        accepted, retired, capacity = int(bool(accepted)), int(bool(retired)), int(capacity)
        if self.capacity is not None and self.capacity != capacity:
            raise ValueError(self.name + ": buffer capacity changed during simulation")
        self.capacity = capacity
        self.cycles += 1
        self.empty_cycles += self.occupancy == 0
        self.full_cycles += self.occupancy == capacity
        self.accepted += accepted
        self.retired += retired
        self.simultaneous_cycles += accepted and retired
        self.occupancy += accepted - retired
        if not 0 <= self.occupancy <= capacity:
            raise ValueError(self.name + ": FIFO occupancy outside physical capacity")
        self.high_water = max(self.high_water, self.occupancy)

    def snapshot(self):
        return {
            "kind": self.kind, "cycles": self.cycles, "capacity_beats": self.capacity,
            "start_occupancy": self.start_occupancy, "end_occupancy": self.occupancy,
            "high_water_beats": self.high_water, "accepted_beats": self.accepted,
            "retired_beats": self.retired, "simultaneous_cycles": self.simultaneous_cycles,
            "full_cycles": self.full_cycles, "empty_cycles": self.empty_cycles,
        }


class StateTap(_EpochTap):
    """Cycles-per-FSM-state histogram for one state register.

    Turns "the block is slow" into "the block spent 83% of its cycles in
    WAIT_COMPUTE", which names the mechanism rather than the symptom. Pypeline
    `@enum` members declared with auto() are 0-based in declaration order, so a
    names tuple in declaration order indexes directly by value.
    """

    kind = "state"

    def __init__(self, name):
        self.state_names = ()
        super().__init__(name)

    def _commit(self, args):
        self.note(*args)

    def reset(self):
        self.cycles = 0
        self.counts = {}

    def note(self, value, names=None):
        if names and not self.state_names:
            self.state_names = tuple(str(n) for n in names)
        self.cycles += 1
        key = int(value)
        self.counts[key] = self.counts.get(key, 0) + 1

    def name_of(self, value):
        if 0 <= value < len(self.state_names):
            return self.state_names[value]
        return f"state_{value}"

    def snapshot(self):
        window = self.cycles or 1
        states = {}
        for value, count in sorted(self.counts.items()):
            states[self.name_of(value)] = {"cycles": count, "frac": count / window}
        dominant = None
        if states:
            dominant = max(states, key=lambda k: states[k]["cycles"])
        return {
            "kind": self.kind,
            "cycles": self.cycles,
            "states": states,
            "dominant": dominant,
        }


class ArbTap(_EpochTap):
    """Arbitration accounting for a resource shared by several requesters.

    Samples the arbiter's actual selection. Every cycle a requester wants the
    resource is exactly one of:

      xfer         its slot, resource ready -- launched
      blocked      its slot, resource NOT ready -- the resource is busy or its
                   output is backpressured (including head-of-line blocking
                   behind another requester's stalled results)
      contention   another side's slot, and that side wanted it too -- the
                   real cost of sharing
      wasted_slot  the selected side had no request. Zero for a
                   request-aware arbiter; an arbiter that alternates
                   unconditionally wastes every other slot when only one side
                   has work

    `note(sel, reqs, granted)`: `sel` is the index the mux points at this cycle,
    `reqs` the per-requester valid bits, `granted` the resource's ready.
    """

    kind = "arb"

    def __init__(self, name, labels=("a", "b")):
        self.labels = tuple(labels)
        super().__init__(name)

    def _commit(self, args):
        self.note(*args)

    def reset(self):
        n = len(self.labels)
        self.cycles = 0
        self.granted_ready_cycles = 0
        self.sel_cycles = [0] * n
        self.req_cycles = [0] * n
        self.xfer_cycles = [0] * n
        self.blocked_cycles = [0] * n
        self.contention_cycles = [0] * n
        self.wasted_slot_cycles = [0] * n

    def note(self, sel, reqs, granted):
        sel = int(sel)
        reqs = [1 if r else 0 for r in reqs]
        granted = 1 if granted else 0
        self.cycles += 1
        self.granted_ready_cycles += granted
        if 0 <= sel < len(self.sel_cycles):
            self.sel_cycles[sel] += 1
        sel_wants = reqs[sel] if 0 <= sel < len(reqs) else 0
        for i, req in enumerate(reqs):
            self.req_cycles[i] += req
            if not req:
                continue
            if i == sel:
                if granted:
                    self.xfer_cycles[i] += 1
                else:
                    self.blocked_cycles[i] += 1
            elif sel_wants:
                self.contention_cycles[i] += 1
            else:
                self.wasted_slot_cycles[i] += 1

    def snapshot(self):
        window = self.cycles or 1
        per = {}
        for i, label in enumerate(self.labels):
            req = self.req_cycles[i] or 1
            per[label] = {
                "req_cycles": self.req_cycles[i],
                "sel_cycles": self.sel_cycles[i],
                "xfer_cycles": self.xfer_cycles[i],
                "blocked_cycles": self.blocked_cycles[i],
                "blocked_frac": self.blocked_cycles[i] / req,
                "contention_cycles": self.contention_cycles[i],
                "wasted_slot_cycles": self.wasted_slot_cycles[i],
                # Of the cycles this side wanted the resource, how often it lost
                # the slot -- split by whether losing it was necessary.
                "arb_loss_frac": (
                    self.contention_cycles[i] + self.wasted_slot_cycles[i]
                )
                / req,
                "contention_frac": self.contention_cycles[i] / req,
                "wasted_slot_frac": self.wasted_slot_cycles[i] / req,
            }
        return {
            "kind": self.kind,
            "cycles": self.cycles,
            "labels": list(self.labels),
            "granted_ready_frac": self.granted_ready_cycles / window,
            "per_requester": per,
        }


class NullTap:
    """A tap that was not enabled this run: every call is a no-op. Accepts any
    tap's note() signature so probe call sites never branch on availability."""

    name = None
    kind = "null"

    def note(self, *args, **kwargs):
        pass

    def sample(self, *args, **kwargs):
        pass

    def flush(self):
        pass

    def reset(self):
        pass

    def snapshot(self):
        return None


class TapRegistry:
    """Name -> tap for the taps enabled this run; unknown/disabled names get a
    NullTap.

    Names are `<label>/<block>.<port>` (e.g. `encrypt/poly1305.data_in`), the
    label coming from the MAIN the probe fired under -- see
    stream_perf_probe.MAIN_LABELS. `enable()` accepts exact names, a
    `<label>/` or `<block>` prefix, or the literal "all", so `poly1305` picks
    up every label's `poly1305.*` taps.
    """

    ALL = "all"

    def __init__(self, enabled=()):
        self.enabled = []
        self._taps = {}
        self._null = NullTap()
        self._lookup = {}
        self.enable(enabled)

    # ---- enablement -------------------------------------------------------
    def enable(self, names):
        for name in names or ():
            name = str(name).strip()
            if name and name not in self.enabled:
                self.enabled.append(name)
        self._lookup.clear()

    def any_enabled(self):
        return bool(self.enabled)

    def _matches(self, full_name):
        if not self.enabled:
            return False
        bare = full_name.split("/", 1)[-1]
        for token in self.enabled:
            if token == self.ALL:
                return True
            if token == full_name or token == bare:
                return True
            if full_name.startswith(token) or bare.startswith(token):
                return True
        return False

    # ---- tap access -------------------------------------------------------
    def tap(self, full_name, factory=HandshakeTap, *args, **kwargs):
        """Return the tap for `full_name`, creating it on first use. Result is
        cached per name, so a probe call site costs one dict hit per cycle."""
        cached = self._lookup.get(full_name)
        if cached is not None:
            return cached
        tap = (
            factory(full_name, *args, **kwargs)
            if self._matches(full_name)
            else self._null
        )
        self._lookup[full_name] = tap
        if tap is not self._null:
            self._taps[full_name] = tap
        return tap

    def active_names(self):
        """Names that actually matched a probe call site and fired this run. An
        enabled name that never appears here did not match anything."""
        return sorted(self._taps)

    def snapshot(self):
        for tap in self._taps.values():
            tap.flush()
        return {name: tap.snapshot() for name, tap in sorted(self._taps.items())}

    def reset(self):
        for tap in self._taps.values():
            tap.reset()


def stream_fifo_capacity_beats(depth):
    """Total words a `make_stream_fifo(data_t, depth)` can hold: its memory
    rounds up to a power of two, plus the separate FWFT output register."""
    return (1 << (int(depth) - 1).bit_length()) + 1


# ---------------------------------------------------------------------------
# Boundary measurement: phase plan, meter, runner, barrier, recorder
# ---------------------------------------------------------------------------
def packet_size_phases(
    sizes, packets, peak_bytes=0, peak_packets=None, max_packet_bytes=None
):
    """A throughput-vs-packet-size phase plan: one phase of `packets`
    back-to-back packets per size (named `b2b-<size>`), then an optional
    `peak-<peak_bytes>` phase of `peak_packets` (default `packets`) long ones.

    `max_packet_bytes` is the design's hard limit (e.g. a store-and-forward
    buffer's capacity); a size beyond it would deadlock rather than measure, so
    it raises here instead.
    """
    phases = [
        {"name": f"b2b-{size}", "packet_bytes": size, "num_packets": packets}
        for size in sizes
    ]
    if peak_bytes:
        phases.append(
            {
                "name": f"peak-{peak_bytes}",
                "packet_bytes": peak_bytes,
                "num_packets": packets if peak_packets is None else peak_packets,
            }
        )
    for phase in phases:
        if phase["packet_bytes"] <= 0 or (
            max_packet_bytes is not None and phase["packet_bytes"] > max_packet_bytes
        ):
            limit = "" if max_packet_bytes is None else f"..{max_packet_bytes}"
            raise ValueError(
                f"phase {phase['name']}: packet_bytes must be in 1{limit}, got "
                f"{phase['packet_bytes']}"
            )
    return phases


class PhaseBarrier:
    """Keeps every participant in the same phase: a participant that has
    drained `arrive()`s and waits until all have, so each phase measures the
    same packet size under the same contention on any shared resource."""

    def __init__(self, participants):
        self.participants = list(participants)
        self._arrived = {}

    def arrive(self, who, phase_idx):
        self._arrived.setdefault(phase_idx, set()).add(who)

    def released(self, phase_idx):
        return len(self._arrived.get(phase_idx, ())) >= len(self.participants)


class PerfRecorder:
    """Collects every participant's per-phase results and (re)writes the JSON
    after every completed phase, so a killed or hung run still leaves usable
    data behind. `path=""` keeps everything in memory only."""

    def __init__(self, path, config, source="perf_tb"):
        self.path = path
        self.config = dict(config)
        self.source = source
        self.phases = {}  # phase_idx -> {"name":..., "<runner name>": {...}, ...}
        self.errors = []
        self.packets_checked = 0
        self.finalized = False
        self.total_cycles = None
        self._taps_done = set()  # phase indices whose taps were already taken

    def _entry(self, phase_idx, phase):
        return self.phases.setdefault(
            phase_idx,
            {
                "name": phase["name"],
                "packet_bytes": phase["packet_bytes"],
                "num_packets": phase["num_packets"],
            },
        )

    def record_phase(self, phase_idx, phase, direction, result, taps=None):
        entry = self._entry(phase_idx, phase)
        entry[direction] = result
        if taps:
            entry["taps"] = taps
        if result.get("timed_out"):
            entry["timed_out"] = True
        self.write()

    def record_taps(self, phase_idx, phase, registry):
        """Snapshot and zero the internal taps for one phase, exactly once.

        Every runner calls this on the same cycle (the barrier release that
        ends the phase); the first caller wins, so the counters are never split
        across two half-windows. The tap window is barrier-to-barrier -- a bit
        wider than a runner's own `window_cycles`, since it also covers the
        drain and settle cycles at the end of the phase -- which is what makes
        the per-tap fractions comparable across phases.
        """
        if registry is None or phase_idx in self._taps_done:
            return
        self._taps_done.add(phase_idx)
        snapshot = registry.snapshot()
        registry.reset()
        if not snapshot:
            return
        self._entry(phase_idx, phase)["taps"] = snapshot
        self.write()

    def note_error(self, message):
        # Bounded: a systematically broken run must not grow the JSON without
        # limit (or hide the first, most useful, failure behind thousands).
        if len(self.errors) < 100:
            self.errors.append(message)

    def as_dict(self):
        return {
            "schema_version": 1,
            "source": self.source,
            "config": self.config,
            "phases": [self.phases[i] for i in sorted(self.phases)],
            "checks": {
                "functional_pass": not self.errors,
                "packets_checked": self.packets_checked,
                "errors": self.errors,
            },
            "sim": {"total_cycles": self.total_cycles, "finalized": self.finalized},
        }

    def write(self):
        if not self.path:
            return
        tmp = self.path + ".tmp"
        d = os.path.dirname(os.path.abspath(self.path))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(self.as_dict(), f, indent=1, sort_keys=False)
        os.replace(tmp, self.path)

    def finalize(self, total_cycles=None):
        self.total_cycles = total_cycles
        self.finalized = True
        self.write()


def _median(values):
    return statistics.median(values) if values else None


class StreamMeter:
    """Per-cycle measurement of one stream pair: packets in on one interface,
    packets out on another. `note_in`/`note_out` are idempotent per cycle (so
    a convergence re-entry can never double-count) and `tick()` advances the
    cycle counter -- call it last, once per cycle.
    """

    STEADY_MIN_BEATS = 20
    STEADY_MIN_SPAN_CYCLES = 8

    def __init__(self, name, bus_bytes):
        self.name = name
        self.bus_bytes = bus_bytes
        self.cycle = 0
        self._in_noted_cycle = -1
        self._out_noted_cycle = -1
        self.reset_phase()

    def reset_phase(self):
        self.window_cycles_counted = 0
        self.in_valid_cycles = 0
        self.in_accepted_beats = 0
        self.in_stall_cycles = 0
        self.in_bytes = 0
        self.out_beats = 0
        self.out_bytes = 0
        self.first_in_cycle = None
        self.last_in_cycle = None
        self.first_out_cycle = None
        self.last_out_cycle = None
        self._in_packet_open = False
        self._out_packet_open = False
        self.in_packets = []  # [{"first_in":c, "last_in":c, "bytes":n}, ...]
        self.out_packets = []  # [{"first_out":c, "last_out":c, "bytes":n}, ...]
        self.out_trace = []  # [(cycle, cumulative_out_bytes)] for steady-state rate
        self.in_trace = []  # [(cycle, cumulative_accepted_in_bytes)], likewise
        self.last_activity_cycle = self.cycle

    # ---- input side, called once per cycle after convergence -------------
    def note_in(self, valid, ready, keep_count, eod):
        if self._in_noted_cycle == self.cycle:
            return False
        self._in_noted_cycle = self.cycle
        valid = 1 if valid else 0
        ready = 1 if ready else 0
        if valid:
            self.in_valid_cycles += 1
        accepted = bool(valid and ready)
        if valid and not ready:
            self.in_stall_cycles += 1
        if not accepted:
            return False
        self.in_accepted_beats += 1
        self.in_bytes += keep_count
        self.in_trace.append((self.cycle, self.in_bytes))
        self.last_activity_cycle = self.cycle
        if self.first_in_cycle is None:
            self.first_in_cycle = self.cycle
        self.last_in_cycle = self.cycle
        if not self._in_packet_open:
            self.in_packets.append(
                {"first_in": self.cycle, "last_in": self.cycle, "bytes": 0}
            )
            self._in_packet_open = True
        pkt = self.in_packets[-1]
        pkt["last_in"] = self.cycle
        pkt["bytes"] += keep_count
        if eod:
            self._in_packet_open = False
        return True

    # ---- output side, called once per cycle after convergence ------------
    def note_out(self, valid, keep_count, eod):
        """Count one output beat; pass `valid` as the TRANSFER (valid & ready)
        if the consumer can backpressure. Returns True on the cycle an output
        packet completes (its eod beat)."""
        if self._out_noted_cycle == self.cycle:
            return False
        self._out_noted_cycle = self.cycle
        if not valid:
            return False
        self.out_beats += 1
        self.out_bytes += keep_count
        self.last_activity_cycle = self.cycle
        if self.first_out_cycle is None:
            self.first_out_cycle = self.cycle
        self.last_out_cycle = self.cycle
        self.out_trace.append((self.cycle, self.out_bytes))
        if not self._out_packet_open:
            self.out_packets.append(
                {"first_out": self.cycle, "last_out": self.cycle, "bytes": 0}
            )
            self._out_packet_open = True
        pkt = self.out_packets[-1]
        pkt["last_out"] = self.cycle
        pkt["bytes"] += keep_count
        if eod:
            self._out_packet_open = False
            return True
        return False

    def tick(self):
        """Once per cycle, after note_in/note_out."""
        self.window_cycles_counted += 1
        self.cycle += 1

    # ---- results ---------------------------------------------------------
    def _steady_bytes_per_cycle(self, trace):
        """Byte rate over the middle 80% of `trace`'s beats -- excludes
        fill/drain. A DIAGNOSTIC for burst behaviour, not a throughput figure:
        when packets are processed serially with gaps between them it measures
        "how fast bytes move while they are moving" (an input accepted in one
        burst per packet reads near the bus width, and a store-and-forward
        output drains at the bus width however slowly the packet was
        processed). The sustained number is `sustained_bytes_per_cycle`.
        """
        n = len(trace)
        # Needs enough beats that the middle 80% is a real window: with only a
        # handful of beats the trimmed span can collapse to one or two cycles
        # and report a meaningless burst rate (e.g. 16 B / 1 cycle).
        if n < self.STEADY_MIN_BEATS:
            return None
        lo = int(0.1 * n)
        hi = int(0.9 * n) - 1
        if hi <= lo:
            return None
        c_lo, b_lo = trace[lo]
        c_hi, b_hi = trace[hi]
        if c_hi - c_lo < self.STEADY_MIN_SPAN_CYCLES:
            return None
        return (b_hi - b_lo) / (c_hi - c_lo)

    def phase_result(self, phase, timed_out=False):
        goodput_bytes = phase["packet_bytes"] * phase["num_packets"]
        if self.first_in_cycle is None or self.last_out_cycle is None:
            window = None
        else:
            window = self.last_out_cycle - self.first_in_cycle + 1
        packets = []
        heads = []
        totals = []
        for idx, out_pkt in enumerate(self.out_packets):
            in_pkt = self.in_packets[idx] if idx < len(self.in_packets) else None
            head = total = None
            if in_pkt is not None:
                head = out_pkt["first_out"] - in_pkt["first_in"]
                total = out_pkt["last_out"] - in_pkt["first_in"]
                heads.append(head)
                totals.append(total)
            packets.append(
                {
                    "idx": idx,
                    "in_bytes": in_pkt["bytes"] if in_pkt else None,
                    "out_bytes": out_pkt["bytes"],
                    "first_in": in_pkt["first_in"] if in_pkt else None,
                    "last_in": in_pkt["last_in"] if in_pkt else None,
                    "first_out": out_pkt["first_out"],
                    "last_out": out_pkt["last_out"],
                    "head_latency": head,
                    "total_latency": total,
                }
            )
        # Sustained rate, averaged over same-size packets back to back: the mean
        # number of cycles between consecutive packet completions. This drops the
        # first packet's pipeline-fill cost entirely (it measures period, not
        # end-to-end time), so it is the number that extrapolates to a long
        # stream of this packet size -- whereas `bytes_per_cycle` over the whole
        # window still carries the one-off fill of the phase's first packet.
        # Needs at least 2 completed packets.
        packet_period = None
        sustained = None
        if len(self.out_packets) >= 2:
            span = self.out_packets[-1]["last_out"] - self.out_packets[0]["last_out"]
            intervals = len(self.out_packets) - 1
            packet_period = span / intervals
            if packet_period > 0:
                sustained = phase["packet_bytes"] / packet_period

        w = window or 1
        return {
            "window_cycles": window,
            "goodput_bytes": goodput_bytes,
            "in_beats": self.in_accepted_beats,
            "out_beats": self.out_beats,
            "in_line_bytes": self.in_accepted_beats * self.bus_bytes,
            "out_line_bytes": self.out_beats * self.bus_bytes,
            "in_payload_bytes": self.in_bytes,
            "out_payload_bytes": self.out_bytes,
            "beats_per_packet": (
                self.out_beats / phase["num_packets"] if phase["num_packets"] else None
            ),
            "bytes_per_cycle": (goodput_bytes / window) if window else None,
            "packet_period_cycles": packet_period,
            "sustained_bytes_per_cycle": sustained,
            "steady_in_bytes_per_cycle": self._steady_bytes_per_cycle(self.in_trace),
            "steady_out_bytes_per_cycle": self._steady_bytes_per_cycle(self.out_trace),
            "in_duty": self.in_accepted_beats / w,
            "out_duty": self.out_beats / w,
            "in_stall_cycles": self.in_stall_cycles,
            "in_stall_frac": self.in_stall_cycles / w,
            "latency_cycles": {
                "cold_head": heads[0] if heads else None,
                "head_min": min(heads) if heads else None,
                "head_med": _median(heads),
                "head_max": max(heads) if heads else None,
                "total_min": min(totals) if totals else None,
                "total_med": _median(totals),
                "total_max": max(totals) if totals else None,
            },
            "packets": packets,
            "packets_in": len(self.in_packets),
            "packets_out": len(self.out_packets),
            "timed_out": bool(timed_out),
            "first_in_cycle": self.first_in_cycle,
            "last_out_cycle": self.last_out_cycle,
        }


class PhaseRunner:
    """Drives one stream through a phase plan and records its metrics.

    `frame_builder(length, rng)` -> `(in_frame_bytes, expected_out_bytes, meta)`
    is the only stream-specific piece; `meta` is passed to
    `scoreboard.expect(expected_out, idx=..., **meta)`. `src` needs
    `send(frame)` and `idle()`, `snk` needs `empty()` -- e.g.
    `axi.axis_sim.ConvergedAxisSimSource`/`AxisSimSink`.

    Per cycle, from the testbench's converged `@sim_output`: `note_in(...)`,
    `note_out(...)`, `note_checked(...)` for every scoreboard result, then
    `tick()` last. `prepare_input()` (from `@sim_input`) queues a phase's
    packets the first time it is called in that phase.
    """

    IDLE_SETTLE_CYCLES = 8  # let DUT internals settle between phases

    def __init__(
        self,
        name,
        phases,
        barrier,
        recorder,
        src,
        snk,
        scoreboard,
        frame_builder,
        bus_bytes=16,
        seed=0,
        max_cycles_per_phase=None,
        settle_cycles=None,
        stall_timeout_cycles=None,
        taps=None,
    ):
        self.name = name
        self.phases = phases
        self.barrier = barrier
        self.recorder = recorder
        self.src = src
        self.snk = snk
        self.scoreboard = scoreboard
        self.frame_builder = frame_builder
        self.bus_bytes = bus_bytes
        self.seed = seed
        # Shared across runners (one registry per run); snapshotted per phase
        # by whichever runner reaches the barrier release first.
        self.taps = taps
        self.max_cycles_per_phase = max_cycles_per_phase
        # Fail fast on a real deadlock (a full/never-drained FIFO, a lost
        # handshake) instead of burning sim time up to max_cycles_per_phase.
        self.stall_timeout_cycles = stall_timeout_cycles
        self.settle_cycles = (
            self.IDLE_SETTLE_CYCLES if settle_cycles is None else settle_cycles
        )
        self.meter = StreamMeter(name, bus_bytes)
        self.phase_idx = 0
        self.queued = False
        self.checked = 0
        self.phase_start_cycle = 0
        self.drained_at = None
        self.reported = False
        # A runner with an empty plan is done immediately: it never queues, so
        # its source drives valid=0 all run long.
        self.done = self.phase_idx >= len(self.phases)
        self.pending_log = []  # human-readable lines for the TB to sim_print

    # ---- phase plumbing --------------------------------------------------
    @property
    def phase(self):
        if self.phase_idx < len(self.phases):
            return self.phases[self.phase_idx]
        return None

    def prepare_input(self):
        """Queue the whole phase's packets at once (the source streams them
        back-to-back with no inter-packet gap), from @sim_input."""
        phase = self.phase
        if phase is None or self.queued:
            return
        # A string seed hashes deterministically (a tuple holding a str would
        # follow PYTHONHASHSEED), so a given seed reproduces its payloads.
        rng = random.Random(f"{self.seed}/{self.phase_idx}/{self.name}")
        for idx in range(phase["num_packets"]):
            in_frame, expected_out, meta = self.frame_builder(
                phase["packet_bytes"], rng
            )
            self.scoreboard.expect(expected_out, idx=idx, **meta)
            self.src.send(in_frame)
        self.queued = True
        self.pending_log.append(
            f"{self.name}: phase {self.phase_idx} '{phase['name']}': "
            f"{phase['num_packets']} x {phase['packet_bytes']} B queued"
        )

    def note_in(self, valid, ready, keep_count, eod):
        self.meter.note_in(valid, ready, keep_count, eod)

    def note_out(self, valid, keep_count, eod):
        return self.meter.note_out(valid, keep_count, eod)

    def note_checked(self, passed, message=None):
        self.checked += 1
        self.recorder.packets_checked += 1
        if not passed:
            text = f"{self.name}: {message}"
            self.recorder.note_error(text)
            self.pending_log.append("ERROR: " + text)

    def tick(self):
        """Advance the phase state machine, then the cycle counter. Last thing
        in this runner's @sim_output."""
        phase = self.phase
        if phase is not None and self.queued and not self.reported:
            elapsed = self.meter.cycle - self.phase_start_cycle
            idle_for = self.meter.cycle - self.meter.last_activity_cycle
            timed_out = (
                self.max_cycles_per_phase is not None
                and elapsed > self.max_cycles_per_phase
            ) or (
                self.stall_timeout_cycles is not None
                and idle_for > self.stall_timeout_cycles
            )
            complete = (
                self.checked >= phase["num_packets"]
                and self.src.idle()
                and self.snk.empty()
            )
            if complete and self.drained_at is None:
                self.drained_at = self.meter.cycle
            settled = (
                self.drained_at is not None
                and self.meter.cycle - self.drained_at >= self.settle_cycles
            )
            if settled or timed_out:
                if timed_out:
                    self.recorder.note_error(
                        f"{self.name}: phase '{phase['name']}' timed out after "
                        f"{elapsed} cycles, idle {idle_for} "
                        f"({self.checked}/{phase['num_packets']} packets checked)"
                    )
                self.recorder.record_phase(
                    self.phase_idx,
                    phase,
                    self.name,
                    self.meter.phase_result(phase, timed_out=timed_out),
                )
                self.pending_log.append(
                    f"{self.name}: phase {self.phase_idx} '{phase['name']}' DONE"
                )
                self.reported = True
                self.barrier.arrive(self.name, self.phase_idx)
        # Every runner reported this phase: start the next one together.
        if self.reported and self.barrier.released(self.phase_idx):
            self.recorder.record_taps(self.phase_idx, phase, self.taps)
            self._next_phase()
        self.meter.tick()

    def _next_phase(self):
        self.phase_idx += 1
        self.queued = False
        self.checked = 0
        self.reported = False
        self.drained_at = None
        self.meter.reset_phase()
        self.phase_start_cycle = self.meter.cycle
        if self.phase is None:
            self.done = True

    def drain_log(self):
        lines = self.pending_log
        self.pending_log = []
        return lines
