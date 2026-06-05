# pyright: reportInvalidTypeForm=none
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

from pypeline import MAIN, Wire, Input, Output, uint1_t


global_in: Input[uint1_t]
global_out: Output[uint1_t]


@MAIN
def global_io_test():
    global_out = ~global_in


main_a_in: Wire[uint1_t]  # input into main_a
main_a_out: Wire[uint1_t]  # output from main_a


@MAIN
def main_a():
    main_a_out = ~main_a_in


main_b_in: Wire[uint1_t]  # input into main_b
main_b_out: Wire[uint1_t]  # output from main_b


@MAIN
def main_b():
    main_b_out = ~main_b_in


# Connect output of A into B
# and output of B into A
# (nevermind this is bad combinatorial loop in synthesis)
@MAIN
def a_b_connect():
    main_b_in = main_a_out
    main_a_in = main_b_out
