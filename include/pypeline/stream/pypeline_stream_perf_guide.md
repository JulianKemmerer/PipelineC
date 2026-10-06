# Pypeline Stream Performance Library: Throughput, Latency & Bottlenecks

The library source lives in `include/pypeline/stream/` (same directory as this guide)
and in `include/pypeline/axi/axis_sim.py`.

This library measures a valid/ready stream design in native simulation:
- **how fast it is**: throughput versus packet size, per-packet latency, input stalls;
- **why**: which block holds it up, by how much, and what that block's FSM was doing.

It costs no hardware. The in-design probes are `@sim_output` calls, which the hardware
elaborator deletes. Everything is counted in cycles, beats and bytes; clock rates are
applied afterwards. So one simulated run can be re-expressed at any fmax, and a pipelined
`--sim` run measures exactly the build it just synthesized.

The library grew out of the QoR tooling in the
[wireguard-fpga](https://github.com/chili-chips-ba/wireguard-fpga) ChaCha20-Poly1305 port
(`3.build/pypeline_build/`).

| Module | Imports pypeline? | What it holds |
|---|---|---|
| `stream/stream_perf_probe.py` | yes | the in-design probes (`hs`, `stream_hs`, `state`, `occupancy`, `arb`, `arb_n`), `make_probed_stream_fifo`, `make_probed_skid_buffer`, the tap `REGISTRY`, `MAIN_LABELS` |
| `stream/stream_perf.py` | no | the taps (`HandshakeTap`, `StateTap`, `BufferTap`, `ArbTap`, `TapRegistry`), boundary measurement (`StreamMeter`, `PhaseRunner`, `PhaseBarrier`, `PerfRecorder`, `packet_size_phases`) |
| `stream/stream_bottleneck.py` | no | block-graph rollup, the bottleneck verdict, headline, markdown/CSV reports, buffer checks |
| `stream/stream_perf_report.py` | no | cycles → B/cycle, % line rate, Gb/s; summary, CSV, markdown table; README marker splicing |
| `axi/axis_sim.py` | no | `ConvergedAxisSimSource` / `ConvergedAxisSimSink` for testbench stimulus and checking |

The three plain-Python modules also re-analyze a saved results JSON offline, with no
build or simulator.

## The shortest useful example

Probe a block from inside its own hardware function. Then read the taps after the run:

```python
from pypeline import MAIN, Reg, final, hw_func, uint1_t, uint8_t
from stream import stream_bottleneck
from stream import stream_perf_probe as probe

fifo, fifo_t = probe.make_probed_stream_fifo(uint8_t, 4, "fifo")   # taps fifo.in/.out/.occupancy
COOLDOWN_NAMES = ("READY", "COOLDOWN")

@hw_func
def consumer(word: fifo.stream_intrf.stream_t) -> uint1_t:
    cooldown: Reg[uint8_t]
    probe.state("consumer.fsm", cooldown != 0, COOLDOWN_NAMES)  # state probes: TOP of the body
    ready = cooldown == 0
    if word.valid & ready:
        cooldown = 2
    elif cooldown != 0:
        cooldown = cooldown - 1
    probe.hs("consumer.in", word.valid, ready)                  # handshake probes: BOTTOM
    return ready

probe.REGISTRY.enable(["all"])

@final(sim=True)
def report():
    taps = probe.REGISTRY.snapshot()           # {"top/consumer.in": {...}, ...} under MAIN `top`
    print(taps["top/consumer.in"]["service_period_cycles"])   # ~3.0: one beat per 3 cycles
```

[`stream_perf_probe_test.py`](../../../src/tests/pypeline_tests/inst/stream_perf_probe_test.py)
is this example completed: a producer, the FIFO and two `Feedback`-closed chains under
two MAINs, with a bottleneck verdict.

## Probes: `stream_perf_probe`

| Probe | Samples, once per cycle |
|---|---|
| `hs(name, valid, ready, keep=None)` | one handshake; pass a `keep` array for byte accounting, omit it to count beats |
| `stream_hs(name, valid, ready, data)` | a handshake given the stream word; bytes come from `data.frag.keep` (AXIS) or `data.keep`, beats otherwise |
| `state(name, value, names=None)` | an FSM state register; `names` lists state names in declaration order (pypeline `@enum` members number 0..n-1) |
| `occupancy(name, in_valid, in_ready, out_valid, out_ready, capacity_beats)` | a buffer's fill, rebuilt from its two handshakes |
| `arb(name, sel_a, req_a, req_b, granted, label_a="a", label_b="b")` | a two-way arbiter: `sel_a` true when requester A has the slot, `granted` the resource's ready |
| `arb_n(name, sel, reqs, granted, labels)` | an N-way arbiter, `sel` an index |

Two factories wrap the common buffers. Each has the same ports, result type and
attributes as the plain factory, plus `.capacity_beats` and `.tap_name`:

- `make_probed_stream_fifo(data_t, depth, tap_name)`: capacity is the power-of-two memory
  plus the FWFT output register, `stream_perf.stream_fifo_capacity_beats(depth)`.
- `make_probed_skid_buffer(data_t_or_intrf, tap_name, mode="full")`: capacity is its
  slot count.

Each one probes `<tap_name>.in`, `<tap_name>.out` and `<tap_name>.occupancy`.

### Why they cost no hardware, and what they do cost

The elaborator deletes every `@sim_output` call, argument expressions included. So a probe
may be handed a `keep` array, a tuple of state names or anything else, without it becoming
logic. The generated VHDL of a probed FIFO is just the inner FIFO and its wiring.

Two things still touch synthesis caches:
- **Source line numbers.** Generated VHDL signal names embed them. Adding or moving a probe
  line renames signals in the enclosing hierarchy, so it costs one re-synthesis even though
  the logic is unchanged. Once the probes are in place, stimulus-only changes re-measure
  in simulation time alone.
- **Factory arguments.** These are encoded in entity names, like any factory-closure value.
  Renaming a probed buffer's `tap_name` renames its entity.

### Placement rules

1. **Plain `@hw_func` / `@MAIN` bodies only.** An `@interface_func` body only passes
   interface values between calls; probe a plain hw_func it calls instead.
2. **Stateful, zero-latency contexts only.** Never put a probe inside an `AUTO_PIPELINE`
   core or a pipelined pure MAIN. Pipelined native sim models those with delay lines, so
   the probe would see stage-0 values at the wrong cycle. FSMs and other `Reg`-holding
   functions are the natural sites.
3. **State probes at the top of a body, handshake probes at the bottom.** A `Reg` reads
   back its next value once assigned, so a state probe after the FSM logic would count
   next-states. Handshake probes need every `o.*` field final.

### Names, labels and enablement

In native simulation the simulator knows which MAIN it is executing, and a probe qualifies
its name with it: `<label>/<name>`. `MAIN_LABELS` maps MAIN function names to short labels.
For example, two direction-specific MAINs instantiating the same probed FSM become
`encrypt/...` and `decrypt/...`. An unlisted MAIN uses its own name. In a plain `sim_call`
loop there is no MAIN, and names stay bare.

A name identifies one call site per MAIN. If the same probed function is called twice
inside one MAIN, the two calls share a name and only one is counted. Give them distinct
names (a factory `tap_name` argument) or put them under different MAINs.

`REGISTRY.enable([...])` turns taps on. It accepts exact names, a `<label>/` or `<block>`
prefix, or `"all"`. Everything else gets a no-op `NullTap`, so a disabled probe costs one
call per cycle.

`REGISTRY` and `MAIN_LABELS` must only be mutated in place (`.enable(...)`,
`.update(...)`), never rebound. A `@sim_output` body runs against a detached copy of its
module's globals, so a rebound name would leave the probes writing to an orphan.

### Exactly once per cycle

Pypeline runs `@sim_output` only in each cycle's final, converged pass, including inside
a `Feedback[T]` body's convergence loop. A probe therefore fires once per cycle.

Taps also buffer one sample per cycle, keyed by an epoch that a `@sim_input` advances.
The cycle is committed when the epoch changes, so a cycle is never counted twice.
`stream_bottleneck.check_taps` checks that every tap in a phase saw the same number of
cycles. A spread there means some rate is inflated.

## Tap metrics

**Handshake taps** sort every cycle into exactly one of four classes. That partition is
what makes attribution automatic:

| metric | definition |
|---|---|
| `xfer_cycles` | `valid & ready`: a beat moved |
| `stall_cycles` | `valid & ~ready`: the **consumer** backpressured its producer. High here means this block is the slow one |
| `starved_cycles` | `~valid & ready`: the consumer was ready and the **producer** had nothing. High here means the slowness is upstream |
| `idle_cycles` | `~valid & ~ready`: neither side had work |
| `service_period_cycles` | `(xfer + stall) / xfer`: cycles per accepted beat **while work was offered**. This is the block's throughput ceiling in situ, independent of how often it is fed: an II=1 pipeline reads 1.0, a block that re-arms every 6 cycles reads 6.0 |
| `accept_rate` | `xfer / (xfer + stall)`, the same as a fraction |
| `bytes`, `bytes_per_cycle`, `bytes_per_beat` | with byte accounting (`keep` given) |
| `first_transfer_cycle` / `last_transfer_cycle` | simulation cycles of the first and last transfer in the phase |

These are offered/accepted ratios, not windowed rates. Accepts are usually bursty, so a
trimmed-window rate would describe the burst, not the block.

**State taps**: cycles per state (`states`, each with `cycles` and `frac`) and the
`dominant` state. They turn "the block is slow" into "it spent 83% of its cycles in
`WAIT_COMPUTE`".

**Buffer taps**:
- `capacity_beats`, `high_water_beats`;
- `start_occupancy` / `end_occupancy` (occupancy survives a phase reset; counters do not);
- `accepted_beats` / `retired_beats`, `simultaneous_cycles`, `full_cycles`, `empty_cycles`.

A buffer tap raises if occupancy ever leaves `0..capacity`.

**Arbitration taps** sort every cycle a requester wanted the resource into exactly one of:

| class | meaning |
|---|---|
| `xfer` | its slot, the resource was ready: launched |
| `blocked` | its slot, the resource was not ready (busy, or its output backpressured) |
| `contention` | another requester held the slot and wanted it: the real cost of sharing |
| `wasted_slot` | another requester held the slot with nothing to send. Zero for a request-aware arbiter; an arbiter that alternates unconditionally wastes every other slot when one side is idle |

## Boundary measurement: `stream_perf`

`StreamMeter` accounts one input/output stream pair per cycle. `PhaseRunner` drives it
through a **phase plan**:
- `packet_size_phases(sizes, packets, peak_bytes=0, peak_packets=None, max_packet_bytes=None)`
  builds the plan: N back-to-back packets of each size, then an optional peak phase.
  `max_packet_bytes` makes an over-sized packet raise at import, so a store-and-forward
  buffer can't deadlock instead of measuring.
- `PhaseBarrier` keeps several runners (e.g. two concurrent directions) in the same phase,
  so every packet size sees the same contention.
- `PerfRecorder` (re)writes the results JSON after every phase, so a killed run still
  leaves data.
- At each barrier release, the first runner snapshots and zeroes the tap registry into
  that phase's `"taps"`.

| metric (per runner, per phase) | definition |
|---|---|
| `window_cycles` | first accepted input beat → last output beat |
| `sustained_bytes_per_cycle` | **the throughput figure**: `packet_bytes / packet_period_cycles`, where the period is the mean cycles between consecutive packet completions. It drops the first packet's pipeline fill, so it is what a long stream of that size sustains. Needs at least 2 packets |
| `bytes_per_cycle` | goodput over the whole window, the conservative end-to-end number |
| `steady_in_bytes_per_cycle` / `steady_out_bytes_per_cycle` | **diagnostics, not throughput**: byte rate over the middle 80% of beats. A burst-accepted input reads near bus width, and a store-and-forward output drains at bus width, however slow the packet was |
| `in_duty` / `out_duty`, `in_stall_cycles` / `in_stall_frac` | accepted beats per window cycle; source backpressure |
| `latency_cycles` | `cold_head` (packet 0, empty pipeline, first in → first out), `head_*` and `total_*` (min/median/max, first in → first / last out) |
| `in_payload_bytes` / `out_payload_bytes` | exact byte accounting from `keep` |

A phase that sees no beat for `stall_timeout_cycles` is reported as timed out
(deadlocked) rather than running to the cycle cap.

### A complete testbench

Present stimulus from `@sim_input`, and commit and measure from `@sim_output` after the
cycle has converged. `ConvergedAxisSimSource` exists for this split. A plain source would
advance on a ready seen before convergence, which can still change when ready depends on
same-cycle logic (an arbiter, a fork). Its `drive()` presents the word and `commit(ready)`
advances it only on a real transfer. `ConvergedAxisSimSink.step(word, ready)` accepts only
real transfers and asserts that a stalled beat stays unchanged.

```python
from pypeline import MAIN, Feedback, Input, final, sim_finish, sim_input, sim_output, uint1_t
from axi.axis import make_axis_interface
from axi.axis_sim import ConvergedAxisSimSink, ConvergedAxisSimSource, Scoreboard
from stream import stream_perf_probe as probe
from stream.stream_perf import PerfRecorder, PhaseBarrier, PhaseRunner, packet_size_phases

BUS = 4
axis_intrf = make_axis_interface(BUS)
fifo, fifo_t = probe.make_probed_stream_fifo(axis_intrf.stream_t.typeof("data"), 8, "fifo")
out_slice, out_slice_t = probe.make_probed_skid_buffer(axis_intrf, "out_slice")
probe.MAIN_LABELS.update({"perf_tb": "dut"})
probe.REGISTRY.enable(["all"])

phases = packet_size_phases([32, 64], 4)
recorder = PerfRecorder("perf_raw.json", {"bus_bytes": BUS})
scoreboard = Scoreboard()
src = ConvergedAxisSimSource(axis_intrf, BUS)
snk = ConvergedAxisSimSink(axis_intrf, BUS, scoreboard=scoreboard)

def frame_builder(length, rng):           # -> (input frame, expected output, scoreboard meta)
    payload = bytes(rng.randrange(256) for _ in range(length))
    return payload, payload, {}

runner = PhaseRunner("dut", phases, PhaseBarrier(["dut"]), recorder, src, snk, scoreboard,
                     frame_builder, bus_bytes=BUS, stall_timeout_cycles=200,
                     taps=probe.REGISTRY)

# Stimulus reaches the design through module-level Input[T] wires: the same top then
# also elaborates (they become ports), which a pipelined --sim run needs.
tb_in_word: Input[axis_intrf.stream_t]
tb_out_ready: Input[uint1_t]
_cycle = [0]

def _nbytes(stream):
    return sum(1 for i in range(BUS) if stream.data.frag.keep[i]) if stream.valid else 0

@sim_input
def drive_in() -> axis_intrf.stream_t:
    runner.prepare_input()                 # queues the phase's packets once
    return src.drive().stream

@sim_input
def drive_out_ready() -> uint1_t:          # the consumer takes one beat every other cycle
    _cycle[0] += 1
    return _cycle[0] % 2

@sim_output
def measure(in_stream, in_ready, out_stream, out_ready):
    runner.note_in(in_stream.valid, in_ready, _nbytes(in_stream), in_stream.data.eod[0])
    src.commit(in_ready)
    moved = out_stream.valid and out_ready
    runner.note_out(moved, _nbytes(out_stream) if moved else 0, out_stream.data.eod[0])
    snk.step(axis_intrf.fwd_t(out_stream), out_ready)
    result = snk.check_nowait()
    if result is not None:
        runner.note_checked(result["passed"], "payload mismatch")
    runner.tick()                          # last: advances the phase machine and the cycle
    if runner.done:
        sim_finish()

@MAIN
def perf_tb() -> axis_intrf.fwd_t:
    slice_ready: Feedback[uint1_t]
    tb_in_word = drive_in()
    tb_out_ready = drive_out_ready()
    f = fifo(axis_intrf.fwd_t(stream=tb_in_word), axis_intrf.fb_t(ready=slice_ready))
    s = out_slice(f.out_stream_if, axis_intrf.fb_t(ready=tb_out_ready))
    slice_ready = s.stream_in_if.ready
    measure(tb_in_word, f.in_stream_if.ready, s.stream_out_if.stream, tb_out_ready)
    return s.stream_out_if

@final(sim=True)
def write_results():
    recorder.finalize(total_cycles=runner.meter.cycle)
```

`pypelinec perf_tb.py --sim --comb --run all` runs it. That top is
[`stream_perf_tb_test.py`](../../../src/tests/pypeline_tests/inst/stream_perf_tb_test.py)
less its result checks. It sustains 2.0 B/cycle: a 4-byte bus drained every other cycle.

Two cautions:
- Assign `@sim_input` results to an `Input[T]`, not a local. HDL elaboration currently
  mishandles a local (it errors for a compound type and can bake in a constant for a
  scalar), and a non-`--comb` run elaborates the top.
- Don't name a `@sim_output` parameter after a module-level wire: the wire name always
  wins inside its module.

The same classes work without a MAIN. Call `note_in`/`note_out`/`tick` around each
`sim_call` (see `test_probed_fifo_sim_call` in
[`stream_perf_test.py`](../../../src/tests/pypeline_tests/inst/stream_perf_test.py)).

## Bottleneck attribution: `stream_bottleneck`

Describe the design as a block graph, one entry per block:

```python
from stream import stream_bottleneck as sb

BLOCKS = {
    "fifo":      sb.block_spec("fifo.in", "fifo.out", downstream=("out_slice",)),
    "out_slice": sb.block_spec("out_slice.in", "out_slice.out", what="output register"),
    # consumes = the block's input handshake tap, produces = its output tap,
    # downstream = who consumes its output (a fork lists several),
    # state = an optional FSM state tap naming *why* it is slow
}
sb.analyze(raw["phases"], BLOCKS, labels=["dut"], bus_bytes=BUS)
```

For each phase and label, `analyze` adds the following (labels whose blocks moved
nothing are dropped):

- **`blocks`**: per block,
  - `bytes_per_cycle` (what it moved);
  - `ceiling_bytes_per_cycle` (bytes/beat ÷ service period, what it could move if never
    starved);
  - stall and starve fractions, the dominant FSM state.

  A block is **`relay_limited`** when its own output was backpressured at least as hard
  as its input (more than 2% of cycles, and at least 0.9× its input stall). Its input
  stall is then partly somebody else's, so its ceiling is only a **lower bound**, shown
  as `≥` in reports.
- **`bottleneck`**: the block that backpressured its producer hardest. The verdict walks
  downstream past blocks that only relay, following whichever consumer stalls hardest, so
  it names the origin rather than the nearest symptom. It carries a one-line `evidence`
  string: stall share, service period, ceiling, top FSM states, runner-up.
- **`taps_check`**: the once-per-cycle consistency check above.
- **`arbitration`**: every arbitration tap.

Reports:
- `markdown_blocks(phases, labels, blocks, compare=None, names=None, extra_sections=(), text=None)`
  gives the full report:
  - an optional headline comparing two blocks' ceilings ("X serves 10 B/cyc, Y 2.7 B/cyc,
    Y is the slower block by 3.8x; the whole datapath runs at 94% of Y's ceiling");
  - the block table, the per-phase bottleneck table and the arbitration table;
  - any design-specific `extra_sections`, then the buffer table.

  `text` overrides wording such as the label column header.
- `tap_rows` / `block_rows` with `TAP_CSV_COLUMNS` / `BLOCK_CSV_COLUMNS` give flat CSV rows.
- `best_ceiling` and `bottleneck_tally` support sweep-level summaries.
- `buffer_tap_errors(phase, {"<label>/<tap_name>": capacity}, taps_required, settled)`
  returns acceptance errors:
  - capacity mismatch or overflow;
  - transfer conservation (`start + accepted - retired == end`);
  - occupancy agreeing with the `.in`/`.out` handshakes;
  - nothing left buffered after a drained phase.

## Reports: `stream_perf_report`

- `derive_throughput(perf_raw, fmax_mhz, target_mhz, bus_bytes, labels)` converts the
  cycle-domain results. It adds `throughput_bytes_per_cycle` (sustained, or whole-window
  for a single-packet phase, as `throughput_basis` says), `line_rate_frac` and Gb/s at
  fmax and at the target clock. The fmax can come from any source, such as a pypelinec
  build's `sweep_history.json`.
- `summarize` gives per-phase headline numbers and per-runner peaks.
- `csv_rows` + `CSV_COLUMNS` and `write_csv` produce one CSV row per phase × runner.
- `markdown_boundary_table(phases, labels, fmax_mhz, target_mhz)` is the throughput and
  latency table, with one Gb/s column when fmax is the target.
- `splice_markers(text, begin, end, body)` replaces a marked region (e.g. HTML comments in
  a README), so measured numbers are never hand-copied.

## Workflow

1. **Iterate with `--comb`.** `pypelinec tb.py --sim --comb --run all` needs no synthesis,
   but the FSMs, multi-cycle paths and handshakes are all real. So every per-block number
   (service periods, ceilings, FSM histograms, the verdict) moves the moment a block gets
   faster.
2. **Score at real timing.** Without `--comb`, `--sim` synthesizes first (fmax, pipeline
   depths), then simulates exactly that build with its latencies modeled. Probes cost no
   hardware, and the phase plan lives in Python, so stimulus-only changes reuse the cached
   synthesis.
3. **Keep the raw JSON.** It is cycle-domain, so it can be re-analyzed or re-expressed at
   another clock later.

## Caveats

- **Consumer speed.** A sink that is always ready makes every throughput figure an upper
  bound with an infinitely fast consumer. Drive a ready pattern through the testbench to
  model a real one.
- **Measured windows differ.** A phase's tap window runs barrier to barrier, so it includes
  drain and settle cycles. A runner's `window_cycles` runs from its first input to its
  last output.
- **Payload seed.** `PhaseRunner` seeds each phase's payloads with a string
  (`seed/phase/name`), so a given seed reproduces the same bytes in any process.

## Tests

| File | Covers |
|---|---|
| [`stream_perf_test.py`](../../../src/tests/pypeline_tests/inst/stream_perf_test.py) | every metric against hand-worked traces (meter, taps, epoch, buffer/arbiter partitions, registry matching), bottleneck rollup/walk/headline/reports on a synthetic graph, the report helpers, and a `sim_call` run of a probed FIFO with the converged AXIS source/sink |
| [`stream_perf_probe_test.py`](../../../src/tests/pypeline_tests/inst/stream_perf_probe_test.py) | probes under the real multi-MAIN runner: MAIN-labelled names, one count per cycle through `Feedback[T]`, service periods and the verdict; also elaborated to VHDL (`--comb` synth) |
| [`stream_perf_tb_test.py`](../../../src/tests/pypeline_tests/inst/stream_perf_tb_test.py) | the complete testbench above, with result checks in its `@final` hook; also elaborated to VHDL |

**See also:** [Byte-Stream & Struct Framing Library](pypeline_stream_guide.md) ·
[FIFOs](../../../docs/pypeline_guide.md#fifos-make_stream_fifo) ·
[Skid Buffers](../../../docs/pypeline_guide.md#skid-buffers-make_skid_buffer) ·
[Simulation Reference](../../../docs/pypeline_guide.md#simulation-reference)
