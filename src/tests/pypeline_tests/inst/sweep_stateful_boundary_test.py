# pyright: reportInvalidTypeForm=none
# Planned throughput sweep test (d): comb logic A -> stateful submodule S
# (no autopipeline tag) -> comb logic B, with a timing goal that forces cuts
# near S's span. Cuts must stop at S's boundary instead of descending into it
# and silently vanishing (regression test for the old "Finding #1" descend
# predicate bug - the CHECK_CUTS_VS_LATENCY invariant raises if cuts are lost).
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
def acc_step(x: uint8_t) -> uint8_t:
    # Stateful (non-volatile Reg) - not sliceable, no autopipeline tag
    acc: Reg[uint8_t]
    acc = acc + x
    return acc


@MAIN(30.0)
def sweep_boundary_main(x: uint8_t) -> uint8_t:
    # Sliceable comb A
    a: uint8_t = x / ~x
    # Atomic stateful S in the middle of the delay axis
    s: uint8_t = acc_step(a)
    # Sliceable comb B
    b: uint8_t = s / ~s
    return b


def test_sweep_boundary_sim():
    sim_reset()
    out = sim_call(sweep_boundary_main, 4)
    print(f"test_sweep_boundary_sim out={out}")


if __name__ == "__main__":
    test_sweep_boundary_sim()
    print("All sweep stateful boundary tests passed.")
