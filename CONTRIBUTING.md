How to contribute to PypelineC
=====================================

Thank you for considering contributing to the PypelineC project!

```
“We do these things not because they are easy 
but because we thought they would be easy”
                           - programming meme
```

# PipelineC pre-contributors 2014~2026 (How did it get like _this_?)

Back in `2014` I was looking for a hobby project, something to work on a few hours per week. Something not too hard but would also be beneficial to myself and hopefully others in some way (I am an FPGA engineer). I estimated that implementing some C -> VHDL with a little pipelining would take a few months, maybe a year at most...

The code would fit all one file - one quick python script making use of an excellent python library `pycparser` for all the _real_ work around dealing with C language. How hard could it be?

There was no real plan in the design because it seemed so simple... and I was off writing a quick script with a handful of big functions, so I gave them all big capitalized names, `PARSE_FILE`, `WRITE_VHDL`, etc...

I am familiar with large scale industry programming practices - good style+formatting, unit tests, documentation, continuous integration, code reviews, thought out organization into classes/interfaces/generators/factories, object oriented best practices, blah blah...

![complexcode](https://imgur.com/SFbwKhil.png)

I saw this all at the large company I was working for, as I had to help maintain such a slow moving and bulky system. I have written code very much like the above - so highly abstracted and flexible it will take a whole meeting to explain. I just had no time for all that on Friday nights churning out some python scripts for some hobby that was already starting to take too long...

There was no time to write a unit test if you cant even be sure _that unit_ of code is what you need to write? And there was no time to spend a few weeks/months fully planning what code you will write so you could also plan unit tests _too_ - I was not going to end up a year's worth of work in with a lot of passing tests and well documented code but with a tenth of the desired functionality towards my goal. Not enough time in life or enough of me to go around for writing all that code that might never get to its end working goal.

Working first, fast if needed, pretty in implementation almost never...

But nothing was ever good enough for anyone (including myself) it seems. And now here we are years later. It's just years and years of 'ill add this last little feature X' that people seem to want/or to make this last demo work... and then done...repeated dozens and dozens of times...

`- Julian`

# What to change?

* Looking for something to work on? Start with the [open issues inventory](docs/issues_inventory.md). It lists every open [issue](https://github.com/JulianKemmerer/PipelineC/issues), most serious first, with how to reproduce it, where to look in the code, and any workaround.
* Fully expect to begin with [discussions](https://github.com/JulianKemmerer/PipelineC/discussions) about changes.
  * The codebase is large and loosely structured. The design documents in `docs/` are the primary architectural record.
  * You will almost certainly need some pointing in the right direction - happy to help.
* Move onto PRs with code once the implementation direction is clear.
  * Keep PRs small and compartmentalized for review.

# When making changes

Before making changes in the PipelineC repo please read this entire section.

See the [what the tool does](docs/README.md#what-the-tool-does) section for additional context.

## Module-to-Documentation Coupling

Most of the compiler's main modules have an LLM-generated design document in [`docs/`](docs/). Read the ones for the code you are changing: it explains how the module works and where a change belongs. If you modify a source file, you must find and update all related design documents.

## Documentation Integrity Rules

* **Audience Separation:** Keep user guides (`docs/pypeline_guide.md`, top-level `README.md`) focused strictly on user workflows, practical CLI usage, and functional explanations in plain terms. Implementation details, intermediate representation structures, and internal memory schemas belong exclusively in the respective `docs/<MODULE>_DESIGN.md`.
* **Edit In-Place (No Appendices):** Locate the exact section that already covers the subject and edit it directly. Never append duplicate summary paragraphs or trailing notes to the bottom of files or under historical sections.
* **Exhaustive Reference Updating:** When changing CLI flags, configuration variables, or generated output paths, grep across all files in `docs/` and `README.md` to update every occurrence (e.g., flag tables and artifact summaries in `docs/README.md`).
* **Sanitize Paths and Validate Links:** Never commit machine-local absolute paths into repository documentation or issue logs. Read every link you add: `doc_links_test` checks the links it can parse, but a malformed one (for example a space in the URL) is not parsed as a link at all and passes silently.
* **Describe Current Behavior:** Design docs and guides describe what the code does now, in the present tense. Version history belongs under a `## History` section.
* **Issue Drafts and the Inventory:** If an issue to be addressed later is found. Draft some text for a GitHub issue and update docs and tests. A GitHub issue draft has a title, and description of what happens with a minimal reproducible snippet, the observed effect, and any known workarounds. An entry in `docs/issues_inventory.md` and `known_issues_tests.py` is expected, can leave issue number TBD until GitHub issue made later.

## Implementation and Code Hygiene

* **Plan Bounds:** Implement agreed architectural designs faithfully. Do not introduce unrequested heuristic bounds, arbitrary floors, or behavioral limits without explicit confirmation and targeted test coverage.
* **Parameter Handling:** Do not accept unused parameters, configuration flags, or state arguments; wire all received parameters into execution paths or remove them.
* **Module Globals:** Document every module global variable with an explanatory single-line comment matching adjacent conventions.
* **Declared State:** Declare results stored on `ParserState` (or any other shared object) in its `__init__`, with a one-line comment. Do not compute such state lazily on first use or branch on `hasattr`: behavior then depends on call order.
* **No Sentinel Values in Tuned Numbers:** Do not signal a mode with a special value of a number that other code scales or nudges (for example `0.0` in a multiplier: no later multiplication can move it off zero). Use an explicit flag.
* **Check Existing One-Time Guards:** When adding a new reason to run a step that is guarded to happen once (for example a measurement fallback), check whether that guard will block the new reason.
* **Retire What You Replace:** When new logic replaces a rule, delete the code that can no longer run. Search `src/` and `docs/` for the old function and rule names, and fix every comment and doc that cites them, including in other modules.
* **Console Noise:** Deduplicate compiler informational messages and warnings (`NOTE: ...`) so they display once per build phase or session rather than repeating across every candidate pass or iteration.
* **Names And Caches Are Tricky:** Caches of synthesis results are there to reduce user synthesis runs. Try to use cached results when possible. Be careful to make sure code identifies and ignores stale pieces. Cached or remembered data must never make a build fail that would succeed without it. The synthesis sweep attributes a timing path to a function by finding the function's name inside instance labels and register names. Changing how instances, entities or functions are named, or restructuring which function is tagged, can change sweep decisions: compare the sweep's attribution and actions in sweep history before and after. If a fix invalidates cache, that is fine, do not need any complex workarounds to preserve existing old caches when things change for the better. A generated file's content must depend only on what names it (its entity name and inputs), never on planner state or the order files were written in; if two renderings can share one name, fix that rather than reproducing whichever was written first.

## Verification and Testing

Consult [`docs/pypeline_TESTS.md`](docs/pypeline_TESTS.md) for full descriptions of test categories, test suite layouts, and runner options. Include information on how changes will be tested in plans.

### Test Suite Structure and Reproducers

* **Standalone Reproducers:** Place regression tests and known-issue reproducers in `src/tests/pypeline_tests/inst/` rather than inlining them directly into test drivers. Register each new file inside the appropriate runner (e.g., `known_issues_tests.py`, `unit_tests.py`, `build_report_tests.py`) accompanied by an explanatory registration comment.
* **Metadata Accuracy:** Keep test header comments and registration docstrings in sync with actual build numbers, test scenarios, and expected runtime durations.
* **One Behavior per Test:** Name each test function after the behavior it checks, and split a test that checks several.
* **Measure Before Claiming:** Report only observed results. Never summarize results before the run that measures them finishes. Reccomended changes should be based on test results.
* **Compare Like with Like:** Gate changes against a baseline built from the same commit and cache state, so unrelated commits can neither hide nor fake a difference.
* **Test Scope Matches Impact:** Focused tests prove the targeted code works. A change to shared planner or sweep policy (behavior that applies to every design of a kind) also needs that policy's broader test categories.
* **Separate QoR Changes from Efficiency Changes:** If work to cut synthesis runs turns up a change to placement or trim decisions, describe and verify each change on its own, and state which results support which change.
* **Long Hardware Verification:** Run long builds (timing sweeps, hardware runs) in the background and wait for their completion notice instead of polling. Consider building from a frozen copy of the compiler and design, so later source edits can't change a run in progress.

## Pre-Commit and Formatting

We use Ruff for linting and formatting (lint rules are being enabled incrementally as the codebase is cleaned up).

Format only the lines you change. Do not reformat untouched lines, even ones next to your edit, so the diff shows only behavior changes.

# Future Goals

This section is painful because it is essentially enabling this whole multi-years long hackathon to continue - its both exciting and exhausting, especially with LLMs in the mix.

Review the [open issues inventory](docs/issues_inventory.md) for ranked, accessible entry tasks. Major architectural directions include:
* Improved support for [FSM style](https://github.com/JulianKemmerer/PipelineC/wiki/FSM-Style) code generation.
* Enhancements to auto-pipelining to track FPGA area/resources alongside timing.
* Integration with modern hardware compiler frameworks and intermediate representations such as [CIRCT](https://circt.llvm.org/).
