# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Fixture for design_params_build_test.py: -D values read as plain globals,
cpp-macro style, with no param() declaration -- INJ_WIDTH at module level,
INJ_INC inside the hardware body."""
from pypeline import MAIN, make_uint_t

data_t = make_uint_t(INJ_WIDTH)


@MAIN
def design_params_injected_main(x: data_t) -> data_t:
    return x + INJ_INC
