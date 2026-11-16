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

If you're unsure where to start, or have a larger change in mind, open a [discussion](https://github.com/JulianKemmerer/PipelineC/discussions). The codebase is large and loosely structured; happy to help you find your way around and work out an approach. Once the direction is clear, small, focused PRs are easiest to review.

# When making changes

Please read this short section before making changes. **LLMs must also read [AGENTS.md](AGENTS.md).**

* **Before you start**, check the [issues inventory](docs/issues_inventory.md) for the area you're changing, and the relevant parts of the [compiler complexity review](docs/code_reviews/complexity_review/REVIEW_COMPLEXITY.md) and [test-suite review](docs/code_reviews/tests_review/TEST_REVIEW.md). Try not to extend the problems they flag. The `docs/*_DESIGN.md` file for each module explains how it works.
* **Keep changes focused.** Reuse existing mechanisms, and clean up the code and comments your change replaces. Format only the lines you change with Ruff ([ruff.toml](ruff.toml)).
* **Keep docs in step with the code**, including the [README](README.md) feature table and [docs/README.md](docs/README.md). If something in the code confused you, add it to that module's review.
* **Test what you changed** ([test-suite guide](docs/pypeline_TESTS.md)), and add a regression test for a bug fix. In your PR, say what you ran and what you couldn't check.
* **Found a separate bug?** Add a small reproducer to the [issues inventory](docs/issues_inventory.md).

This list is short on purpose, so it leaves things out. For the details behind any point, ask an LLM to explain it from [AGENTS.md](AGENTS.md), which holds the full working rules. Or ask a person; we're happy to help: [PipelineC Discord](https://discord.gg/Aupm3DDrK2), [Discussions](https://github.com/JulianKemmerer/PipelineC/discussions).

# Future goals

This section is painful because it is essentially enabling this whole multi-years long hackathon to continue - its both exciting and exhausting, especially with LLMs in the mix.

Major architectural directions include:

* Improved support for [FSM style](https://github.com/JulianKemmerer/PipelineC/wiki/FSM-Style) code generation.
* Enhancements to auto-pipelining to track FPGA area/resources alongside timing.
* Integration with modern hardware compiler frameworks and intermediate representations such as [CIRCT](https://circt.llvm.org/).
