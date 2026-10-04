# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none

from pypeline import *

# Install+configure synthesis tool then specify part here, e.g.
#
#   PART("ICE40UP5K-SG48")      # iCE40 (pico-ice)
#   PART("xc7a100tcsg324-1")    # Artix 7 100T (Arty)

# Extra top-level output port: watch the register on hardware or in a waveform
counter_debug: Output[uint16_t]


# 'Called'/'Executing' every 40ns (25MHz)
@MAIN(25.0)
def counter() -> uint16_t:
    # Reg[T] = registers
    the_counter_reg: Reg[uint16_t]
    # Drive the extra debug output port
    counter_debug = the_counter_reg
    # sim_print works in simulation
    sim_print(f"Counter register value: {the_counter_reg}")
    # an adder
    the_counter_reg += 1
    # connection to output port
    return the_counter_reg


# Version where the register connects directly to the output port
# (no adder in the path to the output port):
#
#   the_counter_reg: Reg[uint16_t]
#   output = the_counter_reg
#   the_counter_reg += 1
#   return output
