# pyright: reportInvalidTypeForm=none
# Design for sweep_planless_test.py (not registered as a test itself):
# the MAIN is a stateful (Reg) function with no AUTOPIPELINE regions -
# nothing autopipelining can help - but unlike sweep_unpipelinable_design.py
# the clock goal is easily met as written. The sweep must run ONE standalone
# whole-module synthesis so the user sees the as-written PASS, without
# storing the reported critical path as the func's delay value.
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


@MAIN(1.0)
def sweep_planless_main(x: uint8_t) -> uint8_t:
    # Stateful main, no autopipeline tags anywhere, trivially meets 1 MHz
    acc: Reg[uint8_t]
    acc = acc + x
    return acc


def test_sweep_planless_sim():
    sim_reset()
    out = sim_call(sweep_planless_main, 4)
    print(f"test_sweep_planless_sim out={out}")


if __name__ == "__main__":
    test_sweep_planless_sim()
    print("All sweep planless design sims passed.")
