# pyright: reportInvalidTypeForm=none
"""The hardware top of built_hardware_core_design.py: real input and output
ports, so synthesis keeps and times all of it. See built_hardware_sim_test.py."""

from pypeline import MAIN, Input, Output, uint16_t, wires

import built_hardware_core_design as core

body_in_port: Input[uint16_t]  # drives core.body_in
body_out_port: Output[uint16_t]  # core.body_out
fsm_in_port: Input[core.OPS_FSM.in_stream_t]  # drives core.fsm_in
fsm_out_port: Output[core.OPS_FSM.out_stream_t]  # core.fsm_out


@MAIN(core.GOAL_MHZ)
@wires
def built_hardware_ports():
    core.body_in = body_in_port
    body_out_port = core.body_out
    core.fsm_in = fsm_in_port
    fsm_out_port = core.fsm_out
