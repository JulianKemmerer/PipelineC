"""Unit checks of how the sweep and the back end treat an async global FIFO:
a parsed two-clock FIFO design (PY_TO_LOGIC.PARSE_FILE, no synthesis) and
fake timing path reports.

- SWEEP.GET_MAIN_INSTS_FOR_PATH_REPORT gives a path inside the FIFO's
  clk_cross instance (labeled with its crossing, rx_FIFO) to the side MAIN on
  the path's clock, to both side MAINs without a path group, a path with one
  end in the instance and the other named by a top-level net to the FIFO too,
  and a path from the FIFO into a user MAIN to that MAIN. A side MAIN's own entity name,
  rx_FIFO_wr_..., is not inside the instance rx_FIFO.
- SWEEP.GLOBAL_INST_MAINS maps both side MAINs, never the crossing, and
  WHY_NOT_SLICEABLE names a side MAIN "global FIFO" and a stub
  "clock_crossing"; PRINT_TIMING_FAILURES names a side MAIN as its FIFO.
- VHDL.CLK_CROSS_USES_XPM: xpm_fifo_async on Vivado, the built-in FIFO for
  impl="builtin", for any other tool, and with no tool.
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
import OPEN_TOOLS
import PY_TO_LOGIC
import SWEEP
import SYN
import VHDL
import VIVADO

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

DESIGN = """
import sys
sys.path.insert(0, {repo_root!r})
from pypeline import *

eth_clk = make_clock(125.0, name="eth_rx")
rx: Fifo[uint8_t] = global_fifo(8)
tx: Fifo[uint8_t] = global_async_fifo(4, impl="builtin")

@MAIN(eth_clk)
def producer():
    n: Reg[uint8_t]
    rx.wr.stream.data = n
    rx.wr.stream.valid = 1
    if rx.wr.ready:
        n += 1
    tx.rd.ready = 1

@MAIN(100.0)
def consumer():
    total: Reg[uint8_t]
    rx.rd.ready = 1
    if rx.rd.stream.valid:
        total += rx.rd.stream.data
    tx.wr.stream.data = total
    tx.wr.stream.valid = 1
"""


def _path(start, end, resources=(), group=None):
    return types.SimpleNamespace(
        start_reg_name=start,
        end_reg_name=end,
        netlist_resources=list(resources),
        path_group=group,
    )


def test_path_attribution(state, params, entity):
    def mains_for(report):
        return SWEEP.GET_MAIN_INSTS_FOR_PATH_REPORT(report, state, params)

    inside_wr = _path(
        "rx_FIFO/pipelinec_fifo_fwft_inst/wr_ptr_reg_reg[1]/C",
        "rx_FIFO/pipelinec_fifo_fwft_inst/wr_ptr_reg_reg[3]/D",
        group="clk_125p0_eth_rx",
    )
    assert mains_for(inside_wr) == {"rx_FIFO_wr"}, mains_for(inside_wr)
    # nextpnr reports lower case and "." separators
    inside_rd = _path(
        "rx_fifo.pipelinec_fifo_fwft_inst.rd_ptr_reg_reg[0]",
        "rx_fifo.pipelinec_fifo_fwft_inst.data_out_pipe_reg[2]",
        group="clk_100p0",
    )
    assert mains_for(inside_rd) == {"rx_FIFO_rd"}, mains_for(inside_rd)
    no_group = _path(
        "rx_FIFO/pipelinec_fifo_fwft_inst/mem_reg[0]/C",
        "rx_FIFO/pipelinec_fifo_fwft_inst/mem_reg[1]/D",
    )
    assert mains_for(no_group) == {"rx_FIFO_wr", "rx_FIFO_rd"}, mains_for(no_group)
    # nextpnr can name one end by a top-level net: still the FIFO's path
    to_net = _path(
        "rx_fifo.pipelinec_fifo_fwft_inst.wr_ptr_gray_reg[2]",
        "global_to_module[101]",
        group="clk_125p0_eth_rx",
    )
    assert mains_for(to_net) == {"rx_FIFO_wr"}, mains_for(to_net)
    cons = entity["consumer"]
    fifo_to_consumer = _path(
        "rx_FIFO/pipelinec_fifo_fwft_inst/data_out_pipe_reg[3]/C",
        f"{cons}/total_reg[3]/D",
        [f"{cons}/n_2"],
        group="clk_100p0",
    )
    assert mains_for(fifo_to_consumer) == {"consumer"}, mains_for(fifo_to_consumer)
    side = entity["rx_FIFO_wr"]
    assert not SYN.PATH_ENDS_IN_INSTANCE(
        _path(f"{side}/a_reg/C", f"{side}/b_reg/D"), "rx_FIFO"
    )
    print("test_path_attribution PASS")


def test_mains_and_slicing(state):
    mains = SWEEP.GLOBAL_INST_MAINS(state)
    for side in ("rx_FIFO_wr", "rx_FIFO_rd", "tx_FIFO_wr", "tx_FIFO_rd"):
        assert mains[side].bare_name == side[:2], (side, mains)
    assert "rx_FIFO" not in mains and "tx_FIFO" not in mains, mains
    table = state.FuncLogicLookupTable
    assert SWEEP.WHY_NOT_SLICEABLE(table["rx_FIFO_wr"], state) == "global FIFO"
    assert SWEEP.WHY_NOT_SLICEABLE(table["rx_FIFO_WRITE_1"], state) == "clock_crossing"
    timing = types.SimpleNamespace(
        sweep_timing_failures=[("rx_FIFO_rd", 100.0, 61.78, "nothing_auto_pipelinable")]
    )
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert SWEEP.PRINT_TIMING_FAILURES(state, timing)
    expected = "ERROR: TIMING NOT MET: global FIFO rx [async_path_design.py:7] achieved"
    assert expected in out.getvalue(), out.getvalue()
    print("test_mains_and_slicing PASS")


def test_xpm_choice(state):
    saved = SYN.SYN_TOOL
    try:
        SYN.SYN_TOOL = VIVADO
        assert VHDL.CLK_CROSS_USES_XPM("rx_FIFO", state)
        assert not VHDL.CLK_CROSS_USES_XPM("tx_FIFO", state)  # impl="builtin"
        SYN.SYN_TOOL = OPEN_TOOLS
        assert not VHDL.CLK_CROSS_USES_XPM("rx_FIFO", state)
        SYN.SYN_TOOL = None
        assert not VHDL.CLK_CROSS_USES_XPM("rx_FIFO", state)
    finally:
        SYN.SYN_TOOL = saved
    print("test_xpm_choice PASS")


def main():
    with tempfile.TemporaryDirectory(prefix="async_fifo_path_unit_test_") as tmpdir:
        path = os.path.join(tmpdir, "async_path_design.py")
        with open(path, "w") as f:
            f.write(DESIGN.format(repo_root=os.path.abspath(REPO_ROOT)))
        state = PY_TO_LOGIC.PARSE_FILE(path)
    tpl = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(state)
    params = types.SimpleNamespace(TimingParamsLookupTable=tpl)
    entity = {
        m: VHDL.GET_ENTITY_NAME(m, state.LogicInstLookupTable[m], tpl, state)
        for m in state.main_mhz
    }
    test_path_attribution(state, params, entity)
    test_mains_and_slicing(state)
    test_xpm_choice(state)
    print("async_fifo_path_unit_test: all PASS")


if __name__ == "__main__":
    main()
