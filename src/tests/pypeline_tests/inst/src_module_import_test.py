#!/usr/bin/env python3
"""Import-structure checks for the compiler modules in src/.

  - Every src module imports cleanly as the FIRST import of a fresh interpreter.
    The modules import each other in cycles (SYN <-> tool backends, VHDL <->
    AUTO_PIPELINE, C_TO_LOGIC <-> C_TO_FSM, ...), which only works while no module
    reads another's attributes during its own import; a new import-time read
    shows up here as "partially initialized module".
  - A Python design builds with no C preprocessor on PATH (#363): only the C
    front end runs cpp, and it checks for cpp when it first runs it
    (C_TO_LOGIC.REQUIRE_CPP), not when C_TO_LOGIC is imported.
  - A C design without cpp still stops with the cpp message.
  - A build with no synthesis tool installed for its part continues as
    --comb --no_synth, with a warning, and re-elaborates a design that read a
    start_latency= .latency (served by the synthesizing first parse) so the
    read becomes 0.

Run standalone: python3 src_module_import_test.py
"""

import glob
import os
import subprocess
import sys
import tempfile

INST_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(INST_DIR, "..", "..", "..", ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
PIPELINEC = os.path.join(SRC_DIR, "pipelinec")

# Generated parser tables, not compiler modules
_NOT_MODULES = {"__init__", "lextab", "yacctab"}


def _src_modules():
    names = [os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(SRC_DIR, "*.py"))]
    return sorted(n for n in names if n not in _NOT_MODULES)


def _no_cpp_env(bin_dir):
    # PATH holds only a python3 link: no cpp (and no EDA tools, unused by --no_synth)
    os.symlink(sys.executable, os.path.join(bin_dir, "python3"))
    env = dict(os.environ, PATH=bin_dir, PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)
    return env


def test_every_src_module_imports_first():
    failures = []
    for mod in _src_modules():
        p = subprocess.run(
            [sys.executable, "-c", f"import {mod}"],
            cwd=SRC_DIR,
            env=dict(os.environ, PYTHONPATH=SRC_DIR, PYTHONDONTWRITEBYTECODE="1"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if p.returncode != 0:
            failures.append(f"{mod}: {p.stdout.strip().splitlines()[-1]}")
    assert not failures, "src modules that fail as the first import:\n  " + "\n  ".join(failures)


def test_python_build_without_cpp():
    with tempfile.TemporaryDirectory() as tmp:
        env = _no_cpp_env(tmp)
        out_dir = os.path.join(tmp, "out")
        p = subprocess.run(
            [sys.executable, PIPELINEC, os.path.join(REPO_ROOT, "examples", "pypeline", "counter.py"), "--comb", "--no_synth", "--out_dir", out_dir],
            cwd=tmp,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert p.returncode == 0, p.stdout[-3000:]
        assert os.path.isfile(os.path.join(out_dir, "vhdl_files.txt")), p.stdout[-3000:]


def test_c_build_without_cpp_names_cpp():
    with tempfile.TemporaryDirectory() as tmp:
        env = _no_cpp_env(tmp)
        p = subprocess.run(
            [sys.executable, PIPELINEC, os.path.join(REPO_ROOT, "examples", "blink.c"), "--comb", "--no_synth", "--out_dir", os.path.join(tmp, "out")],
            cwd=tmp,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert p.returncode != 0, p.stdout[-3000:]
        assert "'cpp' C preprocessor is not installed!" in p.stdout, p.stdout[-3000:]


def _no_syn_tool_build(design):
    # PATH holds only python3 (no Vivado on it) and XILINX_VIVADO names a missing
    # install, so the xc7 part's tool is not installed on any machine
    with tempfile.TemporaryDirectory() as tmp:
        env = _no_cpp_env(tmp)
        env["XILINX_VIVADO"] = os.path.join(tmp, "no_vivado")
        out_dir = os.path.join(tmp, "out")
        p = subprocess.run(
            [sys.executable, PIPELINEC, design, "--part", "xc7a35tcpg236-1", "--out_dir", out_dir],
            cwd=tmp,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        wrote_vhdl = os.path.isfile(os.path.join(out_dir, "vhdl_files.txt"))
    return p, wrote_vhdl


_NO_SYN_TOOL_WARNING = "WARNING: No synthesis tool install detected based on PART."


def test_no_syn_tool_falls_back_to_comb_no_synth():
    p, wrote_vhdl = _no_syn_tool_build(os.path.join(REPO_ROOT, "examples", "pypeline", "counter.py"))
    assert p.returncode == 0, p.stdout[-3000:]
    assert _NO_SYN_TOOL_WARNING in p.stdout, p.stdout[-3000:]
    assert wrote_vhdl, p.stdout[-3000:]
    assert "Re-elaborating:" not in p.stdout, p.stdout[-3000:]


def test_no_syn_tool_fallback_re_elaborates_start_latency():
    p, _ = _no_syn_tool_build(os.path.join(INST_DIR, "no_syn_tool_fallback_design.py"))
    assert p.returncode == 0, p.stdout[-3000:]
    out = p.stdout
    first = out.find("no_syn_tool_fallback_design: .latency=1")
    reelab = out.find("Re-elaborating: AUTO_PIPELINE start_latency=")
    second = out.find("no_syn_tool_fallback_design: .latency=0")
    assert 0 <= first < reelab < second, out[-3000:]


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
