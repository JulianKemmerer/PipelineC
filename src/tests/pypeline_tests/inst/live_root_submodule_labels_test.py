"""Known issue: native simulation after a build drops the build's pipeline
placements inside a @MAIN of an imported module.

`pypelinec --sim` hands native sim the build's timing per instance name
(SIM.DO_OPTIONAL_SIM's pipeline_timing), and PREPARE_PIPELINE_LATENCY_SIM
re-elaborates the MAINs that reach a @pipeline_latency function through
ELABORATE_LIVE_ROOTS, then looks each instance up by name. A call to a
same-module function inside a sub-module's top-level def is labeled with the
module prefix in the build (PARSE_FILE Step 6 pre-registers `pl_sub_h`, so
the call site is `pl_sub_h[...]`), but without it by live elaboration, which
has no such stubs (`h[...]`). The names differ, so those instances get no
build placement and native sim models them unpipelined.

This test parses a two-file design, re-elaborates the sub-module's MAIN as
a live root, and exits nonzero while some live instance name is missing
from the build. Registered in known_issues_tests.py with expect_fail=True.
"""

import os
import sys
import tempfile

SRC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(0, SRC_DIR)

_HEADER = f"import sys\nsys.path.insert(0, {SRC_DIR!r})\nfrom pypeline import *\n"

SUB = """
@pipeline_latency(1)
@hw_func
def delay_one(x: uint8_t) -> uint8_t:
    saved: Reg[uint8_t]
    rv = saved
    saved = x
    return rv


@hw_func
def h(x: uint8_t) -> uint8_t:
    return delay_one(x) + 1


@MAIN
def sub_main() -> uint8_t:
    t: Reg[uint8_t]
    y = h(t)
    t += 1
    return y
"""

TOP = """
import pl_sub


@MAIN
def top():
    n: Reg[uint8_t]
    n += 1
"""


def main():
    import PY_TO_LOGIC
    import pypeline
    import pypeline_sim

    with tempfile.TemporaryDirectory(prefix="live_root_submodule_labels_") as tmp:
        for name, text in (("pl_sub.py", SUB), ("pl_top.py", TOP)):
            with open(os.path.join(tmp, name), "w") as f:
                f.write(_HEADER + text)
        path = os.path.join(tmp, "pl_top.py")
        build = set(PY_TO_LOGIC.PARSE_FILE(path).LogicInstLookupTable)
        # As run_sim does: re-import the design, then elaborate its MAIN
        pypeline_sim._evict_design_modules()
        pypeline_sim.import_design(path)
        roots = [
            f
            for f in pypeline._main_registry
            if f._pypeline_main.name == "pl_sub_sub_main"
        ]
        live = set(PY_TO_LOGIC.ELABORATE_LIVE_ROOTS(roots).LogicInstLookupTable)
    missing = sorted(live - build)
    if missing:
        print("Live instance names the build does not have:")
        for name in missing:
            print("   ", name)
        sys.exit(1)
    print("live_root_submodule_labels_test: live names match the build")


if __name__ == "__main__":
    main()
