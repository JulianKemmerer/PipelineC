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
    # est_top_ns / est_op_ns: what ESTIMATE_HIER_PATH_DELAYS predicted for the
    # whole bench_main and for the operator entity itself, BEFORE any slicing.
    # These are what the slicer places cuts from, so est vs measured is the
    # estimation error that decides whether cuts land where the delay actually
    # is. A soft (hierarchical) implementation is a topological SUM of leaf
    # delays with no cross-module optimization, so it can over-predict badly
    # where a single raw leaf had one measured number -- which shows up here as
    # est_top_ns >> path_delay_ns at n_cuts=0.
    "est_top_ns", "est_op_ns",
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
CMP_IMPLS = [
    "soft_cmp_sub", "soft_cmp_sub_swapped", "soft_cmp_bitwise",
    "soft_cmp_borrow", "soft_cmp_prefix", "raw_revived_sliced",
]
CMP_OPS = ["GT", "GTE", "LT", "LTE"]
EQ_IMPLS = ["raw_default", "soft_default"]
EQ_OPS = ["EQ", "NEQ"]

MIN_KARATSUBA_THRESHOLD = 3  # below this the recursion does not terminate (mid == parent width)


def karatsuba_threshold_reps(n_bits):
    """One representative threshold per DISTINCT Karatsuba structure for a same-width
    n_bits x n_bits multiply. Thresholds between shape changes build byte-identical
    hardware (verified via CANONICAL_CALLABLE_KEY), so sweeping every integer would
    re-measure the same design 2-15x over. T == n_bits is included deliberately: it IS
    make_soft_mult_shift_add, so its measurement doubles as a sanity control that must
    match the soft_shift_add rows exactly."""
    sys.path.insert(0, SRC_DIR)
    sys.path.insert(0, INCLUDE_PYPELINE_DIR)
    from pypeline import make_uint_t
    from operators.soft_mult import make_soft_mult_karatsuba
    from PY_TO_LOGIC import CANONICAL_CALLABLE_KEY

    t = make_uint_t(n_bits)
    reps, seen = [], set()
    for T in range(MIN_KARATSUBA_THRESHOLD, n_bits + 1):
        key = CANONICAL_CALLABLE_KEY(make_soft_mult_karatsuba(t, t, threshold=T))
        if key not in seen:
            seen.add(key)
            reps.append(T)
    return reps


def build_cases(tool):
    cases = []
    for l_bits, r_bits in WIDTH_PAIRS:
        stop = max_useful_cuts(l_bits, r_bits)
        if stop < 0:
            continue
        # MINUS has no distinct soft implementation: make_soft_sub computes
        # a + ~b + 1 using whatever PLUS is currently registered (inferred,
        # by default) -- same netlist as raw_default MINUS, confirmed
        # identical in measured data (see docs/SYN_DESIGN.md). Only
        # raw_default is a real, distinct measurement for MINUS.
        for op, impls in (("PLUS", PLUS_MINUS_IMPLS), ("MINUS", ["raw_default"])):
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
        # Karatsuba base-case threshold sweep -- same-width pairs only.
        # Asymmetric Karatsuba (e.g. uint32 x uint3) is structurally degenerate: it
        # still splits BOTH operands at n_bits//2, so the entire high half of the
        # narrow operand is constant zero and it does three sub-multiplies to
        # compute what shift-and-add does in one. Not worth sweeping.
        if l_bits == r_bits:
            reps = karatsuba_threshold_reps(l_bits)
            if l_bits >= 64:
                # Thresholds 3-6 instantiate 109-333 base multipliers each at this
                # width -- elaboration alone is minutes and they are certain losers
                # (see docs/SYN_DESIGN.md). Skip them; add back only if uint32's
                # low-T rows turn out NOT monotonically bad.
                reps = [T for T in reps if T >= 8]
            for T in reps:
                cases.append(dict(tool=tool, op="INFERRED_MULT", impl=f"soft_karatsuba_t{T}",
                                   l_bits=l_bits, r_bits=r_bits, signed=False, stop=stop))
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
    lines.append('    make_uint_t, make_int_t, arith_result_type,')
    lines.append('    any_integer_t, register_operator, INFERRED,')
    lines.append(')')
    if tool == "vivado":
        lines.append(f'PART({PART!r})')
    # tool == "pyrtl": no PART() call -> falls back to PyRTL estimates
    lines.append(f'l_t = {make_t}({l_bits})')
    lines.append(f'r_t = {make_t}({r_bits})')

    if is_cmp:
        out_t = "uint1_t"
        if impl == "soft_cmp_sub":
            lines.append('from operators.soft_cmp import make_soft_cmp_sub')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_cmp_sub({op!r}))')
        elif impl == "soft_cmp_sub_swapped":
            lines.append('from operators.soft_cmp import make_soft_cmp_sub_swapped')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_cmp_sub_swapped({op!r}))')
        elif impl == "soft_cmp_bitwise":
            lines.append('from operators.soft_cmp import make_soft_cmp_bitwise')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_cmp_bitwise({op!r}))')
        elif impl == "soft_cmp_borrow":
            lines.append('from operators.soft_cmp import make_soft_cmp_borrow')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_cmp_borrow({op!r}))')
        elif impl == "soft_cmp_prefix":
            lines.append('from operators.soft_cmp import make_soft_cmp_prefix')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_cmp_prefix({op!r}))')
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
        # Full-precision result width, exactly what arith_result_type gives the
        # real inferred path. Declaring l_t here instead would TRUNCATE and let
        # synthesis prune the discarded high bits -- fatal for INFERRED_MULT
        # (uint32*uint32 -> uint64: half the product, and a totally different
        # DSP inference decision) and it drops PLUS's carry-out bit.
        lines.append(f'_el, _er, out_t = arith_result_type({op!r}, l_t, r_t)')
        out_t = "out_t"
        if impl == "raw_default":
            pass
        elif impl == "soft_ripple" and op == "PLUS":
            lines.append('from operators.soft_add import make_soft_add_ripple')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_add_ripple)')
        elif impl == "soft_carry_select" and op == "PLUS":
            lines.append('from operators.soft_add import make_soft_add_carry_select')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_add_carry_select)')
        elif impl == "soft_ripple" and op == "MINUS":
            lines.append('from operators.soft_add import make_soft_sub')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_sub)')
        elif impl == "soft_carry_select" and op == "MINUS":
            raise SkipCase()
        elif impl == "soft_shift_add" and op == "INFERRED_MULT":
            lines.append('from operators.soft_mult import make_soft_mult_shift_add')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_mult_shift_add)')
        elif impl == "soft_karatsuba" and op == "INFERRED_MULT":
            lines.append('from operators.soft_mult import make_soft_mult_karatsuba')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, make_soft_mult_karatsuba)')
        elif re.fullmatch(r"soft_karatsuba_t\d+", impl) and op == "INFERRED_MULT":
            # NOTE: registers for any_integer_t like soft_karatsuba above, bypassing
            # register_soft_mult's deliberate unsigned-only restriction (soft
            # multipliers are wrong for signed operands -- see soft.py). Harmless
            # here because build_cases hardcodes signed=False for every case, but a
            # trap if a signed case is ever added to this harness.
            threshold = int(impl[len("soft_karatsuba_t"):])
            # Named module-level factory, not a lambda: _callable_canonical_name
            # (PY_TO_LOGIC.py) drops lambdas into an opaque hash-fallback name,
            # which would make the emitted entity ungreppable and indistinguishable
            # from any other threshold's in the build log.
            lines.append('from operators.soft_mult import make_soft_mult_karatsuba')
            lines.append(f'def _kar_factory_t{threshold}(l, r):')
            lines.append(f'    return make_soft_mult_karatsuba(l, r, threshold={threshold})')
            lines.append(f'register_operator({op!r}, any_integer_t, any_integer_t, _kar_factory_t{threshold})')
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

# "Function: <name> estimated path delay: 13.600 ns (derived from submodules)"
# Printed once per function before the sweep starts -- the numbers the cut
# placer actually works from.
ESTIMATE_LINE_RE = re.compile(
    r"Function:\s*(\S+)\s+estimated path delay:\s*([\d.]+)\s*ns"
)


def run_single_case(case):
    env = os.environ.copy()
    if case["impl"] == "raw_revived_sliced":
        env["PYPELINE_FORCE_RAW_INT_CMP"] = "1"

    work_dir = tempfile.mkdtemp(prefix="op_qor_bench_")
    # NOTE: this shares the repo's path_delay_cache/ with normal builds, so a
    # run does add entries there. They are real measurements of real entities,
    # so that is harmless for the implementations reachable by default. The one
    # case to keep in mind is raw_revived_sliced: FORCE_RAW_INT_CMP_FOR_QOR_BENCH
    # emits a raw comparator under the same canonical BIN_OP_GT_*/BIN_OP_GTE_*
    # name a soft build would use. Nothing reads those today (compares are soft
    # by default, so a build never asks for a BIN_OP_GT_* delay), and if compares
    # were ever flipped back to raw the cached value would be a measurement of
    # exactly that raw implementation anyway. Delete the cache dir if a run's
    # slice placement ever needs to start from a known-empty state.
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
    # --stop is EXCLUSIVE: SYN.py stops once coarse_latency >= stop_at_latency,
    # so `--stop N` measures cut counts 0..N-1. Pass stop+1 to actually measure
    # the intended top cut count -- which is the most decision-relevant point.
    cmd = [
        sys.executable, PIPELINEC, src_path,
        "--out_dir", out_dir, "--top", "bench_main",
        "--coarse", "--sweep", "--start", "0", "--stop", str(stop + 1),
    ]
    # No timeout: real (or pyrtl) synthesis runs legitimately take a while.
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)

    stdout = proc.stdout
    matches = list(RESULT_LINE_RE.finditer(stdout))
    if not matches:
        tail = (stdout + "\n" + proc.stderr)[-2000:]
        return [{"n_cuts": None, "error": f"no result line found (rc={proc.returncode}): {tail}"}]

    # Pre-slicing estimates the cut placer works from. bench_main is the whole
    # design; the operator entity is whichever other function carries the op
    # (op_under_test for an inferred/raw impl, the soft factory's hw_func name
    # for a soft one) -- take the largest non-bench_main estimate, which is the
    # operator itself since nothing else in this design has depth.
    est_top_ns = None
    est_op_ns = None
    for e_match in ESTIMATE_LINE_RE.finditer(stdout):
        e_name, e_val = e_match.group(1), float(e_match.group(2))
        if e_name.endswith("bench_main") or e_name == "op_under_test":
            est_top_ns = e_val
        elif est_op_ns is None or e_val > est_op_ns:
            est_op_ns = e_val

    results = []
    for match in matches:
        fmax_mhz = float(match.group(1))
        path_delay_ns = float(match.group(2))
        got_latency = int(match.group(3))
        got_cuts = int(match.group(4))
        row = {
            "n_cuts": got_cuts, "path_delay_ns": path_delay_ns, "fmax_mhz": fmax_mhz,
            "logic_levels": None, "est_top_ns": est_top_ns, "est_op_ns": est_op_ns,
            "slice_luts": None, "slice_registers": None,
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


def main_driver(tool, jobs=1, ops=None, widths=None, impls=None):
    cases = build_cases(tool)
    if ops:
        op_set = set(ops)
        cases = [c for c in cases if c["op"] in op_set]
    if widths:
        cases = [c for c in cases if (c["l_bits"], c["r_bits"]) in widths]
    if impls:
        impl_set = set(impls)
        cases = [c for c in cases if c["impl"] in impl_set]
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
    parser.add_argument("--ops", default=None,
                         help="Comma-separated op filter, e.g. PLUS,MINUS (default: all)")
    parser.add_argument("--widths", default=None,
                         help="Comma-separated l:r width-pair filter, e.g. 32:32 (default: all)")
    parser.add_argument("--impls", default=None,
                         help="Comma-separated impl filter, e.g. soft_cmp_sub_swapped,soft_cmp_prefix (default: all)")
    parser.add_argument("-j", "--jobs", type=int, default=1,
                         help="Run this many subprocesses concurrently")
    args = parser.parse_args()
    if args.case:
        case = json.loads(args.case)
        results = run_single_case(case)
        print(json.dumps(results))
    else:
        ops = args.ops.split(",") if args.ops else None
        widths = None
        if args.widths:
            widths = set()
            for pair in args.widths.split(","):
                l_s, r_s = pair.split(":")
                widths.add((int(l_s), int(r_s)))
        impls = args.impls.split(",") if args.impls else None
        main_driver(tool=args.tool, jobs=args.jobs, ops=ops, widths=widths, impls=impls)
