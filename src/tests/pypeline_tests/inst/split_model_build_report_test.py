#!/usr/bin/env python3
# Build-report regression test for:
#  - §6a: what's about to be synthesized (cuts/stages) is now printed
#    BEFORE the long "Running syn w timing params" wait, not only after
#  - §6b: pipeline_stages == slices + 1 (was conflated with the
#    slice count itself, making e.g. "cuts=30 main_latency=30
#    pipeline_stages=30" look like 30 cuts bought 0 extra stages)
#  - the D2 fix (RAW_VHDL._EQUAL_WIDTH_BITS_PER_STAGE_DICT) is engaged for
#    real builds, in BOTH the planned sweep and the --coarse path (not just
#    the isolated unit test): every generated multi-stage MINUS entity's
#    bits_per_stage split is as balanced as integer division allows
#    (max-min chunk width <= 1), which is what minimizes the worst stage's
#    delay once each stage is its own registered (and so timing-
#    independent-of-position) computation - see RAW_VHDL.py's module note
#    for why an EARLIER version of this fix (inverting a cumulative delay
#    curve to place UNEVEN bit boundaries) was wrong: verified against real
#    sky130 synthesis, it measurably missed timing goals the plain
#    equal-width split (and even the original linear model) met.
import glob
import os
import re
import subprocess
import sys
import tempfile

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "split_model_design.py")


def _bits_per_stage_from_vhdl(vhd_path):
    bits = []
    with open(vhd_path) as f:
        for line in f:
            m = re.search(r"bits_per_stage_dict\[(\d+)\]\s*=\s*(\d+)", line)
            if m:
                bits.append(int(m.group(2)))
    return bits


def _run(extra_args, out_dir):
    cmd = [sys.executable, PYPELINEC, DESIGN, "--syn_tool", "sky130", "--out_dir", out_dir] + extra_args
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    print(result.stdout)
    return result


def _newest_minus_vhd(out_dir):
    vhd_files = glob.glob(
        os.path.join(out_dir, "built_in", "BIN_OP_MINUS_uint34_t_uint34_t", "*CLK_*.vhd")
    )
    # Skip the 0CLK (unsliced) file, want a real multi-stage split
    sliced = [p for p in vhd_files if not os.path.basename(p).startswith("BIN_OP_MINUS_uint34_t_uint34_t_0CLK")]
    assert sliced, f"no sliced MINUS entity found under {out_dir}"
    return max(sliced, key=os.path.getmtime)


def _assert_balanced_split(vhd_path, label):
    bits = _bits_per_stage_from_vhdl(vhd_path)
    if sum(bits) != 34:
        print(f"FAIL: {vhd_path} bits_per_stage sums to {sum(bits)}, expected 34")
        sys.exit(1)
    if len(bits) < 2:
        print(f"FAIL: {vhd_path} has only {len(bits)} stage(s), expected a real multi-stage split")
        sys.exit(1)
    spread = max(bits) - min(bits)
    if spread > 1:
        print(
            f"FAIL: {label} {vhd_path} bits_per_stage {bits} spans {spread} "
            "(max-min) - expected an equal-width split (<=1) per chunk, since "
            "each stage is its own registered/timing-independent computation "
            "once sliced (see RAW_VHDL._EQUAL_WIDTH_BITS_PER_STAGE_DICT)"
        )
        sys.exit(1)
    return bits


def main():
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    base_out_dir = args.out_dir
    cleanup = False
    if base_out_dir is None:
        base_out_dir = tempfile.mkdtemp(prefix="split_model_build_report_test_")
        cleanup = True

    # 1) Real (non --no_sweep) planned sweep: check §6a ordering and §6b math
    planned_out = os.path.join(base_out_dir, "planned")
    os.makedirs(planned_out, exist_ok=True)
    result = _run([], planned_out)
    if result.returncode != 0:
        print("FAIL: planned sweep build did not succeed")
        sys.exit(1)
    out = result.stdout

    about_to_idx = out.find("about to synthesize")
    running_idx = out.find("Running syn w timing params")
    if about_to_idx == -1:
        print("FAIL: no 'about to synthesize' pre-synthesis report line found")
        sys.exit(1)
    if running_idx == -1:
        print("FAIL: no 'Running syn w timing params' line found (sweep never ran?)")
        sys.exit(1)
    if about_to_idx > running_idx:
        print(
            "FAIL: 'about to synthesize' printed AFTER 'Running syn w timing "
            "params' instead of before the long wait"
        )
        sys.exit(1)

    iter_lines = re.findall(
        r"\[sweep\] iter=\d+ .*?cuts=(\d+) main_latency=(\d+) pipeline_stages=(\d+)",
        out,
    )
    if not iter_lines:
        print("FAIL: no sweep iteration report line found to check pipeline_stages math")
        sys.exit(1)
    for cuts_str, main_latency_str, pipeline_stages_str in iter_lines:
        main_latency = int(main_latency_str)
        pipeline_stages = int(pipeline_stages_str)
        # For this pure-comb single-subtree design, main_latency IS the
        # slice count the pipeline_stages figure is derived from.
        if pipeline_stages != main_latency + 1:
            print(
                f"FAIL: pipeline_stages={pipeline_stages} but main_latency="
                f"{main_latency} (expected pipeline_stages == main_latency + 1)"
            )
            sys.exit(1)

    if "ERROR: TIMING NOT MET" in out:
        print("FAIL: planned sweep did not meet its timing goal")
        sys.exit(1)

    minus_vhd = _newest_minus_vhd(planned_out)
    _assert_balanced_split(minus_vhd, "planned sweep")

    # 2) --coarse landscape-aware path: same balanced-split check
    coarse_out = os.path.join(base_out_dir, "coarse")
    os.makedirs(coarse_out, exist_ok=True)
    result = _run(
        ["--no_sweep", "--coarse", "--start", "4", "--stop", "4"], coarse_out
    )
    if result.returncode != 0:
        print("FAIL: --coarse build did not succeed")
        sys.exit(1)
    if "[coarse] landscape build failed" in result.stdout:
        print(
            "FAIL: --coarse fell back to blind even fractions instead of using "
            "the landscape-aware path"
        )
        sys.exit(1)
    coarse_minus_vhd = _newest_minus_vhd(coarse_out)
    _assert_balanced_split(coarse_minus_vhd, "--coarse")

    if cleanup:
        import shutil

        shutil.rmtree(base_out_dir, ignore_errors=True)

    print("All split-model build-report checks passed.")


if __name__ == "__main__":
    main()
