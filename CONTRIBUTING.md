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

Most of the compiler's main modules have an LLM-generated design document in [`docs/`](docs/). Read the one for the code you are changing: it explains how the module works and where a change belongs. If you modify a source file, you must find and update all related design documents.

## Documentation Integrity Rules

* **Audience Separation:** Keep user guides (`docs/pypeline_guide.md`, top-level `README.md`) focused strictly on user workflows, practical CLI usage, and functional explanations in plain terms. Implementation details, intermediate representation structures, and internal memory schemas belong exclusively in the respective `docs/<MODULE>_DESIGN.md`.
* **Edit In-Place (No Appendices):** Locate the exact section that already covers the subject and edit it directly. Never append duplicate summary paragraphs or trailing notes to the bottom of files or under historical sections.
* **Exhaustive Reference Updating:** When changing CLI flags, configuration variables, or generated output paths, grep across all files in `docs/` and `README.md` to update every occurrence (e.g., flag tables and artifact summaries in `docs/README.md`).
* **Sanitize Paths and Validate Links:** Never commit machine-local absolute paths into repository documentation or issue logs. Inspect all markdown anchors manually; do not assume automated checks catch formatting bugs.
* **Issues Inventory Standards:** If planning to create a GitHub issue `docs/issues_inventory.md` must adhere to standard issue formatting: Title, What Happens (with a minimal reproducible code snippet), Why (root cause), Reproduce command, Fix Directions, and Workarounds.

## Implementation and Code Hygiene

* **Plan Bounds:** Implement agreed architectural designs faithfully. Do not introduce unrequested heuristic bounds, arbitrary floors, or behavioral limits without explicit confirmation and targeted test coverage.
* **Parameter Handling:** Do not accept unused parameters, configuration flags, or state arguments; wire all received parameters into execution paths or remove them.
* **Module Globals:** Document every module global variable with an explanatory single-line comment matching adjacent conventions.
* **Console Noise:** Deduplicate compiler informational messages and warnings (`NOTE: ...`) so they display once per build phase or session rather than repeating across every candidate pass or iteration.

## Verification and Testing

Consult [`docs/pypeline_TESTS.md`](docs/pypeline_TESTS.md) for full descriptions of test categories, test suite layouts, and runner options.

### Test Suite Structure and Reproducers

* **Standalone Reproducers:** Place regression tests and known-issue reproducers in `src/tests/pypeline_tests/inst/` rather than inlining them directly into test drivers. Register each new file inside the appropriate runner (e.g., `known_issues_tests.py`, `unit_tests.py`, `build_report_tests.py`) accompanied by an explanatory registration comment.
* **Metadata Accuracy:** Keep test header comments and registration docstrings in sync with actual build numbers, test scenarios, and expected runtime durations.
* **Long Hardware Verification:** When validating long runs (e.g., iterative timing sweeps), avoid polling waiting to finish, instead let the test run in the background without constant polling.

## Pre-Commit and Formatting

We use Ruff for linting and formatting (lint rules are being enabled incrementally as the codebase is cleaned up).

# Future Goals

This section is painful because it is essentially enabling this whole multi-years long hackathon to continue - its both exciting and exhausting, especially with LLMs in the mix.

Review the [open issues inventory](docs/issues_inventory.md) for ranked, accessible entry tasks. Major architectural directions include:
* Improved support for [FSM style](https://github.com/JulianKemmerer/PipelineC/wiki/FSM-Style) code generation.
* Enhancements to auto-pipelining to track FPGA area/resources alongside timing.
* Integration with modern hardware compiler frameworks and intermediate representations such as [CIRCT](https://circt.llvm.org/).
