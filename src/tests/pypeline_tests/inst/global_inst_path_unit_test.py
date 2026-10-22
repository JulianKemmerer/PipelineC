"""Unit checks of how the sweep treats a global instance's MAIN: a parsed
design (PY_TO_LOGIC.PARSE_FILE, no synthesis) with a stateful instance and an
AUTO_PIPELINE instance, and fake timing path reports.

- SWEEP.GLOBAL_INST_MAIN_CAN_TAKE_LATENCY: false for the stateful instance's
  MAIN, true for the one whose hardware is an AUTO_PIPELINE tag.
- SWEEP.GET_MAIN_INSTS_FOR_PATH_REPORT gives a path inside an instance MAIN
  to it alone. A path with one end in the stateful instance goes to the user
  MAIN at the other end; one into the AUTO_PIPELINE instance goes to both
  MAINs, so its region gets the feedback. Paths without register names leave
  out only the stateful instance.
- SWEEP.WHY_NOT_SLICEABLE names an instance MAIN "global instance".
- SWEEP.PRINT_TIMING_FAILURES names an instance MAIN by its declaration.
"""

import contextlib
import io
import os
import sys
import tempfile
import types

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import AUTO_PIPELINE
import PY_TO_LOGIC
import SWEEP
import VHDL

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

DESIGN = """
import sys
sys.path.insert(0, {repo_root!r})
from pypeline import *

@hw_func
def counter(step: uint8_t) -> uint8_t:
    n: Reg[uint8_t]
    rv = n
    n += step
    return rv

@hw_func
def mul_add(a: uint16_t, b: uint16_t) -> uint32_t:
    return a * b + a

cnt: Inst[counter]
ap: Inst[AUTO_PIPELINE(mul_add)]

@MAIN(100.0)
def driver():
    n: Reg[uint16_t]
    cnt.step = 1
    ap.a = n
    ap.b = n
    n += 1

@MAIN(100.0)
def user():
    total: Reg[uint32_t]
    total += cnt.out + ap.out
"""


def _path(start, end, resources=()):
    return types.SimpleNamespace(
        start_reg_name=start, end_reg_name=end, netlist_resources=list(resources)
    )


def main():
    with tempfile.TemporaryDirectory(prefix="global_inst_path_unit_test_") as tmpdir:
        path = os.path.join(tmpdir, "inst_path_design.py")
        with open(path, "w") as f:
            f.write(DESIGN.format(repo_root=os.path.abspath(REPO_ROOT)))
        state = PY_TO_LOGIC.PARSE_FILE(path)
    assert not SWEEP.GLOBAL_INST_MAIN_CAN_TAKE_LATENCY("cnt_INST", state)
    assert SWEEP.GLOBAL_INST_MAIN_CAN_TAKE_LATENCY("ap_INST", state)
    print("GLOBAL_INST_MAIN_CAN_TAKE_LATENCY PASS")

    tpl = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(state)
    params = types.SimpleNamespace(TimingParamsLookupTable=tpl)
    entity = {
        m: VHDL.GET_ENTITY_NAME(m, state.LogicInstLookupTable[m], tpl, state)
        for m in state.main_mhz
    }
    cnt, ap, drv, usr = (
        entity["cnt_INST"],
        entity["ap_INST"],
        entity["driver"],
        entity["user"],
    )

    def mains_for(report):
        return SWEEP.GET_MAIN_INSTS_FOR_PATH_REPORT(report, state, params)

    inside = _path(f"{cnt}/inst_hardware/n_reg[0]/C", f"{cnt}/inst_hardware/n_reg[7]/D")
    assert mains_for(inside) == {"cnt_INST"}, mains_for(inside)
    cnt_to_user = _path(f"{cnt}/inst_hardware/n_reg[0]/C", f"{usr}/total_reg[3]/D")
    assert mains_for(cnt_to_user) == {"user"}, mains_for(cnt_to_user)
    driver_to_ap = _path(f"{drv}/n_reg[0]/C", f"{ap}/inst_hardware/prod_reg[9]/D")
    assert mains_for(driver_to_ap) == {"driver", "ap_INST"}, mains_for(driver_to_ap)
    no_names = _path(None, None)
    assert mains_for(no_names) == {"driver", "user", "ap_INST"}, mains_for(no_names)
    print("path attribution PASS")

    table = state.FuncLogicLookupTable
    assert SWEEP.WHY_NOT_SLICEABLE(table["cnt_INST"], state) == "global instance"
    print("WHY_NOT_SLICEABLE PASS")

    timing = types.SimpleNamespace(
        sweep_timing_failures=[("cnt_INST", 100.0, 61.78, "nothing_auto_pipelinable")]
    )
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert SWEEP.PRINT_TIMING_FAILURES(state, timing)
    expected = (
        "ERROR: TIMING NOT MET: global instance cnt [inst_path_design.py:17] "
        "achieved 61.78 MHz vs 100.00 MHz goal (nothing_auto_pipelinable)"
    )
    assert expected in out.getvalue(), out.getvalue()
    print("TIMING NOT MET naming PASS")
    print("global_inst_path_unit_test: all PASS")


if __name__ == "__main__":
    main()
