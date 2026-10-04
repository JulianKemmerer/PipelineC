# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""pico-ice / pico2-ice blinky: blinks the red channel of the on-board RGB LED.

Top-level IO here must match top.sv (the wrapper) and ice40.pcf (the pins).
Build with the Makefile next to this file, see README.md.
"""

import os

from pypeline import *

PART("ICE40UP5K-SG48")  # iCE40 UltraPlus 5K, on both the pico-ice and pico2-ice

# The Makefile exports the PLL output rate it asks icepll for.
# A design file is plain Python, so it can read that setting directly.
PLL_CLK_MHZ = float(os.environ.get("PLL_CLK_MHZ", "25.0"))

# Clock input from the PLL in top.sv. make_clock() gives the port a fixed name
# to match the wrapper, instead of a rate-derived name like clk_25p0.
pll_clk: Input[uint1_t] = make_clock(PLL_CLK_MHZ)
# PLL 'locked' signal: low until pll_clk is stable
pll_locked: Input[uint1_t]

# RGB LED pins, active-low (0 = on)
ICE_39: Output[uint1_t]  # green
ICE_40: Output[uint1_t]  # blue
ICE_41: Output[uint1_t]  # red

# Clock cycles in half a second
HALF_SEC = int(PLL_CLK_MHZ * 1e6 / 2)


@MAIN(PLL_CLK_MHZ)
def blinky_main():
    counter: Reg[uint32_t]
    led_reg: Reg[uint1_t]
    # Drive the LED pins
    ICE_41 = led_reg  # red blinks
    ICE_39 = 1  # green off
    ICE_40 = 1  # blue off
    # Toggle the LED every half second
    if counter == HALF_SEC - 1:
        counter = 0
        led_reg = ~led_reg
    else:
        counter += 1
    # Hold in reset until the PLL is stable
    if pll_locked == 0:
        counter = 0
        led_reg = 0
