# AGENTS.md

Instructions for LLM/AI coding agents working in the PypelineC repository. Human
contributors are not required to read this file.

**Read [CONTRIBUTING.md's "When making changes" section](CONTRIBUTING.md#when-making-changes)
first, then read this entire file before your first edit.** That section contains
the shared expectations for humans and agents; this file adds detailed agent
instructions. Follow both. The design documents in [`docs/`](docs/) are the
architectural record.

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
  module, the [priority-ranked issues inventory](docs/issues_inventory.md), the
  [compiler complexity review](docs/code_reviews/complexity_review/REVIEW_COMPLEXITY.md)
  and the [test-suite review and recommendations](docs/code_reviews/tests_review/TEST_REVIEW.md).

Common commands (run from the repo root; put `--out_dir` outside the repo):

```
./src/pypelinec design.py --comb --no_synth --out_dir OUT   # elaborate and write VHDL, no synthesis
./src/pypelinec tb.py --sim --comb --run all                 # native Python simulation
./src/pypelinec tb.py --sim --comb --cocotb --ghdl --run all # generated VHDL through cocotb + GHDL
./src/pipelinec design.c --comb --no_synth --out_dir OUT     # legacy C front end
```

For test-runner commands and selection caveats, see [Testing](#testing).

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
- **Continue relevant work, or wait.** While a build or test runs, continue only
  relevant, necessary work that can be done safely without affecting the run.
  When none remains, use a blocking wait or completion notification as described
  in [Long runs](#long-runs). Do not invent extra work just to stay active.

## Before you change code

### Check known issues and code reviews

- **Check existing problems before planning or editing.** Read the
  [priority-ranked issues inventory](docs/issues_inventory.md). It orders known
  bugs and limitations by seriousness and adds reproduction steps, code pointers
  and workarounds to the GitHub issue records. Search it for the affected features
  and modules, and consult the relevant linked issue threads. Account for known
  failure modes, limitations and workarounds in the implementation and test plan.
  This check applies to ordinary feature and cleanup work too, not just bug fixes.
- **Read relevant review notes before extending existing code.** The
  [compiler complexity review](docs/code_reviews/complexity_review/REVIEW_COMPLEXITY.md)
  and [test-suite review and recommendations](docs/code_reviews/tests_review/TEST_REVIEW.md)
  serve two purposes: finding broader architectural improvements to work on, and
  identifying problems to avoid making worse in everyday contributions. For compiler
  changes, read the complexity overview and the affected modules' reviews linked
  from it. When adding or changing tests, read the test-suite review and consult
  its linked inventory for the affected tests.
- **Do not perpetuate the patterns the reviews identify.** Look for existing
  shared mechanisms before adding duplicate logic, keep responsibilities in their
  owning modules, and avoid adding overlapping test builds or unrelated scenarios
  to an already unwieldy test file. Check the specific review's recommendations
  when choosing an implementation; nearby code is not automatically a good model.
- **Verify review findings against the current tree.** Reviews describe particular
  source snapshots and include proposals. They are not proof that a bug remains
  unfixed or that a proposed API, runner flag or directory layout exists. Use
  current source and the relevant design/test reference to resolve discrepancies.
- **Update review sections when the code's condition changes.** If verification
  shows that a finding is resolved, partly addressed or no longer accurate, or
  your own changes alter it, revise the affected review section in place. Update
  its recommendations and any corresponding overview or module-review summaries
  so they agree. State what remains to be done and the source or test evidence
  supporting the revised finding. Keep historical measurements tied to their
  original source and conditions; claim only the checks you actually reran and
  the findings you revalidated. Update the relevant `*_DESIGN.md`
  sections alongside these review updates.
- **Keep the response proportional to the task.** A local fix does not require
  implementing an entire architectural recommendation. Prefer a focused change
  that avoids adding to the identified problem. If the change must extend a
  flagged pattern, explain the tradeoff and identify the remaining cleanup in the
  handoff or final report.
- **Establish whether failures predate the change.** Consult the relevant issue
  and reproducer, and compare against an unchanged baseline when needed. A similar
  symptom alone does not establish that a failure is a known issue. Report the
  evidence and issue reference; do not hide a failure or call it a regression
  without checking.

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

Read [`docs/pypeline_TESTS.md`](docs/pypeline_TESTS.md) before selecting or changing
tests, especially [Categories](docs/pypeline_TESTS.md#categories),
[Running](docs/pypeline_TESTS.md#running) and, when adding coverage,
[Adding a test](docs/pypeline_TESTS.md#adding-a-test). Keep detailed suite reference
material there. The [test-suite review](docs/code_reviews/tests_review/TEST_REVIEW.md)
identifies weaknesses and proposed improvements; verify the current registrations
and runner when it points out differences from the reference.

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

- **Use a category and an exact name for a single test.** Names can be reused
  across categories; an unqualified `-t NAME` currently selects only one of those
  registrations. Do not use numeric `-t` indices: the displayed `--list` order and
  numeric selection order can differ. `--category CATEGORY --list` lists that
  category, but `--list` currently returns before applying `-t` or `-k`, so it does
  not preview those filters. These limitations are described in the
  [selection review](docs/code_reviews/tests_review/TEST_REVIEW.md#4-fix-targeting-before-changing-coverage).
- **Run new or changed tests through the runner.** Directly executing a fixture
  bypasses category checks, including checking that a synthesis log names the
  expected tool. Use direct runs for diagnosis only, then verify through the
  registered invocation.
- `run_all.py` accepts one `-t` and one `-k`; repeating either does not build a
  list. For an explicit list, use separate category/name invocations. Do not assume
  a name substring selects every execution mode or dependency of a feature.
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
- **Don't wait on long DSP testbenches** (`pdw_tb` and similar) once everything
  relevant has passed, if they are unrelated to the change. Avoid selecting them;
  if already launched, stop only your own unrelated runs and report them as
  incomplete. Complete the integration checks the affected behavior needs.
- **Match the test's execution mode to the claim.** Native simulation, elaboration,
  generated-HDL simulation and synthesis establish different things. Check the
  registered command and assertions; a category name alone does not establish its
  cost or coverage. An `elab` pass does not prove the VHDL compiles, and a native
  simulation pass does not prove hardware correctness.
- Not every machine has every vendor tool. Inspect the summary for skips, timeouts
  and missing-tool failures; none is a pass. Say which tests you couldn't run, and
  why, along with the commands needed to complete that coverage.

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

- Run long builds (timing sweeps, hardware runs, big test runs) in the background
  when there is relevant, necessary independent work to do safely. Otherwise, or
  once that work is finished, use a blocking wait or completion notification.
  Do not spend tokens repeatedly polling log files or process status. Let required
  tests finish even when no other work remains; duration alone is not a reason to
  stop them.
- Consider building from a frozen copy of the compiler and design, so later edits
  can't change a run in progress. The copy needs everything the repo ships
  (`cache/`, data files), or tests fail for setup reasons.
- Launch long test runners detached (`setsid`, with their own log file). Never pause
  (`SIGSTOP`) a runner with tests in flight: a runner started from a background shell
  dies with its tests when its wrapper exits. To change parallelism, start a second
  runner on the tests not yet started.
- If a wait helper must check `/proc/PID/stat`, treat `Z` (zombie) as finished;
  `kill -0` succeeds on a zombie. Keep any necessary polling inside the helper,
  rather than issuing repeated agent tool calls to check process state.

## Documentation

- **Every source change updates its docs.** Find and update every design document
  that describes code you changed, along with review findings and recommendations
  affected by the change. When you change CLI flags, configuration variables,
  generated output paths or function names, grep all of `docs/` and `README.md`
  and update every occurrence, including flag tables and artifact lists.
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
  and any workaround. First check for an existing issue and reproducer; extend the
  existing record when it is the same bug. Otherwise add an entry to
  [`docs/issues_inventory.md`](docs/issues_inventory.md) at its rank and register a
  reproducer in `known_issues_tests.py`. The issue number can stay TBD until the
  issue exists.

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
