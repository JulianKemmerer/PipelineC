# MULTI_CYCLE and AUTO_MULTI_CYCLE: multi-cycle paths

A multi-cycle path relaxes the timing requirement between two registers:
`MULTI_CYCLE[N]` tells synthesis the launch register's value is only captured
every N clock cycles, and `AUTO_MULTI_CYCLE(...)` lets the throughput sweep
choose N. Neither adds registers; they widen the permitted settling time.
The untagged logic between launch and capture stays combinational, even when
another call to the same helper is pipelined. The holder's state registers
block compiler-added latency under the [caller-context rule](SWEEP_DESIGN.md#cut-subtree).

- Implementation: [`src/AUTO_MULTI_CYCLE.py`](../src/AUTO_MULTI_CYCLE.py).
- The tags: [`pypeline_DESIGN.md`](pypeline_DESIGN.md#multi_cyclencycles--multi-cycle-path-tag)
  and [its AUTO_MULTI_CYCLE section](pypeline_DESIGN.md#auto_multi_cycle--tool-tuned-multi-cycle-path-tag);
  elaboration into `Logic.mcp_tuples`:
  [`PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md#multi_cyclencycles--regt-tag--multi-cycle-path-constraint);
  user guide: [Multi-Cycle Paths](pypeline_guide.md#multi-cycle-paths-multi_cycle).

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section, if it
> has one, rather than appending a new one. See
> [documentation conventions](pypeline_DESIGN.md#documentation-conventions).

## 1. Who does what

| piece of `src/AUTO_MULTI_CYCLE.py` | used by | role |
|---|---|---|
| `DESCRIBE_MCP_PATHS` | caller-context diagnostics | readable launch -> capture paths for an instance whose state blocks added latency |
| `GET_MCP_CELL_PATHS` | constraint writer, sweep | the Vivado cell globs of every multi-cycle path in an instance: the one source for both constraints and report matching |
| `GET_MCP_PATH_CONSTRAINTS`, `MCP_EFFECTIVE_NCYCLES` | `SYN.WRITE_CLK_CONSTRAINTS_FILE` | `set_multicycle_path` / `DONT_TOUCH` lines for the clock constraints file, with the sweep's current count |
| `MCP_ENDPOINT_REGS`, `MCP_IMPLEMENTATION_VERSION` | VHDL emission, timing identity | preserve tagged endpoint signals before synthesis and invalidate affected artifacts |
| `CHECK_MCP_TIMING_REPORT` | Vivado backend | reject identifiable exception coverage failures before timing feedback |
| `ELABORATED_AUTO_MULTI_CYCLE_NCYCLES` | everything below, `MultiMainTimingParams.GET_HASH_EXT` | the counts the design was elaborated with |
| `AutoMultiCycleGroup`, `COLLECT_AUTO_MULTI_CYCLE_GROUPS`, `AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT`, `AUTO_MULTI_CYCLE_NEEDED_NCYCLES`, `AUTO_MULTI_CYCLE_FEEDBACK` | `SWEEP.DO_PLANNED_THROUGHPUT_SWEEP` | sweep feedback (§3) |
| `HARVEST_AUTO_MULTI_CYCLE_NCYCLES`, `AUTO_MULTI_CYCLE_BUILT_MATCHES_ELABORATED`, `PRINT_AUTO_MULTI_CYCLE_NCYCLES`, `CHECK_AUTO_MULTI_CYCLE_TAGS_READ` | `AUTO_PIPELINE.DO_AUTO_PIPELINE_LATENCY_PASSES`, `SIM` | pin-and-confirm (§4) |

`pypeline.AUTO_MULTI_CYCLE(latency= / start_latency= / max_latency=)` tags a multi-cycle path
exactly like `MULTI_CYCLE[N]`, but lets the sweep choose N. The elaborator records the
elaborated N in `Logic.mcp_tuples`, as for any MCP, and additionally records
`Logic.auto_multi_cycle_tuples[(start_reg, end_reg)] = C_TO_LOGIC.AutoMultiCycleConstraint(key, ...)`.

## 2. Constraints

`MULTI_CYCLE[N]` and `AUTO_MULTI_CYCLE` paths are written into the clock
constraints file as

```
set_multicycle_path N -setup -from [get_pins {<start>_reg[*]/C}] -to [get_pins {<end>_reg[*]/D}]
set_multicycle_path N-1 -hold -from [get_pins {<start>_reg[*]/C}] -to [get_pins {<end>_reg[*]/D}]
set_property DONT_TOUCH TRUE [get_cells {<start>_reg[*]}]
set_property DONT_TOUCH TRUE [get_cells {<end>_reg[*]}]
```

relative to the synthesized top. Only Vivado is supported: any other tool
raises an error when a design has a multi-cycle path. `N-1` above is emitted
as an integer, including zero when `N=1`. The setup exception permits N
periods; the hold exception restores the ordinary same-clock hold relationship.
Both use the same C-to-D pin collections, leaving enable/reset paths untouched.
See [Vivado set_multicycle_path](https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/set_multicycle_path).

**Preservation starts in RTL.** `GET_PIPELINE_ARCH_DECL_TEXT` places a string
`dont_touch` attribute on each tagged state-register signal. This includes
record/array payloads and both fixed and automatic MCPs. The XDC reinforces
that property on the resulting cells. `KEEP` in XDC alone is insufficient:
early synthesis can transform an endpoint before XDC processing, and `KEEP`
does not preserve it through implementation. An absorbed DSP input register
changes the timing startpoint, potentially escaping the named exception.
See [Vivado KEEP](https://docs.amd.com/r/en-US/ug901-vivado-synthesis/KEEP) and
[UG901 synthesis attributes](https://www.amd.com/content/dam/xilinx/support/documents/sw_manuals/xilinx2022_1/ug901-vivado-synthesis.pdf).
Only tagged endpoints receive these attributes; arithmetic can still map to
DSPs, and a separate AUTO_PIPELINE call of the same helper retains its ordinary
optimization and pipelining behavior. Preserving endpoints can cost fabric
registers and restrict packing, so preservation is deliberately narrow.

**Constraint value.** `MultiMainTimingParams.auto_multi_cycle_ncycles` holds the sweep's current
count per AUTO_MULTI_CYCLE key. `GET_MCP_PATH_CONSTRAINTS` writes
`MCP_EFFECTIVE_NCYCLES`: that override, else the elaborated count. The sweep changes a
count without re-elaborating, and only the XDC changes, so
`MultiMainTimingParams.GET_HASH_EXT` appends the overrides that **differ** from the
elaborated counts. Otherwise a same-named log from another count would be replayed.
Counts equal to their elaborated values add no override to that hash.
Independently, `TimingParams` includes `MCP_IMPLEMENTATION_VERSION` and the
sorted MCP tuples at each MCP-bearing instance. Their recursive contribution
changes ancestor and top-level identities while leaving unrelated arithmetic
leaves unchanged. A preservation/constraint recipe change must bump this
version. Existing reports/checkpoints remain available as evidence, but are
not reused under the new identities; an unchanged warm run still reuses them.
See [synthesis caches](SYN_DESIGN.md#6-caches).
`GET_MCP_CELL_PATHS` is the one source of the register cell globs, used both by the
XDC writer and by report matching.

## 3. Sweep feedback

Pipelining feedback never inserts registers in an untagged MCP interior:
mini-sweeps, boundary banks, coarse slicing, and the planner all enforce the
same absorbing-caller rule. A fixed MULTI_CYCLE path receives the same
protection; AUTO_MULTI_CYCLE feedback changes only its allowed count.

Before a Vivado report reaches any sweep, `CHECK_MCP_TIMING_REPORT` checks
fixed and automatic MCPs in both fresh and reused per-module/top-level reports.
A named C-to-D pair with the wrong setup requirement raises `MCP timing
coverage error`. A sequential DSP startpoint mapped inside a known untagged,
combinational MCP descendant also raises that error. Diagnostics name the
holder, physical endpoints, expected cycles/time, and observed requirement.
These failures require repairing preservation/coverage; changing another
instance's pipeline cannot repair them. Enable/reset destinations and explicitly
pipelined or user-stateful descendants are not treated as escaped MCP data paths.
Unmapped hierarchy is left unclassified rather than guessed.

`SWEEP.DO_PLANNED_THROUGHPUT_SWEEP` handles AUTO_MULTI_CYCLE paths as follows:

1. **Setup.** `COLLECT_AUTO_MULTI_CYCLE_GROUPS` gathers every instance's AUTO_MULTI_CYCLE paths by key; a key
   is one group with one count, since the design reads one `.latency` int. The counts are
   initially taken from elaboration. `SEED_COUNTS` then uses valid isolated
   endpoint reports for all groups, before the first sweep or pinned confirmation.
   `requirement - slack` is raw effective launch-to-capture time, including timing
   overhead; the cached scalar `Logic.delay` is per-cycle and is never used alone
   to seed a group. The seed is `ceil(raw / goal_period)`, respecting fixed counts,
   user starts and caps. Missing endpoint evidence leaves the elaborated count.
   In a pin-and-confirm pass, a seed that changes a count the elaboration
   consumed skips that pass's confirmation synthesis: the handshake reads
   `.latency`, so the driver re-elaborates with the seeded count and confirms
   that hardware instead ([AUTO_PIPELINE_DESIGN.md](AUTO_PIPELINE_DESIGN.md)).
   The rebuilt holder is not re-synthesized during that pass's path-delay
   characterization when every multi-cycle path it owns already has evidence
   for its current `MCP_SHAPE`. Only the handshake's compare constant changed,
   so `HOLDER_DELAY_FROM_EVIDENCE` gives raw delay / elaborated count, which is
   what synthesis reports per cycle. For WireGuard's 5-lane Poly1305 MAC holders
   (Vivado 2019.2, xc7a200t) that is 67.5 ns / 4 against a measured 16.8 ns, and
   skipping their re-synthesis saves about 17 minutes per pass. A new shape, or
   a holder with fixed (non-tag) paths, is still synthesized.
2. **Matching.** For each report, `AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT` matches the report's
   start/end register cells against the XDC globs (`[*]` → `\[[^/]*\]`), excludes
   non-D destination pins, and requires
   `requirement / period` to equal the group's current count.
3. **Feedback.** When the matched path fails, `AUTO_MULTI_CYCLE_FEEDBACK` runs **before** any
   pipelining feedback for that main:
   - Needed count: `AUTO_MULTI_CYCLE_NEEDED_NCYCLES` = `max(N + 1, ceil(N · path_delay_ns / period))`.
     `VIVADO.PathReport` already reports a multi-cycle path's delay per cycle.
   - Needed ≤ the cap (`latency=` or `max_latency=`): the count is raised and the
     iteration's action is `auto_multi_cycle(key N->N')`. The plan's cut bookkeeping is untouched,
     because a failing MCP says nothing about cut count, and its stagnation counters are
     reset.
   - Needed > the cap: the plan stops with `stopped_reason = "auto_multi_cycle_latency_limit"` and
     `[sweep] WARNING: limited by AUTO_MULTI_CYCLE ...`, then TIMING NOT MET. Planless mains record
     the same reason.
4. **Provisional seed correction.** After a pass, complete per-pair reports may
   propose a smaller count once per canonical MCP group and datapath shape
   (`MCP_SHAPE`). The shape follows the capture data cone, stopping at register
   outputs, and includes callable identities and types, not timing hashes.
   Changes confined to the count/ready controller do not reset this allowance.
   The trial changes XDC overrides before harvesting, never drops below the
   elaborated/user floor, and requires whole-design confirmation. Failure
   restores the passing counts. Thereafter feedback is grow-only for that shape;
   ordinary pipeline trimming still counts only cuts.
5. **Termination.** Distinct groups receive feedback from their optional per-pair
   reports in the same synthesis, so they need not serially become clock-worst.
   A changed count always earns another synthesis run, including for
   planless designs, which otherwise stop after one run.
6. **Bookkeeping.** Best and met snapshots, their restores, and `sweep_history.json`
   (`auto_multi_cycle_ncycles`) record the counts each run was *synthesized* with. The final
   summary prints `[sweep] AUTO_MULTI_CYCLE <key> (<constraint>): N cycle(s) constrained on K
   multi-cycle path(s)`.

## 4. Pin-and-confirm

The `.latency` pin-and-confirm loop is described in
[`AUTO_PIPELINE_DESIGN.md`](AUTO_PIPELINE_DESIGN.md#5-latency-pin-and-confirm-loop-pypeline-designs-only);
AUTO_MULTI_CYCLE takes part in it through `HARVEST_AUTO_MULTI_CYCLE_NCYCLES`: the
elaborated counts overlaid with the sweep's final overrides.

- **Skip.** Pass 2 is skipped for AUTO_MULTI_CYCLE's sake when the harvest equals both the
  elaborated counts and every `.latency` value design code read
  (`AUTO_MULTI_CYCLE_BUILT_MATCHES_ELABORATED`). The build prints `AUTO_MULTI_CYCLE: every .latency read
  matched the built multi-cycle count`, and a correct `start_latency=` costs nothing.
- **Confirmation repair.** Resized datapaths are seeded from their new isolated
  endpoint measurements before confirmation. An MCP-only failure raises counts
  through the XDC overrides, preserves every pipeline, and re-confirms. It does
  not restart the placement search. A fixed/capped failure remains a failure.
  Repairs are bounded (`SWEEP.MAX_CONFIRMATION_MCP_REPAIRS`, 4 syntheses); a
  confirmation still failing after that reports timing not met. Isolated
  evidence from replicated instances keeps the worst raw delay.
- **Pass 2.** Otherwise the loop runs even for designs with no AUTO_PIPELINE reads: it
  installs `pypeline.SET_AUTO_MULTI_CYCLE_LATENCY_CACHE` next to the AUTO_PIPELINE cache before
  `PARSE_FILE`. Convergence requires both harvests to be unchanged, and every pass prints
  `AUTO_MULTI_CYCLE <key>: N cycles`.
- **Renaming.** Re-elaborating renames the function holding the tagged registers (the
  resolved count is part of its identity). The fresh `MultiMainTimingParams` carries no
  overrides; endpoint-qualified characterization can seed them before confirmation. Both
  exact-path and function-name pipeline seeding check the new caller chain;
  the renamed MCP interior and its primitive leaves remain combinational.
- **Unread tags.** `CHECK_AUTO_MULTI_CYCLE_TAGS_READ` runs at the start of
  `AUTO_PIPELINE.DO_SWEEP_AND_AUTO_PIPELINE`: a non-fixed AUTO_MULTI_CYCLE nothing read would let the XDC and the
  handshake disagree, so the build exits before any synthesis.
- **Native sim.** A non-`--comb` `--sim` passes the harvest to `pypeline_sim.run_sim`
  (`auto_multi_cycle_latencies=`).

## 5. Limitations

- A user-written AUTO_PIPELINE call inside MCP logic still authorizes that call
  to be pipelined. The MCP count does not include this added latency; the
  caller-context rule deliberately preserves that explicit authorization.

- Only Vivado emits multi-cycle constraints (`GET_MCP_PATH_CONSTRAINTS`). Every other
  backend writes its constraints through the same function, so a design with a
  multi-cycle path stops there with "Multi cycle paths have only been tested with Vivado!".
  Support for other tools is discussed in [#346](https://github.com/JulianKemmerer/PipelineC/discussions/346).
- The coarse sweep, `--no_sweep` and `--comb` build the elaborated counts unchanged.
- The count never goes below where it started: a post-met probe downward would cost a
  full synthesis per step on large designs.
- Only the worst path per clock group is reported, so an AUTO_MULTI_CYCLE path hidden behind a
  worse path is raised in a later iteration.
- Tagged endpoints must exist in the synthesized netlist. Preservation is not a
  substitute for an observable datapath or valid handshake. Empty endpoint
  collections remain errors; a nonempty collection alone does not prove every
  relevant bit survived or received the exception.
- Report diagnostics inspect the reported worst paths, not every netlist path.
  Full coverage requires checking physical endpoints and setup/hold requirements;
  the DSP regression performs that audit on its variable-input fixture.
- Report matching accepts struct registers, whose cells are named per field
  (`launch_reg[field][bit]`, matched by `[*]` → `\[[^/]*\]`).

## 6. Tests

See [`pypeline_TESTS.md`](pypeline_TESTS.md#auto_multi_cycle-coverage). The
end-to-end check is `auto_multi_cycle_sweep_test.py` (**Vivado**,
`build_report_vivado`), in three builds: (1) from the default start of 1, the
sweep raises the multi-cycle count (`action=auto_multi_cycle(...)`) until the
path meets timing; pass 2 re-elaborates, the final XDC carries the count, and
the pipelined native `--sim` asserts the handshake waits count + 1 cycles;
(2) restarting at that count settles with no change and pass 2 skipped; (3) a
`max_latency=1` cap fails the build naming it. `auto_multi_cycle_unit_test.py`
covers this module's functions in-process on synthetic reports.
[`added_latency_context_test.py`](../src/tests/pypeline_tests/inst/added_latency_context_test.py)
adds a shared-helper regression across two MAINs, tagged bodies, fixed/auto
MCP wrappers, direct FSM calls, and untagged bridges. It checks actual
stage-zero wrapper maps, lock/boundary strategies, seeding, and pre-write
rejection without synthesis.

`mcp_dsp_packing_test.py` adds a variable-input DSP chain shared across fixed
and automatic MCPs and an AUTO_PIPELINE call. It checks per-bit endpoint
preservation, actual setup/hold requirements, DSP register settings, control
and neighboring timing, native/GHDL data and backpressure behavior, automatic
count growth/confirmation, routed preservation, negative audit cases, and warm
reuse. Launch control is checked from controller registers to each preserved
launch register's CE or D pin: Vivado can legally tie CE high and implement the
enable with a data-input feedback mux. This transformation keeps the MCP timing
endpoints intact. The audit requires single-cycle setup and ordinary hold on
those controller paths, and a negative case deliberately relaxes them to ensure
that the check rejects incorrect control exceptions.
The routed fixed-count fixture uses `--comb`, leaving its separate body call
unpipelined. Its audit checks MCP preservation and timing requirements; it does
not require whole-design timing closure, and the body can violate the target.
The automatic fixture separately checks synthesis timing confirmation with body
pipelining enabled; it is not routed by this test.
`--prepare-only` runs elaboration and native/GHDL checks without Vivado synthesis.
Focused tests do not establish whole-application timing or QoR.
