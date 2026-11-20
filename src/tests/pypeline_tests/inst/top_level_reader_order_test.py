"""Regression test for issue #380: the generated top level's global-wire
connections do not depend on Python's string hashing.

VHDL.GLOBAL_WIRE_CONNECTIONS plans the connections from
ParserState.global_wire_access, whose functions and instances are sorted, so a
wire read by several instances gets one block of connections per reader in the
same order on every run. This test builds a design (by default
global_wire_nested_split_test.py: wires w and w2, each read by two functions)
with PYTHONHASHSEED=0 and =1 and exits nonzero if the two top/top.vhd files
differ, which would also miss every cache keyed by the file's text (synthesis
logs).

Registered in build_report_tests.py (two --no_synth builds), and in
known_issues_tests.py with the design argument c_inst_array_order_design.c: the
C front end's INST_ARRAY connections in VHDL.WRITE_MULTIMAIN_TOP still loop over
unsorted sets (expect_fail while that bug is present).
"""
import os
import subprocess
import sys
import tempfile

INST_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.abspath(os.path.join(INST_DIR, "..", "..", ".."))
DEFAULT_DESIGN = os.path.join(INST_DIR, "global_wire_nested_split_test.py")


def _top_vhd(design, tmpdir, seed):
    out_dir = os.path.join(tmpdir, f"seed_{seed}")
    env = dict(os.environ, PYTHONHASHSEED=str(seed))
    subprocess.run(
        [
            sys.executable,
            os.path.join(SRC_DIR, "pypelinec"),
            design,
            "--comb",
            "--no_synth",
            "--out_dir",
            out_dir,
        ],
        env=env,
        cwd=tmpdir,  # the C parser writes its lextab.py / yacctab.py here
        check=True,
        stdout=subprocess.DEVNULL,
    )
    with open(os.path.join(out_dir, "top", "top.vhd")) as f:
        return f.read()


def main():
    design = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DESIGN
    with tempfile.TemporaryDirectory(prefix="top_level_reader_order_") as tmpdir:
        tops = [_top_vhd(design, tmpdir, seed) for seed in (0, 1)]
    if tops[0] != tops[1]:
        print("top/top.vhd differs between PYTHONHASHSEED=0 and =1")
        sys.exit(1)
    print("top_level_reader_order_test: top.vhd is the same for both seeds")


if __name__ == "__main__":
    main()
