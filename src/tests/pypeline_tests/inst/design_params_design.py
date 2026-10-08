# pyright: reportInvalidTypeForm=none
"""Fixture for design_params_test.py / design_params_build_test.py: a data
width, a clock goal and an increment, each declared with param() and set
with -D NAME=VALUE."""
from pypeline import MAIN, make_uint_t, param

WIDTH = param("WIDTH", 8, choices=(8, 12, 16), help="data path width in bits")
GOAL_MHZ = param("GOAL_MHZ", 100.0, help="clock goal")
STEP = param("STEP", 1, help="increment added to the input")

data_t = make_uint_t(WIDTH)


@MAIN(GOAL_MHZ)
def design_params_main(x: data_t) -> data_t:
    return x + STEP
