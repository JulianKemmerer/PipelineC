# AUTO_PIPELINE: automatic pipelining

How PypelineC represents pipelines, builds them into VHDL, and turns
`AUTO_PIPELINE(func)` call sites into a known, readable `.latency`.

- Implementation: [`src/AUTO_PIPELINE.py`](../src/AUTO_PIPELINE.py); the tag
  class in [`src/pypeline.py`](../src/pypeline.py); the elaborator hook in
  [`src/PY_TO_LOGIC.py`](../src/PY_TO_LOGIC.py) (see its
  [AUTO_PIPELINE section](PY_TO_LOGIC_DESIGN.md#auto_pipelinefunc-latency-start_latency-max_latency--forced-submodule-pipelining)).
- *Where* registers go -- the throughput sweep that iterates synthesis toward a
  timing goal -- is [`SWEEP_DESIGN.md`](SWEEP_DESIGN.md). The synthesis runs,
  reports and delay model it relies on are [`SYN_DESIGN.md`](SYN_DESIGN.md).
  Entity/architecture emission outside the pipelined stages is
  [`VHDL_DESIGN.md`](VHDL_DESIGN.md).

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section rather
> than appending a new one. See
> [documentation conventions](pypeline_DESIGN.md#documentation-conventions).

## 1. Who does what

| piece of `src/AUTO_PIPELINE.py` | role |
|---|---|
| `TimingParams`, `MultiMainTimingParams` | the pipeline representation: each instance's leaf slices (`_slices`) and IO-register flags, its total latency, and the timing hash that names its VHDL entity; one lookup table per build (plus per-key AUTO_MULTI_CYCLE overrides) |
| `GET_PIPELINE_MAP`, `PipelineMap` | assigns every wire and submodule of a hierarchical function to a stage from data dependencies and child latencies (§2, §3) |
| `GET_ZERO_ADDED_CLKS_*`, `WRITE_ALL_ZERO_CLK_VHDL`, `WRITE_ALL_NON_ZERO_CLK_VHDL_FILES` | the zero-added-latency table every build starts from, and writing the VHDL for a table |
| `SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES`, `ADD_SLICES_DOWN_HIERARCHY_...`, `BUILD_AND_WRITE_COARSE_SLICED_TIMING_PARAMS`, `GET_BEST_GUESS_IDEAL_SLICES` | fractional (coarse/compatibility) slicing down the hierarchy |
| `PiplineHDLParams`, `GET_PIPELINE_ARCH_DECL_TEXT`, `GET_PIPELINE_LOGIC_COMB_PROCESS_TEXT`, `GET_STAGE_TEXT`, `GET_SUBMODULE_LEVEL_TEXT` | the pipelined VHDL architecture text (§3) |
| `DO_PIPELINED_BUILD`, `DO_SWEEP_AND_AUTO_PIPELINE`, `DO_AUTO_PIPELINE_LATENCY_PASSES`, `HARVEST_AUTO_PIPELINE_LATENCIES`, `SEED_TIMING_PARAMS_FROM_PREVIOUS` | the build entry point and the `.latency` pin-and-confirm loop (§4, §5) |
| `BUILD_FIXED_AUTO_PIPELINE_TIMING_PARAMS`, `COLLECT_AUTO_PIPELINE_REGIONS`, `ENFORCE_AUTO_PIPELINE_REGIONS`, `REENFORCE_AUTO_PIPELINE_REGIONS`, `AUTO_PIPELINE_REGION_FEEDBACK`, ... | constrained call sites: `latency=` / `start_latency=` / `max_latency=` (§6) |
| `FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL`, `FUNC_SUBTREE_HAS_AUTO_PIPELINE` | "can registers be added below here?" predicates, used by slicing, the sweep and SYN's delay collection |
| `DEL_PIPELINE_CACHES` | this module's per-parse caches; called from `SYN.DEL_ALL_CACHES` |

Vocabulary shared with [`SWEEP_DESIGN.md`](SWEEP_DESIGN.md#1-who-does-what):
a **slice** is one serial register boundary inserted by pipelining; a
**cut** is a requested stage boundary on a cut subtree's delay axis; a
**placement** is one typed physical register location.

## 2. How pipelines physically form

Registers physically exist in two forms:

1. **Leaf slices** — a raw HDL leaf (no submodules, e.g. `BIN_OP_PLUS`) with
   `TimingParams._slices = [0.5]` becomes a 2-stage adder, carry chain broken
   at 50% of its delay (a slice value is a fraction 0.0–1.0 of that module's
   *own* delay, but what that fraction turns into differs by leaf kind). Leaf
   latency = `len(_slices)`:

   ```
   4 ns ADD, _slices = [0.5]:
   in --[ low 2 ns of carry chain ]--REG--[ high 2 ns ]-- out   (1 clk latency)
   ```

   `RAW_VHDL.GET_LEAF_SPLIT_KIND` puts every raw HDL leaf into one of four
   kinds, which each generator's own code (not the sweep/landscape layer)
   decides how to honor:
   - `SPLIT_KIND_BITS` (PLUS/MINUS/EQ/NEQ/GT/GTE/LT/LTE/accum): the operand
     bit range is what gets split. `RAW_VHDL.GET_BITS_PER_STAGE_DICT` divides
     the width as **evenly as possible across the requested chunk COUNT**
     (`len(_slices) + 1` stages). Compatibility/coarse fractional requests
     therefore set the count rather than arbitrary bit boundaries. Typed
     bit placements normally carry the canonical equal-width boundary,
     ordinal, and count all the way through lowering, so the trace describes
     the exact emitted split. Typed `exact` placements may instead carry a
     strictly increasing integer boundary group; that group is validated,
     hashed, and emitted without changing the compatibility path. The normal
     equal-width conversion looks like it throws away information, but it
     doesn't: once a boundary is registered, each stage computes its own
     chunk from scratch off a registered 1-bit carry-in, so that stage's
     delay depends only on its own chunk width, not on where along the
     leaf's *unregistered* delay axis the cut nominally sits. Since real
     per-width delay is monotonic (and concave — sky130 measured
     `D(10)=2.607ns`, `D(34)=3.851ns` for a 34-bit `MINUS`, nowhere near
     linear), minimizing the worst stage's delay for a given stage count
     means equal-width chunks, full stop — an uneven, delay-fraction-derived
     boundary measurably misses real sky130 timing goals that the plain
     equal-width split meets, even when it looks better for one isolated
     leaf in isolation. Locally optimal per-leaf boundaries do not reliably
     predict whole-design QoR after real lowering (fanout and
     max-capacitance effects dominate there instead), so exact per-leaf
     boundaries remain available as an internal placement mechanism
     (`exact_bit_boundaries`) rather than the default allocation policy.
   - `SPLIT_KIND_MUX_BITS` (every built-in MUX): the initial landscape deliberately
     exposes only the normal operation-output boundary. A typed physical
     placement may split the packed output bits, however, making each stage's
     select drive only that chunk. Aggregate data uses the generated
     `c_structs_pkg` SLV conversion functions around the stage-local selection.
     A selected bank at least `SWEEP.DEFAULT_MUX_CHUNK_MIN_WIDTH` (32) bits
     wide is chunked this way by default when the plan is built
     (`SWEEP.CHUNK_SELECTED_MUX_OUTPUT_BANKS`) — same latency contribution,
     same cut count, half the select fanout, so `--no_sweep` gets it too.
     The bounded same-depth-neighbor refinement below (`BUILD_CHUNKED_MUX_
     REFINEMENT`) only adds the terminal, deliberately unregistered MUX on
     top of that, after a real measurement fails.

   A single mux select bus registered *on top of* an already-registered,
   wider parallel sibling can materialize a real register while adding
   **zero pipeline depth**: `GET_PIPELINE_MAP` schedules a shared
   downstream consumer by the *max* of its inputs' readiness, so a short
   branch's register is free once a slower sibling already bounds that max —
   a mismatch between requested cuts and actually-built slices is the tell.
   `SWEEP.DROP_NON_DEEPENING_PLACEMENTS` drops any `INSTANCE_INPUT`/
   `INSTANCE_OUTPUT` placement, or a complete synchronized boundary-register
   group, whose removal leaves the subtree's
   real post-lowering `GET_TOTAL_LATENCY` exactly where it started — ground
   truth after real lowering, not a landscape estimate, since only the real
   synchronous schedule can see this. The comparison also folds in each
   AUTO_PIPELINE-tagged descendant region's own latency: such a region
   reports 0 latency to its immediate container by convention (so
   balanced-latency reporting doesn't double-count an already-decoupled
   region), so a monolithic-only comparison would misread every one of that
   region's real registers as adding no depth and drop them all.
   `DROP_NON_DEEPENING_PLACEMENTS` mirrors `SUMMARIZE_SUBTREE_PIPELINE`'s own
   `monolithic + sum(regions)` formula exactly to avoid this.
   Group members are tested and removed atomically: testing one parallel bank
   at a time would make every member appear redundant and leave an arbitrary
   incomplete frontier behind.
   - `SPLIT_KIND_1LL` ("one logic level" — AND/OR/XOR/NOT/NEGATE/MULT):
     these generators (`stage_for_1ll`) always place the *whole* operation in
     exactly one stage no matter the latency — only the register *boundary*
     moves. Latency 1 puts the op in stage 0 or 1 depending on which side of
     0.5 the slice falls; latency 2 puts registers on both sides with the op
     untouched in the middle. A 3rd slice is provably wasted (a bare register
     around logic that never shrinks), so `RAW_VHDL.LEAF_MAX_SPLIT_SLICES`
     caps these at 2 — enforced primarily in the landscape ([`SWEEP_DESIGN.md`](SWEEP_DESIGN.md#landscape-segments-and-typed-candidates): only a
     `SPLIT_KIND_1LL` segment's own two boundary units are ever legal cut
     positions) and backstopped by a hard error in
     `SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES` if anything else ever
     requests a 3rd.
   - `SPLIT_KIND_NONE` (bit-manip/cast/const-shift/const-ref): no
     stage-dependent behavior at all; in practice unreachable since
     `LOGIC_IS_ZERO_DELAY` already excludes these from ever getting cuts.
2. **IO regs** — `_has_input_regs/_has_output_regs` add boundary registers.
   Typed `instance_input` and `instance_output` placements lower directly to
   the selected child boundary. They do not manufacture fractional cuts in
   every primitive below that child.

Everything else is *emergent*: a hierarchical module's latency is rebuilt
bottom-up from its children by `GET_PIPELINE_MAP`, and the VHDL writer
registers wires crossing stage boundaries (`REG_STAGEn_<wire>`).

The planned sweep preserves a concrete `PipelinePlacement` through selection
and lowering rather than immediately projecting a fractional cut through
every descendant. `instance_input`/`instance_output` set one entity boundary
flag; `bit_internal` adds a local slice only to a genuinely bit-splittable
raw leaf. An older recursive fraction mechanism remains for the coarse
sweep and compatibility paths:

```
        MAIN  cut at 30% of 100ns
          |
         foo  -> cut lands at 25% of foo's 40ns
          |
       adder  -> cut lands at 50% of adder's 5ns   <- real register here
```

**Cuts != latency.** The two are related but distinct numbers, always
reported separately. Latency can exceed the cut count (children of one cut
sliced at misaligned positions, IO regs, `make_stream_auto_pipeline`-style
factories with internal `AUTO_PIPELINE` call sites). A mini-swept WireGuard
`block_step` accepts one internal half-way slice, with its external banks
then chosen over direct parent-dataflow edges: a ten-instance serial chain
needs the ten internal slices plus nine shared boundaries, not both banks on
every instance — three clocks per instance is only the final fallback when
compact boundary policies miss timing. An **auto-pipeline-tagged call site
reports latency 0 to its container** (so FSMs keep their cycle accounting) —
a stateful MAIN prints `main_latency=0` while a deep pipeline runs inside
it. That is expected, not a bug.

**A module's latency is not its slice count.** A module's total latency is
its own leaf slices *plus* the summed latencies of its submodule instances,
so an entity named `foo_25CLK` can legitimately carry only 8 slices of its
own (the other 17 register delays live in submodules). `latency == slice count` holds
*only* for a pure-comb, fully-sliceable region (nothing below it to add
depth) — which is exactly the region `CHECK_CUTS_VS_LATENCY` marks `strict`.

**Reporting how deep the design got pipelined.** Because a stream MAIN reads
`main_latency=0` and the deepest single instance (one block_step) is far
shallower than the whole pipeline, neither alone answers "how many stages did
auto-pipelining build?". So `GET_SUBTREE_PIPELINE_STAGES`/`SUMMARIZE_SUBTREE_
PIPELINE` compute the **total slices in a main's cut subtrees**:

```
total = (slices inserted directly into the cut-subtree roots)
      + (latency of every decoupled auto-pipeline region instance in them)
```

The two parts never overlap: a subtree root's own latency already zeroes its
decoupled children (they report 0 to it), and the second term adds exactly
those back. This equals the input-to-output register count when the regions
sit in series, as in a stream pipeline — a topology-aware lock records its
shared boundary cover and reports the realized total (a WireGuard-shaped
design's `block_step` repeated ten times reports its true shared-boundary
total, not a naive per-instance sum). The `Pipeline depth summary` at
*Writing Results* prints this figure as "N slice(s) total (N+1 pipeline
stages)" (computed at *Writing Results* on the final, actually-emitted
table, so it reflects any extra depth the AUTO_PIPELINE pin-and-confirm
re-elaboration (§5) added).

**Slices vs. pipeline stages — `stages = slices + 1`.** A slice
count is not the same number as "how many pipeline stages". 0 slices (comb
logic) is 1 stage; 1 slice splits it into 2 stages; N slices in series
give N+1 stages. So the `pipeline_stages=` field printed per sweep iteration
and written to `sweep_history.json` is always **realized deepest slices + 1**,
not the requested `cuts` count. The requested cut count and realized slice
count are often equal for one pure-comb subtree (so `pipeline_stages` is then
`cuts + 1`), but those two counts can differ after boundary lowering or with
decoupled regions — a print like `cuts=0 main_latency=0 pipeline_stages=20`
can look like no registers were added at all when in fact locked slices
distributed across decoupled regions account for all 20 stages.

Entity naming is also unchanged: each distinct (IO regs + leaf slices)
combination hashes to its own VHDL entity `funcname_<latency>CLK_<hash>`.

### Fixed user pipelines

Pypeline's `@pipeline_latency(N)` and C's `FUNC_LATENCY` populate the same
`parser_state.func_fixed_latency` table. `TimingParams.CALC_TOTAL_LATENCY` reports
N for the tagged function; `GET_PIPELINE_LOGIC_ADDED_LATENCY` subtracts that user
latency when emitting its body, so the user registers are not duplicated.
`CAN_HAVE_ADDED_LATENCY` rejects further stages on the tagged implementation,
and the planner treats it as an atomic fixed-latency building block. Caller
pipeline maps consume its N-cycle output timing and add alignment on other paths.

A tagged leaf consisting only of wire assignments and registers has zero
combinational delay. `LOGIC_IS_ZERO_DELAY` recognizes that case directly, avoiding
a meaningless zero-delay frequency calculation in the PYRTL timing model.
Pypeline elaboration rejects internal AUTO_PIPELINE requests that would alter the
fixed implementation.
Both typed placements and legacy fractional slicing call
`CHECK_FIXED_LATENCY_BOUNDARY`, rejecting registers at the tagged instance or any
of its descendants. Python stateful/fixed bodies mark pipeline calls as
`submodule_latencies_are_self_timed`; `GET_SUBMODULE_LATENCY` exposes their physical
outputs to that body's stage-zero logic. Sliceable callers continue to see N.

The native simulator uses these same placements only for affected user-pipeline
regions. Its architecture and compatibility gate are documented in
[pypeline_sim_DESIGN.md](pypeline_sim_DESIGN.md#fixed-user-pipelines).

## 3. The pipelined VHDL architecture

`VHDL.WRITE_LOGIC_ENTITY` renders every entity. For a function whose
`TimingParams` add latency it builds a `PiplineHDLParams` from the pipeline map
and asks this module for the architecture's stage declarations
(`GET_PIPELINE_ARCH_DECL_TEXT`, via `VHDL.GET_ARCH_DECL_TEXT`) and its
combinational stage process (`GET_PIPELINE_LOGIC_COMB_PROCESS_TEXT`); the C
frontend's per-stage text goes through `GET_C_ENTITY_PROCESS_STAGES_TEXT` and
`GET_STAGE_TEXT`, and a submodule instance is placed at its stage by
`GET_SUBMODULE_LEVEL_TEXT`. `VHDL.py` imports this module lazily inside those
three functions, so importing `VHDL` never imports `AUTO_PIPELINE`.

For hierarchical logic, `GET_PIPELINE_MAP` assigns each wire and submodule
connection to a stage from data dependencies and child latencies.
`GET_PIPELINE_ARCH_DECL_TEXT` declares stage records/signals, while
`GET_PIPELINE_LOGIC_COMB_PROCESS_TEXT` and the clocked portions of the
architecture implement the stage-to-stage transfers. Names containing
`REG_STAGE<n>` are rendered alignment/storage wires, not evidence that each
source-level variable owns an independent physical delay chain; synthesis may
merge equivalent registers.

`io_registers_r` (the record holding a clocked function's input/output register
banks) and `REG_STAGE<n>_<wire>` are deliberately GENERIC signal names -- they
carry no reference to source location or the variable's Python name, unlike the
generated entity/instance names elsewhere in this build (see
[PY_TO_LOGIC_DESIGN.md](PY_TO_LOGIC_DESIGN.md)'s "Canonical function name
format"). This is intentional, not an oversight: `SWEEP.py`'s critical-path
attribution parses `stage(\d+)` back out of a register name
(`_PATH_REPORT_STAGE_INFO`) to report local pipeline-stage info, and a Vivado/
yosys timing report cross-references these exact strings, so renaming them would
require updating both. To find the source construct a specific `io_registers_r`/
`REG_STAGE<n>` field belongs to, read the ENCLOSING hierarchical instance path
instead -- that path segment does carry a `_py_lNN` location suffix, and
`name_index.log` (see [SYN_DESIGN.md](SYN_DESIGN.md)) decodes it further.

Reconvergent branches and bypass inputs are aligned to the stage at which
their consumer runs. An operation-output placement creates a register at that
instance boundary; values which remain live across it are delayed through the
same pipeline map. A genuine bit-internal placement delegates the split to
the raw leaf generator. Exact placements carry their integer boundary group
through `TimingParams`; every built-in MUX can therefore render a different
packed output bit chunk in each local stage while the pipeline map aligns its
condition, data inputs, and partial output. Integer/signed/vector MUXes select
their native vectors directly. Composite MUXes use the generated
`<type>_to_slv` functions at stage 0 and `slv_to_<type>` after the final
chunk, so structs, arrays, enums, floats, and nested combinations use the same
canonical packed layout as all other VHDL connections. These cases remain
distinct through lowering, so an output boundary does not get recursively
pushed into every descendant.

One logical delay-axis cut may lower to a synchronized placement group when a
parallel or reconvergent frontier needs more than one physical register bank.
Each member remains an ordinary instance-output or bit-internal placement in
`TimingParams`; the shared group identity says that the banks form one stage
boundary and must be materialized or removed atomically. PipelineMap then
aligns their consumers exactly as it does for an ungrouped boundary. This is
different from multiple serial slices: the group adds one unit of latency even
though it contains several physical banks.

The SLV alternatives and partial result are fields of the raw leaf's pipeline
record. They consequently participate in the same register transfer and live
wire alignment as native typed values. Slice coordinates, exact packed-bit
boundaries, and the composite type all remain part of entity hashing; two
typed entities may share a width-keyed timing-cache result without becoming
the same VHDL entity or losing their type-specific conversion functions.
The two-stage two-bit unsigned-adder specialization uses the same mechanism:
its propagate/generate prefix fields cross the leaf's internal register, then
the final stage reconstructs the upper sum and carry without leaving another
complete full-adder path after that register.

`TimingParams._has_input_regs` and `_has_output_regs` implement independent
entity-boundary registers. They participate in latency, hashing,
clock/clock-enable requirements, and wire alignment just like internal
stages. The sweep may therefore put a shared direct connection's register on
the producer output *or* the consumer input; it must not render both merely
because adjacent helper instances were independently mini-swept. PipelineMap
still aligns every other input and bypass at the selected consumer stage. A
design with `N` serial register slices has `N + 1` combinational pipeline
stages. The fresh WireGuard shared build validates this lowering on ten
serial `chacha20_block_step` instances: one internal slice per helper plus
nine producer-output banks rendered as 19 slices / 20 stages, with no
redundant output-to-input register pairs.

## 4. Build entry points

`src/pipelinec` calls `AUTO_PIPELINE.DO_PIPELINED_BUILD` for every non-`--comb`
build. It dispatches to `AUTO_FSM.DO_SCHEDULE_PASSES` when the design has
AUTO_FSM call sites (which wraps the flow below, see
[`AUTO_FSM_DESIGN.md`](AUTO_FSM_DESIGN.md#34-the-driver-loop)) and otherwise to
`DO_SWEEP_AND_AUTO_PIPELINE`:

```
DO_SWEEP_AND_AUTO_PIPELINE
    AUTO_MULTI_CYCLE.CHECK_AUTO_MULTI_CYCLE_TAGS_READ
    SWEEP.DO_THROUGHPUT_SWEEP                 <- pass 1: the full sweep
    DO_AUTO_PIPELINE_LATENCY_PASSES           <- §5: harvest, and if needed
        re-PARSE_FILE with .latency pinned,
        SEED_TIMING_PARAMS_FROM_PREVIOUS,
        SWEEP.DO_SEEDED_CONFIRM_OR_SWEEP      <- one confirmation synthesis
```

Builds that run no sweep (`--comb`, `--no_synth`, `--yosys_json`) use
`BUILD_FIXED_AUTO_PIPELINE_TIMING_PARAMS` instead (§6).

## 5. `.latency` pin-and-confirm loop (Pypeline designs only)

Pypeline's `AUTO_PIPELINE(func)` tag exposes the sweep's discovered stage count back to
the design's Python as `.latency` (e.g. `make_stream_auto_pipeline` sizes its output FIFO
from it). The stage count only exists *after* the sweep, so `DO_SWEEP_AND_AUTO_PIPELINE`
wraps the parse+sweep sequence in an outer loop — a **pin-and-confirm** loop, not a
repeat-the-sweep one:

1. **Pass 1 (bootstrap, identical to a normal build):** `PARSE_FILE` with an empty
   latency cache (`.latency` reads 0, or a call site's fixed `latency=N` /
   `start_latency=S`) → path delays → full throughput
   sweep → `HARVEST_AUTO_PIPELINE_LATENCIES` walks the finished
   TimingParamsLookupTable and groups each AUTO_PIPELINE-tagged instance's
   `GET_TOTAL_LATENCY` by the tag's canonical key (a pure in-memory walk; no
   synthesis, no file I/O). The harvest invalidates every entry's memoized
   latency/hash first (same rationale as `WRITE_FINAL_FILES`): the planner
   mutates submodule `_slices` after container totals were first memoized,
   and a stale memo here would feed `.latency` (and the native simulator's
   delay lines) a number contradicting the entities actually written.
2. **Early exits (the zero-added-cost invariant):** if there are no AUTO_PIPELINE call
   sites, or the design's Python never *read* any `.latency`
   (`pypeline.AUTO_PIPELINE_LATENCY_WAS_READ()`, a read-tracked property flag), or every
   value it read already equals the stage count harvested for that key, the
   loop ends here. The second check compares `pypeline.AUTO_PIPELINE_SERVED_LATENCIES()`
   with the harvest using `AUTO_PIPELINE_SERVED_VALUES_MATCH`, and holds for fixed
   `latency=` call sites, a correct `start_latency=` guess, or a discovered 0. It
   prints "skipping pin-and-confirm pass 2". Either way the loop ends here — the cache couldn't have influenced the elaborated design, so
   pass 1's result is final. Cost is exactly the classic single parse + single
   sweep. `.c` designs never enter the loop at all (`AUTO_PIPELINE` is
   Pypeline-only syntax).
3. **Pass 2 (pin + confirm):** install the harvested latencies
   (`pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE`), re-run `PARSE_FILE` (re-executes the
   whole design import graph; `.latency` reads now resolve), rewrite the zero-clk
   VHDL, re-run path delays (mostly disk-cached), then
   `SEED_TIMING_PARAMS_FROM_PREVIOUS` carries pass 1's sweep solution (slices +
   IO-reg flags) into the fresh zero-clk table. Matching is **two-tier**: exact
   instance path first, else func (entity) name — the func-name tier is load-bearing
   because entity names encode closure values, so a `.latency`-derived parameter
   change (e.g. FIFO depth) renames its factory entity and every instance path
   underneath, exactly where the AUTO_PIPELINE'd core lives (the core's own name is
   stable — its closure captures only the user's func). Seeding ends by
   invalidating EVERY entry's cached hash/latency strings — cached hash
   chains embed child func names, and any cache carried across the
   re-elaboration boundary may reference since-renamed entities (the class
   of bug behind a "unit not found" GHDL failure on a shared-across-instances
   design). Then `SWEEP.DO_SEEDED_CONFIRM_OR_SWEEP` runs **one** full-design
   synthesis. The loop stops only when the post-confirmation harvest
   **equals** the values this pass's Python consumed — meeting timing alone
   is not sufficient: realizing the seeded fractional slices hierarchically
   (e.g. into pipelined built-in div/mult entities with their own stage
   granularity) can change an instance's total latency even on a passing
   confirmation, and exiting then would build VHDL whose actual depth
   contradicts every `.latency`-derived constant baked into it (and desync the
   native simulator's latency emulation). When the totals change, the loop simply
   re-elaborates with the fresh numbers (an extra pass, typically converging
   immediately since the per-instance slices are already in place); on exit the
   `.latency` values the design consumed provably equal the stage counts built. The
   confirmation is guaranteed to be a REAL synthesis, not a cached-log
   replay: timing hashes (`RECURSIVE_GET_IO_REGS_AND_NO_SUBMODULE_SLICES`)
   record each child's func name alongside its subtree, so a design whose
   descendants renamed (resized FIFO) hashes differently from pass 1 even
   with identical slices — both the multimain top log name and every entity
   filename are content-aware, which also keeps the skip-if-exists entity
   write sound ("same filename ⇒ same rendered content"). The module's own
   name is deliberately not in its tuple (it's already in every filename),
   so leaf tuples — and therefore previously cached leaf synthesis logs —
   are unaffected. The confirmation's verdict feeds the driver's
   TIMING-NOT-MET exit gate via `sweep_timing_failures` (empty on met; a
   failed confirmation falls back to the full sweep, whose own result then
   governs). The confirmation also records its measurements in
   `sweep_history.json` (`SWEEP.RECORD_CONFIRMATION_RESULTS`). A pass makes
   each goal main's `final.source` `confirmation_run`: a passing confirmation
   runs no sweep, so otherwise the file would still describe the previous
   pass's sweep ([`SWEEP_DESIGN.md` *Plan*](SWEEP_DESIGN.md#plan)). `SYN.WRITE_FINAL_FILES` additionally invalidates the entire
   final table before writing (final files computed 100% against current
   state) and runs `CHECK_VHDL_FILES_CONSISTENCY`: every `entity work.X`
   referenced inside a listed file must be defined by a listed file, turning
   any stale/mixed entity references into an immediate build error instead
   of a downstream GHDL/Vivado analysis failure.
4. **Fallback (rare):** if the confirmation fails timing, it falls back to a full
   planned sweep (which replans from a fresh zero-clk table each iteration, so the
   seeds can't corrupt it), harvests again, and loops back to step 3 with the new
   numbers. Bounded by `AUTO_PIPELINE_MAX_LATENCY_PASSES` (3 total passes); at
   the cap the build fails loudly, advising an explicit `latency=N` pin at the
   unstable call site.

Hard errors (instead of silently-wrong hardware):
- **Divergent `.latency`:** the same AUTO_PIPELINE-tagged function instantiated at
  multiple sites with *different* discovered stage counts — legal per-instance in
  the framework, unrepresentable as the single `.latency` int the design's Python
  read. Fix: give each call site its own factory-produced closure, or pin `latency=N`.
- **Call-site set changed between passes:** an AUTO_PIPELINE-tagged instance on pass
  2 whose func didn't exist in pass 1 (detected as unseedable) — i.e. Python control
  flow, or closure-captured values encoded in a tagged function's identity, depended
  on `.latency`'s own value. Only sizing *outside* AUTO_PIPELINE'd functions may
  depend on it.
- **No settling within the pass cap:** a `.latency`-derived change keeps perturbing
  timing enough to change the discovered stage counts themselves.

Repeated-`PARSE_FILE` support (sys.modules eviction of the design import graph,
per-parse compiler-cache cleanup via `DEL_ALL_CACHES`) lives in `PY_TO_LOGIC.py` —
see `PY_TO_LOGIC_DESIGN.md`'s AUTO_PIPELINE section.

The converged harvest has one more consumer: a non-`--comb` `--sim` run hands it
(plus the final per-MAIN latencies) to the native simulator at the end of the build,
which re-imports the design with the cache installed and emulates every latency —
see [`pypeline_sim_DESIGN.md`](pypeline_sim_DESIGN.md)'s "Pipelined native sim" section.

## 6. Constrained AUTO_PIPELINE regions (`latency=` / `start_latency=` / `max_latency=`)

`AUTO_PIPELINE(func, latency=N)`, `start_latency=S` and `max_latency=M` record a
`C_TO_LOGIC.AutoPipelineLatency` for each tagged instance, in
`Logic.sub_inst_to_auto_pipeline_latency`. C's `#pragma AUTOPIPELINE N` records a fixed
N the same way. Unconstrained tags, the default, take none of the paths below, so
designs without constraints plan, name and build exactly as before.

**Planned sweep (`ENFORCE_AUTO_PIPELINE_REGIONS`).** A tagged instance is
latency-decoupled from its container (`GET_SUBMODULE_LATENCY` reports it as 0), so each
constrained instance is treated as its own *region*. Every iteration, right after
`SWEEP.APPLY_LOCKS` and before any cut-subtree landscape is built, each region goes through:
1. its own `SWEEP.BUILD_SLICE_LANDSCAPE`;
2. choosing a register count K;
3. count-targeted placements;
4. real lowering (`SWEEP.APPLY_PIPELINE_PLACEMENTS` → `SWEEP.CHECK_PIPELINE_PLACEMENTS_REALIZED` →
   `SWEEP.DROP_NON_DEEPENING_PLACEMENTS`);
5. verification against its real `GET_TOTAL_LATENCY`;
6. `params_are_fixed`.

Containing landscapes then see an ordinary `Segment.LOCKED`, the mini-sweep lock path. A
region that is itself a cut-subtree root takes the existing locked-root branch. Clamping
cuts inside a shared landscape instead would not work: parallel branches share one
delay axis, and the container can't count the region's latency.

- **Register count K.**
  - Fixed: K = N.
  - `start_latency` on its first iteration: K = S. The region's private budget divisor
    `region.scale` is calibrated so that unchanged knobs keep reproducing S.
  - Otherwise: the planner's own count for the plan's clock period, with the budget
    divided by `global_scale * region.scale` and in-region weights including
    `func_delay_scale`, capped at M.

  Instances that share a canonical key form one group and are planned to one K, so the
  harvested `.latency` can't diverge between them.
- **Count-targeted placement (`COUNT_TARGETED_PLACEMENTS`).** Bisect the budget given to
  `SWEEP.PLAN_PIPELINE_PLACEMENTS` until it yields K; cut count never increases as the budget
  grows. The result is the planner's own tightest-stage placement for exactly K
  registers. When the count jumps past K, the nearest larger plan is trimmed down
  (`_TRIM_PLACEMENT_PLAN_TO_COUNT`). Asking a fixed region for more registers than it
  has legal positions is an error.
- **Verify and retry.** The realized latency can differ from the cut count, because of
  built-in operator stage granularity or non-deepening drops. A fixed region that
  realizes anything but N, or a capped region that realizes more than M, is reset to
  zero clocks and re-planned with a corrected count (`AUTO_PIPELINE_REGION_RETRIES`). If
  that still fails, the build exits and names the call site, the constraint and the
  realized value.
- **Growth and shrinking.**
  - Region landscapes feed `SWEEP.RANK_PATH_FUNC_CANDIDATES`, and a region root counts as a
    valid attribution. When `REGION_FOR_HOTSPOT` places a critical path inside a region,
    that group's `region.scale` is multiplied (the `grow_auto_pipeline` action).
  - Global replans grow regions too.
  - If nothing else in the plan can change and no region count moved, the region with
    the worst predicted stage gets one more register.
  - Trimming after timing is met counts non-fixed region cuts and can shrink them,
    including below `start_latency`.
- **At the cap.** A hotspot in a region at its limit (fixed, or realized = M) first gets
  one same-count rebalance, with the hotspot's weight raised. If that doesn't help, the
  plan stops with `stopped_reason = "auto_pipeline_latency_limit"` and prints
  `[sweep] WARNING: ... limited by AUTO_PIPELINE latency constraint(s) ...`, followed by
  the usual TIMING NOT MET exit. Two cases stop the same way without an attributed
  hotspot:
  - no attribution is available (PyRTL) and every register the plan can place is
    inside capped regions;
  - an iteration's physical schedule fingerprint (region placements included) repeats
    one already tried while a region is at its cap. This stops before re-synthesizing.
- **Mini-sweeps** never lock a hotspot that lies inside a region or contains one.
- **Everything else includes regions:**
  - snapshots;
  - `sweep_history.json` and placement traces (`auto_pipeline_regions`);
  - the final summary (`[sweep] AUTO_PIPELINE <key> (<constraint>): N clk(s) built at <inst>`);
  - `CHECK_AUTO_PIPELINE_CONSTRAINTS_REALIZED`, a safety net run on every final
    table and after every harvest.

**Coarse sweep.** `BUILD_AND_WRITE_COARSE_SLICED_TIMING_PARAMS` enforces fixed regions
before slicing the main's even fractions; slicing skips locked children. Afterwards it
re-plans any region that those fractions pushed over `max_latency` back down to its cap
(`REENFORCE_AUTO_PIPELINE_REGIONS`). Under a coarse sweep, `start_latency` only
sets the bootstrap `.latency`, and a NOTE says so.

**Builds without a sweep.** `--comb`, `--no_synth` and `--yosys_json` still build every
fixed latency. `BUILD_FIXED_AUTO_PIPELINE_TIMING_PARAMS`:
1. measures delays for just those regions' subtrees
   (`SYN.ADD_PATH_DELAY_TO_LOOKUP(parser_state, root_func_names=...)`);
2. enforces the regions on a zero-clock table;
3. hands that table to `SYN.WRITE_FINAL_FILES`, the `--comb` characterization synthesis,
   and a cocotb/GHDL comb-stage sim.

Without a timing-capable tool, the PyRTL delay model is borrowed for the measurement.
The latency is still exact; only the stage balance is estimated. The path-delay cache
is keyed per tool, so the borrowed numbers don't pollute another tool's cache. Designs
with no fixed latency above 0 keep the historical zero-clock path.
`pypeline.SET_AUTO_PIPELINE_BUILD_MODE` (`"sweep"` / `"fixed_only"`, set by `pypelinec`
before parsing) decides whether `start_latency` feeds the bootstrap `.latency`. If the
no-tool fallback downgrades a sweep build after start values were already read, the
design is re-elaborated.

**Pin-and-confirm.** Seeding by function name can copy another call site's slices onto a
constrained region, so the seeded table goes through `REENFORCE_AUTO_PIPELINE_REGIONS`
before the confirmation synthesis. The served-value skip in step 2 means fixed latencies
and correct `start_latency` guesses cost no second elaboration.

## 7. Tests

Tests live in `src/tests/pypeline_tests/inst/`; see
[`pypeline_TESTS.md`](pypeline_TESTS.md#auto_pipeline-latency-constraint-coverage)
for the full coverage list. The ones that exercise this module end to end
(all under `--syn_tool sky130` unless marked):

| test | proves |
|---|---|
| `auto_pipeline_latency_test.py` | end-to-end factory design (`make_stream_auto_pipeline`) through the full sweep **plus** the §5 pin-and-confirm loop: pass 2 runs, harvested `.latency` > 0, the seeded confirmation synthesis passes with no fallback sweep, the loop settles within the pass cap, and `sweep_history.json` `final` records come from the confirmation run |
| `auto_pipeline_constraints_test.py` | §6 constrained regions: `latency=2` / `start_latency=1` call sites built with exactly 2 / 1 registers and pass 2 skipped; a `max_latency=1` cap stops an unreachable goal promptly, naming the cap, then `TIMING NOT MET` |
| `auto_pipeline_c_pragma_test.py` | C `#pragma AUTOPIPELINE 2` is a fixed latency, built with exactly 2 clocks even by a `--comb` build |
| `sweep_fsm_auto_pipeline_test.py` | Reg-FSM main + AUTO_PIPELINE region: the cut subtree is the tagged child, the FSM's latency stays 0 |

In-process: `auto_pipeline_harvest_test.py` (harvest grouping and divergence,
two-tier seed matching, call-site-change detection, latency cache/read flag,
constructor validation), `auto_pipeline_region_planning_test.py` (region
planning), `pipeline_latency_test.py` (fixed user pipelines),
`typed_pipeline_placement_test.py` and `mux_fanout_planning_test.py`
(placement lowering through `TimingParams` and the pipeline map).

## History

### Why `AUTO_PIPELINE(func, depth=N)` became `latency=N`

`depth=N` was stored and never read, so a user asking for N registers silently
got whatever the sweep chose. It was replaced by `latency=N` (with
`start_latency=` / `max_latency=`), which every build enforces (§6).
