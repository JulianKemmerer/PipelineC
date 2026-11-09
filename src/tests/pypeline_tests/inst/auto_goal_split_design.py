"""Fixture for double_parse_file_test.py: AUTO_PIPELINE objects from one
factory, built in a comprehension and used under MAINs at two clock goals, so
PARSE_FILE splits their key and names their products by goal (see
auto_goal_split_test.py)."""
from pypeline import AUTO_PIPELINE, MAIN, hw_func, uint32_t, Input, make_reset, uint1_t


@hw_func
def work(x: uint32_t) -> uint32_t:
    return (x * x) + x


def make_lane():
    AP = AUTO_PIPELINE(work)
    depth = AP.latency

    @hw_func
    def lane(x: uint32_t) -> uint32_t:
        return AP(x) + depth

    return lane


LANES = [make_lane() for _ in range(3)]


# Synchronous reset pins, one per clock (pulsed in cycle 0 by the simulators):
# every @MAIN resets every register with its clock's pin
rst_100: Input[uint1_t] = make_reset()
rst_50: Input[uint1_t] = make_reset()


@MAIN(50.0, reset=rst_50, reset_registers="all")
def slow(x: uint32_t) -> uint32_t:
    return LANES[0](x) + LANES[1](x)


@MAIN(100.0, reset=rst_100, reset_registers="all")
def fast(x: uint32_t) -> uint32_t:
    return LANES[2](x)
