# pyright: reportInvalidTypeForm=none
# Design for sweep_unpipelinable_test.py (not registered as a test itself):
# the MAIN is itself a stateful (Reg) function with no AUTOPIPELINE regions
# and a slow divider inside - there is nothing autopipelining can help. The
# sweep must say so plainly (at planning time and when the timing report
# fails) instead of silently failing or blindly iterating.
import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import (
    MAIN,
    Reg,
    uint8_t,
    sim_call,
    sim_reset,
)


@MAIN(100.0)
def sweep_unpipelinable_main(x: uint8_t) -> uint8_t:
    # Stateful main, no autopipeline tags anywhere: the divider path can
    # never be cut by added registers
    acc: Reg[uint8_t]
    acc = acc / (x + 1)
    return acc


def test_sweep_unpipelinable_sim():
    sim_reset()
    out = sim_call(sweep_unpipelinable_main, 4)
    print(f"test_sweep_unpipelinable_sim out={out}")


if __name__ == "__main__":
    test_sweep_unpipelinable_sim()
    print("All sweep unpipelinable design sims passed.")
