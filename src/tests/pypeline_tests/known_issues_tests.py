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

from common import (
    EXAMPLES_PYPELINE_DIR,
    INST_DIR,
    PYPELINEC,
    SYN_TOOL_ARGS,
    Test,
    main,
)

# Backends the per-SYN_TOOL sweep matrix cannot run on this machine. Each is a
# real, reproducible failure of that tool -- none of them is a PipelineC bug,
# which is why the fix is not in this repo:
#
#   gowin     gw_sh exits "License verification failed  License hostid not
#             match." The IDE is installed; its license is not valid for this
#             host.
#   diamond   "Error: License checkout failed. FlexNet Licensing error:-10,32"
#             from diamondc. Same situation.
#   cc_tools  yosys synthesis succeeds and writes the netlist, then CologneChip
#             p_r crashes inside itself: "Exception Handler called. ExitCode:
#             112, Exception Class: ERangeError". The design presents 357
#             inputs / 480 outputs to p_r, far past a CCGM1A1's real I/O count,
#             and the tool range-errors instead of reporting that.
#
# These stay registered so the matrix documents every backend, and so a fixed
# license or a working part/tool combination shows up as an XPASS telling
# someone to move the entry back into synth_<tool>.
SWEEP_FLOAT32_BLOCKED = {
    "gowin": "gw_sh license hostid mismatch",
    "diamond": "diamondc FlexNet license checkout failed (-10,32)",
    "cc_tools": "CologneChip p_r crashes (ERangeError, exit 112)",
}


def get_tests() -> list:
    tests = []
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
    # (pdw_tb was here while Path B's delay line was misaligned. That is
    # fixed -- make_delay_line is now self-timed off the FSM's gate_advance --
    # so it lives in native_sim_tests.py as a normal passing test.)
    # (global_wire_nested_split_known_issue was here while the multi-writer
    # overlap check misread a soft_cmp_prefix helper as a second whole-wire
    # writer of Global Output 'combined'. That no longer reproduces, so
    # global_wire_nested_split_test.py is back in synth_tests.py as a normal
    # --comb entry.)
    # Per-SYN_TOOL sweep matrix entries whose backend cannot run here. Same
    # design and goal as the synth_<tool> entries in synth_tests.py; only the
    # category and expect_fail differ. See SWEEP_FLOAT32_BLOCKED above.
    from synth_tests import SWEEP_FLOAT32_MHZ

    for tool, why in SWEEP_FLOAT32_BLOCKED.items():
        tests.append(
            Test(
                name=f"sweep_float32_{tool}_known_issue",
                category="known_issues",
                cmd=[PYPELINEC, INST_DIR / "sweep_float32_test.py"]
                + SYN_TOOL_ARGS[tool],
                needs_out_dir=True,
                expect_fail=True,
                env={"SWEEP_FLOAT32_MHZ": SWEEP_FLOAT32_MHZ[tool]},
            )
        )
    return tests


if __name__ == "__main__":
    sys.exit(
        main(get_tests, "PipelineC pypeline known-issue (expected-to-fail) reproducers.")
    )
