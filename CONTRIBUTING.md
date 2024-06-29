How to contribute to PipelineC
=====================================

Thank you for considering contributing to the PipelineC project!

```
“We do these things not because they are easy 
but because we thought they would be easy”
                           - programming meme
```

# Pre-contributors (How did it get like _this_?)

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


# General Information

* Fully expect to begin with [discussions](https://github.com/JulianKemmerer/PipelineC/discussions) about changes.
  * The code base is large and only loosely structured with essentially no documentation.
  * You will almost certainly need some pointing in the right direction - happy to help.
* Move onto PRs w/ code once the idea is making sense
  * Try to keep PRs small/compartmentalized for easy review

# Architecture

See the [How does the compiler work?](https://github.com/JulianKemmerer/PipelineC/wiki/How-does-the-compiler-work%3F) page.

# Pre-Commit

We use ruff for formatting and linting (currently most lint rules are disabled, we are enabling them incrementally as the codebase is cleaned up). To ensure this is done, we use a pre-commit hook.

You can install Poetry (for dev dependency management) via https://python-poetry.org/docs/#installation. Once you have poetry installed, you can run 'poetry install' to get the dev dependencies installed. From there, you must run 'poetry run pre-commit install' once before making a commit. This will ensure that the pre-commit hook gets run when you make any commit. If the lint fails, follow the guidance given by Ruff (you can look up the name of the error, such as E721, online, if necessary to understand) to fix the lint error.

Cheers!

# Future Goals

This section is painful because it is essentially enabling this whole multi-years long hackathon to continue - its both exciting and exhausting.

First, see existing [issues](https://github.com/JulianKemmerer/PipelineC/issues). Some are pretty easy for new folks to do.

But generally, in kinda easier first order:

* Improved support for [FSM style](https://github.com/JulianKemmerer/PipelineC/wiki/FSM-Style) code
  * is the most hacky of recent hacking - another layer of dumb code gen
* Template types+functions for [~C++ like syntax](https://github.com/JulianKemmerer/PipelineC/discussions/32)
  * Open to other syntaxs+languages Rust, Python, Zig, Go...
* Improvements to autopipelining, maybe with modes to also track area/resources (not just timing as is)
* 'Just compile all the user code with a C compiler for fast simulation' built in
* Integration with modern hardware compiler framework/intermediates+tools like [CIRCT](https://circt.llvm.org/)
  * Would enable/eliminate alot of above features/issues.

