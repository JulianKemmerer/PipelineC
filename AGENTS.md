# AGENTS.md

Instructions for LLM coding agents working in the PypelineC repository.

**Read [CONTRIBUTING.md's "When making changes" section](CONTRIBUTING.md#when-making-changes)
first, then read this entire file before planning your edits.** This file adds detailed
agent instructions to that section; follow both. The design documents in [`docs/`](docs/)
are the architectural record.

## What is here

PypelineC is a hardware description language. It has two
front ends that build the same `Logic` objects (`src/LOGIC.py`):

- **Pypeline** (Python, current): `src/PY_TO_LOGIC.py` elaborates designs written with
  `src/pypeline.py`. `src/pypeline_sim.py` simulates them natively in Python.
- **PipelineC** (C, legacy): `src/C_TO_LOGIC.py` and `src/C_TO_FSM.py`. New features go
  into Pypeline.

Everything after `Logic` is shared. The `AUTO_*` modules decide implementations
(pipelining, multi-cycle paths, FSMs). `SWEEP.py` runs the timing sweep. `VHDL.py`
and `RAW_VHDL.py` write VHDL. `SYN.py` and one module per synthesis tool (`VIVADO.py`,
`QUARTUS.py`, `OPEN_TOOLS.py`, `PYRTL.py`, `DEVICE_MODELS.py`, ...) measure timing.
`SIM.py` and its backends simulate the generated HDL. `src/pipelinec` is the command
line; `src/pypelinec` is a link to it.

Other top-level places:

- `include/pypeline/`: Pypeline libraries (operators, floats, fixed point, RAM, streams, DSP).
- `include/*.h`: C front-end libraries.
- `examples/pypeline/` and `examples/`: example designs.
- `cache/`: committed operator delay caches. A copy of the repo without them
  re-characterizes every operator.
- `src/tests/pypeline_tests/`: the test suite ([`docs/pypeline_TESTS.md`](docs/pypeline_TESTS.md)).
- `docs/`: user docs ([`docs/README.md`](docs/README.md),
  [`docs/pypeline_guide.md`](docs/pypeline_guide.md)), one `*_DESIGN.md` per main
  module, the issues inventory and the code reviews (see
  [Check known issues and code reviews](#check-known-issues-and-code-reviews)).

Common commands, run from the repo root:

```
./src/pypelinec design.py --comb --no_synth --out_dir OUT   # elaborate and write VHDL, no synthesis
./src/pypelinec tb.py --sim --comb --run all                 # native Python simulation
./src/pypelinec tb.py --sim --comb --cocotb --ghdl --run all # generated VHDL through cocotb + GHDL
./src/pipelinec design.c --comb --no_synth --out_dir OUT     # legacy C front end
```

For test-runner commands, see [Testing](#testing).

## Ground rules

- **Scratch goes outside the repo.** Build output (`--out_dir`), harness scripts, A/B
  copies and handoff notes do not belong in the tree.
- **Don't edit sources while your own build runs.** Pipelining passes re-run the
  design in-process and re-read function source from disk (`inspect.getsource`).
  An edit shifts line numbers under live function objects, and a later pass reads the
  wrong source block. Make edits between runs, or run from a frozen copy of the
  compiler and design. The copy needs everything the repo ships (`cache/`, data
  files), or tests fail for setup reasons.
- **One `pypelinec` process per output directory.** To reuse a warm build in
  parallel runs, copy the whole directory. Don't add locking so processes can share one.
- **Python 3.8.** Python 3.8 is supported, so don't use newer syntax for now.
  Scripts that edit source by `ast` offsets must check the text at each offset,
  because 3.8 reports wrong column offsets inside f-strings.
- **Long runs.** Run a long build or test run (timing sweep, hardware run, big test
  selection) in the background only when there is relevant, necessary work you can
  do alongside it without affecting it. Otherwise, or once that work is done, use a
  blocking wait or a completion notification. Don't spend tokens polling log files or
  process status, and don't invent work to stay active. Let required tests finish:
  duration alone is not a reason to stop them.

## Before you change code

### Check known issues and code reviews

- **Check the issues inventory first**, for feature and cleanup work as well as bug
  fixes. The [priority-ranked issues inventory](docs/issues_inventory.md) adds
  reproduction steps, code pointers and workarounds to the GitHub issues. Search it
  for the affected features and modules, read the linked issue threads, and account
  for known failure modes, limitations and workarounds in the implementation and
  test plan.
- **Read the relevant reviews.** For compiler changes, read the overview of the
  [compiler complexity review](docs/code_reviews/complexity_review/REVIEW_COMPLEXITY.md)
  and the affected modules' reviews linked from it. When adding or changing tests,
  read the [test-suite review](docs/code_reviews/tests_review/TEST_REVIEW.md) and its
  linked inventory for the affected tests.
- **Don't extend the patterns they flag:** duplicated logic, responsibilities outside
  their owning module, overlapping test builds, unrelated scenarios added to an
  already unwieldy test file. Check the specific review's recommendations when
  choosing an implementation; nearby code is not automatically a good model.
- **Keep the response proportional.** A local fix doesn't need to implement a whole
  architectural recommendation, only to avoid adding to the problem. If a change must
  extend a flagged pattern, explain the tradeoff and name the remaining cleanup in the
  handoff or final report.
- **Verify review findings against the current tree.** Reviews describe particular
  source snapshots and include proposals. They don't prove that a bug remains
  unfixed or that a proposed API, runner flag or directory layout exists. Resolve
  discrepancies from the current source and the relevant design or test reference,
  and update a review whose finding has changed (see [Documentation](#documentation)).

### Find where the change belongs

- Read the design document of every module you change. It says how the module works
  and where a change belongs.
- `src/X.py` pairs with `docs/X_DESIGN.md`. Compare the two folder listings; there is
  no mapping table. A module without its own design doc (tool backends, simulator
  backends, `utilities.py`, `src/pipelinec`, `pypeline_host.py`,
  `pypeline_sim_debug.py`) names the doc section that covers it in its module
  docstring.
- If the feature fits a section of an existing design doc, its code goes in that
  doc's module. A new `src/X.py` is only for a genuinely new subsystem, and it comes
  with its own `docs/X_DESIGN.md`. If the code lands in a different module than the
  doc text, move the doc text to that module's doc.
- Check import constraints before placing code. Native simulation
  (`pypeline_sim.py`) never imports `PY_TO_LOGIC`, so code it runs can't live there.
- The C front end (`C_TO_LOGIC.py`, `C_TO_FSM.py`) is intentionally undocumented for now.
  Don't plan design docs for it.

### Layering rules

- **The driver stays thin.** `src/pipelinec` holds argparse, run settings and a
  top-level sequence of named calls. It defines no functions and no loops. A step
  with logic of its own is a function in the module whose feature it serves
  ([`SYN_DESIGN.md`](docs/SYN_DESIGN.md#the-build-driver-srcpipelinec)).
- **Backend scripts are strings in `src/<TOOL>.py`.** Every backend writes its TCL,
  `.ys` and `.sh` files at run time from Python strings. Don't check in standalone
  helper scripts. Better still, do the work inside the tool itself.
- **Look for one central hook before editing every backend.** If a feature seems to
  need the same edit in every synthesis backend, first find the decision point in
  `SYN.py` that all backends already call, and put the logic there. If per-backend
  edits really are needed, say so before editing, with the alternative.
- **Library features stay pure Pypeline.** A feature in `include/pypeline/` uses raw
  `vhdl()`, `@pipeline_latency`, `@sim_model` and generated functions, with no `src/`
  changes. Don't reuse old C front-end machinery. If you find a compiler bug, work
  around it in the library if that's clean, and write a handoff for the fix.

### Scope the design

- For a large feature, question the requirements, including the human's. Say which
  requested parts aren't worth their cost before writing the plan, and prefer the
  smallest safe design that reuses an existing mechanism.
- Implement agreed designs faithfully. Don't add heuristic bounds, arbitrary floors or
  behavioral limits nobody asked for unless they're confirmed and tested.
- If a simplification turns out unsafe during implementation, fix it and say so plainly.

## Code hygiene

- **Parameters:** don't accept unused parameters, flags or state arguments. Wire every
  received parameter into the code that runs, or remove it.
- **Module globals:** give every module global a one-line comment, matching the
  comments next to it.
- **Declared state:** declare results stored on `ParserState`, or on any other shared
  object, in its `__init__` with a one-line comment. Don't compute such state lazily on
  first use or branch on `hasattr`: behavior then depends on call order.
- **Retire what you replace:** when new logic replaces a rule, delete the code that
  can no longer run. Search `src/` and `docs/` for the old function and rule names and
  fix every comment and doc that cites them, in other modules too. Re-read the
  comments next to any code whose behavior you change.
- **Keep evidence you can't attribute:** if a measured result (a timing path, say)
  can't be matched to part of the design, handle it conservatively or report it.
  Don't silently drop it.
- **Console noise:** print each compiler `NOTE:` or warning once per build phase or
  session, not once per candidate pass or iteration.

## Names, caches and determinism

- **Generated names are a pure function of the source.** The pipelining loop
  re-parses the design in-process and matches functions across passes by name. Never
  build a name from `repr()` or `id()` of an object (those embed memory addresses).
  A module-level memo keyed by name must be cleared on re-parse, through the
  `DEL_ALL_CACHES()` of `LOGIC`, `C_TO_LOGIC` or `SYN`. When you touch naming, extend
  `inst/double_parse_file_test.py`, which asserts the two parses produce identical names.
- **A generated file depends only on what names it**: its entity name and inputs,
  never planner state or the order files were written in. Two different renderings
  that can share one name are a bug to fix. An output file whose content changes
  between passes of one run is a bug too.
- **Names drive sweep decisions.** The sweep attributes a timing path to a function
  by finding the function's name in instance labels and register names. If you change
  how instances, entities or functions are named, or which function is tagged,
  compare the attribution and actions in `sweep_history.json` before and after.
- **Generated names are expected to move with line numbers.** Library code is named
  from its source line (`pypeline_py_lNNNN`), so adding or deleting lines in
  `pypeline.py` renames everything defined below. That is not a regression.
- **Caches save synthesis runs.** Use cached results whenever they're valid, and make
  sure code detects and ignores stale entries. Cached or remembered data must never
  make a build fail that would succeed without it. A fix that invalidates old caches
  is fine; don't add workarounds to preserve them.
- **C front-end output is not byte-reproducible.** C instance names carry
  `id()`-derived suffixes, so an A/B comparison of C builds must normalize those
  suffixes and compare sorted lines.

## Writing Pypeline designs and libraries

- **Synthesize what you build.** Native simulation (`sim_call`, and `--sim --comb`
  without `--cocotb`) runs the design as Python and never goes through the
  `PY_TO_LOGIC` elaborator, so it misses errors like the two below. Give each new
  reusable block a `*_synth_top.py` registered as a synthesis test, and register the
  composed top-level design as its own synthesis test too: per-block tests can't see
  the cross-module paths that often set the clock rate.
- **VHDL reserved words fail only at synthesis.** Don't name `@enum` members or
  `@struct` fields `release`, `reject`, `register`, `next`, `block`, `open`, `range`,
  `wait`, `file`, `label`, `null` or any other VHDL reserved word. Locals with such
  names get auto-renamed with a warning; grep build logs for
  `not a legal VHDL identifier` rather than trusting the exit code.
- **Ternary branches must have identical types.** A bare integer literal gets its
  minimum width, so `CONST if c else x16` fails when `CONST = 1`. Bind the constant to
  a typed local first (`k: uint16_t = CONST`).
- **Native sim doesn't model VHDL-only primitives.** Functions that exist only as
  VHDL primitives (`rotl`, `bswap`, `bit_dup`, `array_to_uint_le`, and `vhdl()`-based
  wrappers like `make_stream_fifo`) raise `NotImplementedError` in native sim. That is
  expected. Use them in designs anyway, and test that code through cocotb + GHDL.
  Check the specific factory first: being built on `vhdl()` doesn't by itself mean a
  wrapper can't simulate natively.
- **Never hardcode a latency.** Read it from a `.latency` value (an `AUTO_PIPELINE`
  instance has one), and give new pipelined blocks one too.
- **Read the critical path, don't guess.** Before changing a design for timing, read
  the failing path from the synthesis tool's log in the output directory.

## Testing

Read [`docs/pypeline_TESTS.md`](docs/pypeline_TESTS.md) before selecting or changing
tests, especially [Categories](docs/pypeline_TESTS.md#categories),
[Running](docs/pypeline_TESTS.md#running) and, when adding coverage,
[Adding a test](docs/pypeline_TESTS.md#adding-a-test). Keep detailed suite reference
material there.

### Run the existing suite

Run from the repo root. Replace `CATEGORY`, `NAME` and `SUBSTRING` with the category
and registered test names you intend to exercise:

```sh
# Discover registered names in a category without running them.
python3 src/tests/pypeline_tests/run_all.py --category unit --list

# Run one registered test with its category's checks.
python3 src/tests/pypeline_tests/run_all.py --category CATEGORY -t NAME -j 1

# Run matching names within one category, or several relevant categories.
python3 src/tests/pypeline_tests/run_all.py --category CATEGORY -k SUBSTRING -j 2
python3 src/tests/pypeline_tests/run_all.py --category elab --category unit -j 4

# Documentation changes: check repository links and documentation conventions.
python3 src/tests/pypeline_tests/run_all.py --category unit -t doc_links_test -j 1

# Known-issue reproducers are opt-in, including when selecting one by name.
python3 src/tests/pypeline_tests/run_all.py --category known_issues -t NAME -j 1
```

- **Select a single test by category and exact name.** Names can be reused across
  categories, and an unqualified `-t NAME` currently selects only one of those
  registrations. Don't use numeric `-t` indices: the displayed `--list` order and
  numeric selection order can differ. `--list` returns before applying `-t` or `-k`,
  so it does not preview those filters.
- **One `-t` and one `-k`.** Repeating either does not build a list; run an explicit
  list as separate category/name invocations. Don't assume a name substring selects
  every execution mode or dependency of a feature. The
  [selection review](docs/code_reviews/tests_review/TEST_REVIEW.md#4-fix-targeting-before-changing-coverage)
  describes these limitations.
- **Run new or changed tests through the runner.** Directly executing a fixture
  bypasses category checks, including checking that a synthesis log names the
  expected tool. Use direct runs for diagnosis only, then verify through the
  registered invocation.
- The runner creates a fresh output root and prints each test's log path. Inspect
  those logs for failures. Choose `-j` to fit the machine and tools; some test
  wrappers launch their own parallel work. Keep timeouts enabled unless the
  selected workload calls for an explicit override.

### Choose what to run

- **Test what changed.** A narrow fix needs its reproducer, its new regression test,
  the categories whose code paths it touches (for example `elab`,
  `elab_introspect`, `native_sim`, `unit`) and the affected example's own test. A full
  default `run_all.py` starts hours of vendor synthesis first; run it only for broad
  compiler or backend changes. A change to shared planner or sweep policy (behavior
  that applies to every design of a kind) also needs that policy's broader categories.
- **The per-tool sweep matrix** (`-k sweep_float32`) only needs the backends whose code
  or shared timing parsing the change touched. Restrict it with the corresponding
  `--category synth_<tool>` selections.
- **Match the test's execution mode to the claim.** Native simulation, elaboration,
  generated-HDL simulation and synthesis establish different things. Check the
  registered command and assertions; a category name alone does not establish its
  cost or coverage. An `elab` pass does not prove the VHDL compiles, and a native
  simulation pass does not prove hardware correctness.

### Write tests

- **Pick the test by the bug's failure mode.** An elaboration failure can use a
  plain design registered in `elab_tests.py`. A GHDL or synthesis rejection needs
  an invocation that actually runs that tool. Silent bugs need assertions on the
  affected behavior: inspect `PY_TO_LOGIC.PARSE_FILE` state for structural contracts,
  or check generated hardware behavior through the appropriate HDL simulation.
  Don't copy the nearest-looking test's plumbing without checking what it proves.
- **Prove the test catches the bug.** Revert the fix by hand, confirm the test fails,
  then restore it. A test that passes either way tests nothing; the exact construction
  often decides whether the buggy path is reached.
- **Reuse a related test file when its execution mode and setup fit.** Each
  registration can pay its own elaboration, synthesis or GHDL start-up cost, but
  combining unrelated cases or cheap assertions with expensive integration builds
  makes focused testing harder. Follow the test review's guidance on preserving
  coverage while sharing setup; do not merge or delete tests merely to reduce file
  counts. When adding a `test_*` function, verify that the registered invocation
  runs it: importing a design through `pypelinec` skips its `__main__` test harness.
- **Layout in `inst/`:** `*_test.py` files are registered tests (`registration_audit_test`
  enforces that every one is registered), `*_design.py` files are fixtures. Keep
  regression cases and known-issue reproducers in these files rather than inlining
  them into category drivers. Register each new test file in the right runner
  module with a comment saying what it checks; a new case in an existing file
  should use that file's existing registration when it exercises the case.
- **Synthesizing tests use `device_models` (sky130) by default**, one tool per test.
  Use Vivado only for Vivado-specific behavior, on a part with a committed cache. See
  [Choosing a synthesis tool](docs/pypeline_TESTS.md#choosing-a-synthesis-tool).
- **One behavior per test.** Name each test function after the behavior it checks,
  and split a test that checks several. Keep header comments and registration
  docstrings in step with the real build counts, scenarios and run times.
- **Known issues:** register unfixed-bug reproducers in `known_issues_tests.py`.
  Use `expect_fail=True` when the underlying command fails while the bug is present;
  an XFAIL records that failure, not correct behavior. If exit status cannot capture
  the bug, use explicit assertions and document the verdict semantics. The category
  is excluded from the default run. Investigate an XPASS and, once the fix is
  verified, promote the reproducer to the appropriate normal regression category
  and update the issue inventory. Do not count an unrelated setup failure as proof
  that a known bug reproduced.

### Report results honestly

- **Measure before claiming.** Report only results you observed, and never summarize
  results before the run that measures them finishes. Base recommendations on test
  results. Say whether a pass count comes from one complete run or from reruns of
  earlier failures.
- **Tell your failures from existing ones.** Gate a change against a baseline built
  from the same commit and cache state, so unrelated commits can neither hide nor
  fake a difference. Before calling a failure a known issue or a regression, check
  the relevant issue and reproducer and, when needed, the unchanged baseline: a
  similar symptom alone is not enough. Report the evidence and the issue reference;
  never hide a failure.
- **Keep quality-of-results changes apart from efficiency changes.** If work to cut
  synthesis runs also changes placement or trim decisions, describe and verify each
  change on its own, and say which results support which.
- **Report what you couldn't run.** Not every machine has every vendor tool. Skips,
  timeouts and missing-tool failures are not passes. Say which tests you couldn't
  run and why, along with the commands needed to complete that coverage.

## Documentation

- **Every source change updates its docs.** Find and update every design document
  that describes code you changed. When you change CLI flags, configuration
  variables, generated output paths or function names, grep all of `docs/` and
  `README.md` and update every occurrence, including flag tables and artifact lists.
- **Keep reviews current.** If verification shows that a review finding is resolved,
  partly addressed or no longer accurate, or your change alters it, revise that
  review section in place, together with its recommendations, any overview or
  module-review summary of it, and the matching `*_DESIGN.md` sections. State what
  remains to be done and the source or test evidence for the revised finding. Keep
  historical measurements tied to their original source and conditions, and claim
  only the checks you reran and the findings you revalidated.
- **Reference, not a logbook.** Docs describe what the code does now, in the present
  tense. No dated entries, no "recently added" or "now supports", no session
  write-ups. `git log` is the change record. A reason worth keeping goes in the file's
  `## History` section, under the entry that owns the topic. See
  [Documentation conventions](docs/pypeline_DESIGN.md#documentation-conventions).
- **Edit in place.** Change the section that already covers the subject. Never append
  summary paragraphs or trailing notes.
- **Audience separation.** User guides (`README.md`, `docs/README.md`,
  `docs/pypeline_guide.md`) cover user workflows, CLI usage and behavior in plain
  terms. Implementation details and internal data structures belong in the module's
  `*_DESIGN.md`.
- **Numbers carry their conditions** (tool, part, model version, a commit hash where
  it pins an artifact), not the date they were measured.
- **Cite other docs by anchor**, from code comments too: `SYN_DESIGN.md#6-caches`,
  not "section 6".
- **Every `docs/*_DESIGN.md` has the convention note and a complete
  `## Table of Contents`.** A new `##` heading needs a TOC line.
  `inst/doc_links_test.py` enforces both and checks links in every Markdown file.
- **No machine-local absolute paths** in docs or issue text. Read every link you
  add: a malformed link (a space in the URL, say) isn't parsed as a link at all, so
  the link test passes it silently.
- **Diagrams are generated.** Edit the Python source next to an image (for example
  `docs/images/dev_board.py`) and re-render it. Never hand-edit the SVG.

## Issues and handoffs

### Issues

- **Issue or discussion?** An issue is something broken in a real design (wrong
  hardware, a sim/hardware mismatch, invalid HDL, a crash, a misleading error) or a
  missing feature that practically blocks designs. Ideas, cosmetics and generated-HDL
  style belong in Discussions. Before recommending that an enhancement move to
  Discussions, probe it for a real bug hiding inside. Close a C-only issue that
  Pypeline already solves with a comment saying so. Open-ended discussions stay open.
- **When you find a bug to address later,** draft a GitHub issue: a title, a
  description of what happens with a minimal reproducing snippet, the observed effect
  and any workaround. First check for an existing issue and reproducer; extend the
  existing record when it is the same bug. Otherwise add an entry to
  [`docs/issues_inventory.md`](docs/issues_inventory.md) at its rank and register a
  reproducer in `known_issues_tests.py`. The issue number can stay TBD until the
  issue exists.

### Handoffs

A handoff is a standalone Markdown note for another session or person to act on.
If possible it holds a reproducer, expected vs actual behavior, the suspected code location, a
suggested fix and a regression test. It contains only the work being handed off: no
list of follow-ups already tracked in issues or the inventory. Keep handoffs out of
`docs/`, and tell the human where you put one.
