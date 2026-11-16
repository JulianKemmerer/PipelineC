# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none

# A II=1 pipeline from a pure function (no globals or Reg[T] state)

from pypeline import *
from floating_point import float32_t  # IEEE 754 single precision, with + - * /

# The target part and clock rate come from the command line, ex.
#
#   pypelinec pipeline.py --part LFE5UM5G-85F-8BG756C -D MHZ=100
#
# --part LFE5UM5G-85F-8BG756C picks Lattice ECP5 with ghdl+yosys+nextpnr.
# Without --part (or --syn_tool), the PyRTL timing model is used.
MHZ = param("MHZ", 90.0, help="target clock rate in MHz")


@MAIN(MHZ)
def my_pipeline(x: float32_t, y: float32_t) -> float32_t:
    return x + y
