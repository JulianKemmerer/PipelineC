# pyright: reportInvalidTypeForm=none
"""Structural regression for top-level OpenDrain[T] electrical semantics."""

import os
import sys
import tempfile
import textwrap

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import AUTO_PIPELINE
import PY_TO_LOGIC
import SYN
import VHDL


def test_open_drain_final_top_contract():
    here = os.path.dirname(os.path.abspath(__file__))
    design = os.path.join(here, "open_drain_design.py")
    out_dir = tempfile.mkdtemp(prefix="open_drain_test_")
    SYN.SYN_OUTPUT_DIRECTORY = out_dir

    ps = PY_TO_LOGIC.PARSE_FILE(design)
    assert ps.open_drain_wires == {"PS2Clk"}, ps.open_drain_wires

    # Normally initialized by the pypelinec CLI before final-top generation.
    SYN.TOP_LEVEL_MODULE = "top"
    mtp = AUTO_PIPELINE.MultiMainTimingParams()
    for main_name in ps.main_mhz:
        logic = ps.LogicInstLookupTable[main_name]
        mtp.TimingParamsLookupTable[main_name] = AUTO_PIPELINE.TimingParams(main_name, logic)

    VHDL.WRITE_GLOBAL_WIRES_VHDL_PACKAGE(ps)
    VHDL.WRITE_MULTIMAIN_TOP(ps, mtp, is_final_top=True)
    top_path = os.path.join(out_dir, "top", "top.vhd")
    with open(top_path) as f:
        text = f.read()
    pkg_path = os.path.join(out_dir, "global_wires_pkg.pkg.vhd")
    with open(pkg_path) as f:
        pkg_text = f.read()

    # An OpenDrain writer has a true duplex interface: drive intent leaves the
    # function while resolved-pad readback independently enters it.
    assert "PS2Clk : unsigned(0 downto 0);" in pkg_text
    assert "PS2Clk_PYPELINE_READBACK : unsigned(0 downto 0);" in pkg_text
    assert "PS2Clk : inout unsigned(0 downto 0)" in text
    assert (
        "PS2Clk <= to_unsigned(0, 1) when "
        "module_to_global.open_drain_main.PS2Clk = to_unsigned(0, 1) "
        "else (others => 'Z');"
    ) in text
    assert (
        "global_to_module.open_drain_main.PS2Clk_PYPELINE_READBACK <= PS2Clk;"
        in text
    )
    print("test_open_drain_final_top_contract PASS")


def _parse_source(src: str):
    tmp_dir = tempfile.mkdtemp(prefix="open_drain_parse_test_")
    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="open_drain_parse_syn_")
    path = os.path.join(tmp_dir, "design.py")
    with open(path, "w") as f:
        f.write(textwrap.dedent(src))
    return PY_TO_LOGIC.PARSE_FILE(path)


def _expect_elaboration_error(src: str, label: str):
    try:
        _parse_source(src)
        assert False, f"expected ElaborationError for {label}"
    except PY_TO_LOGIC.ElaborationError:
        print(f"test_{label} PASS")


def test_open_drain_rejections():
    _expect_elaboration_error(
        """
        from pypeline import *
        pin: OpenDrain[uint8_t]
        @MAIN
        def main():
            pin = 0
        """,
        "open_drain_non_uint1",
    )
    _expect_elaboration_error(
        """
        from pypeline import *
        pin: OpenDrain[uint1_t]
        @MAIN
        def main():
            x = pin
        """,
        "open_drain_no_writer",
    )
    _expect_elaboration_error(
        """
        from pypeline import *
        pin: OpenDrain[uint1_t]
        @MAIN
        def main_a():
            pin = 0
        @MAIN
        def main_b():
            pin = 1
        """,
        "open_drain_multiple_writers",
    )
    _expect_elaboration_error(
        """
        from pypeline import *
        @MAIN
        def main():
            pin: OpenDrain[uint1_t]
        """,
        "open_drain_local_declaration",
    )


if __name__ == "__main__":
    test_open_drain_final_top_contract()
    test_open_drain_rejections()
