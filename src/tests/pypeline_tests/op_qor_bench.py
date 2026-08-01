#!/usr/bin/env python3
"""QoR bench: measure per-stage (sliced) delay of every candidate
implementation of PLUS/MINUS/INFERRED_MULT/GT/GTE/LT/LTE/EQ/NEQ.

Two tools, selected per case:

  tool="pyrtl"  No PART() call -> PART_SET_TOOL(None) falls back to PyRTL
                software timing estimates (no part, no real synthesis --
                seconds per case instead of minutes). Fast first-pass signal.
                INFERRED_MULT is skipped here: PyRTL's ASIC-style estimate
                doesn't model DSP inference, so raw-vs-soft mult comparisons
                under pyrtl aren't meaningful -- soft mult variants are still
                compared against each other.
  tool="vivado" PART(xc7a200tffg1156-2) -- wireguard-fpga's actual part.
                Real synthesis, minutes per case. Ground truth / fallback.

Both drive the real `pipelinec` CLI with `--coarse --sweep --start 0 --stop
N` -- ONE subprocess per (op, impl, widths) sweeps cut counts 0..N inside a
single pipelinec run (each step is still an independent OOC synthesis/estimate,
but elaboration + CLI startup only happens once), instead of one subprocess
per (op, impl, widths, n_cuts). The sweep loop naturally stops early if it
can no longer slice further (e.g. hit bit-granularity floor) -- fine, that's
a real data point (the operator's floor).

Modes:
  --case <json>   Run exactly one (op, impl, widths) sweep in-process and
                   print one JSON result (a list of per-n_cuts dicts) to
                   stdout. Used internally, one fresh subprocess per case, so
                   env-gated compiler flags and per-case sys.modules state
                   never leak between measurements.

  (no args)        Driver: enumerate the full matrix, spawn one subprocess
                   per case, append all resulting rows to
                   op_qor_results_<tool>.csv. Resumable: skips any
                   (op,impl,l_type,r_type,tool) already fully represented in
                   the CSV.

The decision metric is pipelined per-stage delay at n_cuts >= 1 -- NOT
n_cuts=0 (comb), which is measured only as context and never used to pick a
winner. This harness never writes to path_delay_cache/ -- results are parsed
directly from Vivado/PyRTL's own printed summary line and (for vivado) the
timing/utilization report text.
"""
import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", "..", ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
INCLUDE_PYPELINE_DIR = os.path.join(REPO_ROOT, "include", "pypeline")

PART = "xc7a200tffg1156-2"

# Max cut count to sweep per width pair (0..MAX_CUTS inclusive), independent
# of the >=4 bits/stage filter applied per-width below.
MAX_CUTS_CAP = 15


def max_useful_cuts(l_bits, r_bits):
    # Don't bother slicing below ~4 bits/stage -- CARRY4 packs 4 bits/prim.
    max_stages = max(1, max(l_bits, r_bits) // 4)
    return min(MAX_CUTS_CAP, max_stages - 1)


def csv_path(tool):
    return os.path.join(THIS_DIR, f"op_qor_results_{tool}.csv")


CSV_FIELDS = [
    "tool", "op", "impl", "l_type", "r_type", "n_cuts",
    "path_delay_ns", "fmax_mhz", "logic_levels",
    "slice_luts", "slice_registers", "carry4",
    "error",
]

# ---------------------------------------------------------------------------
# Case matrix
# ---------------------------------------------------------------------------

WIDTH_PAIRS = [
    (8, 8), (16, 16), (32, 32), (64, 64),
    (32, 3), (32, 4), (16, 1), (8, 1),
]

PLUS_MINUS_IMPLS = ["raw_default", "soft_ripple", "soft_carry_select"]
MULT_IMPLS = ["raw_default", "soft_shift_add", "soft_karatsuba"]
CMP_IMPLS = ["soft_default", "soft_fixed", "soft_bitwise", "raw_revived_sliced"]
CMP_OPS = ["GT", "GTE", "LT", "LTE"]
EQ_IMPLS = ["raw_default", "soft_default"]
EQ_OPS = ["EQ", "NEQ"]


def build_cases(tool):
    cases = []
    for l_bits, r_bits in WIDTH_PAIRS:
        stop = max_useful_cuts(l_bits, r_bits)
        if stop < 0:
            continue
        for op, impls in (("PLUS", PLUS_MINUS_IMPLS), ("MINUS", PLUS_MINUS_IMPLS)):
            for impl in impls:
                cases.append(dict(tool=tool, op=op, impl=impl, l_bits=l_bits, r_bits=r_bits,
                                   signed=False, stop=stop))
        if tool != "pyrtl":
            # INFERRED_MULT raw-vs-soft comparison only meaningful with a
            # real part (DSP inference); pyrtl's ASIC estimate can't model it.
            for impl in MULT_IMPLS:
                cases.append(dict(tool=tool, op="INFERRED_MULT", impl=impl, l_bits=l_bits, r_bits=r_bits,
                                   signed=False, stop=stop))
        else:
            for impl in [i for i in MULT_IMPLS if i != "raw_default"]:
                cases.append(dict(tool=tool, op="INFERRED_MULT", impl=impl, l_bits=l_bits, r_bits=r_bits,
                                   signed=False, stop=stop))
        for op in CMP_OPS:
            for impl in CMP_IMPLS:
                cases.append(dict(tool=tool, op=op, impl=impl, l_bits=l_bits, r_bits=r_bits,
                                   signed=False, stop=stop))
        for op in EQ_OPS:
            for impl in EQ_IMPLS:
                cases.append(dict(tool=tool, op=op, impl=impl, l_bits=l_bits, r_bits=r_bits,
                                   signed=False, stop=stop))
    return cases


def case_key(case):
    l_t = ("int" if case["signed"] else "uint") + str(case["l_bits"]) + "_t"
    r_t = ("int" if case["signed"] else "uint") + str(case["r_bits"]) + "_t"
    return (case["tool"], case["op"], case["impl"], l_t, r_t)


# ---------------------------------------------------------------------------
# Per-case Pypeline source generation
# ---------------------------------------------------------------------------

class SkipCase(Exception):
    pass


def gen_source(case):
    l_bits, r_bits, signed = case["l_bits"], case["r_bits"], case["signed"]
    op, impl, tool = case["op"], case["impl"], case["tool"]
    is_cmp = op in ("GT", "GTE", "LT", "LTE")
    is_eq = op in ("EQ", "NEQ")
    make_t = "make_int_t" if signed else "make_uint_t"

    lines = []
    lines.append('import sys')
    lines.append(f'sys.path.insert(0, {SRC_DIR!r})')
    lines.append(f'sys.path.insert(0, {INCLUDE_PYPELINE_DIR!r})')
    lines.append('from pypeline import (')
    lines.append('    hw_func, MAIN, PART, uint1_t,')
    lines.append('    make_uint_t, make_int_t,')
    lines.append('    any_integer_t, register_operator, INFERRED,')
    lines.append(')')
    if tool == "vivado":
        lines.append(f'PART({PART!r})')
    # tool == "pyrtl": no PART() call -> falls back to PyRTL estimates
    lines.append(f'l_t = {make_t}({l_bits})')
    lines.append(f'r_t = {make_t}({r_bits})')

    if is_cmp:
        out_t = "uint1_t"
        if impl == "soft_default":
            lines.append('from operators.soft_cmp import make_soft_sub_cmp')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_sub_cmp({op!r}))')
        elif impl == "soft_fixed":
            lines.append('from operators.soft_cmp import make_soft_sub_cmp_swapped')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_sub_cmp_swapped({op!r}))')
        elif impl == "soft_bitwise":
            lines.append('from operators.soft_cmp import make_soft_bitwise_cmp')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_bitwise_cmp({op!r}))')
        elif impl == "raw_revived_sliced":
            if tool != "vivado":
                raise SkipCase()  # env-gated raw override only wired for the real VHDL path
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, INFERRED)')
        else:
            raise ValueError(impl)
    elif is_eq:
        out_t = "uint1_t"
        negate = op == "NEQ"
        if impl == "raw_default":
            pass
        elif impl == "soft_default":
            lines.append('from operators.soft_misc import make_soft_eq')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_eq(negate={negate}))')
        else:
            raise ValueError(impl)
    else:
        out_t = "l_t"
        if impl == "raw_default":
            pass
        elif impl == "soft_ripple" and op == "PLUS":
            lines.append('from operators.soft_add import make_soft_ripple_add')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_ripple_add)')
        elif impl == "soft_carry_select" and op == "PLUS":
            lines.append('from operators.soft_add import make_soft_carry_select_add')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_carry_select_add)')
        elif impl == "soft_ripple" and op == "MINUS":
            lines.append('from operators.soft_add import make_soft_sub')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_sub)')
        elif impl == "soft_carry_select" and op == "MINUS":
            raise SkipCase()
        elif impl == "soft_shift_add" and op == "INFERRED_MULT":
            lines.append('from operators.soft_mult import make_soft_shift_add_mult')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_shift_add_mult)')
        elif impl == "soft_karatsuba" and op == "INFERRED_MULT":
            lines.append('from operators.soft_mult import make_soft_karatsuba_mult')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_karatsuba_mult)')
        else:
            raise SkipCase()

    py_op = {"PLUS": "+", "MINUS": "-", "INFERRED_MULT": "*",
              "GT": ">", "GTE": ">=", "LT": "<", "LTE": "<=",
              "EQ": "==", "NEQ": "!="}[op]

    lines.append('@hw_func')
    lines.append(f'def op_under_test(a: l_t, b: r_t) -> {out_t}:')
    lines.append(f'    return a {py_op} b')
    lines.append('@MAIN')
    lines.append(f'def bench_main(a: l_t, b: r_t) -> {out_t}:')
    lines.append('    return op_under_test(a, b)')
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Single-case runner: ONE pipelinec invocation, --coarse --sweep, parses
# every "Current: ... latency=N clks cuts=N slices" line it prints.
# ---------------------------------------------------------------------------

PIPELINEC = os.path.join(SRC_DIR, "pipelinec")

RESULT_LINE_RE = re.compile(
    r"Current:\s*([\d.]+)\s*\(MHz\)\(([\d.]+)\s*ns\)\s*latency=(\d+)\s*clks\s*cuts=(\d+)\s*slices"
)


def run_single_case(case):
    env = os.environ.copy()
    if case["impl"] == "raw_revived_sliced":
        env["PYPELINE_FORCE_RAW_INT_CMP"] = "1"

    work_dir = tempfile.mkdtemp(prefix="op_qor_bench_")
    src_path = os.path.join(work_dir, "case.py")
    try:
        source = gen_source(case)
    except SkipCase:
        return [{"n_cuts": None, "error": "skipped (no such impl/op/tool combination)"}]

    with open(src_path, "w") as f:
        f.write(source)

    out_dir = os.path.join(work_dir, "out")
    stop = case["stop"]

    # --sweep -> do_incremental_guesses=False -> literal clock-by-clock
    # increase from --start to --stop, one printed result line per clock,
    # all inside this single pipelinec invocation (no explicit mhz goal is
    # ever set on bench_main, so it never "meets timing" early and the sweep
    # runs the full requested range, or stops naturally if it can't slice
    # further -- both are real data, not harness bugs).
    cmd = [
        sys.executable, PIPELINEC, src_path,
        "--out_dir", out_dir, "--top", "bench_main",
        "--coarse", "--sweep", "--start", "0", "--stop", str(stop),
    ]
    # No timeout: real (or pyrtl) synthesis runs legitimately take a while.
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)

    stdout = proc.stdout
    matches = list(RESULT_LINE_RE.finditer(stdout))
    if not matches:
        tail = (stdout + "\n" + proc.stderr)[-2000:]
        return [{"n_cuts": None, "error": f"no result line found (rc={proc.returncode}): {tail}"}]

    results = []
    for match in matches:
        fmax_mhz = float(match.group(1))
        path_delay_ns = float(match.group(2))
        got_latency = int(match.group(3))
        got_cuts = int(match.group(4))
        row = {
            "n_cuts": got_cuts, "path_delay_ns": path_delay_ns, "fmax_mhz": fmax_mhz,
            "logic_levels": None, "slice_luts": None, "slice_registers": None,
            "carry4": None, "error": None,
        }
        if got_latency != got_cuts:
            row["error"] = f"latency={got_latency} != cuts={got_cuts}"

        if case["tool"] == "vivado":
            try:
                sys.path.insert(0, SRC_DIR)
                import VIVADO
                log_matches = glob.glob(os.path.join(out_dir, "bench_main", f"vivado_{got_cuts}CLK_*.log"))
                if log_matches:
                    log_text = open(log_matches[0]).read()
                    timing_report = VIVADO.ParsedTimingReport(log_text)
                    util_report = VIVADO.ParsedUtilizationReport(log_text)
                    if timing_report.path_reports:
                        row["logic_levels"] = list(timing_report.path_reports.values())[0].logic_levels
                    row["slice_luts"] = util_report.slice_luts
                    row["slice_registers"] = util_report.slice_registers
                    row["carry4"] = util_report.carry4
            except Exception:
                pass  # diagnostics only, never fail the row over these
        results.append(row)
    return results


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def load_done_keys(tool):
    done = set()
    path = csv_path(tool)
    if os.path.exists(path):
        with open(path) as f:
            for row in csv.DictReader(f):
                done.add((row["tool"], row["op"], row["impl"], row["l_type"], row["r_type"]))
    return done


def append_csv_rows(case, results):
    l_t = ("int" if case["signed"] else "uint") + str(case["l_bits"]) + "_t"
    r_t = ("int" if case["signed"] else "uint") + str(case["r_bits"]) + "_t"
    path = csv_path(case["tool"])
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            w.writeheader()
        for result in results:
            row = {"tool": case["tool"], "op": case["op"], "impl": case["impl"],
                   "l_type": l_t, "r_type": r_t}
            row.update(result)
            w.writerow(row)


def run_case_subprocess(case):
    proc = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--case", json.dumps(case)],
        capture_output=True, text=True,
    )
    results = None
    if proc.returncode == 0 and proc.stdout.strip():
        try:
            last_line = [l for l in proc.stdout.strip().splitlines() if l.startswith("[")][-1]
            results = json.loads(last_line)
        except Exception:
            results = None
    if results is None:
        results = [{"n_cuts": None, "path_delay_ns": None, "fmax_mhz": None, "logic_levels": None,
                     "slice_luts": None, "slice_registers": None, "carry4": None,
                     "error": f"subprocess failed rc={proc.returncode}: {proc.stderr[-2000:]}"}]
    return case, results


def main_driver(tool, jobs=1):
    cases = build_cases(tool)
    done = load_done_keys(tool)
    todo = [c for c in cases if case_key(c) not in done]
    print(f"[{tool}] {len(cases)} total cases, {len(done)} already done, {len(todo)} to run.", flush=True)

    completed = 0
    if jobs <= 1:
        for case in todo:
            _, results = run_case_subprocess(case)
            completed += 1
            append_csv_rows(case, results)
            n_ok = len([r for r in results if not r.get("error")])
            print(f"[{completed}/{len(todo)}] {case_key(case)} -> {n_ok}/{len(results)} cuts ok "
                  f"err={[r.get('error') for r in results if r.get('error')][:1]}", flush=True)
    else:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(run_case_subprocess, case): case for case in todo}
            for future in concurrent.futures.as_completed(futures):
                case, results = future.result()
                completed += 1
                append_csv_rows(case, results)
                n_ok = len([r for r in results if not r.get("error")])
                print(f"[{completed}/{len(todo)}] {case_key(case)} -> {n_ok}/{len(results)} cuts ok "
                      f"err={[r.get('error') for r in results if r.get('error')][:1]}", flush=True)

    print("Done. Results in", csv_path(tool))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default=None, help="JSON case dict; runs one sweep and prints JSON result list")
    parser.add_argument("--tool", choices=["pyrtl", "vivado"], default="pyrtl",
                         help="pyrtl = fast software timing estimate (no PART); vivado = real synthesis on xc7a200tffg1156-2")
    parser.add_argument("-j", "--jobs", type=int, default=1,
                         help="Run this many subprocesses concurrently")
    args = parser.parse_args()
    if args.case:
        case = json.loads(args.case)
        results = run_single_case(case)
        print(json.dumps(results))
    else:
        main_driver(tool=args.tool, jobs=args.jobs)
