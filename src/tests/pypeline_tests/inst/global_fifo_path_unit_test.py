"""Unit checks of how the sweep treats a global FIFO's MAIN: a parsed FIFO
design (PY_TO_LOGIC.PARSE_FILE, no synthesis) and fake timing path reports.

- SWEEP.GET_MAIN_INSTS_FOR_PATH_REPORT gives a path inside the FIFO MAIN to
  it alone, in Vivado's hierarchical names and in sky130 STA's flattened
  ones, and a path with one end in it to the user MAIN at the other end.
  Paths with no MAIN attribution (flattened cell names, no register names)
  go to the user MAINs only.
- SWEEP.WHY_NOT_SLICEABLE names the FIFO MAIN and the handshake user.
- SWEEP.PRINT_TIMING_FAILURES names a FIFO MAIN as its FIFO.
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
import DEVICE_MODELS
import PY_TO_LOGIC
import SWEEP
import SYN
import VHDL

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

DESIGN = """
import sys
sys.path.insert(0, {repo_root!r})
from pypeline import *

rx: Fifo[uint8_t] = global_fifo(4)

@MAIN(100.0)
def producer():
    n: Reg[uint8_t]
    rx.wr.stream.data = n
    rx.wr.stream.valid = 1
    if rx.wr.ready:
        n += 1

@MAIN(100.0)
def consumer():
    total: Reg[uint8_t]
    rx.rd.ready = 1
    if rx.rd.stream.valid:
        total += rx.rd.stream.data
"""


def _path(start, end, resources=()):
    return types.SimpleNamespace(
        start_reg_name=start, end_reg_name=end, netlist_resources=list(resources)
    )


def main():
    with tempfile.TemporaryDirectory(prefix="global_fifo_path_unit_test_") as tmpdir:
        path = os.path.join(tmpdir, "fifo_path_design.py")
        with open(path, "w") as f:
            f.write(DESIGN.format(repo_root=os.path.abspath(REPO_ROOT)))
        state = PY_TO_LOGIC.PARSE_FILE(path)
    tpl = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(state)
    params = types.SimpleNamespace(TimingParamsLookupTable=tpl)
    entity = {
        m: VHDL.GET_ENTITY_NAME(m, state.LogicInstLookupTable[m], tpl, state)
        for m in state.main_mhz
    }
    fifo, prod, cons = entity["rx_FIFO"], entity["producer"], entity["consumer"]

    def mains_for(report):
        return SWEEP.GET_MAIN_INSTS_FOR_PATH_REPORT(report, state, params)

    saved_tool = SYN.SYN_TOOL
    try:
        # Vivado-style hierarchical names
        inside = _path(
            f"{fifo}/fifo_hardware/fifo_fwft_inst/mem_reg[1][3]/C",
            f"{fifo}/fifo_hardware/fifo_fwft_inst/data_out_pipe_reg[3]/D",
            [f"{fifo}/fifo_hardware/fifo_fwft_inst/n_0", f"{cons}/total_reg[0]/Q"],
        )
        assert mains_for(inside) == {"rx_FIFO"}, mains_for(inside)
        fifo_to_consumer = _path(
            f"{fifo}/fifo_hardware/fifo_fwft_inst/valid_out_pipe_reg/C",
            f"{cons}/total_reg[3]/D",
            [f"{fifo}/fifo_hardware/fifo_fwft_inst/n_1", f"{cons}/n_2"],
        )
        assert mains_for(fifo_to_consumer) == {"consumer"}, mains_for(fifo_to_consumer)
        producer_to_fifo = _path(
            f"{prod}/n_reg[0]/C",
            f"{fifo}/fifo_hardware/fifo_fwft_inst/mem_reg[0][0]/D",
            [f"{prod}/n_3", f"{fifo}/fifo_hardware/n_4"],
        )
        assert mains_for(producer_to_fifo) == {"producer"}, mains_for(producer_to_fifo)
        no_names = _path(None, None)
        assert mains_for(no_names) == {"producer", "consumer"}, mains_for(no_names)

        # sky130 STA's flattened names
        SYN.SYN_TOOL = DEVICE_MODELS
        flat = "$flatten\\" + fifo.lower() + ".\\fifo_hardware.\\fifo_fwft_inst."
        inside_flat = _path(
            flat + "$auto$ff.cc:266:slice$1091", flat + "$auto$ff.cc:266:slice$1026"
        )
        assert mains_for(inside_flat) == {"rx_FIFO"}, mains_for(inside_flat)
        unattributed = _path("$auto$ff.cc:266:slice$7", "$auto$ff.cc:266:slice$8")
        assert mains_for(unattributed) == {"producer", "consumer"}, mains_for(
            unattributed
        )
    finally:
        SYN.SYN_TOOL = saved_tool
    print("path attribution PASS")

    table = state.FuncLogicLookupTable
    assert SWEEP.WHY_NOT_SLICEABLE(table["rx_FIFO"], state) == "global FIFO"
    assert SWEEP.WHY_NOT_SLICEABLE(table["producer"], state) == "global FIFO handshake"
    print("WHY_NOT_SLICEABLE PASS")

    timing = types.SimpleNamespace(
        sweep_timing_failures=[
            ("rx_FIFO", 100.0, 61.78, "nothing_auto_pipelinable"),
            ("producer", 100.0, 61.78, "nothing_auto_pipelinable"),
        ]
    )
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert SWEEP.PRINT_TIMING_FAILURES(state, timing)
    text = out.getvalue()
    expected = (
        "ERROR: TIMING NOT MET: global FIFO rx [fifo_path_design.py:6] achieved "
        "61.78 MHz vs 100.00 MHz goal (nothing_auto_pipelinable)"
    )
    assert expected in text, text
    assert "ERROR: TIMING NOT MET: producer achieved" in text, text
    print("TIMING NOT MET naming PASS")
    print("global_fifo_path_unit_test: all PASS")


if __name__ == "__main__":
    main()
