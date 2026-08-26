#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression coverage for the "Argument list too long" bug:
`./build.py --shared --sim --syn_tb` (wireguard-fpga) failed before GHDL even
started, deep inside make/execvp, once a design's VHDL file list crossed
~128 KiB.

Root cause: cocotb's Makefile.ghdl "analyse" target is one
backslash-continued logical recipe line, so GNU Make hands it to the shell
as a *single* argv string. Linux caps any one argv/envp string at
MAX_ARG_STRLEN (PAGE_SIZE * 32 = 131072 bytes here), independent of the
much larger overall ARG_MAX -- COCOTB.py's old `VHDL_SOURCES +=
$(shell cat "vhdl_files.txt")` inlined every absolute path straight into
that one recipe string, so a large enough design's own file list alone
could push it over.

COCOTB.GET_MAKEFILE_TEXT() now emits VHDL_SOURCES as a GHDL "@file"
response file instead (see its own docstring for the .PHONY/
CUSTOM_COMPILE_DEPS details). OPEN_TOOLS.WRITE_YOSYS_SCRIPT() applies the
analogous fix at every `yosys -p '<huge ghdl file list>'` call site
(OPEN_TOOLS/CXXRTL/PYRTL/CC_TOOLS/DEVICE_MODELS): write the commands to a
`.ys` script file and pass `-s <path>` instead, so the file list never
becomes a single exec argv.

This is a byte-count check only (no real toolchain run): assert the fully
expanded `make -n analyse` recipe -- and the yosys script's own "-s <path>"
argv fragment -- both stay under MAX_ARG_STRLEN for a synthetic file list
that is deliberately built to exceed it. Real designs never get near this
threshold, so a normal-sized design test would never exercise the bug.
"""

import os
import shlex
import subprocess
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import COCOTB
import OPEN_TOOLS

# The kernel limit this bug hits: any single argv/envp string is capped at
# PAGE_SIZE * 32, independent of the much larger overall ARG_MAX.
MAX_ARG_STRLEN = os.sysconf("SC_PAGESIZE") * 32


def _synthetic_vhdl_paths(tmp_dir, min_total_bytes):
    """Absolute paths whose space-joined total exceeds min_total_bytes.

    Sized by total bytes, not a fixed file count, so the test still exceeds
    MAX_ARG_STRLEN regardless of how long tmp_dir itself happens to be.
    """
    paths = []
    total = 0
    i = 0
    while total <= min_total_bytes:
        path = os.path.join(tmp_dir, f"synthetic_entity_{i:04d}", f"file_{i:04d}.vhd")
        paths.append(path)
        total += len(path.encode()) + 1  # +1 for the joining space
        i += 1
    return paths


def test_cocotb_makefile_recipe_under_max_arg_strlen():
    with tempfile.TemporaryDirectory() as tmp_dir:
        vhdl_files_txt = os.path.join(tmp_dir, "vhdl_files.txt")
        with open(vhdl_files_txt, "w") as f:
            f.write(" ".join(_synthetic_vhdl_paths(tmp_dir, MAX_ARG_STRLEN)))
        assert os.path.getsize(vhdl_files_txt) > MAX_ARG_STRLEN, (
            "synthetic file list must itself exceed MAX_ARG_STRLEN or this "
            "test does not exercise the bug"
        )

        makefile_text = COCOTB.GET_MAKEFILE_TEXT(
            "SIM ?= ghdl\nEXTRA_ARGS += --std=08\n",
            vhdl_files_txt,
            "top",
            "test_top",
        )
        makefile_path = os.path.join(tmp_dir, "Makefile")
        with open(makefile_path, "w") as f:
            f.write(makefile_text)

        # -n: dry run. Requires ghdl on PATH (Makefile.ghdl's own
        # `command -v ghdl` check runs at parse time, not recipe time) but
        # never actually invokes it -- this only checks the expanded recipe
        # text's length, the exact thing execvp choked on.
        proc = subprocess.run(
            ["make", "-n", "analyse"],
            cwd=tmp_dir,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, (
            f"make -n analyse failed (exit {proc.returncode}):\n{proc.stderr}"
        )
        for line in proc.stdout.splitlines():
            line_len = len(line.encode())
            assert line_len < MAX_ARG_STRLEN, (
                f"expanded recipe line is {line_len} bytes (>= "
                f"MAX_ARG_STRLEN={MAX_ARG_STRLEN}): {line[:200]}..."
            )


def test_yosys_script_argv_under_max_arg_strlen():
    with tempfile.TemporaryDirectory() as tmp_dir:
        huge_ghdl_command = (
            "ghdl --std=08 "
            + " ".join(_synthetic_vhdl_paths(tmp_dir, MAX_ARG_STRLEN))
            + " -e top"
        )
        assert len(huge_ghdl_command.encode()) > MAX_ARG_STRLEN, (
            "synthetic ghdl command must itself exceed MAX_ARG_STRLEN or "
            "this test does not exercise the bug"
        )

        script_path = os.path.join(tmp_dir, "build.ys")
        yosys_script_arg = OPEN_TOOLS.WRITE_YOSYS_SCRIPT(
            [huge_ghdl_command, "synth -top top"], script_path
        )

        for token in shlex.split(yosys_script_arg):
            token_len = len(token.encode())
            assert token_len < MAX_ARG_STRLEN, (
                f"yosys argv token is {token_len} bytes (>= "
                f"MAX_ARG_STRLEN={MAX_ARG_STRLEN}): {token[:200]}..."
            )

        with open(script_path) as f:
            script_contents = f.read()
        assert huge_ghdl_command in script_contents
        assert "synth -top top" in script_contents


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
