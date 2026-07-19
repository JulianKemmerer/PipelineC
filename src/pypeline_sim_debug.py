#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pypeline_sim_debug.py -- cycle-accurate native-vs-VHDL sim console diff tool.

Runs a Pypeline testbench two ways -- native Python sim and VHDL sim (via
cocotb+GHDL), concurrently -- and diffs their sim_print(..., debug=True)
console output cycle by cycle, reporting the first cycle where the two sims
disagree.

Usage (mirrors pipelinec's own args -- pass whatever you'd normally pass to
`pipelinec ... --sim ...`, this script runs it once as given and once again
with --cocotb --ghdl added):

    pypeline_sim_debug.py ./src/chacha20poly1305_encrypt_syn_tb.py --sim --comb --run all

Only sim_print(..., debug=True) output is compared -- plain sim_print(...)
lines (debug=False, the default) are ignored, since simulators print those in
different orders/formats and most aren't relevant for cycle-accuracy
debugging. See docs/pypeline_guide.md.

Full raw stdout from both runs is always saved to <out_dir>/native.log and
<out_dir>/vhdl.log (regardless of match/mismatch), so a divergence can be
inspected afterward without re-running either sim -- the GHDL run in
particular is slow. On mismatch, the report also prints +/- --context cycles
of debug-tagged lines around the first divergence, side by side, from both
logs -- no manual grep round-trip needed.
"""

import argparse
import concurrent.futures
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PIPELINEC = os.path.join(_HERE, "pipelinec")

_CLOCK_RE = re.compile(r"^Clock:\s+(\d+)\s*$")
_DEBUG_LINE_RE = re.compile(r"^\[SIM DEBUG PRINT: .*\]: ")

_DEFAULT_CONTEXT_CYCLES = 10


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


def _find_c_file(pipelinec_args):
    for a in pipelinec_args:
        if not a.startswith("-"):
            return a
    return "design"


def _print_context(native_cycles, vhdl_cycles, center_cycle, context, all_cycles):
    lo = center_cycle - context
    hi = center_cycle + context
    print(f"--- Context: cycles {lo}..{hi} around first divergence (side by side) ---")
    for cycle in range(lo, hi + 1):
        if cycle not in all_cycles:
            continue
        native_lines = sorted(native_cycles.get(cycle, []))
        vhdl_lines = sorted(vhdl_cycles.get(cycle, []))
        marker = " <<< MISMATCH" if native_lines != vhdl_lines else ""
        print(f"Cycle {cycle}:{marker}")
        print("  NATIVE:")
        for l in native_lines:
            print(f"    {l}")
        print("  VHDL:")
        for l in vhdl_lines:
            print(f"    {l}")
    print()


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
        help="Base output directory. For non---comb designs, pipelinec builds "
        "once directly into <out_dir> and both sims reuse it; for --comb "
        "designs, pipelinec build outputs go in '<out_dir>/native' and "
        "'<out_dir>/vhdl'. Full raw sim stdout is always saved to "
        "'<out_dir>/native.log' and '<out_dir>/vhdl.log'. Default: a new "
        "'./pypeline_sim_debug_out_<design>_<pid>' directory.",
    )
    parser.add_argument(
        "--context",
        type=int,
        default=_DEFAULT_CONTEXT_CYCLES,
        help=f"On mismatch, print +/- this many cycles of debug-tagged lines "
        f"around the first divergence, from both runs side by side "
        f"(default: {_DEFAULT_CONTEXT_CYCLES}; 0 disables).",
    )
    args, pipelinec_args = parser.parse_known_args()

    if "--cocotb" in pipelinec_args or "--ghdl" in pipelinec_args:
        print(
            "error: do not pass --cocotb/--ghdl yourself -- pypeline_sim_debug.py "
            "adds them itself for the VHDL run",
            file=sys.stderr,
        )
        return 2

    if args.out_dir is not None:
        out_dir = args.out_dir
    else:
        c_file_base = os.path.basename(_find_c_file(pipelinec_args))
        out_dir = f"./pypeline_sim_debug_out_{c_file_base}_{os.getpid()}"
    os.makedirs(out_dir, exist_ok=True)
    native_log_path = os.path.join(out_dir, "native.log")
    vhdl_log_path = os.path.join(out_dir, "vhdl.log")

    serial = not any(
        a in ("--comb", "--sim_comb", "--no_synth") for a in pipelinec_args
    )
    if serial:
        # Non---comb: build once (no --sim) into the shared out_dir, doing
        # the full throughput sweep + AUTOPIPELINE pin-and-confirm just a
        # single time. Then point BOTH the native and VHDL sim invocations
        # at that same now-populated out_dir and run them concurrently --
        # each re-runs pipelinec's build path internally, but with the sweep
        # already warm (existing VHDL/log/timing-params results in out_dir,
        # plus the repo-level path-delay / pipeline-min-period caches) it
        # converges fast, and both are guaranteed to converge to the same
        # discovered latencies as the build phase (same inputs, same warm
        # out_dir/caches) -- a prerequisite for a meaningful cycle diff.
        # --sim/--sim_comb (if the user passed one, per this script's own
        # usage) must be stripped for the build-only phase.
        no_sim_args = [a for a in pipelinec_args if a not in ("--sim", "--sim_comb")]
        build_args = no_sim_args + ["--out_dir", out_dir]
        _run_pipelinec(build_args, "build")
        native_args = no_sim_args + ["--sim", "--out_dir", out_dir]
        vhdl_args = no_sim_args + [
            "--cocotb",
            "--ghdl",
            "--sim",
            "--out_dir",
            out_dir,
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            native_future = pool.submit(_run_pipelinec, native_args, "native")
            vhdl_future = pool.submit(_run_pipelinec, vhdl_args, "VHDL/cocotb")
            native_stdout = native_future.result()
            vhdl_stdout = vhdl_future.result()
    else:
        native_out_dir = os.path.join(out_dir, "native")
        vhdl_out_dir = os.path.join(out_dir, "vhdl")
        native_args = list(pipelinec_args) + ["--out_dir", native_out_dir]
        vhdl_args = list(pipelinec_args) + [
            "--cocotb",
            "--ghdl",
            "--out_dir",
            vhdl_out_dir,
        ]
        # Comb: native sim is fast; VHDL/cocotb+GHDL sim is slow -- run both
        # concurrently (they're independent subprocesses writing to separate
        # --out_dirs) rather than paying their combined wall-clock time
        # serially.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            native_future = pool.submit(_run_pipelinec, native_args, "native")
            vhdl_future = pool.submit(_run_pipelinec, vhdl_args, "VHDL/cocotb")
            native_stdout = native_future.result()
            vhdl_stdout = vhdl_future.result()

    # Always saved, match or mismatch -- so a divergence can be inspected later
    # without re-running either sim (GHDL especially is slow).
    with open(native_log_path, "w") as f:
        f.write(native_stdout)
    with open(vhdl_log_path, "w") as f:
        f.write(vhdl_stdout)

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
        print(f"Full logs: {native_log_path}  {vhdl_log_path}")
        return 1

    all_cycles_set = set(native_cycles) | set(vhdl_cycles)
    all_cycles = sorted(all_cycles_set)
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
        print(f"Full logs: {native_log_path}  {vhdl_log_path}")
        return 0
    else:
        if args.context > 0:
            _print_context(
                native_cycles,
                vhdl_cycles,
                first_mismatch_cycle,
                args.context,
                all_cycles_set,
            )
        print(
            f"MISMATCH: first divergence at cycle {first_mismatch_cycle}; "
            f"{mismatched_cycles}/{len(all_cycles)} cycles differ, "
            f"{mismatched_lines} total differing lines."
        )
        print(f"Full logs: {native_log_path}  {vhdl_log_path}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
