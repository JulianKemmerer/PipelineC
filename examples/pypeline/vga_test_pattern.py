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

# ── Sim-only display state (plain Python; harmless at import / compile time) ─
_img_data = None  # H×W×3 uint8 numpy array, lazily created
_ax_img = None  # matplotlib AxesImage handle
_fig = None
_ax = None


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


@sim_output
def capture_pixel(sig, px):
    global _img_data, _ax_img, _fig, _ax
    if _fig is None:
        import matplotlib.pyplot as plt
        import numpy as np

        plt.ion()
        _fig, _ax = plt.subplots(figsize=(8, 6))
        _img_data = np.zeros(
            (VGA_640_480.frame_height, VGA_640_480.frame_width, 3), dtype="uint8"
        )
        _ax_img = _ax.imshow(_img_data, vmin=0, vmax=255)
        _ax.axis("off")
        plt.tight_layout()
        plt.show(block=False)
        _fig.canvas.flush_events()
    if int(sig.active):
        x, y = int(sig.pos.x), int(sig.pos.y)
        if 0 <= x < VGA_640_480.frame_width and 0 <= y < VGA_640_480.frame_height:
            v = int(px.r)
            _img_data[y, x, 0] = (v << 4) | v
            v = int(px.g)
            _img_data[y, x, 1] = (v << 4) | v
            v = int(px.b)
            _img_data[y, x, 2] = (v << 4) | v
    if int(sig.pos.x) == 0:  # start of new scan line = previous line just finished
        _ax_img.set_data(_img_data)
        _fig.canvas.flush_events()


import atexit


@atexit.register
def _show_final():
    if _fig is not None:
        import matplotlib.pyplot as plt

        plt.ioff()
        _ax.set_title("VGA Test Pattern — done")
        plt.show()


@MAIN
def vga_test_pattern():
    sig = vga_timing()
    px = test_pattern(sig)
    board_vga.vga_pmod = px
    capture_pixel(sig, px)  # @sim_output — skipped by pipelinec, runs in sim
