#!/usr/bin/env python3
# Regression guard for the D1 fix (SPLIT_KIND_1LL leaves modelled as freely
# splittable when their generator only ever places their logic in ONE
# stage): builds leaf_1ll_cap_design.py (a serial AND/OR/XOR/MUX-only
# chain - no SPLIT_KIND_BITS leaf anywhere, the shape where this bug is
# total) under --syn_tool sky130 at an aggressive clock target, and checks
#  - the build succeeds
#  - no generated AND/OR/XOR/NOT entity ever exceeds latency 1, no MUX ever
#    exceeds latency 2 (RAW_VHDL.LEAF_MAX_SPLIT_SLICES's real ceiling -
#    stage_for_1ll never reduces delay past that, so a 3rd+ slice would be
#    a bare register around logic that never shrinks)
#  - the fmax floor report now blames a specific 1LL op as unsliceable
#    (before this fix: "no unsliceable spans", since every 1LL leaf was
#    marked freely SLICEABLE with zero floor contribution)
#  - this design STILL gets pipelined at all (several cuts, not one giant
#    uncuttable atomic span - the failure mode a "1LL leaves refuse every
#    slice" version of this fix would have produced)
import glob
import os
import re
import subprocess
import sys
import tempfile

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "leaf_1ll_cap_design.py")

# func_name prefixes -> max legal slices for SPLIT_KIND_1LL leaves (see
# RAW_VHDL.LEAF_MAX_SPLIT_SLICES): stage_for_1ll's own generator code
# supports latency 0/1/2 identically for every one of AND/OR/XOR/MUX (and
# NOT/NEGATE/MULT, not used in this design) - 2 is the real, uniform
# ceiling across all of them, not just MUX.
TWO_SLICE_MAX_PREFIXES = ("BIN_OP_AND_", "BIN_OP_OR_", "BIN_OP_XOR_", "MUX_")

_ENTITY_CLK_RE = re.compile(r"^(.+?)_(\d+)CLK_[0-9a-f]+(?:_top)?\.vhd$")


def main():
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    out_dir = args.out_dir
    cleanup = False
    if out_dir is None:
        out_dir = tempfile.mkdtemp(prefix="leaf_1ll_cap_test_")
        cleanup = True

    cmd = [
        sys.executable,
        PYPELINEC,
        DESIGN,
        "--syn_tool",
        "sky130",
        "--no_sweep",
        "--out_dir",
        out_dir,
    ]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out = result.stdout
    print(out)

    if result.returncode != 0:
        print("FAIL: pypelinec exited non-zero")
        sys.exit(1)

    if "no unsliceable spans" in out:
        print(
            "FAIL: floor report says 'no unsliceable spans' - a 1LL leaf "
            "should be blamed as an atomic bottleneck (D1 regression)"
        )
        sys.exit(1)
    if "unsliceable" not in out:
        print("FAIL: no fmax floor/unsliceable report found at all")
        sys.exit(1)

    # Must still get pipelined (regression guard against a "1LL leaves
    # refuse every slice" overcorrection collapsing this whole chain into
    # one uncuttable atomic span)
    stage_match = re.search(r"cuts=(\d+)", out)
    if stage_match is None or int(stage_match.group(1)) < 2:
        print(
            f"FAIL: expected several cuts through this 1LL-only chain, "
            f"found: {stage_match.group(0) if stage_match else 'none'}"
        )
        sys.exit(1)

    violations = []
    vhd_files = glob.glob(os.path.join(out_dir, "built_in", "**", "*.vhd"), recursive=True)
    if not vhd_files:
        print(f"FAIL: no generated VHDL entity files found under {out_dir}/built_in")
        sys.exit(1)
    for path in vhd_files:
        fname = os.path.basename(path)
        m = _ENTITY_CLK_RE.match(fname)
        if m is None:
            continue
        entity, clk_str = m.group(1), int(m.group(2))
        if entity.startswith(TWO_SLICE_MAX_PREFIXES) and clk_str > 2:
            violations.append(f"{fname}: {clk_str} clocks, max is 2 (SPLIT_KIND_1LL)")
    if violations:
        print("FAIL: 1LL leaf(s) exceeded their real slice ceiling:")
        for v in violations:
            print("  " + v)
        sys.exit(1)

    if cleanup:
        import shutil

        shutil.rmtree(out_dir, ignore_errors=True)

    print("All leaf 1LL cap regression checks passed.")


if __name__ == "__main__":
    main()
