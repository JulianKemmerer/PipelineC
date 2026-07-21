# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none

from pypeline import *

# Install+configure synthesis tool then specify part here, e.g.
#
#   PART("xc7a35ticsg324-1l")   # Xilinx Vivado
#   PART("LFE5U-85F-6BG381C")   # Lattice
#   PART("5CEBA4F23C8")         # Intel/Altera

# 'Called'/'Executing' every 40ns (25MHz)
@MAIN(25.0)
def blink() -> uint1_t:
    # Count to 25000000 iterations * 40ns each = 1 sec
    counter: Reg[uint32_t] = 0

    # LED on/off state
    led: Reg[uint1_t] = 0

    sim_print(f"counter={counter} led={led}")

    # If reached 1 second
    if counter == (25000000 - 1):
        led = ~led  # Toggle led
        counter = 0  # Reset counter
    else:
        counter = counter + 1  # one 40ns increment

    return led
