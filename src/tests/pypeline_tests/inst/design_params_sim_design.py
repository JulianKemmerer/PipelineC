# pyright: reportInvalidTypeForm=none
"""Fixture for design_params_build_test.py: native simulation sees -D values
(STEP declared with param(), TAG read as an injected global)."""
from pypeline import MAIN, Reg, param, sim_finish, sim_output, sim_print, uint8_t, Input, make_reset, uint1_t

STEP = param("STEP", 1)


@sim_output
def show(count: uint8_t):
    sim_print(f"DESIGN_PARAMS_SIM count={int(count)} STEP={STEP} TAG={TAG}")
    if int(count) >= 3 * STEP:
        sim_finish()


# Synchronous reset pin (pulsed in cycle 0 by the simulators): every @MAIN
# resets every register with it
rst: Input[uint1_t] = make_reset()


@MAIN(100.0, reset=rst, reset_registers="all")
def design_params_sim_main():
    count: Reg[uint8_t]
    show(count)
    count = count + STEP
