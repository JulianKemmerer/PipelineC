#!/usr/bin/env python3
"""Pure unit coverage for PipelineC's open-source Xilinx 7-series flow.

No FPGA tools are invoked here: the real OpenXC7 builds are the synth_open_tools
tests openxc7_bitstream_test and sweep_float32_openxc7. These tests pin the
configuration/selection behavior and the parsing of nextpnr-xilinx reports.
"""

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import C_TO_LOGIC  # Establish PipelineC's normal module-import order.
import SYN
import OPEN_TOOLS


PART = "xc7a35tcpg236-1"

# Real nextpnr-xilinx output (openXC7 bundle 2026-09-15, examples/pypeline/blink.py
# characterization top): its older "curr total" path table, and the clock timed
# on the net past the BUFG rather than on the constrained clk_25p0.
NEXTPNR_XILINX_BLINK_REPORT = r"""
Info: constraining clock net 'clk_25p0' to 25.00 MHz
Info: Propagating clock constraints...
Info:     derived 25.0 MHz for net 'blink_0clk_c4b4c111.clk' (through BUFG '$auto$clkbufmap.cc:261:execute$2748')
Info: Critical path report for clock 'blink_0clk_c4b4c111.clk' (posedge -> posedge):
Info: curr total
Info:  0.1  0.1  Source $auto$ff.cc:266:slice$1711.Q
Info:  0.0  0.1    Net blink_0clk_c4b4c111.bin_op_eq_blink_py_l24_c7_ec32_left[0] budget 0.000000 ns (13,1) -> (13,1)
Info:                Sink $abc$2731$lut$not$aiger2730$3.A3
Info:  0.1  0.2  Source $abc$2731$lut$not$aiger2730$3.O6
Info:  1.2  1.4    Net blink_0clk_c4b4c111.bin_op_plus_blink_py_l28_c18_ec29_return_output[0] budget 0.000000 ns (13,1) -> (10,9)
Info:                Sink blink_0clk_c4b4c111.bin_op_plus_blink_py_l28_c18_ec29_return_output[0]$LUT$2.A4
Info:  0.1  1.5  Source blink_0clk_c4b4c111.bin_op_plus_blink_py_l28_c18_ec29_return_output[0]$LUT$2.O6
Info:  0.0  1.5    Net blink_0clk_c4b4c111.bin_op_plus_blink_py_l28_c18_ec29_return_output[0]$legal$1 budget 2.688000 ns (10,9) -> (10,9)
Info:                Sink $auto$alumacc.cc:485:replace_alu$1290.genblk1.slice[0].genblk1.carry4.S0
Info:  0.5  2.0  Source $auto$alumacc.cc:485:replace_alu$1290.genblk1.slice[0].genblk1.carry4.CO3
Info:  0.1  2.2    Net $auto$alumacc.cc:485:replace_alu$1290.genblk1.slice[0].genblk1.carry4$carry$130 budget 3.160000 ns (10,9) -> (10,8)
Info:                Sink $auto$alumacc.cc:485:replace_alu$1290.genblk1.slice[0].genblk1.carry4$split$129.CIN
Info:  0.2  2.3  Source $auto$alumacc.cc:485:replace_alu$1290.genblk1.slice[0].genblk1.carry4$split$129.CO1
Info:  1.0  3.3    Net $techmap2738$abc$2731$lut$aiger2730$112.A[4] budget 0.000000 ns (10,8) -> (10,2)
Info:                Sink $abc$2731$lut$aiger2730$112.A3
Info:  0.1  3.4  Source $abc$2731$lut$aiger2730$112.O6
Info:  0.3  3.7    Net $techmap2745$abc$2731$lut\blink_return_output_output.A[1] budget 0.000000 ns (10,2) -> (10,2)
Info:                Sink $abc$2731$lut$auto$rtlil.cc:2976:NotGate$2036.A1
Info:  0.1  3.8  Source $abc$2731$lut$auto$rtlil.cc:2976:NotGate$2036.O6
Info:  1.1  4.9    Net $abc$2731$auto$rtlil.cc:2976:NotGate$2036 budget 5.519000 ns (10,2) -> (10,3)
Info:                Sink $auto$ff.cc:266:slice$1731.SR
Info:  0.1  5.0  Setup $auto$ff.cc:266:slice$1731.SR
Info: 1.4 ns logic, 3.7 ns routing

Info: Max frequency for clock 'blink_0clk_c4b4c111.clk': 199.08 MHz (PASS at 25.00 MHz)
"""


def _restore_env(name, old):
    if old is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = old


def test_xc7_part_and_chipdb_name():
    assert OPEN_TOOLS.IS_XC7_PART(PART)
    assert not OPEN_TOOLS.IS_XC7_PART("LFE5U-85F-6BG381C")
    # Base part (device + package), no speed grade: the Apio/openXC7 naming
    assert OPEN_TOOLS.XC7_CHIPDB_NAME(PART) == "xc7a35tcpg236.bin"


def test_xc7_chipdb_lookup_needs_the_parts_package():
    # A device-only chipdb (xc7a35t.bin) may hold another package's pin map, so
    # a directory search never picks it; naming the file directly still does.
    old_root = OPEN_TOOLS.OPENXC7_PATH
    old_chipdb = os.environ.get("OPENXC7_CHIPDB")
    try:
        OPEN_TOOLS.OPENXC7_PATH = None  # keep the default install out of this
        with tempfile.TemporaryDirectory() as tmp_dir:
            device_only = Path(tmp_dir) / "xc7a35t.bin"
            device_only.write_bytes(b"chipdb")
            os.environ["OPENXC7_CHIPDB"] = tmp_dir
            assert OPEN_TOOLS.GET_XC7_CHIPDB_PATH(PART) is None

            exact = Path(tmp_dir) / "xc7a35tcpg236.bin"
            exact.write_bytes(b"chipdb")
            assert OPEN_TOOLS.GET_XC7_CHIPDB_PATH(PART) == str(exact)

            os.environ["OPENXC7_CHIPDB"] = str(device_only)
            assert OPEN_TOOLS.GET_XC7_CHIPDB_PATH(PART) == str(device_only)
    finally:
        OPEN_TOOLS.OPENXC7_PATH = old_root
        _restore_env("OPENXC7_CHIPDB", old_chipdb)


def test_openxc7_root_locates_tools_chipdb_and_family_database():
    old_root = OPEN_TOOLS.OPENXC7_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tool = root / "bin" / "nextpnr-xilinx"
            tool.parent.mkdir()
            tool.write_text("#!/bin/sh\n")
            tool.chmod(0o755)
            chipdb = root / "chipdb" / "xc7a35tcpg236.bin"
            chipdb.parent.mkdir()
            chipdb.write_bytes(b"chipdb")
            family_db = (
                root / "share" / "nextpnr" / "external" / "prjxray-db" / "artix7"
            )
            family_db.mkdir(parents=True)

            OPEN_TOOLS.OPENXC7_PATH = str(root)
            assert OPEN_TOOLS.GET_XC7_TOOL_PATH("nextpnr-xilinx") == str(tool)
            assert OPEN_TOOLS.GET_XC7_CHIPDB_PATH(PART) == str(chipdb)
            assert OPEN_TOOLS.GET_XC7_PRJXRAY_DB_DIR(PART) == str(family_db)
    finally:
        OPEN_TOOLS.OPENXC7_PATH = old_root


def test_xc7_database_family_is_not_hardcoded_to_artix7():
    assert OPEN_TOOLS._XC7_DATABASE_FAMILY("xc7a35tcpg236-1") == "artix7"
    assert OPEN_TOOLS._XC7_DATABASE_FAMILY("xc7s50csga324-1") == "spartan7"
    assert OPEN_TOOLS._XC7_DATABASE_FAMILY("xc7z020clg400-1") == "zynq7"
    assert OPEN_TOOLS._XC7_DATABASE_FAMILY("xc7k325tffg900-2") == "kintex7"
    assert OPEN_TOOLS._XC7_DATABASE_FAMILY("xc7v585tffg1761-2") == "virtex7"


def test_openxc7_characterization_avoids_physical_iopads():
    characterization = OPEN_TOOLS.XC7_YOSYS_COMMANDS("a.vhd", "timing_top", False)
    final = OPEN_TOOLS.XC7_YOSYS_COMMANDS("a.vhd", "top", True)
    # Characterization: no I/O buffers, and no top-level ports left for
    # nextpnr-xilinx to turn into PADs
    assert "-noiopad" in characterization[1]
    assert characterization[1].endswith("-top timing_top")
    assert characterization[-2:] == [
        "delete -port timing_top",
        "write_json timing_top.json",
    ]
    # Final: normal board I/O for the --pins XDC
    assert "-noiopad" not in final[1]
    assert final[1].endswith("-top top")
    assert not any(command.startswith("delete") for command in final)
    assert final[-1] == "write_json top.json"


def test_openxc7_timing_parser_accepts_colons_in_synthesized_clock_names():
    text = """\
Info: Critical path report for clock '$auto$clkbufmap.cc:294:execute$2176' (posedge -> posedge):
Info: curr total
Info:  0.1  0.1  Source input_ff.Q
Info:  1.8  1.9    Net logic
Info:                Sink output_ff.D
Info:  0.1  2.0  Setup output_ff.D
Info: 1.3 ns logic, 0.7 ns routing
Info: Max frequency for clock '$auto$clkbufmap.cc:294:execute$2176': 498.50 MHz (FAIL at 1000.00 MHz)
"""
    report = OPEN_TOOLS.ParsedTimingReport(text)
    assert "$auto$clkbufmap.cc:294:execute$2176" in report.path_reports
    path = report.path_reports["$auto$clkbufmap.cc:294:execute$2176"]
    assert abs(path.path_delay_ns - (1000.0 / 498.50)) < 1e-9
    assert path.source_ns_per_clock == 1.0


def test_openxc7_timing_parser_reads_nextpnr_xilinx_report():
    report = OPEN_TOOLS.ParsedTimingReport(NEXTPNR_XILINX_BLINK_REPORT)
    # Keyed by the constrained clock, as nextpnr-ecp5 reports it
    assert list(report.path_reports) == ["clk_25p0"]
    path = report.path_reports["clk_25p0"]
    assert path.path_group == "clk_25p0"
    assert abs(path.path_delay_ns - (1000.0 / 199.08)) < 1e-9
    assert path.source_ns_per_clock == 1000.0 / 25.0
    # Register and net names, for the sweep's critical path attribution
    assert path.start_reg_name.startswith("blink_0clk_c4b4c111/")
    assert path.end_reg_name is not None
    assert len(path.netlist_resources) == 7


def test_openxc7_clock_alias_needs_one_constrained_clock_at_that_frequency():
    # Two clocks at one frequency: which one the derived net came from is
    # unknown, so it keeps the name nextpnr reported
    text = NEXTPNR_XILINX_BLINK_REPORT.replace(
        "Info: Propagating clock constraints...",
        "Info: constraining clock net 'clk_25p0_other' to 25.00 MHz\n"
        "Info: Propagating clock constraints...",
    )
    report = OPEN_TOOLS.ParsedTimingReport(text)
    assert list(report.path_reports) == ["blink_0clk_c4b4c111.clk"]


def test_openxc7_bitstream_conversion_is_an_explicit_backend_operation():
    old_tool = SYN.SYN_TOOL
    try:
        parser_state = object()
        timing_params = object()
        sentinel = object()
        calls = []

        def generate_bitstream(ps, params):
            calls.append((ps, params))
            return sentinel

        SYN.SYN_TOOL = SimpleNamespace(GENERATE_BITSTREAM=generate_bitstream)
        result = SYN.GENERATE_FINAL_BITSTREAM(parser_state, timing_params)
        assert result is sentinel
        assert calls == [(parser_state, timing_params)]
    finally:
        SYN.SYN_TOOL = old_tool


def test_openxc7_uses_existing_open_tools_backend_selection():
    # Keep Vivado as the historical/default backend for an xc7 part, while
    # allowing an explicit --syn_tool open_tools to select the open flow.
    assert SYN.PART_TO_TOOL(PART) is SYN.VIVADO
    assert SYN.GET_TOOL_MODULE("open_tools") is SYN.OPEN_TOOLS
    assert SYN.TOOL_MATCHES_PART(SYN.VIVADO, PART)
    assert SYN.TOOL_MATCHES_PART(SYN.OPEN_TOOLS, PART)


def test_openxc7_bitstream_preflight_checks_conversion_tools_and_part_database():
    old_root = OPEN_TOOLS.OPENXC7_PATH
    old_prjxray = os.environ.get("PRJXRAY_DB_DIR")
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bindir = root / "bin"
            bindir.mkdir()
            for name in ("fasm2frames", "xc7frames2bit"):
                tool = bindir / name
                tool.write_text("#!/bin/sh\n")
                tool.chmod(0o755)
            family_db = (
                root / "share" / "nextpnr" / "external" / "prjxray-db" / "artix7"
            )
            part_dir = family_db / PART.lower()
            part_dir.mkdir(parents=True)
            part_yaml = part_dir / "part.yaml"
            part_yaml.write_text("part: test\n")

            os.environ.pop("PRJXRAY_DB_DIR", None)
            OPEN_TOOLS.OPENXC7_PATH = str(root)
            f2f, f2b, db, yaml = OPEN_TOOLS.GET_XC7_BITSTREAM_TOOLS_AND_DB(PART)
            assert f2f == str(bindir / "fasm2frames")
            assert f2b == str(bindir / "xc7frames2bit")
            assert db == str(family_db)
            assert yaml == str(part_yaml)

            part_yaml.unlink()
            try:
                OPEN_TOOLS.GET_XC7_BITSTREAM_TOOLS_AND_DB(PART)
            except Exception as e:
                assert "part file" in str(e)
            else:
                raise AssertionError("missing Project X-Ray part file was accepted")
    finally:
        OPEN_TOOLS.OPENXC7_PATH = old_root
        _restore_env("PRJXRAY_DB_DIR", old_prjxray)


def test_openxc7_bitstream_runs_final_implementation_before_conversion():
    old_root = OPEN_TOOLS.OPENXC7_PATH
    old_out = SYN.SYN_OUTPUT_DIRECTORY
    old_top = SYN.TOP_LEVEL_MODULE
    old_pins = SYN.PIN_CONSTRAINTS_FILE
    old_final_impl = OPEN_TOOLS.SYN_AND_REPORT_TIMING_FINAL_TOP
    old_run = OPEN_TOOLS.subprocess.run
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "openxc7"
            bindir = root / "bin"
            bindir.mkdir(parents=True)
            for name in ("fasm2frames", "xc7frames2bit"):
                tool = bindir / name
                tool.write_text("#!/bin/sh\n")
                tool.chmod(0o755)
            part_dir = (
                root
                / "share"
                / "nextpnr"
                / "external"
                / "prjxray-db"
                / "artix7"
                / PART.lower()
            )
            part_dir.mkdir(parents=True)
            (part_dir / "part.yaml").write_text("part: test\n")

            out = Path(tmp_dir) / "out"
            top_dir = out / "top"
            top_dir.mkdir(parents=True)
            pins = Path(tmp_dir) / "board.xdc"
            pins.write_text("# pins\n")
            # An earlier run's outputs, which must be gone before this run's
            # implementation can fail part way
            outputs = ("top.fasm", "top.frames", "top.bit")
            for name in outputs:
                (top_dir / name).write_text("stale\n")

            class Params:
                TimingParamsLookupTable = {}

            params = Params()
            parser_state = SimpleNamespace(part=PART)
            SYN.SYN_OUTPUT_DIRECTORY = str(out)
            SYN.TOP_LEVEL_MODULE = "top"
            SYN.PIN_CONSTRAINTS_FILE = str(pins)
            OPEN_TOOLS.OPENXC7_PATH = str(root)
            final_report = object()
            implementation_calls = []

            def fake_final_impl(*args):
                implementation_calls.append(args)
                stale = [name for name in outputs if (top_dir / name).exists()]
                assert stale == [], f"stale outputs at implementation: {stale}"
                (top_dir / "top.fasm").write_text("test fasm\n")
                return final_report

            conversion_calls = []

            def fake_run(argv, **kwargs):
                conversion_calls.append(list(argv))
                return SimpleNamespace(returncode=0)

            OPEN_TOOLS.SYN_AND_REPORT_TIMING_FINAL_TOP = fake_final_impl
            OPEN_TOOLS.subprocess.run = fake_run
            result = OPEN_TOOLS.GENERATE_BITSTREAM(parser_state, params)
            assert result is final_report
            assert len(implementation_calls) == 1
            assert implementation_calls[0] == (parser_state, params)
            assert len(conversion_calls) == 2
            assert conversion_calls[0][0].endswith("fasm2frames")
            assert conversion_calls[1][0].endswith("xc7frames2bit")
    finally:
        OPEN_TOOLS.OPENXC7_PATH = old_root
        OPEN_TOOLS.SYN_AND_REPORT_TIMING_FINAL_TOP = old_final_impl
        OPEN_TOOLS.subprocess.run = old_run
        SYN.SYN_OUTPUT_DIRECTORY = old_out
        SYN.TOP_LEVEL_MODULE = old_top
        SYN.PIN_CONSTRAINTS_FILE = old_pins


def test_openxc7_install_check_requires_xc7_specific_payload():
    old_yosys = OPEN_TOOLS.YOSYS_BIN_PATH
    old_ghdl_prefix = OPEN_TOOLS.GHDL_PREFIX
    old_get_tool = OPEN_TOOLS.GET_XC7_TOOL_PATH
    old_get_chipdb = OPEN_TOOLS.GET_XC7_CHIPDB_PATH
    try:
        OPEN_TOOLS.YOSYS_BIN_PATH = "/fake/oss-cad-suite/bin"
        OPEN_TOOLS.GHDL_PREFIX = "/fake/oss-cad-suite/lib/ghdl"
        OPEN_TOOLS.GET_XC7_TOOL_PATH = lambda _name: None
        OPEN_TOOLS.GET_XC7_CHIPDB_PATH = lambda _part: None
        assert not SYN.CHECK_TOOL_INSTALLED(
            SYN.OPEN_TOOLS, PART, allow_fail=True
        )

        OPEN_TOOLS.GET_XC7_TOOL_PATH = lambda _name: "/fake/openxc7/bin/nextpnr-xilinx"
        OPEN_TOOLS.GET_XC7_CHIPDB_PATH = lambda _part: "/fake/openxc7/chipdb/part.bin"
        assert SYN.CHECK_TOOL_INSTALLED(SYN.OPEN_TOOLS, PART)
    finally:
        OPEN_TOOLS.YOSYS_BIN_PATH = old_yosys
        OPEN_TOOLS.GHDL_PREFIX = old_ghdl_prefix
        OPEN_TOOLS.GET_XC7_TOOL_PATH = old_get_tool
        OPEN_TOOLS.GET_XC7_CHIPDB_PATH = old_get_chipdb


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
