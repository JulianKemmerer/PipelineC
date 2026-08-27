#!/usr/bin/env python3
# Build-report regression test for the sky130 area estimate/measurement
# reporting (SYN.WRITE_AREA_ESTIMATE_FILE / SYN.PRINT_MEASURED_AREA_IF_AVAILABLE):
#  - mode 1 (--no_hier_syn --no_sweep, latchup.app's own usage): every leaf
#    is area-cached or measured on the spot, the build prints one
#    "Estimated area: ..." line, and a parseable _area.json sidecar with a
#    schema real tooling can consume is written next to _registers.log.
#  - mode 2 (normal use, a real confirmation/sweep synthesis runs): the
#    build additionally prints one "Measured area: ..." line taken from the
#    exact mapped netlist that synthesis run, produced free by the same
#    DEVICE_MODELS._run_synth_and_sta call that already measures delay.
# Uses an isolated PYPELINEC_AREA_CACHE_DIR so this test never depends on,
# or writes into, the real committed area_cache/.
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
MODE1_DESIGN = os.path.join(THIS_DIR, "leaf_1ll_cap_design.py")
MODE2_DESIGN = os.path.join(THIS_DIR, "split_model_design.py")


def _run(design, extra_args, out_dir, area_cache_dir):
    cmd = [
        sys.executable,
        PYPELINEC,
        design,
        "--syn_tool",
        "sky130",
        "--out_dir",
        out_dir,
    ] + extra_args
    env = dict(os.environ)
    env["PYPELINEC_AREA_CACHE_DIR"] = area_cache_dir
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    print(result.stdout)
    return result


def main():
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    base_out_dir = args.out_dir
    cleanup = False
    if base_out_dir is None:
        base_out_dir = tempfile.mkdtemp(prefix="area_estimate_build_report_test_")
        cleanup = True
    area_cache_dir = os.path.join(base_out_dir, "area_cache")

    # ---- Mode 1: --no_hier_syn --no_sweep ----
    mode1_out = os.path.join(base_out_dir, "mode1")
    os.makedirs(mode1_out, exist_ok=True)
    result = _run(
        MODE1_DESIGN,
        ["--no_hier_syn", "--no_sweep"],
        mode1_out,
        area_cache_dir,
    )
    if result.returncode != 0:
        print("FAIL: mode-1 (--no_hier_syn --no_sweep) build did not succeed")
        sys.exit(1)
    out = result.stdout

    m = re.search(
        r"Estimated area: ([\d.]+) um2 \(comb ([\d.]+) \+ regs ([\d.]+), (\d+) FFs\)",
        out,
    )
    if not m:
        print("FAIL: no 'Estimated area: ...' report line found")
        sys.exit(1)
    total, comb, regs, ffs = (float(m.group(1)), float(m.group(2)), float(m.group(3)), int(m.group(4)))
    if abs(total - (comb + regs)) > 0.5:
        print(f"FAIL: printed total {total} != comb {comb} + regs {regs}")
        sys.exit(1)
    if total <= 0.0:
        print(f"FAIL: printed total area is not positive: {total}")
        sys.exit(1)

    area_json_paths = glob.glob(
        os.path.join(mode1_out, "top", "*_area.json")
    )
    if not area_json_paths:
        print("FAIL: no *_area.json sidecar written under top/")
        sys.exit(1)
    with open(area_json_paths[0]) as f:
        sidecar = json.load(f)
    for key in (
        "schema_version",
        "total_area",
        "combinational_area",
        "sequential_area",
        "n_ffs",
        "area_unit",
        "missing_leaf_area_funcs",
    ):
        if key not in sidecar:
            print(f"FAIL: _area.json sidecar missing key {key!r}: {sidecar}")
            sys.exit(1)
    if sidecar["area_unit"] != "um2":
        print(f"FAIL: unexpected area_unit {sidecar['area_unit']!r}")
        sys.exit(1)
    if sidecar["missing_leaf_area_funcs"]:
        print(
            "FAIL: mode-1 build left leaf areas uncached after its own forced "
            f"remeasure pass: {sidecar['missing_leaf_area_funcs']}"
        )
        sys.exit(1)

    # A second run against the now-warm area_cache must report the SAME
    # total without re-synthesizing any leaf (cache actually got used).
    result2 = _run(
        MODE1_DESIGN,
        ["--no_hier_syn", "--no_sweep"],
        os.path.join(base_out_dir, "mode1_rerun"),
        area_cache_dir,
    )
    if result2.returncode != 0:
        print("FAIL: mode-1 rerun build did not succeed")
        sys.exit(1)
    if "Synthesizing function" in result2.stdout:
        print(
            "FAIL: mode-1 rerun re-synthesized a leaf despite a warm "
            "area_cache + path_delay_cache"
        )
        sys.exit(1)
    m2 = re.search(r"Estimated area: ([\d.]+) um2", result2.stdout)
    if not m2 or abs(float(m2.group(1)) - total) > 0.5:
        print(
            f"FAIL: rerun estimated area {m2.group(1) if m2 else None} "
            f"!= first run's {total}"
        )
        sys.exit(1)

    # ---- Mode 2: normal use, a real confirmation/sweep synthesis runs ----
    mode2_out = os.path.join(base_out_dir, "mode2")
    os.makedirs(mode2_out, exist_ok=True)
    result3 = _run(MODE2_DESIGN, [], mode2_out, area_cache_dir)
    if result3.returncode != 0:
        print("FAIL: mode-2 (real sweep) build did not succeed")
        sys.exit(1)
    out3 = result3.stdout
    if "Estimated area:" not in out3:
        print("FAIL: mode-2 build has no 'Estimated area: ...' line")
        sys.exit(1)
    m3 = re.search(r"Measured area: ([\d.]+) um2", out3)
    if not m3:
        print("FAIL: mode-2 build (real synthesis ran) has no 'Measured area: ...' line")
        sys.exit(1)
    if float(m3.group(1)) <= 0.0:
        print(f"FAIL: measured area is not positive: {m3.group(1)}")
        sys.exit(1)

    if cleanup:
        import shutil

        shutil.rmtree(base_out_dir, ignore_errors=True)

    print("PASS")


if __name__ == "__main__":
    main()
