# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test: pushes a fixed stimulus table into a FIFO, then pops
it back and checks FWFT order against the same table via sim_assert, then calls
sim_finish() once the last expected value is confirmed -- no external Python
sim_call/assert harness needed, mirroring self_check_counter_test.py and
wireguard-fpga's syn_tb testbenches (fixed expected-value table, shift-register-
style push/pop state machine, sim_assert + sim_finish for in-hardware checking).

Registered in both native_sim_tests.py (--sim --comb --run all) and vhdl_sim_tests.py
(--sim --comb --cocotb --ghdl --run all).
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)
from pypeline import MAIN, Reg, sim_assert, sim_finish, uint1_t, uint32_t

from fifo import make_fifo

STIMULUS = [10, 20, 30, 40, 50]
NUM_VALUES = len(STIMULUS)

fifo_fwft, fifo_fwft_t = make_fifo(uint32_t, NUM_VALUES)


@MAIN
def self_check_fifo():
    push_idx: Reg[uint32_t]
    pop_idx: Reg[uint32_t]
    values: uint32_t[NUM_VALUES] = STIMULUS

    # Push phase first, then pop phase -- no overlap, avoiding any same-cycle
    # push/pop ordering questions.
    do_push: uint1_t = push_idx < NUM_VALUES
    do_pop: uint1_t = ~do_push

    data_in: uint32_t = 0
    if do_push:
        data_in = values[push_idx]

    fifo_out: fifo_fwft_t = fifo_fwft(do_pop, data_in, do_push)

    if do_push & fifo_out.data_in_ready:
        push_idx = push_idx + 1

    if do_pop & fifo_out.data_out_valid:
        sim_assert(
            fifo_out.data_out == values[pop_idx],
            f"self_check_fifo: pop order mismatch at index {pop_idx}: "
            f"expected {values[pop_idx]} got {fifo_out.data_out}",
        )
        if pop_idx == NUM_VALUES - 1:
            sim_finish()
        pop_idx = pop_idx + 1
