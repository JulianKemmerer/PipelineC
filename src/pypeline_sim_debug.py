#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pypeline_sim_debug.py -- cycle-accurate native-vs-VHDL sim console diff tool.

Runs a Pypeline testbench two ways -- native Python sim and VHDL sim (via
cocotb+GHDL) -- and diffs their sim_print(..., debug=True) console output
cycle by cycle, reporting the first cycle where the two sims disagree.

Usage (mirrors pipelinec's own args -- pass whatever you'd normally pass to
`pipelinec ... --sim ...`, this script runs it once as given and once again
with --cocotb --ghdl added):

    pypeline_sim_debug.py ./src/chacha20poly1305_encrypt_syn_tb.py --sim --comb --run all

Only sim_print(..., debug=True) output is compared -- plain sim_print(...)
lines (debug=False, the default) are ignored, since simulators print those in
different orders/formats and most aren't relevant for cycle-accuracy
debugging. See docs/pypeline_guide.md.
"""

import argparse
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PIPELINEC = os.path.join(_HERE, "pipelinec")

_CLOCK_RE = re.compile(r"^Clock:\s+(\d+)\s*$")
_DEBUG_LINE_RE = re.compile(r"^\[SIM DEBUG PRINT: .*\]: ")


def _run_pipelinec(extra_args, label):
    cmd = [sys.executable, _PIPELINEC] + extra_args
    print(f"--- running {label} sim: {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(
            f"--- WARNING: {label} sim exited with code {proc.returncode} -- "
            f"comparing whatever output was captured anyway",
            file=sys.stderr,
        )
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
    return proc.stdout


def _cycles_of_debug_lines(stdout_text):
    """Returns {cycle_number: [debug_line, ...]} extracted from raw sim stdout."""
    cycles = {}
    cur_cycle = None
    for line in stdout_text.splitlines():
        m = _CLOCK_RE.match(line)
        if m:
            cur_cycle = int(m.group(1))
            cycles.setdefault(cur_cycle, [])
            continue
        if cur_cycle is not None and _DEBUG_LINE_RE.match(line):
            cycles[cur_cycle].append(line)
    return cycles


def _out_dir_for(base_out_dir, suffix):
    if base_out_dir is None:
        return None
    return base_out_dir.rstrip("/") + suffix


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Run a Pypeline testbench natively and via cocotb+GHDL, diff their "
            "sim_print(..., debug=True) console output cycle by cycle, and report "
            "the first divergence."
        )
    )
    parser.add_argument(
        "--out_dir",
        type=str,
        default=None,
        help="Base output directory. Native/VHDL runs use '<out_dir>-native' "
        "and '<out_dir>-vhdl'. Default: let pipelinec pick its own default "
        "for each run.",
    )
    args, pipelinec_args = parser.parse_known_args()

    if "--cocotb" in pipelinec_args or "--ghdl" in pipelinec_args:
        print(
            "error: do not pass --cocotb/--ghdl yourself -- pypeline_sim_debug.py "
            "adds them itself for the VHDL run",
            file=sys.stderr,
        )
        return 2

    native_args = list(pipelinec_args)
    vhdl_args = list(pipelinec_args) + ["--cocotb", "--ghdl"]
    native_out_dir = _out_dir_for(args.out_dir, "-native")
    vhdl_out_dir = _out_dir_for(args.out_dir, "-vhdl")
    if native_out_dir is not None:
        native_args += ["--out_dir", native_out_dir]
        vhdl_args += ["--out_dir", vhdl_out_dir]

    native_stdout = _run_pipelinec(native_args, "native")
    vhdl_stdout = _run_pipelinec(vhdl_args, "VHDL/cocotb")

    native_cycles = _cycles_of_debug_lines(native_stdout)
    vhdl_cycles = _cycles_of_debug_lines(vhdl_stdout)

    total_native_lines = sum(len(v) for v in native_cycles.values())
    total_vhdl_lines = sum(len(v) for v in vhdl_cycles.values())
    if total_native_lines == 0 and total_vhdl_lines == 0:
        print(
            "WARNING: no sim_print(..., debug=True) output found in either run -- "
            "nothing to compare. Did you use debug=True in the testbench?",
            file=sys.stderr,
        )
        return 1

    all_cycles = sorted(set(native_cycles) | set(vhdl_cycles))
    first_mismatch_cycle = None
    mismatched_cycles = 0
    mismatched_lines = 0
    for cycle in all_cycles:
        native_lines = sorted(native_cycles.get(cycle, []))
        vhdl_lines = sorted(vhdl_cycles.get(cycle, []))
        if native_lines == vhdl_lines:
            continue
        mismatched_cycles += 1
        native_only = [l for l in native_lines if l not in vhdl_lines]
        vhdl_only = [l for l in vhdl_lines if l not in native_lines]
        mismatched_lines += len(native_only) + len(vhdl_only)
        if first_mismatch_cycle is None:
            first_mismatch_cycle = cycle
            print(f"=== First divergence at cycle {cycle} ===")
            for l in native_only:
                print(f"  NATIVE only: {l}")
            for l in vhdl_only:
                print(f"  VHDL   only: {l}")

    print()
    if first_mismatch_cycle is None:
        print(
            f"MATCH: {len(all_cycles)} cycles compared, all sim_print(debug=True) output identical."
        )
        return 0
    else:
        print(
            f"MISMATCH: first divergence at cycle {first_mismatch_cycle}; "
            f"{mismatched_cycles}/{len(all_cycles)} cycles differ, "
            f"{mismatched_lines} total differing lines."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
