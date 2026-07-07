# pyright: reportInvalidTypeForm=none
# Planned throughput sweep test (a): pure comb MAIN needing pipelining.
# The whole main is one cut domain; the planner must place cuts and meet
# timing (PYRTL software timing model, no PART()).
import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import (
    MAIN,
    hw_func,
    uint8_t,
    sim_call,
    sim_reset,
)


@hw_func
def heavy(x: uint8_t) -> uint8_t:
    # Division is a large sliceable comb structure (~57 ns under PYRTL)
    return x / ~x


@MAIN(50.0)
def sweep_comb_main(x: uint8_t) -> uint8_t:
    a: uint8_t = heavy(x)
    b: uint8_t = heavy(a)
    return b


def test_sweep_comb_sim():
    sim_reset()
    out = sim_call(sweep_comb_main, 4)
    print(f"test_sweep_comb_sim out={out}")


if __name__ == "__main__":
    test_sweep_comb_sim()
    print("All sweep comb tests passed.")
