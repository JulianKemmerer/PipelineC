#!/usr/bin/env python3
"""Known issue: factory specializations that differ only inside a large numpy
array argument share one identity, so they elaborate as one function.

pypeline._stable_key falls back to repr() for a numpy array, and numpy's repr
elides the middle of any array over 1000 elements ("0, 1, 2, ..., 1999"). The
two lookups in numpy_factory_arg_identity_design.py then get the same `_s`
specialization digest: the second one is elaborated as a DUPLICATE of the
first, and the built hardware adds 1000 twice instead of 1000 and 7.

Exits 1 while the bug is present (registered expect_fail in
known_issues_tests.py), 0 once the two lookups are distinct functions.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(HERE, "..", "..", "..", "pipelinec")
DESIGN = os.path.join(HERE, "numpy_factory_arg_identity_design.py")


def main():
    out_dir = sys.argv[sys.argv.index("--out_dir") + 1]
    build = os.path.join(out_dir, "build")
    subprocess.run(
        [sys.executable, PYPELINEC, DESIGN, "--no_synth", "--out_dir", build],
        check=True,
    )
    with open(os.path.join(build, "name_index.log")) as f:
        index = f.read()
    keys = sorted(
        set(re.findall(r"^\s*logical: (lookup_\w*?_s[0-9a-f]{12})$", index, re.M))
    )
    print("lookup logical keys:", keys)
    if len(keys) != 2:
        print("FAIL: the two numpy-specialized lookups share one function")
        return 1
    print("PASS: two distinct lookup functions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
