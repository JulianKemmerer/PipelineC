# pyright: reportInvalidTypeForm=none
"""Fixture for design_params_build_test.py: native simulation sees -D values
(STEP declared with param(), TAG read as an injected global)."""
from pypeline import MAIN, Reg, param, sim_finish, sim_output, sim_print, uint8_t

STEP = param("STEP", 1)


@sim_output
def show(count: uint8_t):
    sim_print(f"DESIGN_PARAMS_SIM count={int(count)} STEP={STEP} TAG={TAG}")
    if int(count) >= 3 * STEP:
        sim_finish()


@MAIN(100.0)
def design_params_sim_main():
    count: Reg[uint8_t]
    show(count)
    count = count + STEP
