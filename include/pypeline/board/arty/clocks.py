"""
Arty A7 board clocks.

The 100 MHz oscillator arrives on the pin CLK100MHZ, the name the Arty's
constraints file uses. A design names this clock instead of repeating its
rate:

    import board.arty.clocks as arty_clocks

    @MAIN(arty_clocks.clk100)
    def top(): ...

Importing this module binds the pin, so some @MAIN must run on clk100.
"""

from pypeline import Input, make_clock, uint1_t

clk100 = make_clock(100.0)  # the unnamed 100 MHz clock, as @MAIN(100.0) runs on
CLK100MHZ: Input[uint1_t] = clk100  # the pin that clock arrives on
