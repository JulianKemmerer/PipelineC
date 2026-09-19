# pyright: reportInvalidTypeForm=none
# Per-SYN_TOOL planned throughput sweep: the smallest design that still needs
# real pipelining -- one float32 adder @MAIN, the Pypeline twin of
# examples/pipeline.c.
#
# Deliberately part-neutral: no PART() here, so the same source file is
# registered once per backend in synth_tests.py with just --syn_tool <tool>,
# and each tool's own DEFAULT_PART (src/<TOOL>.py) supplies the part. That is
# the whole point of the matrix -- every backend builds THE SAME design, so a
# failure is about the backend and nothing else.
#
# The clock goal comes from SWEEP_FLOAT32_MHZ (set per registration via
# Test.env) because a float32 adder's unpipelined fmax differs by an order of
# magnitude between an ASIC standard-cell model and an FPGA: one shared goal
# would either cut nothing on the fast tools or churn on the slow ones. Each
# goal is picked to need a few sweep iterations, not zero and not many.
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# Path for pypeline import
sys.path.insert(0, os.path.join(_HERE, "../../../"))
# Path for floating_point (include/pypeline) import
sys.path.insert(0, os.path.join(_HERE, "../../../../include/pypeline"))

from pypeline import MAIN
from floating_point import float32_t

_MHZ = float(os.environ.get("SWEEP_FLOAT32_MHZ", "25.0"))


@MAIN(_MHZ)
def sweep_float32_main(x: float32_t, y: float32_t) -> float32_t:
    return x + y
