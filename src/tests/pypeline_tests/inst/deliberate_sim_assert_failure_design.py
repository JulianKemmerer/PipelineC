# pyright: reportInvalidTypeForm=none
"""Fixture for cocotb_verdict_test.py: a design whose sim_assert always
fires, so real --cocotb --ghdl runs exit nonzero deterministically and
independently of any particular compiler bug's lifecycle. (A previous
revision of cocotb_verdict_test.py borrowed a known-issue reproducer for
this instead -- nested_truncate_vhdl_mismatch_known_issue.py, whose failure
depended on a since-fixed VHDL-emission bug; see docs/pypeline_DESIGN.md's
Casting section. Coupling a "does the harness correctly report FAIL"
regression guard to an unrelated bug's continued existence was fragile by
construction -- this fixture has no such dependency.)
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, sim_assert, sim_finish, uint1_t


@MAIN
def deliberate_sim_assert_failure():
    finishing: Reg[uint1_t]
    if finishing:
        sim_finish()
    else:
        sim_assert(0, "deliberate failure for cocotb_verdict_test.py")
        finishing = 1
