# pyright: reportInvalidTypeForm=none
# Design for sweep_floor_detect_test.py (not registered as a test itself):
# a stateful submodule with a big internal comb path (division inside a Reg
# func) makes the clock goal unreachable - the sweep must predict the fmax
# floor up front, blame this submodule, and stop quickly instead of blindly
# adding more and more cuts.
#
# The goal comes from SWEEP_FLOOR_DETECT_MHZ (default 100), because the two
# tools stop this design on different evidence:
#  - sky130, 100 MHz: the measured plateau (51.4 MHz) sits far above the
#    pessimistic soft-floor prediction (~37 MHz), outside
#    SWEEP.AT_PREDICTED_FLOOR's band, so the sweep stops on the
#    prediction-independent "plateau" stop (SWEEP.AT_PLATEAU). At 50 MHz
#    sky130 simply meets the goal.
#  - PyRTL, 50 MHz: the predicted soft floor (~16 MHz) matches the measured
#    plateau, so the sweep stops at the "empirical_floor".
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


GOAL_MHZ = float(os.environ.get("SWEEP_FLOOR_DETECT_MHZ", "100.0"))


@MAIN(GOAL_MHZ)
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
