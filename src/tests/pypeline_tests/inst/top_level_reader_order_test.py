"""Known issue: the generated top level's global-wire connections come out in
an order that depends on Python's string hashing.

VHDL.WRITE_MULTIMAIN_TOP gathers a shared wire's readers into sets
(read_funcs, read_insts) and writes one block of connections per reader in
set order. For a wire with several readers, the order of those blocks in
top/top.vhd changes with PYTHONHASHSEED, so two builds of one design can write
two different top.vhd files. The hardware is the same; any cache keyed by
the file's text (synthesis logs) misses.

This test builds global_wire_nested_split_test.py (wires w and w2, each read
by two functions) with PYTHONHASHSEED=0 and =1 and exits nonzero while the
two top.vhd files differ. Registered in known_issues_tests.py with
expect_fail=True.
"""

import os
import subprocess
import sys
import tempfile

INST_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.abspath(os.path.join(INST_DIR, "..", "..", ".."))
DESIGN = os.path.join(INST_DIR, "global_wire_nested_split_test.py")


def _top_vhd(tmpdir, seed):
    out_dir = os.path.join(tmpdir, f"seed_{seed}")
    env = dict(os.environ, PYTHONHASHSEED=str(seed))
    subprocess.run(
        [
            sys.executable,
            os.path.join(SRC_DIR, "pypelinec"),
            DESIGN,
            "--comb",
            "--no_synth",
            "--out_dir",
            out_dir,
        ],
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    with open(os.path.join(out_dir, "top", "top.vhd")) as f:
        return f.read()


def main():
    with tempfile.TemporaryDirectory(prefix="top_level_reader_order_") as tmpdir:
        tops = [_top_vhd(tmpdir, seed) for seed in (0, 1)]
    if tops[0] != tops[1]:
        print("top/top.vhd differs between PYTHONHASHSEED=0 and =1")
        sys.exit(1)
    print("top_level_reader_order_test: top.vhd is the same for both seeds")


if __name__ == "__main__":
    main()
