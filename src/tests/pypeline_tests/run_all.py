#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run all pypeline tests in parallel. See docs/pypeline_TESTS.md for what
belongs in each category.

synth_tests.py and build_report_tests.py each feed three categories, one per
synthesis tool (synth_vivado / synth_pyrtl / synth_device_models and
build_report_vivado / build_report_pyrtl / build_report_device_models), so a
category here selects that module's tests whose Test.category matches.

known_issues is deliberately NOT part of the default category set: every
entry there is expect_fail=True (documents a known, unfixed compiler bug),
so it must be requested explicitly with --category known_issues.

Replaces the old run_all.sh. Run standalone:
python3 run_all.py [-j N] [--category CATEGORY ...]
"""

import sys

import build_report_tests
import elab_introspect_tests
import elab_tests
import known_issues_tests
import native_sim_tests
import native_vs_vhdl_sim_tests
import synth_tests
import unit_tests
from common import (
    SYN_TOOLS,
    filter_tests,
    make_arg_parser,
    make_tmp_root,
    print_summary,
    run_tests,
)

DEFAULT_CATEGORY_MODULES = dict(
    {
        "native_sim": native_sim_tests,
        "native_vs_vhdl_sim": native_vs_vhdl_sim_tests,
        "elab": elab_tests,
        "elab_introspect": elab_introspect_tests,
        "unit": unit_tests,
    },
    **{f"synth_{tool}": synth_tests for tool in SYN_TOOLS},
    **{f"build_report_{tool}": build_report_tests for tool in SYN_TOOLS},
)

# known_issues is excluded from the default set on purpose (see module
# docstring) -- only reachable via an explicit --category known_issues.
ALL_CATEGORY_MODULES = dict(DEFAULT_CATEGORY_MODULES, known_issues=known_issues_tests)

# Heaviest (Vivado, then sky130 synth/STA, or GHDL+cocotb) categories first: tests are
# submitted to run_tests()'s ThreadPoolExecutor up front, in list order, and a
# thread pool dispatches queued work FIFO -- so whatever sits at the front of
# this combined list starts at t=0 and runs concurrently with everything
# after it, while whatever sits at the back only starts once an earlier test
# frees a worker. Alphabetical order (the previous default, via sorted())
# left the two heaviest categories (then synth and build_report) running
# second-to-last and first respectively -- accidental, not deliberate. This
# order is the deliberate one; explicit --category flags are unaffected.
# Vivado runs are the slowest per test, so they start first.
_DEFAULT_CATEGORY_ORDER = [
    "synth_vivado",
    "build_report_vivado",
    "synth_device_models",
    "build_report_device_models",
    "synth_pyrtl",
    "build_report_pyrtl",
    "native_vs_vhdl_sim",
    "elab_introspect",
    "elab",
    "native_sim",
    "unit",
]
assert set(_DEFAULT_CATEGORY_ORDER) == set(DEFAULT_CATEGORY_MODULES), (
    "_DEFAULT_CATEGORY_ORDER is out of sync with DEFAULT_CATEGORY_MODULES -- "
    "a category was added/removed without updating the other"
)


def main() -> int:
    parser = make_arg_parser(
        "Run all PipelineC pypeline tests (default categories: "
        + ", ".join(sorted(DEFAULT_CATEGORY_MODULES))
        + "; known_issues is opt-in via --category)."
    )
    parser.add_argument(
        "--category",
        choices=sorted(ALL_CATEGORY_MODULES),
        action="append",
        help="Limit to one or more categories (default: all EXCEPT known_issues, "
        "which must be requested explicitly). May be passed multiple times.",
    )
    args = parser.parse_args()

    categories = args.category or _DEFAULT_CATEGORY_ORDER
    tests = []
    module_tests = {}
    for category in categories:
        module = ALL_CATEGORY_MODULES[category]
        if module not in module_tests:
            module_tests[module] = module.get_tests()
            # A Test whose category isn't mapped to its own module would
            # silently never run from here -- fail loudly instead.
            own = {c for c, m in ALL_CATEGORY_MODULES.items() if m is module}
            stray = sorted({t.category for t in module_tests[module]} - own)
            assert not stray, (
                f"{module.__name__} registers tests under unknown "
                f"categor{'y' if len(stray) == 1 else 'ies'} {stray}; "
                f"expected one of {sorted(own)}"
            )
        tests += [t for t in module_tests[module] if t.category == category]

    tests = filter_tests(tests, args)
    tmp_root = make_tmp_root()
    results = run_tests(tests, args.jobs, tmp_root)
    return print_summary(results)


if __name__ == "__main__":
    sys.exit(main())
