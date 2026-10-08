#!/usr/bin/env python3
"""Synthesis result reuse (SYN.py; docs/SYN_DESIGN.md#6-caches).

In-process:
  - SYNTHESIS_INPUT_MANIFEST is path-independent, and any change to HDL bytes, a
    constraint file, the part, the tool installation, the recipe module or a
    run setting gives a new signature;
  - REUSE_SYNTHESIS_LOG reads a log only when its input record equals the run's
    identity, and moves a log without a record, or with another record, aside
    (with the reason) instead of reading it;
  - the shared store round-trips a result, ignores unreadable and foreign
    entries, replaces a damaged one on the next insert, and prunes entries
    unused for N days and half-written entries as old;
  - inside REUSE_ONLY (a lookup), a miss in the output directory and the
    store stops the backend instead of letting it run, a hit reads, and a
    run fails loudly.
Builds (PyRTL, seconds each):
  - stale-input regression: swapping a subtraction's operands keeps every
    entity and log name, and must re-synthesize in a reused --out_dir. Before
    the input records, the old log was read and the old design's timing used;
  - the final pipelined VHDL in a reused --out_dir follows the edit too.
    Before, an existing entity file from an earlier run was never rewritten;
  - two fresh output directories sharing --syn_cache: the second synthesizes
    nothing and ends with the same results;
  - stored measurements: after a --full_hier_syn build measured f and g, a
    default build uses those runs instead of estimating f and g, from the
    store in a fresh output directory, from the output directory alone, and
    under --no_hier_syn, without running synthesis; --no_stored_measurements
    estimates them as before;
  - a -D value only simulation code reads changes no HDL, so a build with
    another value reuses every result;
  - a --yosys_json netlist export always runs (yosys only), even in a fresh
    output directory whose store holds an identical earlier export: a store
    hit restores a log, never the netlist the run exists to write.

run_all registers two tests from this file, because every synthesis run in a
build_report_<tool> test must use that tool: syn_cache_test (--cases pyrtl,
build_report_pyrtl) and syn_cache_netlist_test (--cases netlist, the yosys
export, build_report_open_tools). A direct run does both.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(THIS_DIR, "..", "..", ".."))
sys.path.insert(0, SRC)
PYPELINEC = os.path.join(SRC, "pypelinec")

import SYN  # noqa: E402
import OPEN_TOOLS  # noqa: E402  (after SYN: importing it first is a cycle)

SUB_DESIGN = """
from pypeline import MAIN, uint16_t

@MAIN(30.0)
def top(x: uint16_t, y: uint16_t) -> uint16_t:
    return {expr}
"""

# An unreachable goal on purpose: the sweep places one cut after the
# multiplier (the slowest part, an unsliceable primitive here) and stops
PIPELINED_DESIGN = """
from pypeline import MAIN, uint16_t

@MAIN(150.0)
def top(x: uint16_t, y: uint16_t) -> uint16_t:
    return {expr}
"""

# f and g are hierarchical and fully combinational: estimated from their
# submodules in the default and --no_hier_syn modes, synthesized by
# --full_hier_syn
HIER_DESIGN = """
from pypeline import MAIN, hw_func, uint16_t

@hw_func
def g(a: uint16_t, b: uint16_t) -> uint16_t:
    return (a + b) ^ (a - b)

@hw_func
def f(a: uint16_t, b: uint16_t) -> uint16_t:
    return g(a, b) + g(b, a)

@MAIN(50.0)
def top(a: uint16_t, b: uint16_t) -> uint16_t:
    return f(a, b) + b
"""

SIM_PARAM_DESIGN = """
from pypeline import MAIN, param, sim_output, sim_print, uint16_t

LABEL = param("LABEL", "a")

@sim_output
def show(v: uint16_t):
    sim_print(f"{{LABEL}}: {{int(v)}}")

@MAIN(30.0)
def top(x: uint16_t, y: uint16_t) -> uint16_t:
    r: uint16_t = x - y
    show(r)
    return r
"""


def _write(path, text):
    with open(path, "w") as f:
        f.write(text)
    return path


def _expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _makedirs(path):
    os.makedirs(path)
    return path


# ─────────────────────────────── in-process ───────────────────────────────


def test_manifest_identity(tmp):
    a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
    for d in (a, b):
        os.makedirs(d)
        _write(os.path.join(d, "top.vhd"), "entity top is end;\n")
        _write(os.path.join(d, "clk.sdc"), "create_clock -period 10\n")
    tool = _write(os.path.join(tmp, "tool"), "v1")

    def manifest(d, part="p", extra=None, tool_path=tool, recipe=(SYN,)):
        return SYN.SYNTHESIS_INPUT_MANIFEST(
            "t", part, "top", os.path.join(d, "top.vhd") + " ",
            [os.path.join(d, "clk.sdc")], tool_paths=[tool_path],
            recipe_modules=recipe, extra=extra,
        )

    base = manifest(a)
    _expect(manifest(b) == base, "the output directory's path must not change the identity")
    _write(os.path.join(b, "top.vhd"), "entity top is end; -- edited\n")
    _expect(manifest(b)["signature"] != base["signature"], "HDL bytes")
    _write(os.path.join(b, "top.vhd"), "entity top is end;\n")
    _write(os.path.join(b, "clk.sdc"), "create_clock -period 5\n")
    _expect(manifest(b)["signature"] != base["signature"], "constraint bytes")
    _expect(manifest(a, part="q")["signature"] != base["signature"], "part")
    _expect(manifest(a, extra={"seed": 2})["signature"] != base["signature"], "run setting")
    _expect(manifest(a, recipe=(SYN, OPEN_TOOLS))["signature"] != base["signature"], "recipe module")
    time.sleep(0.01)
    _write(tool, "v2 reinstalled")
    _expect(manifest(a)["signature"] != base["signature"], "tool installation")
    missing = SYN.SYNTHESIS_INPUT_MANIFEST("t", "p", "top", os.path.join(a, "gone.vhd"))
    _expect(missing["hdl"] == [["gone.vhd", None]], "a missing input is recorded, not raised")


def test_reuse_log(tmp):
    d = os.path.join(tmp, "reuse")
    os.makedirs(d)
    hdl = _write(os.path.join(d, "top.vhd"), "entity top is end;\n")
    manifest = SYN.SYNTHESIS_INPUT_MANIFEST("t", "p", "top", hdl)
    log = os.path.join(d, "t.log")
    _expect(SYN.REUSE_SYNTHESIS_LOG("t", log, manifest) is None, "no log: run")
    _write(log, "report A")
    SYN.RECORD_SYNTHESIS_LOG("t", log, manifest)
    _expect(SYN.REUSE_SYNTHESIS_LOG("t", log, manifest) == "report A", "matching record: reuse")

    other = dict(manifest, hdl=[["top.vhd", "0" * 64]])
    _expect(SYN.REUSE_SYNTHESIS_LOG("t", log, other) is None, "different inputs: run")
    _expect(not os.path.exists(log) and os.path.exists(log + ".stale"), "moved aside, not deleted")
    _expect(os.path.exists(SYN.SYNTHESIS_INPUT_RECORD_PATH(log) + ".stale"), "its record moved too")

    _write(log, "report from an older compiler")
    _expect(SYN.REUSE_SYNTHESIS_LOG("t", log, manifest) is None, "no record: run")
    _expect(os.path.exists(log + ".stale2"), "a second stale copy gets its own name")

    _write(log, "report B")
    SYN.RECORD_SYNTHESIS_LOG("t", log, manifest)
    _expect(SYN.REUSE_SYNTHESIS_LOG("t", log, manifest, use_existing_log_file=False) is None,
            "a requested fresh run never reads")
    _expect(os.path.exists(log + ".stale3"), "and keeps the old log aside")


def test_store(tmp):
    store = os.path.join(tmp, "store")
    d1, d2 = os.path.join(tmp, "o1"), os.path.join(tmp, "o2")
    for d in (d1, d2):
        os.makedirs(d)
        _write(os.path.join(d, "top.vhd"), "entity top is end;\n")
    m1 = SYN.SYNTHESIS_INPUT_MANIFEST("t", "p", "top", os.path.join(d1, "top.vhd"))
    m2 = SYN.SYNTHESIS_INPUT_MANIFEST("t", "p", "top", os.path.join(d2, "top.vhd"))
    _expect(m1 == m2, "same inputs, other directory")
    old = SYN.SYNTHESIS_STORE_DIR
    SYN.SYNTHESIS_STORE_DIR = store
    try:
        log1 = _write(os.path.join(d1, "t.log"), "stored report")
        SYN.RECORD_SYNTHESIS_LOG("t", log1, m1)
        log2 = os.path.join(d2, "t_other_name.log")
        _expect(SYN.REUSE_SYNTHESIS_LOG("t", log2, m2) == "stored report", "store hit under this run's name")
        _expect(json.load(open(SYN.SYNTHESIS_INPUT_RECORD_PATH(log2))) == m2, "the hit is recorded locally")

        entry = SYN._synthesis_store_entry_dir("t", m1["signature"])
        _write(os.path.join(entry, "manifest.json"), "{not json")
        os.remove(log2)
        _expect(SYN.REUSE_SYNTHESIS_LOG("t", log2, m2) is None, "unreadable entry: miss")
        _write(log2, "fresh report")
        SYN.RECORD_SYNTHESIS_LOG("t", log2, m2)
        _expect(json.load(open(os.path.join(entry, "manifest.json"))) == m2, "damaged entry replaced")

        foreign = dict(m1, part="other")
        _expect(not SYN.SYNTHESIS_STORE_FETCH("t", m1["signature"], {"log": log2}, foreign),
                "an entry recording other inputs is never used")

        stamp = time.time() - 10 * 86400
        os.utime(os.path.join(entry, "manifest.json"), (stamp, stamp))
        # An insert interrupted before its rename: no manifest, never a hit
        abandoned = f"{SYN._synthesis_store_entry_dir('t', 'ab' * 32)}.tmp.1.2.3"
        _write(os.path.join(_makedirs(abandoned), "log"), "partial")
        os.utime(abandoned, (stamp, stamp))
        _expect(SYN.SYNTHESIS_STORE_PRUNE(5) == 1 and not os.path.exists(entry), "prune old entries")
        _expect(not os.path.exists(abandoned), "prune half-written entries as old")
    finally:
        SYN.SYNTHESIS_STORE_DIR = old


def test_reuse_only(tmp):
    d = os.path.join(tmp, "lookup")
    os.makedirs(d)
    hdl = _write(os.path.join(d, "top.vhd"), "entity top is end;\n")
    manifest = SYN.SYNTHESIS_INPUT_MANIFEST("t", "p", "top", hdl)
    log = os.path.join(d, "t.log")
    store = os.path.join(tmp, "lookup_store")
    old = SYN.SYNTHESIS_STORE_DIR
    try:
        for store_dir in (None, store):
            SYN.SYNTHESIS_STORE_DIR = store_dir
            try:
                with SYN.REUSE_ONLY():
                    SYN.REUSE_SYNTHESIS_LOG("t", log, manifest)
                raise AssertionError("a lookup miss must stop the backend, not let it run")
            except SYN.SynthesisNotStored:
                pass
        _expect(SYN.REUSE_SYNTHESIS_LOG("t", log, manifest) is None, "outside a lookup a miss runs")
        _write(log, "report")
        SYN.RECORD_SYNTHESIS_LOG("t", log, manifest)
        with SYN.REUSE_ONLY():
            _expect(SYN.REUSE_SYNTHESIS_LOG("t", log, manifest) == "report", "a lookup hit reads")
        os.remove(log)
        with SYN.REUSE_ONLY():
            _expect(SYN.REUSE_SYNTHESIS_LOG("t", log, manifest) == "report", "a lookup hit from the store")
        try:
            with SYN.REUSE_ONLY():
                SYN.COUNT_SYNTHESIS_RESULT("run")
            raise AssertionError("a run during a lookup must fail loudly")
        except SYN.SynthesisRanDuringLookup:
            pass
    finally:
        SYN.SYNTHESIS_STORE_DIR = old


# ─────────────────────────────── builds ───────────────────────────────


def run(args, cwd):
    cmd = [sys.executable, PYPELINEC] + args + ["--syn_tool", "pyrtl"]
    env = dict(os.environ, PYTHONHASHSEED="0", PIPELINEC_INTERNAL_SKIP_PIPELINE_MAP_PNG="1")
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    print(result.stdout[-3000:], flush=True)
    return result.returncode, result.stdout


def results_line(log):
    m = re.search(r"^Synthesis results: (\d+) reused from the output directory, "
                  r"(?:(\d+) from the store [^,]*, )?(\d+) new run\(s\)", log, re.M)
    _expect(m is not None, "no synthesis results line")
    return int(m.group(1)), int(m.group(2) or 0), int(m.group(3))


def test_stale_inputs_rebuild(out):
    design = os.path.join(out, "swap.py")
    _write(design, SUB_DESIGN.format(expr="x - y"))
    rc, log1 = run([design, "--out_dir", "o"], out)
    _expect(rc == 0, "first build")
    names1 = sorted(re.findall(r"^Running: (\S+)$", log1, re.M))
    _write(design, SUB_DESIGN.format(expr="y - x"))  # same names, other hardware
    rc, log2 = run([design, "--out_dir", "o"], out)
    _expect(rc == 0, "rebuild")
    names2 = sorted(re.findall(r"^Running: (\S+)$", log2, re.M))
    _expect(names2 == names1 and names1, f"the edit keeps every log name: {names1} {names2}")
    _expect("Reading log" not in log2, "a stale log was read")
    _expect(len(re.findall(r"^Not reusing .*its inputs differ: HDL", log2, re.M)) == len(names1),
            "each stale log is named with the changed input")
    _expect(results_line(log2) == (0, 0, len(names1)), "everything re-synthesized")


def test_final_vhdl_follows_edit(out):
    design = os.path.join(out, "pipelined.py")
    _write(design, PIPELINED_DESIGN.format(expr="x * y + 3"))
    run([design, "--out_dir", "p"], out)
    final_list = os.path.join(out, "p", "vhdl_files.txt")
    entity_files = [p for p in open(final_list).read().split() if "top_" in os.path.basename(p) and "CLK" in p]
    _expect(any(re.search(r"_[1-9]\d*CLK_", p) for p in entity_files),
            f"fixture no longer pipelines: {entity_files}")
    before = {p: open(p).read() for p in entity_files}
    _write(design, PIPELINED_DESIGN.format(expr="y * x + 3"))  # same names, other wiring
    run([design, "--out_dir", "p"], out)
    entity_files2 = [p for p in open(final_list).read().split() if "top_" in os.path.basename(p) and "CLK" in p]
    same_names = sorted(set(entity_files) & set(entity_files2))
    _expect(same_names, f"the edit keeps the pipelined entity names: {entity_files} {entity_files2}")
    changed = [p for p in same_names if open(p).read() != before[p]]
    _expect(changed, "a same-named pipelined entity kept the earlier run's VHDL")


def test_shared_store(out):
    design = os.path.join(out, "shared.py")
    _write(design, SUB_DESIGN.format(expr="x - y"))
    rc1, log1 = run([design, "--out_dir", "s1", "--syn_cache", "store"], out)
    rc2, log2 = run([design, "--out_dir", "s2", "--syn_cache", "store"], out)
    _expect(rc1 == rc2 == 0, "builds")
    reused, stored, ran = results_line(log2)
    _expect(ran == 0 and stored >= 1 and stored == results_line(log1)[2], "second build synthesized nothing")
    h1 = json.load(open(os.path.join(out, "s1", "top", "sweep_history.json")))
    h2 = json.load(open(os.path.join(out, "s2", "top", "sweep_history.json")))
    _expect(h1["mains"]["top"]["final"] == h2["mains"]["top"]["final"], "same results from the store")


def path_delays(log):
    return dict(re.findall(r"^(\w+) Path delay \(maybe to be pipelined\): ([\d.]+) ns$", log, re.M))


def test_stored_measurements(out):
    design = _write(os.path.join(out, "hier.py"), HIER_DESIGN)
    rc, full = run([design, "--out_dir", "m1", "--syn_cache", "mstore", "--full_hier_syn"], out)
    _expect(rc == 0, "--full_hier_syn build")
    measured = path_delays(full)
    _expect({"f", "g"} <= set(measured), f"--full_hier_syn did not measure f and g: {measured}")
    for case, args in (
        ("the store, in a fresh output directory", ["--out_dir", "m2", "--syn_cache", "mstore"]),
        ("the output directory, without a store", ["--out_dir", "m1"]),
        ("--no_hier_syn", ["--out_dir", "m3", "--syn_cache", "mstore", "--no_hier_syn"]),
    ):
        rc, log = run([design] + args, out)
        _expect(rc == 0, f"{case}: build")
        _expect(not re.search(r"^Function: [fg] estimated path delay", log, re.M),
                f"{case}: f or g was estimated although an earlier run measured it")
        stored = set(re.findall(r"^Function: (\w+) stored path delay", log, re.M))
        _expect({"f", "g"} <= stored, f"{case}: stored path delays {stored}")
        delays = path_delays(log)
        _expect(all(delays.get(n) == measured[n] for n in ("f", "g")),
                f"{case}: {delays} differ from the measured {measured}")
        _expect(results_line(log)[2] == 0, f"{case}: a lookup ran synthesis")
    rc, log = run([design, "--out_dir", "m4", "--syn_cache", "mstore", "--no_stored_measurements"], out)
    _expect(rc == 0, "--no_stored_measurements build")
    estimated = set(re.findall(r"^Function: (\w+) estimated path delay", log, re.M))
    _expect(estimated == {"f", "g"}, f"--no_stored_measurements estimated {estimated}, not f and g")


def test_sim_only_param_reuses(out):
    design = os.path.join(out, "simparam.py")
    _write(design, SIM_PARAM_DESIGN)
    rc1, log1 = run([design, "--out_dir", "q1", "--syn_cache", "qstore", "-D", "LABEL=first"], out)
    rc2, log2 = run([design, "--out_dir", "q2", "--syn_cache", "qstore", "-D", "LABEL=second"], out)
    _expect(rc1 == rc2 == 0, "builds")
    _expect(results_line(log2)[2] == 0, "a simulation-only parameter changed the synthesis inputs")


def test_yosys_json_never_cached(out):
    design = os.path.join(out, "netlist.py")
    _write(design, SUB_DESIGN.format(expr="x - y"))
    for out_dir in ("j1", "j2"):
        rc, log = run([design, "--out_dir", out_dir, "--syn_cache", "jstore", "--yosys_json"], out)
        _expect(rc == 0, f"--yosys_json build in {out_dir}")
        m = re.search(r"^Stopping after json output in: (\S+)", log, re.M)
        _expect(m is not None, f"{out_dir}: the netlist run was skipped")
        netlists = [p for p in glob.glob(os.path.join(m.group(1), "*.json"))
                    if '"modules"' in open(p).read()]
        _expect(netlists, f"{out_dir}: no yosys netlist in {m.group(1)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    parser.add_argument("--cases", choices=("all", "pyrtl", "netlist"), default="all",
                        help="pyrtl: in-process cases and PyRTL builds; netlist: the "
                        "--yosys_json export (a yosys run); all: both")
    args = parser.parse_args()
    out = args.out_dir or tempfile.mkdtemp(prefix="syn_cache_test_")
    os.makedirs(out, exist_ok=True)
    if args.cases in ("all", "pyrtl"):
        unit = os.path.join(out, "unit")
        shutil.rmtree(unit, ignore_errors=True)
        os.makedirs(unit)
        test_manifest_identity(unit)
        test_reuse_log(unit)
        test_store(unit)
        test_reuse_only(unit)
        print("In-process synthesis cache tests passed.", flush=True)
        test_stale_inputs_rebuild(out)
        test_final_vhdl_follows_edit(out)
        test_shared_store(out)
        test_stored_measurements(out)
        test_sim_only_param_reuses(out)
    if args.cases in ("all", "netlist"):
        test_yosys_json_never_cached(out)
    print(f"Synthesis cache tests passed ({args.cases} cases).")


if __name__ == "__main__":
    main()
