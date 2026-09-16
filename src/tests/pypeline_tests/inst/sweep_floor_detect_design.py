# pyright: reportInvalidTypeForm=none
# Design for sweep_floor_detect_test.py (not registered as a test itself):
# a stateful submodule with a big internal comb path (division inside a Reg
# func) makes the 50 MHz goal unreachable - the sweep must predict the fmax
# floor up front, blame this submodule, and stop quickly instead of blindly
# adding more and more cuts. The test builds under --syn_tool pyrtl, where the
# predicted soft floor (~16 MHz) matches the measured plateau. Under sky130 the
# goal is met at 50 MHz, and at an unreachable 100 MHz the measured plateau
# (51.4 MHz) sits far above the pessimistic soft-floor prediction (~37 MHz),
# outside SWEEP.AT_PREDICTED_FLOOR's band, so the sweep runs to its iteration
# limit instead of stopping.
import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import (
    MAIN,
    hw_func,
    Reg,
    uint8_t,
    sim_call,
    sim_reset,
)


@hw_func
def slow_acc(x: uint8_t) -> uint8_t:
    # Stateful and slow: the divider is trapped inside a Reg func with no
    # auto-pipeline tag, so no added registers can ever cut this path
    acc: Reg[uint8_t]
    acc = acc / (x + 1)
    return acc


@MAIN(50.0)
def sweep_floor_main(x: uint8_t) -> uint8_t:
    # Sliceable comb logic around the atomic hot spot
    a: uint8_t = x / ~x
    s: uint8_t = slow_acc(a)
    return s + x


def test_sweep_floor_sim():
    sim_reset()
    out = sim_call(sweep_floor_main, 4)
    print(f"test_sweep_floor_sim out={out}")


if __name__ == "__main__":
    test_sweep_floor_sim()
    print("All sweep floor design sims passed.")
