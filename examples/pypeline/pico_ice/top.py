# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""pico-ice / pico2-ice blinky: blinks the red channel of the on-board RGB LED.

Top-level IO here must match top.sv (the wrapper) and ice40.pcf (the pins).
Build with the Makefile next to this file, see README.md.
"""

from pypeline import *

PART("ICE40UP5K-SG48")  # iCE40 UltraPlus 5K, on both the pico-ice and pico2-ice

# The Makefile passes the PLL output rate it asks icepll for as
# -D PLL_CLK_MHZ=..., and param() reads it (25.0 when not given).
PLL_CLK_MHZ = param("PLL_CLK_MHZ", 25.0, help="PLL output clock rate in MHz")

# PLL 'locked' signal: low until pll_clk is stable. It is not synchronous to
# pll_clk (ASYNC), so lock_sync brings it in through two registers.
pll_locked: Input[uint1_t, ASYNC]
# Reset while the PLL is not locked, synchronous to pll_clk
pll_rst: Wire[uint1_t] = make_reset()
# Clock input from the PLL in top.sv. make_clock() gives the port a fixed name
# to match the wrapper, instead of a rate-derived name like clk_25p0, and makes
# pll_rst the reset of its @MAINs.
pll_clk: Input[uint1_t] = make_clock(PLL_CLK_MHZ, reset=pll_rst)

# RGB LED pins, active-low (0 = on)
ICE_39: Output[uint1_t]  # green
ICE_40: Output[uint1_t]  # blue
ICE_41: Output[uint1_t]  # red

# Clock cycles in half a second
HALF_SEC = int(PLL_CLK_MHZ * 1e6 / 2)


# Not reset: it drives the reset. Its registers start at 0, so the design is
# held in reset from power-up until the lock has passed through both.
@MAIN(pll_clk, reset=None)
def lock_sync():
    s0: Reg[uint1_t]
    s1: Reg[uint1_t]
    pll_rst = ~s1
    s1 = s0
    s0 = pll_locked


# Every register below resets (to 0) while the PLL is not locked
@MAIN(pll_clk, reset_registers="all")
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
