# pyright: reportInvalidTypeForm=none
"""VGA test pattern — hardware design + simulation display.

Hardware: compiles with pipelinec to drive a VGA monitor via the Arty A7 PMOD connectors.
Simulation: run with pypeline_sim.py for a live matplotlib display.

    python3 src/pypeline_sim.py examples/pypeline/vga_test_pattern.py --run 420000

One frame = 800 x 525 = 420 000 cycles (640x480 @ 25 MHz pixel clock).
"""

import sys, os
import atexit

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "include", "pypeline"
    ),
)

from pypeline import *

# Board info:
import board.arty.part35t  # sets PART pragma for this board
import board.arty.vga_pmod_ja_jb as board_vga  # swap for different board/connector
# import board.arty.vga_pmod_jc_jd  as board_vga
# import board.pico_ice.vga_pmod01  as board_vga

# VGA info:
from vga.types import vga_timing_signals_t, vga_12bpp_t
from vga.timing import make_vga_timing, VGA_640_480

vga_timing = make_vga_timing(VGA_640_480)  # swap spec for different resolution

# ── Sim-only display state (plain Python) ─
img_data = None  # H×W×3 uint8 numpy array, lazily created
ax_img = None  # matplotlib AxesImage handle
fig = None
ax = None


@sim_output  # @sim_output — skipped by pipelinec, runs in sim
def capture_pixel(sig, px):
    """Accumulate pixels into a numpy image and refresh the display each scan line.

    Lazily initialises the matplotlib figure on first call.  4-bit colour channels
    are expanded to 8-bit by replicating the nibble: v → (v << 4) | v.
    Called once per cycle in the final pass; skipped during convergence.
    Invisible to the hardware elaborator (pipelinec) via the @sim_output guard.
    """
    global img_data, ax_img, fig, ax
    if fig is None:
        import matplotlib.pyplot as plt
        import numpy as np

        plt.ion()
        fig, ax = plt.subplots(figsize=(8, 6))
        img_data = np.zeros(
            (VGA_640_480.frame_height, VGA_640_480.frame_width, 3), dtype="uint8"
        )
        ax_img = ax.imshow(img_data, vmin=0, vmax=255)
        ax.axis("off")
        plt.tight_layout()
        plt.show(block=False)
        fig.canvas.flush_events()
    if int(sig.active):
        x, y = int(sig.pos.x), int(sig.pos.y)
        if 0 <= x < VGA_640_480.frame_width and 0 <= y < VGA_640_480.frame_height:
            v = int(px.r)
            img_data[y, x, 0] = (v << 4) | v
            v = int(px.g)
            img_data[y, x, 1] = (v << 4) | v
            v = int(px.b)
            img_data[y, x, 2] = (v << 4) | v
    if int(sig.pos.x) == 0:  # start of new scan line = previous line just finished
        ax_img.set_data(img_data)
        fig.canvas.flush_events()


@atexit.register
def _show_final():
    if fig is not None:
        import matplotlib.pyplot as plt

        plt.ioff()
        ax.set_title("VGA Test Pattern — done")
        plt.show()


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
def vga_test_pattern():
    """Top-level hardware process: generate timing, compute pixel colour, drive board output."""
    sig = vga_timing()
    px = test_pattern(sig)
    board_vga.vga_pmod = px
    capture_pixel(sig, px)
