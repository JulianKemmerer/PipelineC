# MULTI_CYCLE and AUTO_MULTI_CYCLE: multi-cycle paths

A multi-cycle path relaxes the timing requirement between two registers:
`MULTI_CYCLE[N]` tells synthesis the launch register's value is only captured
every N clock cycles, and `AUTO_MULTI_CYCLE(...)` lets the throughput sweep
choose N. Neither adds registers; they widen the permitted settling time.

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
| `GET_MCP_CELL_PATHS` | constraint writer, sweep | the Vivado cell globs of every multi-cycle path in an instance: the one source for both constraints and report matching |
| `GET_MCP_PATH_CONSTRAINTS`, `MCP_EFFECTIVE_NCYCLES` | `SYN.WRITE_CLK_CONSTRAINTS_FILE` | `set_multicycle_path` / `KEEP` lines for the clock constraints file, with the sweep's current count |
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
set_multicycle_path N -setup -from [get_pins <start>_reg[*]/C] -to [get_pins <end>_reg[*]/D]
set_property KEEP TRUE [get_cells <start>_reg[*]]
set_property KEEP TRUE [get_cells <end>_reg[*]]
```

relative to the synthesized top. Only Vivado is supported: any other tool
raises an error when a design has a multi-cycle path.

**Constraint value.** `MultiMainTimingParams.auto_multi_cycle_ncycles` holds the sweep's current
count per AUTO_MULTI_CYCLE key. `GET_MCP_PATH_CONSTRAINTS` writes
`MCP_EFFECTIVE_NCYCLES`: that override, else the elaborated count. The sweep changes a
count without re-elaborating, and only the XDC changes, so
`MultiMainTimingParams.GET_HASH_EXT` appends the overrides that **differ** from the
elaborated counts. Otherwise a same-named log from another count would be replayed.
Designs without a raised AUTO_MULTI_CYCLE hash exactly as before.
`GET_MCP_CELL_PATHS` is the one source of the register cell globs, used both by the
XDC writer and by report matching.

## 3. Sweep feedback

`SWEEP.DO_PLANNED_THROUGHPUT_SWEEP` handles AUTO_MULTI_CYCLE paths as follows:

1. **Setup.** `COLLECT_AUTO_MULTI_CYCLE_GROUPS` gathers every instance's AUTO_MULTI_CYCLE paths by key; a key
   is one group with one count, since the design reads one `.latency` int. The counts are
   seeded from the elaborated values.
2. **Matching.** For each report, `AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT` matches the report's
   start/end register cells against the XDC globs (`[*]` → `\[\d+\]`) and requires
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
4. **Growth only.** The count never drops below its start: post-met trimming counts only
   cuts.
5. **Termination.** A changed count always earns another synthesis run, including for
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
- **Pass 2.** Otherwise the loop runs even for designs with no AUTO_PIPELINE reads: it
  installs `pypeline.SET_AUTO_MULTI_CYCLE_LATENCY_CACHE` next to the AUTO_PIPELINE cache before
  `PARSE_FILE`. Convergence requires both harvests to be unchanged, and every pass prints
  `AUTO_MULTI_CYCLE <key>: N cycles`.
- **Renaming.** Re-elaborating renames the function holding the tagged registers (the
  resolved count is part of its identity). The fresh `MultiMainTimingParams` carries no
  overrides, so the confirmation constrains the elaborated counts.
- **Unread tags.** `CHECK_AUTO_MULTI_CYCLE_TAGS_READ` runs at the start of
  `AUTO_PIPELINE.DO_SWEEP_AND_AUTO_PIPELINE`: a non-fixed AUTO_MULTI_CYCLE nothing read would let the XDC and the
  handshake disagree, so the build exits before any synthesis.
- **Native sim.** A non-`--comb` `--sim` passes the harvest to `pypeline_sim.run_sim`
  (`auto_multi_cycle_latencies=`).

## 5. Limitations

- Only Vivado emits multi-cycle constraints (`GET_MCP_PATH_CONSTRAINTS`). Every other
  backend writes its constraints through the same function, so a design with a
  multi-cycle path stops there with "Multi cycle paths have only been tested with Vivado!".
  Support for other tools is discussed in [#346](https://github.com/JulianKemmerer/PipelineC/discussions/346).
- The coarse sweep, `--no_sweep` and `--comb` build the elaborated counts unchanged.
- The count never goes below where it started: a post-met probe downward would cost a
  full synthesis per step on large designs.
- Only the worst path per clock group is reported, so an AUTO_MULTI_CYCLE path hidden behind a
  worse path is raised in a later iteration.
- The tagged `.start` / `.end` registers must survive synthesis. A capture register
  whose value nothing uses is optimized away, along with the launch register feeding
  it, and Vivado then rejects the `set_multicycle_path` because it names no cells. That
  is true of `MULTI_CYCLE[...]` as well.
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
