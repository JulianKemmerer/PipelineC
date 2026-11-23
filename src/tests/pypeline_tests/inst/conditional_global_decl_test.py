"""Known issue: a global wire or port declared inside a module-level `if` is
not part of the hardware.

PY_TO_LOGIC._discover_global_wires reads only the direct children of the
module body. An Output[T] declared inside a module-level `if` that ran gets no
port: the build succeeds, and the @MAIN's write to it becomes an unused local.
Native simulation finds wires in the live module's annotations
(pypeline_sim._discover_wire_names), so it treats the declaration as a wire. A
Wire[T] declared the same way and read by another @MAIN stops the build with
"Unknown name" instead.

This test parses conditional_global_decl_design.py in process. It passes if
the build has the `led` output, or if PARSE_FILE refuses the declaration with
an error that names `led`: either fix ends the silent drop. Registered in
known_issues_tests.py (expect_fail): it fails while the port is dropped.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))

import PY_TO_LOGIC


def test_output_declared_in_module_level_if_is_a_port():
    design = os.path.join(HERE, "conditional_global_decl_design.py")
    try:
        state = PY_TO_LOGIC.PARSE_FILE(design)
    except PY_TO_LOGIC.ElaborationError as e:
        assert "led" in str(e), f"unrelated elaboration error: {e}"
        print("PASS: the declaration inside `if` is refused with an error naming led")
        return
    assert "led" in state.output_wires, (
        "the Output declared inside a module-level `if` has no port; "
        f"output_wires = {sorted(state.output_wires)}"
    )
    print("PASS: led is an output port")


if __name__ == "__main__":
    test_output_declared_in_module_level_if_is_a_port()
