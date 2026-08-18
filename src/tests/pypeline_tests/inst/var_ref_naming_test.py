#!/usr/bin/env python3
# Regression guard for two process-nondeterminism bugs in generated VHDL for
# designs with sequential runtime variable-index writes to the same array
# (var_ref_naming_design.py): a real synthesis-log-reuse repro, not just the
# in-process double_parse_file_test.py check.
#
#  - cause 1 (entity NAMES): a variable-index ref tok is a Python AST node,
#    and str(ast_node) embeds a per-process repr memory address. That leaked
#    into the md5 hash PY_TO_LOGIC uses for VAR_REF_ASSIGN/VAR_REF_RD/
#    CONST_REF_RD func names, so this design got different entity names on
#    every process -- and therefore a different synthesis log file path --
#    defeating --continue's log reuse. Checked here by building TWICE into
#    the SAME out_dir and diffing the generated *.vhd file name set.
#
#  - cause 2 (entity CONTENT): RAW_VHDL's CONST_REF_RD body renderer iterates
#    C_TO_LOGIC.EXPAND_REF_TOKS_OR_STRS's returned set directly to emit one
#    VHDL assignment line per element; that set's iteration order is
#    PYTHONHASHSEED-salted for str-containing tuples, so semantically
#    identical VHDL came out in process-random line order. Invisible to
#    Vivado's filename-only reuse check, but sky130 DEVICE_MODELS hashes the
#    exact VHDL bytes, so this alone defeats ITS reuse even with stable
#    names. Checked here by building once into two INDEPENDENT out_dirs and
#    diffing every generated *.vhd byte-for-byte.
#
# Found via wireguard-fpga's chacha20 byte-sink writers, which have this
# exact two-sequential-variable-index-write shape.
import glob
import hashlib
import os
import subprocess
import sys
import tempfile

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "var_ref_naming_design.py")


def _run(out_dir):
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
    print(result.stdout)
    if result.returncode != 0:
        print(f"FAIL: pypelinec exited non-zero for out_dir={out_dir}")
        sys.exit(1)
    return result.stdout


def _vhd_files_by_relpath(out_dir):
    paths = glob.glob(os.path.join(out_dir, "**", "*.vhd"), recursive=True)
    return {os.path.relpath(p, out_dir): p for p in paths}


def main():
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    root = args.out_dir
    cleanup = False
    if root is None:
        root = tempfile.mkdtemp(prefix="var_ref_naming_test_")
        cleanup = True

    # ── cause 1: same out_dir, twice -- entity NAMES must not change ──
    same_dir = os.path.join(root, "same")
    _run(same_dir)
    names_1 = set(_vhd_files_by_relpath(same_dir))
    out_2 = _run(same_dir)
    names_2 = set(_vhd_files_by_relpath(same_dir))

    if names_1 != names_2:
        print("FAIL: generated *.vhd file set changed on a repeat build "
              "into the same out_dir (cause 1: unstable entity names):")
        print("  only in build 1:", sorted(names_1 - names_2))
        print("  only in build 2:", sorted(names_2 - names_1))
        sys.exit(1)

    if "Running:" in out_2:
        print("FAIL: repeat build into the same out_dir re-ran synthesis "
              "(expected full log reuse, zero 'Running:' lines):")
        for line in out_2.splitlines():
            if line.startswith("Running:"):
                print("  " + line)
        sys.exit(1)

    if "identity/input mismatch" in out_2:
        print("FAIL: repeat build into the same out_dir hit a cached-timing "
              "identity/input mismatch (cause 2: unstable VHDL content):")
        sys.exit(1)

    # ── cause 2: two independent fresh out_dirs -- entity CONTENT (not
    # just names) must be byte-identical ──
    fresh_a = os.path.join(root, "fresh_a")
    fresh_b = os.path.join(root, "fresh_b")
    _run(fresh_a)
    _run(fresh_b)
    files_a = _vhd_files_by_relpath(fresh_a)
    files_b = _vhd_files_by_relpath(fresh_b)

    if set(files_a) != set(files_b):
        print("FAIL: two independent fresh builds produced different "
              "*.vhd file sets:")
        print("  only in fresh_a:", sorted(set(files_a) - set(files_b)))
        print("  only in fresh_b:", sorted(set(files_b) - set(files_a)))
        sys.exit(1)
    if not files_a:
        print(f"FAIL: no generated VHDL entity files found under {fresh_a}")
        sys.exit(1)

    def sha256(path):
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    mismatches = [
        relpath
        for relpath, path_a in files_a.items()
        if sha256(path_a) != sha256(files_b[relpath])
    ]
    if mismatches:
        print("FAIL: generated VHDL content differs between two independent "
              "fresh builds of the identical design (cause 2 regression):")
        for relpath in sorted(mismatches):
            print("  " + relpath)
        sys.exit(1)

    if cleanup:
        import shutil

        shutil.rmtree(root, ignore_errors=True)

    print("All var_ref naming determinism checks passed.")


if __name__ == "__main__":
    main()
