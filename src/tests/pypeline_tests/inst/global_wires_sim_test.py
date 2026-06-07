# pyright: reportInvalidTypeForm=none
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

from pypeline import MAIN, Wire, Reg, Input, Output, sim_output, uint1_t


@sim_output
def sim_print(*args, **kwargs):
    print("SIM", *args, **kwargs)


main_a_in: Wire[uint1_t]  # input into main_a
main_a_out: Wire[uint1_t]  # output from main_a


@MAIN
def main_a():
    r: Reg[uint1_t]
    sim_print("main_a r", r)
    main_a_out = r
    r = ~main_a_in


main_b_in: Wire[uint1_t]  # input into main_b
main_b_out: Wire[uint1_t]  # output from main_b


@MAIN
def main_b():
    r: Reg[uint1_t]
    sim_print("main_b r", r)
    main_b_out = r
    r = ~main_b_in


# Connect output of A into B
# and output of B into A
@MAIN
def a_b_connect():
    main_b_in = main_a_out
    main_a_in = main_b_out
