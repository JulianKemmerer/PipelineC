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


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
