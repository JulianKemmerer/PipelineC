#!/usr/bin/env python3
# Regression guard for a process-nondeterminism bug in generated VHDL for
# designs that hit C_TO_LOGIC.TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE's
# duplicate-submodule-collapsing "multi-coordinate" branch
# (duplicate_collapse_naming_design.py: one bit-select read twice on two
# different source lines with the same driver wire, so two "uint34_33_33"
# instances collapse into one with two distinct ASTMeta).
#
# That branch used to build the "_lNN_lMM" fragment of the collapsed
# instance's name by iterating a set of ASTMeta directly. ASTMeta.__hash__
# is hash(coord_str()) -- a str hash, randomized per-process by
# PYTHONHASHSEED -- so the SAME design could spell the fragment
# "_py_l23_l24_" or "_py_l24_l23_" depending on the process, changing
# generated VHDL bytes with no change to the design. Invisible to
# Vivado's filename-only log reuse, but sky130 DEVICE_MODELS hashes exact
# VHDL bytes, so this alone could defeat ITS synthesis-cache reuse.
#
# Confirmed empirically (pre-fix) that PYTHONHASHSEED=0 and
# PYTHONHASHSEED=1 land on opposite orderings for this exact design, so
# those two seeds are pinned here to make detection deterministic --
# unlike a bare repeat-build, which only catches a 2-element set flip
# about half the time.
#
# Uses --comb --no_synth (elaboration + VHDL emission, no synthesis tool
# required) so this runs in seconds with no yosys/ghdl dependency.
import glob
import hashlib
import os
import subprocess
import sys
import tempfile

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "duplicate_collapse_naming_design.py")

# Empirically confirmed to disagree pre-fix (see header comment).
SEEDS = ("0", "1")


def _run(out_dir, seed):
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    cmd = [
        sys.executable,
        PYPELINEC,
        DESIGN,
        "--comb",
        "--no_synth",
        "--out_dir",
        out_dir,
    ]
    print("Running:", " ".join(cmd), f"(PYTHONHASHSEED={seed})", flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"FAIL: pypelinec exited non-zero for out_dir={out_dir} seed={seed}")
        sys.exit(1)


def _vhd_files_by_relpath(out_dir):
    paths = glob.glob(os.path.join(out_dir, "**", "*.vhd"), recursive=True)
    return {os.path.relpath(p, out_dir): p for p in paths}


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    root = args.out_dir
    cleanup = False
    if root is None:
        root = tempfile.mkdtemp(prefix="duplicate_collapse_naming_test_")
        cleanup = True

    files_by_seed = {}
    for seed in SEEDS:
        seed_dir = os.path.join(root, f"seed_{seed}")
        _run(seed_dir, seed)
        files_by_seed[seed] = _vhd_files_by_relpath(seed_dir)

    first_seed = SEEDS[0]
    first_files = files_by_seed[first_seed]

    # Non-empty guard: if the design stops hitting the duplicate-collapse
    # "else" branch, this test would otherwise silently pass while testing
    # nothing.
    duplicate_names = set()
    for relpath, path in first_files.items():
        with open(path, "r") as f:
            content = f.read()
        for line in content.splitlines():
            if "_DUPLICATE_" in line:
                duplicate_names.add(relpath)
    if not duplicate_names:
        print(
            "FAIL: no generated VHDL file contains '_DUPLICATE_' -- "
            "duplicate_collapse_naming_design.py no longer exercises the "
            "duplicate-collapsing 'else' branch, so this test is checking "
            "nothing. Fix the design fixture."
        )
        sys.exit(1)

    for seed in SEEDS[1:]:
        files = files_by_seed[seed]
        if set(files) != set(first_files):
            print(
                f"FAIL: generated *.vhd file set differs between "
                f"PYTHONHASHSEED={first_seed} and PYTHONHASHSEED={seed}:"
            )
            print(f"  only in seed {first_seed}:", sorted(set(first_files) - set(files)))
            print(f"  only in seed {seed}:", sorted(set(files) - set(first_files)))
            sys.exit(1)

        mismatches = [
            relpath
            for relpath, path in first_files.items()
            if _sha256(path) != _sha256(files[relpath])
        ]
        if mismatches:
            print(
                f"FAIL: generated VHDL content differs between "
                f"PYTHONHASHSEED={first_seed} and PYTHONHASHSEED={seed} "
                f"for identical design (duplicate-collapse naming regression):"
            )
            for relpath in sorted(mismatches):
                print("  " + relpath)
            sys.exit(1)

    if cleanup:
        import shutil

        shutil.rmtree(root, ignore_errors=True)

    print("All duplicate-collapse naming determinism checks passed.")


if __name__ == "__main__":
    main()
