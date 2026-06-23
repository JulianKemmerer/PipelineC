#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run all pypeline tests (sim + elab + synth) in parallel.

Replaces the old run_all.sh. Run standalone: python3 run_all.py [-j N] [--category sim elab synth]
"""

import sys

import elab_tests
import sim_tests
import synth_tests
from common import (
    filter_tests,
    make_arg_parser,
    make_tmp_root,
    print_summary,
    run_tests,
)

CATEGORY_MODULES = {
    "sim": sim_tests,
    "elab": elab_tests,
    "synth": synth_tests,
}


def main() -> int:
    parser = make_arg_parser("Run all PipelineC pypeline tests (sim + elab + synth).")
    parser.add_argument(
        "--category",
        choices=sorted(CATEGORY_MODULES),
        action="append",
        help="Limit to one or more categories (default: all). May be passed multiple times.",
    )
    args = parser.parse_args()

    categories = args.category or sorted(CATEGORY_MODULES)
    tests = []
    for category in categories:
        tests += CATEGORY_MODULES[category].get_tests()

    tests = filter_tests(tests, args)
    tmp_root = make_tmp_root()
    results = run_tests(tests, args.jobs, tmp_root)
    return print_summary(results)


if __name__ == "__main__":
    sys.exit(main())
