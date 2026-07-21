# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none

# A II=1 pipeline from a pure function (no globals or Reg[T] state)

from pypeline import *

# Set FPGA part/synthesis tool, ex.
#
#   PART("LFE5UM5G-85F-8BG756C")   # Lattice, ghdl+yosys+nextpnr ECP5U flow


@MAIN(100.0)
def my_pipeline(x: float, y: float) -> float:
    return x + y
