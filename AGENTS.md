# AGENTS.md

Instructions for AI coding agents, and the people directing them, working in the
PypelineC repository. Read all of it before your first edit. The design documents in
[`docs/`](docs/) are the architectural record; this file covers how to work in the repo.

## What is here

PypelineC is a hardware description language with automatic pipelining. It has two
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
  module, and the [open issues inventory](docs/issues_inventory.md).

Common commands (run from the repo root; put `--out_dir` outside the repo):

```
./src/pypelinec design.py --comb --no_synth --out_dir OUT   # elaborate and write VHDL, no synthesis
./src/pypelinec tb.py --sim --comb --run all                 # native Python simulation
./src/pypelinec tb.py --sim --comb --cocotb --ghdl --run all # generated VHDL through cocotb + GHDL
./src/pipelinec design.c --comb --no_synth --out_dir OUT     # legacy C front end
python3 src/tests/pypeline_tests/run_all.py --list           # numbered test list
python3 src/tests/pypeline_tests/run_all.py -t NAME          # one test, with its category's tool check
python3 src/tests/pypeline_tests/run_all.py --category elab --category unit -j 4
```

## Ground rules

- **No commits.** Never run `git commit` or any git command that writes the index:
  `add`, `mv`, `rm`, `stash`, `worktree`. Use plain `mv`, `rm` and edits. Read-only
  git (`status`, `diff`, `log`, `ls-files`) is fine. End multi-file work with one
  `git add ...` line for the human to run. List every new and modified path, plus the
  old paths of removed or renamed files so the deletions get staged too. For a
  "before" reference, copy the clean tree outside the repo.
- **Scratch goes outside the repo.** Build output, harness scripts, A/B copies and
  handoff notes do not belong in the tree.
- **Don't edit sources while your own build runs.** Pipelining passes re-run the
  design in-process and re-read function source from disk (`inspect.getsource`).
  An edit shifts line numbers under live function objects, and a later pass reads the
  wrong source block. Batch all edits, then launch builds. While they run, only read,
  or write outside the repo. If a build that overlapped edits fails strangely, rerun
  it clean before debugging anything.
- **One `pypelinec` process per output directory.** To reuse a warm build in
  parallel runs, copy the whole directory. Don't add locking so processes can share one.
- **Other sessions may be editing too.** Re-read shared files (test registrations,
  docs) right before a targeted edit. If a file already carries someone else's
  changes, point the human to `git add -p` for it.
- **Never message other agent sessions** unless told to. A "note to another session"
  means a handoff file (see [Handoffs](#handoffs)).
- **Python 3.8.** The package supports Python 3.8, so don't use newer syntax:
  `match`, `X | Y` annotations evaluated at runtime, parenthesized context managers.
  Scripts that edit source by `ast` offsets must check the text at each offset,
  because 3.8 reports wrong column offsets inside f-strings.
- **Keep working during long runs.** While a long build or test run goes, do
  independent work that doesn't touch the files it imports.

## Before you change code

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
- The C front end (`C_TO_LOGIC.py`, `C_TO_FSM.py`) is intentionally undocumented.
  Don't plan design docs for it.

### Layering rules

- **AUTO_PIPELINE decides, VHDL renders.** Planning code doesn't write VHDL text, and
  rendering code doesn't make planning decisions.
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
- Include how the change will be tested in any plan.

## Code hygiene

- **Parameters:** don't accept unused parameters, flags or state arguments. Wire every
  received parameter into the code that runs, or remove it.
- **Module globals:** give every module global a one-line comment, matching the
  comments next to it.
- **Declared state:** declare results stored on `ParserState`, or on any other shared
  object, in its `__init__` with a one-line comment. Don't compute such state lazily on
  first use or branch on `hasattr`: behavior then depends on call order.
- **No sentinel values in tuned numbers:** don't signal a mode with a special value of
  a number that other code scales or nudges. For example, no later multiplication can
  move a `0.0` multiplier off zero. Use an explicit flag.
- **One-time guards:** when adding a new reason to run a step that is guarded to run
  once (a measurement fallback, say), check whether the guard blocks the new reason.
- **Retire what you replace:** when new logic replaces a rule, delete the code that
  can no longer run. Search `src/` and `docs/` for the old function and rule names and
  fix every comment and doc that cites them, in other modules too. Re-read the
  comments next to any code whose behavior you change.
- **Keep evidence you can't attribute:** if a measured result (a timing path, say)
  can't be matched to part of the design, handle it conservatively or report it.
  Don't silently drop it.
- **Console noise:** print each compiler `NOTE:` or warning once per build phase or
  session, not once per candidate pass or iteration.
- **Formatting:** Ruff lints and formats ([`ruff.toml`](ruff.toml),
  [`.pre-commit-config.yaml`](.pre-commit-config.yaml)). Format only the lines you
  change. Don't run the formatter over whole files, so the diff shows only behavior
  changes.

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

- **Native simulation never emits VHDL.** `sim_call` and `--sim --comb` without
  `--cocotb` run the design as Python and never go through the `PY_TO_LOGIC` elaborator. A
  passing native sim proves nothing about the generated hardware. Give each new
  reusable block a `*_synth_top.py` registered as a synthesis test, and register the
  composed top-level design as its own synthesis test too: per-block tests can't see
  the cross-module paths that often set the clock rate.
- **Native sim doesn't model VHDL-only primitives.** Functions that exist only as
  VHDL primitives (`rotl`, `bswap`, `bit_dup`, `array_to_uint_le`, and `vhdl()`-based
  wrappers like `make_stream_fifo`) raise `NotImplementedError` in native sim. That is
  expected. Use them in designs anyway, and test that code through cocotb + GHDL.
  Check the specific factory first: being built on `vhdl()` doesn't by itself mean a
  wrapper can't simulate natively.
- **VHDL reserved words fail only at synthesis.** Don't name `@enum` members or
  `@struct` fields `release`, `reject`, `register`, `next`, `block`, `open`, `range`,
  `wait`, `file`, `label`, `null` or any other VHDL reserved word. Locals with such
  names get auto-renamed with a warning; grep build logs for
  `not a legal VHDL identifier` rather than trusting the exit code.
- **Ternary branches must have identical types.** A bare integer literal gets its
  minimum width, so `CONST if c else x16` fails when `CONST = 1`. Bind the constant to
  a typed local first (`k: uint16_t = CONST`).
- **Publish latency as `.latency`.** Expose every pipeline register's depth through a
  `.latency` attribute and compute alignment, testbench delays and golden models from
  it. Never hardcode a latency that timing work might change.
- **Read the critical path, don't guess.** Before changing a design for timing, read
  the failing path from the synthesis tool's log in the output directory.

## Testing

[`docs/pypeline_TESTS.md`](docs/pypeline_TESTS.md) describes the categories, file
layout and runner options. The essentials:

### Choose what to run

- **Test what changed.** A narrow fix needs its reproducer, its new regression test,
  the categories whose code paths it touches (for example `elab`,
  `elab_introspect`, `native_sim`, `unit`) and the affected example's own test. A full
  default `run_all.py` starts hours of vendor synthesis first; run it only for broad
  compiler or backend changes. A change to shared planner or sweep policy (behavior
  that applies to every design of a kind) also needs that policy's broader categories.
- **The per-tool sweep matrix** (`-k sweep_float32`) only needs the backends whose code
  or shared timing parsing the change touched.
- **Don't wait on long DSP testbenches** (`pdw_tb` and similar) once everything
  relevant has passed. Kill them.
- **Run new or changed tests through `run_all.py -t NAME`**, not directly. Run
  directly, a test skips its category's tool check, which fails a test whose log shows
  a synthesis tool other than the one its category names.
- `run_all.py` takes one `-t` and one `-k`. To run an explicit list, write a small
  wrapper over `common.run_tests`.
- Not every machine has every vendor tool. Say which tests you couldn't run, and why.

### Write tests

- **Pick the test by the bug's failure mode.** If the bug makes a tool fail loudly
  (GHDL or synthesis rejects the VHDL), the test is a plain design file registered in
  `synth_tests.py` or `elab_tests.py`, with no custom assertions. If the bug is silent
  (wrong logic, no error), call `PY_TO_LOGIC.PARSE_FILE` in-process and inspect the
  compiler's state directly. Don't copy the nearest-looking test's plumbing.
- **Prove the test catches the bug.** Revert the fix by hand, confirm the test fails,
  then restore it. A test that passes either way tests nothing; the exact construction
  often decides whether the buggy path is reached.
- **Prefer a `test_*` function in an existing file** over a new file: each
  registration pays its own elaboration, synthesis or GHDL start-up cost.
- **Layout in `inst/`:** `*_test.py` files are registered tests (`registration_audit_test`
  enforces that every one is registered), `*_design.py` files are fixtures. Put
  regression tests and known-issue reproducers there as standalone files, and register
  each one in the right runner module with a comment saying what it checks.
- **Synthesizing tests use `device_models` (sky130) by default**, one tool per test.
  Use Vivado only for Vivado-specific behavior, on a part with a committed cache. See
  [Choosing a synthesis tool](docs/pypeline_TESTS.md#choosing-a-synthesis-tool).
- **One behavior per test.** Name each test function after the behavior it checks,
  and split a test that checks several. Keep header comments and registration
  docstrings in step with the real build counts, scenarios and run times.
- **Known issues:** reproducers of unfixed bugs go in `known_issues_tests.py` with
  `expect_fail=True`. The category is excluded from the default run. An XPASS means
  the bug got fixed: promote the test out of that category.
- **The PDW project has one test in `run_all.py`:** `pdw_tb`, with no timeout.
  Don't register PDW component tests. DSP library tests are fine.

### Report results honestly

- **Measure before claiming.** Report only results you observed, and never summarize
  results before the run that measures them finishes. Base recommendations on test
  results. Say whether a pass count comes from one complete run or from reruns of
  earlier failures.
- **Compare like with like.** Gate a change against a baseline built from the same
  commit and cache state, so unrelated commits can neither hide nor fake a difference.
- **Keep quality-of-results changes apart from efficiency changes.** If work to cut
  synthesis runs also changes placement or trim decisions, describe and verify each
  change on its own, and say which results support which.

### Long runs

- Run long builds (timing sweeps, hardware runs, big test runs) in the background and
  wait for their completion notice. Don't poll in a loop.
- Consider building from a frozen copy of the compiler and design, so later edits
  can't change a run in progress. The copy needs everything the repo ships
  (`cache/`, data files), or tests fail for setup reasons.
- Launch long test runners detached (`setsid`, with their own log file). Never pause
  (`SIGSTOP`) a runner with tests in flight: a runner started from a background shell
  dies with its tests when its wrapper exits. To change parallelism, start a second
  runner on the tests not yet started.
- Wait on a process with a `/proc/PID/stat` state check that treats `Z` (zombie) as
  finished. `kill -0` succeeds on a zombie.

## Documentation

- **Every source change updates its docs.** Find and update every design document
  that describes code you changed. When you change CLI flags, configuration
  variables, generated output paths or function names, grep all of `docs/` and
  `README.md` and update every occurrence, including flag tables and artifact lists.
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
- **Output shown in docs comes from real runs.**
- **Diagrams are generated.** Edit the Python source next to an image (for example
  `docs/images/dev_board.py`) and re-render it. Never hand-edit the SVG.

## Issues, handoffs and reviews

### Issues

- **Issue or discussion?** An issue is something broken in a real design (wrong
  hardware, a sim/hardware mismatch, invalid HDL, a crash, a misleading error) or a
  missing feature that practically blocks designs. Ideas, cosmetics and generated-HDL
  style belong in Discussions. Before recommending that an enhancement move to
  Discussions, probe it for a real bug hiding inside. Close a C-only issue that
  Pypeline already solves with a comment saying so. Open-ended discussions stay open.
- **When you find a bug to address later,** draft a GitHub issue: a title, a
  description of what happens with a minimal reproducing snippet, the observed effect
  and any workaround. Add an entry to [`docs/issues_inventory.md`](docs/issues_inventory.md)
  at its rank and a reproducer to `known_issues_tests.py`. The issue number can stay
  TBD until the issue exists.

### Handoffs

A handoff is a standalone Markdown note for another session or person to act on.
It holds a reproducer, expected vs actual behavior, the suspected code location, a
suggested fix and a regression test. It contains only the work being handed off: no
list of follow-ups already tracked in issues or the inventory. Keep handoffs out of
`docs/`, and tell the human where you put one.

### Reviews

A synthesis backend that doesn't report measured area is not a review finding; most
tools aren't expected to measure area. Gaps in timing parsing still count.

## Projects built on PipelineC

Downstream projects such as `wireguard-fpga` live in their own repositories, owned by
their own sessions.

- Don't edit them from a PipelineC session. If a compiler change needs a change
  there, write a handoff with `file:line` and the exact edit.
- Reading their sources and building them is fine. Put `--out_dir` outside their
  tree, and check their `git status` before and after to show nothing changed.
- WireGuard verification is three configurations (encrypt, decrypt, and shared with
  both resources shared), each with the native random testbench and the fixed-vector
  `syn_tb`. Skip the legacy Poly1305, partial-sharing and stress variants unless the
  change targets them.
- Before handing off a structural WireGuard change, run its default hardware sweep and
  compare pipeline depths, multi-cycle path counts, device fit and timing with the
  recorded reference. Native simulation can't check any of those. Report only the
  hardware results you observed.
