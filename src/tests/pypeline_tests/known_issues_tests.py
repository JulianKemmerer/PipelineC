#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reproducers for known, unfixed compiler bugs -- every Test here has
expect_fail=True (its underlying command is expected to exit nonzero), so a
passing run means the bug is still present (reported as XFAIL) and a CLEAN
run means it got fixed without anyone updating this file (reported as XPASS,
which run_all.py treats as a FAILURE -- promote that test out of
known_issues into whichever category now fits it).

One entry (sim_finish_debug_print_race_test) is registered WITHOUT
expect_fail: see its own module docstring for why plain exit-code inversion
can't express its particular known issue, and how its PASS/FAIL should be
read instead.

Deliberately EXCLUDED from run_all.py's default category set (see
run_all.py's module docstring) -- run explicitly:
    python3 known_issues_tests.py [-j N]
    python3 run_all.py --category known_issues

Do not fix these bugs as part of touching this file. If you fix one
elsewhere, this file's XPASS (or, for the exit-code entry, its own FAIL) will
tell you to move its test out.
"""

import sys

from common import EXAMPLES_PYPELINE_DIR, INST_DIR, PYPELINEC, Test, main


def get_tests() -> list:
    tests = []
    # int16_t squaring-then-truncating a value that overflows int16_t range
    # computes a DIFFERENT result in real GHDL hardware (7233) than in native
    # sim (-25535, which matches a plain-Python model). See the reproducer's
    # own docstring for how this was found and why it went unnoticed.
    tests.append(
        Test(
            name="nested_truncate_vhdl_mismatch_known_issue",
            category="known_issues",
            cmd=[
                PYPELINEC,
                INST_DIR / "nested_truncate_vhdl_mismatch_known_issue.py",
                "--sim",
                "--comb",
                "--cocotb",
                "--ghdl",
                "--run",
                "all",
            ],
            needs_out_dir=True,
            expect_fail=True,
            requires=["ghdl"],
        )
    )
    # A sim_print(..., debug=True) call the SAME cycle as sim_finish() races
    # GHDL's write-flush against std.env.finish and the print is silently
    # dropped from the VHDL/cocotb log entirely (present in native sim,
    # absent in VHDL). This wrapper runs both sims itself and asserts on
    # that (NOT expect_fail -- pypelinec's exit code is 0 either way; see
    # the wrapper's own docstring for why text/exit-code alone can't express
    # this).
    tests.append(
        Test(
            name="sim_finish_debug_print_race_test",
            category="known_issues",
            cmd=[INST_DIR / "sim_finish_debug_print_race_test.py"],
            needs_out_dir=True,
            requires=["ghdl"],
        )
    )
    # SYN._IS_PYPELINE_OPERATOR_LIBRARY_CODE never fires for any real
    # operator-library callable (it inspects the @hw_func wrapper's source
    # file, always pypeline.py, instead of the wrapped function's) -- build
    # time only, delay numbers are unaffected either way.
    tests.append(
        Test(
            name="operator_library_predicate_never_fires_known_issue",
            category="known_issues",
            cmd=[INST_DIR / "operator_library_predicate_never_fires_known_issue.py"],
            expect_fail=True,
        )
    )
    # pdw_tb.py's PATH_B_SKEW = 0 is the CORRECT Path B alignment and is
    # expected to fail until pulse_detect.py's delay line is fixed to match
    # (see that function's docstring and README.md section 5's "Known gap").
    # Once that hardware fix lands, this becomes pdw_tb.py's acceptance test
    # and should move to native_sim_tests.py.
    tests.append(
        Test(
            name="pdw_tb",
            category="known_issues",
            cmd=[
                PYPELINEC,
                EXAMPLES_PYPELINE_DIR / "dsp" / "pdw" / "pdw_tb.py",
                "--sim",
                "--comb",
                "--run",
                "6200",
            ],
            expect_fail=True,
        )
    )
    # Structurally richest multi-writer global wire design (3 writers splitting
    # nested struct leaves + a mixed-depth whole-subtree claim + readback), moved
    # here from synth_tests.py: PY_TO_LOGIC.PARSE_FILE raises ElaborationError
    # complaining that Global Output 'combined' has two whole-wire writers
    # ('combiner' and a soft_cmp_prefix helper), even though the writers'
    # actually-driven fields are disjoint -- the overlap check is over-eager
    # about "whole wire" vs. the fields each writer really touches.
    tests.append(
        Test(
            name="global_wire_nested_split_known_issue",
            category="known_issues",
            cmd=[PYPELINEC, INST_DIR / "global_wire_nested_split_test.py", "--comb"],
            needs_out_dir=True,
            expect_fail=True,
        )
    )
    return tests


if __name__ == "__main__":
    sys.exit(
        main(get_tests, "PipelineC pypeline known-issue (expected-to-fail) reproducers.")
    )
