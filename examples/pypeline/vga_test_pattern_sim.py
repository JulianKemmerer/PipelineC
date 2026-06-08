#!/usr/bin/env python3
"""
VGA test-pattern software simulation.

Runs the same vga_timing + test_pattern logic through the pypeline sim engine
and renders each completed frame to a matplotlib window (live, per-frame).

Usage:
    python3 examples/pypeline/vga_test_pattern_sim.py [--frames N]

One frame of 640x480 @ 25 MHz = 800 x 525 = 420,000 sim cycles (~10s on typical hardware).
"""

import sys, os, argparse

_REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_REPO, "src"))
sys.path.insert(0, os.path.join(_REPO, "include", "pypeline"))

import pypeline
from pypeline import *
import pypeline_sim

from vga.types import vga_timing_signals_t, vga_12bpp_t
from vga.timing import make_vga_timing, VGA_640_480

uint4_t = make_uint(4)
_SPEC = VGA_640_480
_W = _SPEC.frame_width  # 640
_H = _SPEC.frame_height  # 480
_H_MAX = _SPEC.h_max  # 800
_V_MAX = _SPEC.v_max  # 525
_CYCLES_PER_FRAME = _H_MAX * _V_MAX  # 420,000

vga_timing = make_vga_timing(_SPEC)


def test_pattern(sig: vga_timing_signals_t) -> vga_12bpp_t:
    """XY gradient — matches vga_test_pattern.py exactly."""
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


# -- pixel accumulation (shared between @sim_output and runner) ---------------

_frame_buf: dict = {}  # (x, y) → (r8, g8, b8)
_frame_flags = [False]  # [0] = end_of_frame seen this cycle


@sim_output
def on_pixel(sig, px):
    if int(sig.active):
        x, y = int(sig.pos.x), int(sig.pos.y)
        r8 = (int(px.r) << 4) | int(px.r)  # 4-bit → 8-bit: 0xF → 0xFF
        g8 = (int(px.g) << 4) | int(px.g)
        b8 = (int(px.b) << 4) | int(px.b)
        _frame_buf[(x, y)] = (r8, g8, b8)
    if int(sig.end_of_frame):
        _frame_flags[0] = True


@MAIN
def sim_vga():
    sig = vga_timing()
    px = test_pattern(sig)
    on_pixel(sig, px)


# -- renderer -----------------------------------------------------------------


def _build_image():
    import numpy as np

    img = np.zeros((_H, _W, 3), dtype="uint8")
    for (x, y), (r, g, b) in _frame_buf.items():
        if 0 <= x < _W and 0 <= y < _H:
            img[y, x] = (r, g, b)
    return img


# -- main runner --------------------------------------------------------------


def run(num_frames: int = 1) -> None:
    import numpy as np
    import matplotlib.pyplot as plt

    mains = list(pypeline._main_registry)
    pypeline.sim_reset()
    pypeline._sim_wire_readers.clear()

    plt.ion()
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.set_title("VGA Test Pattern — simulating…")
    ax.axis("off")
    placeholder = np.zeros((_H, _W, 3), dtype="uint8")
    ax_img = ax.imshow(placeholder, vmin=0, vmax=255)
    plt.tight_layout()
    plt.show(block=False)
    fig.canvas.flush_events()

    total_cycles = num_frames * _CYCLES_PER_FRAME
    frame_num = 0

    for cycle in range(total_cycles):
        _frame_flags[0] = False
        pypeline_sim._run_clock_cycle(mains, cycle)

        if _frame_flags[0]:
            frame_num += 1
            img = _build_image()
            _frame_buf.clear()
            ax_img.set_data(img)
            ax.set_title(f"VGA Test Pattern (640×480) — frame {frame_num}/{num_frames}")
            fig.canvas.draw()
            fig.canvas.flush_events()
            print(f"  frame {frame_num}/{num_frames} rendered", flush=True)

    plt.ioff()
    ax.set_title(f"VGA Test Pattern — {frame_num} frame(s) simulated")
    plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="VGA test-pattern pypeline simulation with matplotlib display."
    )
    parser.add_argument(
        "--frames",
        metavar="N",
        type=int,
        default=1,
        help="Number of frames to simulate (default: 1 = 420,000 cycles).",
    )
    args = parser.parse_args()
    run(args.frames)
