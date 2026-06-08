# pyright: reportInvalidTypeForm=none
import sys, os

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "include", "pypeline"
    ),
)

from pypeline import *
import board.arty.vga_pmod_ja_jb as board_vga  # ← swap for different board/connector
# import board.arty.vga_pmod_jc_jd  as board_vga
# import board.pico_ice.vga_pmod01  as board_vga

from vga.types import vga_timing_signals_t, vga_12bpp_t
from vga.timing import make_vga_timing, VGA_640_480

uint4_t = make_uint(4)
vga_timing = make_vga_timing(VGA_640_480)  # ← swap spec for different resolution


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


@MAIN
def vga_test_pattern():
    sig = vga_timing()
    board_vga.vga_pmod = test_pattern(sig)
