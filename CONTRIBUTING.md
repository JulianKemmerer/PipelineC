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

Looking for something to work on? There are two useful starting points:

* The [open issues inventory](docs/issues_inventory.md) ranks known bugs and limitations from [GitHub issues](https://github.com/JulianKemmerer/PipelineC/issues) by priority, most serious first, and adds reproduction steps, code pointers, and workarounds where available. Use it to understand what needs attention most and where to start.
* The [compiler complexity review](docs/code_reviews/complexity_review/REVIEW_COMPLEXITY.md) and [test-suite review and recommendations](docs/code_reviews/tests_review/TEST_REVIEW.md) identify broader opportunities to improve architecture, reduce code complexity, and organize tests. These are useful sources of improvement ideas that may span several modules rather than fit a single bug report.

If you're unsure where to start, or have a larger change in mind, open a [discussion](https://github.com/JulianKemmerer/PipelineC/discussions). The codebase is large and loosely structured; we're happy to help you find your way around and work out an approach. Once the direction is clear, small, focused PRs are easiest to review.

# When making changes

Please read this section before making changes; it applies to both human contributors and LLM agents. **LLM agents must also read [AGENTS.md](AGENTS.md)** for detailed working instructions. Human contributors aren't required to read that file.

## Before you start

Check the [priority-ranked issues inventory](docs/issues_inventory.md) and related issue threads for the area you'll be working on. Knowing about existing bugs and workarounds helps avoid surprises and distinguish an existing problem from something your change introduced.

Also read the relevant parts of the [compiler complexity review](docs/code_reviews/complexity_review/REVIEW_COMPLEXITY.md) and, when changing tests, the [test-suite review and recommendations](docs/code_reviews/tests_review/TEST_REVIEW.md). They point out places where code has become too complex, responsibilities overlap, or tests could be better organized. Try to avoid extending those problems or copying the practices the reviews flag. A small contribution doesn't need to solve the whole architectural problem; a focused improvement is welcome. Review recommendations describe possible future work, so check them against the current code.

For context, see [what the tool does](docs/README.md#what-the-tool-does) and the design documents in [`docs/`](docs/). Most main compiler modules have a corresponding `*_DESIGN.md`; reading the relevant sections will help you understand how the code fits together.

## Implementation and Code Hygiene

Keep changes focused on the problem you're solving, and reuse existing mechanisms where they fit. When replacing code, tidy up the old paths and related comments so the next contributor can follow what's happening. Take particular care with generated names and synthesis caches: they can affect later compiler decisions as well as build time.

We use Ruff for linting and formatting (see [ruff.toml](ruff.toml) and [.pre-commit-config.yaml](.pre-commit-config.yaml)). Please format only the lines you change so unrelated formatting doesn't obscure the contribution.

## Keep documentation useful

Please keep the related design docs and usage instructions in step with your code. If your changes or verification show that a code review finding has changed, update the affected review sections and recommendations alongside the relevant `*_DESIGN.md` sections. User guides explain workflows and behavior; module design docs explain the implementation. Update the section that already covers the topic, describe current behavior, and check any other references affected by renamed options, functions, or output paths. Use portable paths and check the links you add.

## Verification and Testing

Think about how you'll check the change as you plan it. The [test-suite guide](docs/pypeline_TESTS.md) explains the existing tests, how to run a selection, and where to add coverage. Start with tests relevant to your change, and include a regression case for a bug fix. Changes to shared compiler behavior need broader coverage; a small contribution usually doesn't need the full suite of hardware-tool runs.

In your PR, say what you ran, what happened, and anything you couldn't check, such as a test requiring a tool you don't have installed. This helps reviewers understand what the results establish and where more checking is needed.

If you uncover a separate bug, share a small reproducer and any workaround, and add it to the [issues inventory](docs/issues_inventory.md) if it isn't already tracked. That gives the next contributor a heads-up too.

# Future Goals

This section is painful because it is essentially enabling this whole multi-years long hackathon to continue - its both exciting and exhausting, especially with LLMs in the mix.

Review the [open issues inventory](docs/issues_inventory.md) for ranked, accessible entry tasks. Major architectural directions include:
* Improved support for [FSM style](https://github.com/JulianKemmerer/PipelineC/wiki/FSM-Style) code generation.
* Enhancements to auto-pipelining to track FPGA area/resources alongside timing.
* Integration with modern hardware compiler frameworks and intermediate representations such as [CIRCT](https://circt.llvm.org/).
