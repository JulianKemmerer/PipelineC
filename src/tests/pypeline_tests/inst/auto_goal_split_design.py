"""Fixture for double_parse_file_test.py: AUTO_PIPELINE objects from one
factory, built in a comprehension and used under MAINs at two clock goals, so
PARSE_FILE splits their key and names their products by goal (see
auto_goal_split_test.py)."""
from pypeline import AUTO_PIPELINE, MAIN, hw_func, uint32_t


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


@MAIN(50.0)
def slow(x: uint32_t) -> uint32_t:
    return LANES[0](x) + LANES[1](x)


@MAIN(100.0)
def fast(x: uint32_t) -> uint32_t:
    return LANES[2](x)
