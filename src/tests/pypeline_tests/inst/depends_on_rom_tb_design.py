"""Native testbench of the hardware built from depends_on_rom_design.py: prints
the ROM's word at address zero. See depends_on_test.py."""

import depends_on_rom_design as design
from pypeline import MAIN, sim_output


@MAIN
@sim_output
def observe_rom():
    print(f"ROM word: {int(design.read_word(0))}")
