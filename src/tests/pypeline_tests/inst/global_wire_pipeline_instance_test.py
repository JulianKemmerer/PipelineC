"""Global wires used below the root of a pipelined function, and VOLATILE ones
(pypeline_guide.md, "Global wires in pipelined code").

1. Hardware: global_wire_pipeline_instance_design.py self-checks under
   cocotb/GHDL that a global is aligned with the function instance that uses
   it (read_g at stage 0 vs stage 2 sees g from different cycles), that a
   VOLATILE read happens at its consumer's stage, and that a VOLATILE write
   is driven immediately while an aligned one waits for the return.
2. Native sim cannot model either of those. It must refuse loudly
   (pypeline.SimPipelineModelError) instead of producing cycle-wrong values:
   global_wire_pipeline_refusal_design.py, once per case.

Run standalone: python3 global_wire_pipeline_instance_test.py
"""

import argparse
import os
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "..", "..", "..", "pypelinec")
HW_DESIGN = os.path.join(THIS_DIR, "global_wire_pipeline_instance_design.py")
REFUSAL_DESIGN = os.path.join(THIS_DIR, "global_wire_pipeline_refusal_design.py")

REFUSALS = {
    "nested": "'read_g' is called inside the pipeline",
    "volatile": "it is declared VOLATILE",
}


def _run(cmd):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return result.stdout, result.returncode


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    out_dir = args.out_dir or os.path.join(THIS_DIR, "global_wire_pipeline_instance_test_out")

    hw_out, hw_rc = _run(
        [
            sys.executable, PYPELINEC, HW_DESIGN,
            "--sim", "--comb", "--cocotb", "--ghdl", "--run", "all",
            "--out_dir", os.path.join(out_dir, "hw"),
        ]
    )
    print(hw_out)
    if hw_rc != 0 or "TESTS=1 PASS=1 FAIL=0" not in hw_out:
        fail(f"hardware self-check of {HW_DESIGN} did not pass (exit {hw_rc})")

    for case, reason in REFUSALS.items():
        out, rc = _run(
            [
                sys.executable, PYPELINEC, REFUSAL_DESIGN,
                "-D", f"GWP_REFUSAL_CASE={case}",
                "--sim", "--comb", "--run", "8",
                "--out_dir", os.path.join(out_dir, "native_" + case),
            ]
        )
        print(out)
        if rc == 0:
            fail(f"native sim accepted the '{case}' case; it must refuse it")
        if "SimPipelineModelError" not in out or reason not in out:
            fail(f"native sim's '{case}' refusal did not say {reason!r}")

    print("PASS: hardware aligns globals per instance; native sim refuses what it cannot model.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
