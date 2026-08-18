# pyright: reportInvalidTypeForm=none
import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)
# Path for floating_point (include/pypeline) import
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)
from pypeline import MAIN
from floating_point import float32_t


# Split out of float_ops_test.py: float32 division is a restoring-division
# loop unrolled to 2*(M_LEN+1) = 48 serially-dependent stages
# (floating_point.py's make_float_divider), a known-pathological shape for
# yosys/abc tech-mapping and STA -- by far the slowest single test in the
# whole suite. Registered as its own Test, first in synth_tests.py's list, so
# it starts building at t=0 instead of gating float_ops_test's cheap add/
# sub/mul builds behind it. Numeric correctness (this op included) is already
# covered cheaply and bit-exactly by float_ops_test.py's native-sim tests;
# this file exists solely for real --comb synthesis proof of the divider.


@MAIN
def float32_div_main(a: float32_t, b: float32_t) -> float32_t:
    return a / b
