#!/usr/bin/env python3
"""Pure unit coverage for PipelineC's open-source Xilinx 7-series flow.

No FPGA tools are invoked here.  The real Basys 3 hardware proof is kept out of
run_all; these tests pin the configuration/selection behavior that makes that
flow reproducible on any host with a compatible OpenXC7 toolchain.
"""

import json
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


def _restore_env(name, old):
    if old is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = old


def test_xc7_part_and_chipdb_candidates():
    assert OPEN_TOOLS.IS_XC7_PART(PART)
    assert not OPEN_TOOLS.IS_XC7_PART("LFE5U-85F-6BG381C")
    assert OPEN_TOOLS._XC7_ARCH_CHIPDB_NAMES(PART) == [
        "xc7a35tcpg236.bin",
        "xc7a35t.bin",
    ]


def test_xc7_chipdb_directory_lookup_accepts_device_fallback():
    old_openxc7 = os.environ.get("OPENXC7_CHIPDB")
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            candidate = Path(tmp_dir) / "xc7a35t.bin"
            candidate.write_bytes(b"chipdb")
            os.environ["OPENXC7_CHIPDB"] = tmp_dir
            assert OPEN_TOOLS.GET_XC7_CHIPDB_PATH(PART) == str(candidate)
    finally:
        _restore_env("OPENXC7_CHIPDB", old_openxc7)


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
    import openxc7_characterization_netlist

    characterization_cmd = OPEN_TOOLS.XC7_SYNTH_XILINX_COMMAND(
        "timing_top", is_final_top=False
    )
    final_cmd = OPEN_TOOLS.XC7_SYNTH_XILINX_COMMAND("top", is_final_top=True)
    assert "-noiopad" in characterization_cmd
    assert "-noiopad" not in final_cmd
    assert characterization_cmd.endswith("-top timing_top")
    assert final_cmd.endswith("-top top")

    with tempfile.TemporaryDirectory() as tmp_dir:
        json_path = Path(tmp_dir) / "top.json"
        json_path.write_text(
            json.dumps(
                {
                    "modules": {
                        "timing_top": {
                            "ports": {
                                "clk": {"direction": "input", "bits": [2]},
                                "a": {"direction": "input", "bits": [3, 4]},
                                "y": {"direction": "output", "bits": [5]},
                            },
                            "netnames": {
                                "clk": {"bits": [2]},
                                "a_input_reg": {"bits": [6, 7]},
                                "y_output_reg": {"bits": [8]},
                            },
                            "cells": {
                                "input_ff": {
                                    "type": "FDRE",
                                    "connections": {"C": [9], "D": [3], "Q": [6]},
                                },
                                "output_ff": {
                                    "type": "FDRE",
                                    "connections": {"C": [9], "D": [10], "Q": [5]},
                                },
                            },
                        }
                    }
                }
            )
        )
        openxc7_characterization_netlist.strip_top_ports(json_path, "timing_top")
        netlist = json.loads(json_path.read_text())
        top = netlist["modules"]["timing_top"]
        assert top["ports"] == {}
        assert top["netnames"]["a_input_reg"]["bits"] == [6, 7]
        assert top["cells"]["input_ff"]["type"] == "FDRE"
        assert top["cells"]["output_ff"]["type"] == "FDRE"


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


def test_openxc7_comb_timing_uses_board_top_only_with_pins():
    import SWEEP

    old_tool = SYN.SYN_TOOL
    old_pins = SYN.PIN_CONSTRAINTS_FILE
    try:
        parser_state = SimpleNamespace(part=PART)
        SYN.SYN_TOOL = OPEN_TOOLS
        SYN.PIN_CONSTRAINTS_FILE = None
        assert not SWEEP._OPENXC7_COMB_USES_FINAL_TOP(parser_state)

        SYN.PIN_CONSTRAINTS_FILE = "/tmp/board.xdc"
        assert SWEEP._OPENXC7_COMB_USES_FINAL_TOP(parser_state)

        parser_state.part = "LFE5U-85F-6BG381C"
        assert not SWEEP._OPENXC7_COMB_USES_FINAL_TOP(parser_state)
    finally:
        SYN.SYN_TOOL = old_tool
        SYN.PIN_CONSTRAINTS_FILE = old_pins


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
