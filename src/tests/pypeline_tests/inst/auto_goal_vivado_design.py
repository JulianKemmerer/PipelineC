"""Fixture for auto_goal_vivado_test.py: two objects of one AUTO_PIPELINE
factory, one per clock domain (25 and 100 MHz), each read at factory time the
way a FIFO is sized. Separate calls by default; LANES=list builds both in one
comprehension. Each object must get its own goal's depth. The depth is ORed
into the result, so the value read reaches the hardware without adding logic
to the timed path. 100 MHz, not higher: the chained inferred multiplies'
DSP cascade plateaus near 122 MHz on this part (issue #390)."""
from pypeline import AUTO_PIPELINE, MAIN, PART, hw_func, param, uint32_t, Input, make_reset, uint1_t

PART("xc7a35ticsg324-1l")


@hw_func
def work(x: uint32_t) -> uint32_t:
    return (x * x) * x + x


def make_lane():
    AP = AUTO_PIPELINE(work)
    depth = AP.latency

    @hw_func
    def lane(x: uint32_t) -> uint32_t:
        return AP(x) | depth

    lane.ap = AP
    return lane


if param("LANES", "calls", type=str) == "list":
    SLOW, FAST = [make_lane() for _ in range(2)]
else:
    SLOW = make_lane()
    FAST = make_lane()


# Synchronous reset pins, one per clock (pulsed in cycle 0 by the simulators):
# every @MAIN resets every register with its clock's pin
rst_100: Input[uint1_t] = make_reset()
rst_25: Input[uint1_t] = make_reset()


@MAIN(25.0, reset=rst_25, reset_registers="all")
def slow(x: uint32_t) -> uint32_t:
    return SLOW(x)


@MAIN(100.0, reset=rst_100, reset_registers="all")
def fast(x: uint32_t) -> uint32_t:
    return FAST(x)
