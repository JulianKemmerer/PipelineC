# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none

# A II=1 pipeline from a pure function (no globals or Reg[T] state)

from pypeline import *
from floating_point import float32_t  # IEEE 754 single precision, with + - * /

# Set FPGA part/synthesis tool, ex.
#
#   PART("LFE5UM5G-85F-8BG756C")   # Lattice, ghdl+yosys+nextpnr ECP5U flow


@MAIN(90.0)
def my_pipeline(x: float32_t, y: float32_t) -> float32_t:
    return x + y
