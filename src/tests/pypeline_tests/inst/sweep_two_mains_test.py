# pyright: reportInvalidTypeForm=none
# Planned throughput sweep test (b): two MAINs (clock domains), each with its
# own sweep plan. PYRTL reports a single fmax with no path names, exercising
# the no-attribution fallback for multiple mains.
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
def divide(x: uint8_t) -> uint8_t:
    return x / ~x


@MAIN(30.0)
def sweep_heavy_main(x: uint8_t) -> uint8_t:
    a: uint8_t = divide(x)
    b: uint8_t = divide(a)
    return b


@MAIN(30.0)
def sweep_light_main(y: uint8_t) -> uint8_t:
    return divide(y)


def test_sweep_two_mains_sim():
    sim_reset()
    out_a = sim_call(sweep_heavy_main, 4)
    out_b = sim_call(sweep_light_main, 7)
    print(f"test_sweep_two_mains_sim out_a={out_a} out_b={out_b}")


if __name__ == "__main__":
    test_sweep_two_mains_sim()
    print("All sweep two mains tests passed.")
