# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""pico-ice / pico2-ice VGA test pattern on a 12-bit VGA PMOD in PMOD0 + PMOD1.

The same test pattern as ../vga_test_pattern.py, using the pico-ice board
module instead of the Arty one. Build with:

    make clean all PYPELINE_TOP_FILE=vga_top.py

Top-level IO here must match top.sv (the wrapper) and ice40.pcf (the pins).
"""

import os

from pypeline import *

# VGA PMOD output wire, driving ports named after the ICE_XX pins
import board.pico_ice.vga_pmod01 as board_vga
from vga.types import vga_timing_signals_t, vga_12bpp_t
from vga.timing import make_vga_timing, VGA_640_480

PART("ICE40UP5K-SG48")  # iCE40 UltraPlus 5K, on both the pico-ice and pico2-ice

PLL_CLK_MHZ = float(os.environ.get("PLL_CLK_MHZ", "25.0"))

vga_timing = make_vga_timing(VGA_640_480)
# Plain Python check at elaboration time: the PLL must make the pixel clock
if PLL_CLK_MHZ != vga_timing.pixel_clk_mhz:
    raise ValueError(
        f"640x480 VGA needs a {vga_timing.pixel_clk_mhz} MHz pixel clock, "
        f"build with PLL_CLK_MHZ={vga_timing.pixel_clk_mhz}"
    )

# Clock input from the PLL in top.sv, named to match the wrapper
pll_clk: Input[uint1_t] = make_clock(PLL_CLK_MHZ)


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
