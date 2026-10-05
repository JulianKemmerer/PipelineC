# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none

# A simple finite state machine: STATE_A, then STATE_B, then STATE_C,
# waiting in STATE_C until some_input_signal starts it over.

from enum import auto

from pypeline import *

# Install+configure synthesis tool then specify part here, e.g.
#
#   PART("ICE40UP5K-SG48")      # iCE40 (pico-ice)
#   PART("xc7a100tcsg324-1")    # Artix 7 100T (Arty)


# State enum definition
@enum
class my_state_t:
    STATE_A = auto()
    STATE_B = auto()
    STATE_C = auto()


# Module output signals
@struct
class my_fsm_outputs_t(NamedTuple):
    some_output_signal: char_t


# Module input signal, a top-level input port
some_input_signal: Input[uint1_t]

# Simulation only: drive some_input_signal high every 5th clock cycle
sim_cycle = [0]


@sim_input
def drive_some_input_signal():
    some_input_signal = (sim_cycle[0] % 5) == 4
    sim_cycle[0] += 1


# 'Called'/'Executing' every 40ns (25MHz)
@MAIN(25.0)
def fsm() -> my_fsm_outputs_t:
    drive_some_input_signal()  # simulation only, no hardware
    # Reg[T] = registers
    state: Reg[my_state_t]  # state register
    # output wires
    outputs: my_fsm_outputs_t
    # State machine logic
    if state == my_state_t.STATE_A:
        sim_print("State A!")
        outputs.some_output_signal = ord("A")
        state = my_state_t.STATE_B
    elif state == my_state_t.STATE_B:
        sim_print("State B!")
        outputs.some_output_signal = ord("B")
        state = my_state_t.STATE_C
    else:  # state == my_state_t.STATE_C
        sim_print("State C!")
        outputs.some_output_signal = ord("C")
        if some_input_signal:
            state = my_state_t.STATE_A
        else:
            sim_print("Not starting over yet!")
    return outputs
