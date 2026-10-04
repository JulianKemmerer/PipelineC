# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Arty A7 demo: blink RGB LED 0, and draw a VGA test pattern on PMOD JA + JB.

Top-level IO here must match board.vhd (the wrapper) and arty.xdc (the pins).
Build with the Makefile next to this file, see README.md.
"""

from pypeline import *

# Sets PART for the Arty A7-35T (import board.arty.part100t for the A7-100T)
import board.arty.part35t

# VGA PMOD output wire, driving ports ja_0..ja_7 and jb_0..jb_5
import board.arty.vga_pmod_ja_jb as board_vga
from vga.types import vga_timing_signals_t, vga_12bpp_t
from vga.timing import make_vga_timing, VGA_640_480

# Every @MAIN here runs at 25 MHz, so the generated top level has one clock
# port named after that rate: clk_25p0. board.vhd drives it from a PLL.

# PLL 'locked' signal: low until clk_25p0 is stable
pll_locked: Input[uint1_t]

# RGB LED 0 pins, active-high (1 = on)
led0_r: Output[uint1_t]
led0_g: Output[uint1_t]
led0_b: Output[uint1_t]

CLK_MHZ = 25.0
# Clock cycles in half a second
HALF_SEC = int(CLK_MHZ * 1e6 / 2)


@MAIN(CLK_MHZ)
def blinky_main():
    counter: Reg[uint32_t]
    led_reg: Reg[uint1_t]
    # Drive the LED pins
    led0_b = led_reg  # blue blinks
    led0_r = 0
    led0_g = 0
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


# VGA part of the demo: 640x480 uses the same 25 MHz clock as pixel clock
vga_timing = make_vga_timing(VGA_640_480)


def test_pattern(sig: vga_timing_signals_t) -> vga_12bpp_t:
    """XY gradient: R varies horizontally, G vertically, B is XOR diagonal."""
    r: uint4_t = sig.pos.x[7:4]
    g: uint4_t = sig.pos.y[7:4]
    b: uint4_t = sig.pos.x[3:0] ^ sig.pos.y[3:0]
    out_r: uint4_t = 0
    out_g: uint4_t = 0
    out_b: uint4_t = 0
    if sig.active:
        out_r = r
        out_g = g
        out_b = b
    return vga_12bpp_t(r=out_r, g=out_g, b=out_b, hs=sig.hsync, vs=sig.vsync)


@MAIN(vga_timing.pixel_clk_mhz)
def vga_pmod_main():
    # VGA timing for fixed resolution
    sig = vga_timing()
    # Pixel colors, driven out the PMOD pins
    board_vga.vga_pmod = test_pattern(sig)
