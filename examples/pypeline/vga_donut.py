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

DISPLAY_8BIT = False  # False = match 4-bit PMOD output; True = smooth 8-bit sim display

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
            if DISPLAY_8BIT:
                img_data[y, x, 0] = (
                    int(px.r) & 0xFF
                )  # & 0xFF matches hardware uint8_t truncation
                img_data[y, x, 1] = int(px.g) & 0xFF
                img_data[y, x, 2] = int(px.b) & 0xFF
            else:
                # Clamp to uint8 then take upper 4 bits (simulates 4-bit PMOD output)
                v = (int(px.r) & 0xFF) >> 4
                img_data[y, x, 0] = (v << 4) | v
                v = (int(px.g) & 0xFF) >> 4
                img_data[y, x, 1] = (v << 4) | v
                v = (int(px.b) & 0xFF) >> 4
                img_data[y, x, 2] = (v << 4) | v
    if (
        int(sig.pos.y) > 0 and int(sig.pos.x) == 0
    ):  # start of new scan line = previous line just finished
        print("line done.", px.r, px.g, px.b)
        ax_img.set_data(img_data)
        fig.canvas.flush_events()


@atexit.register
def _show_final():
    if fig is not None:
        import matplotlib.pyplot as plt

        plt.ioff()
        ax.set_title("VGA Test Pattern — done")
        plt.show()


# Donut from PipelineC: https://github.com/JulianKemmerer/PipelineC-Graphics/blob/main/donut.cpp

FRAME_WIDTH = VGA_640_480.frame_width  # 640
FRAME_HEIGHT = VGA_640_480.frame_height  # 480
NCORDIC = 6
NITERS = 16
CORDIC_DZ = 5  # ray-sphere offset
CORDIC_R1I = 256  # r1=1, scaled x256
CORDIC_R2I = 512  # r2=2, scaled x256


@struct
class sim_px_t(NamedTuple):
    r: uint8_t
    g: uint8_t
    b: uint8_t
    hs: uint1_t
    vs: uint1_t


@struct
class pair_t(NamedTuple):
    a: int16_t
    b: int16_t


@struct
class full_state_t(NamedTuple):
    sB: int16_t
    cB: int16_t
    sA: int16_t
    cA: int16_t
    sAsB: int16_t
    cAsB: int16_t
    sAcB: int16_t
    cAcB: int16_t
    # Derived per-frame increment values (= trig >> 8, computed pre-rotation)
    yincC: int16_t
    yincS: int16_t
    xincX: int16_t
    xincY: int16_t
    xincZ: int16_t


def length_cordic(x: int16_t, y: int16_t, x2: int16_t, y2: int16_t) -> pair_t:
    cx: int16_t
    cx2: int16_t
    if x < 0:
        cx = -x
        cx2 = -x2
    else:
        cx = x
        cx2 = x2
    cy: int16_t = y
    cy2: int16_t = y2
    for i in range(NCORDIC):
        t: int16_t = cx
        t2: int16_t = cx2
        if cy < 0:
            cx = cx - (cy >> i)
            cy = cy + (t >> i)
            cx2 = cx2 - (cy2 >> i)
            cy2 = cy2 + (t2 >> i)
        else:
            cx = cx + (cy >> i)
            cy = cy - (t >> i)
            cx2 = cx2 + (cy2 >> i)
            cy2 = cy2 - (t2 >> i)
    ra: int16_t = (cx >> 1) + (cx >> 3) - (cx >> 6)
    rb: int16_t = (
        (cx2 >> 1) + (cx2 >> 3) - (cx >> 6)
    )  # last term cx not cx2 (matches C)
    return pair_t(a=ra, b=rb)


def donut(i: int16_t, j: int16_t, state: full_state_t) -> int16_t:
    t: int16_t = 512

    vxi14: int16_t = i * state.xincX - (state.cB + state.sB)
    vyi14: int16_t = (j * state.yincC + state.sAsB - state.sAcB) - i * state.xincY
    vzi14: int16_t = (j * state.yincS - state.cAsB + state.cAcB) + i * state.xincZ

    p0x: int16_t = state.sB * CORDIC_DZ >> 6
    p0y: int16_t = state.sAcB * CORDIC_DZ >> 6
    p0z: int16_t = -state.cAcB * CORDIC_DZ >> 6
    px: int16_t = p0x + (vxi14 >> 5)
    py: int16_t = p0y + (vyi14 >> 5)
    pz: int16_t = p0z + (vzi14 >> 5)

    lx0: int16_t = state.sB >> 2
    ly0: int16_t = state.sAcB - state.cA >> 2  # (sAcB - cA) >> 2
    lz0: int16_t = -state.cAcB - state.sA >> 2  # (-cAcB - sA) >> 2

    d: int16_t = 0
    lz: int16_t = 0

    for _iter in range(NITERS):
        lx: int16_t = lx0
        ly: int16_t = ly0
        lz = lz0

        lc0: pair_t = length_cordic(px, py, lx, ly)
        t0: int16_t = lc0.a
        lx = lc0.b

        t1: int16_t = t0 - CORDIC_R2I
        lc1: pair_t = length_cordic(pz, t1, lz, lx)
        t2: int16_t = lc1.a
        lz = lc1.b

        d = t2 - CORDIC_R1I
        t = t + d

        if (t < 2048) and not (d < 2):
            px = px + (d * vxi14 >> 14)
            py = py + (d * vyi14 >> 14)
            pz = pz + (d * vzi14 >> 14)

    result: int16_t = lz
    if d > 2:
        result = -1
    return result


@hw_func
def full_update(sig: vga_timing_signals_t) -> full_state_t:
    state: Reg[full_state_t]
    initialized: Reg[uint1_t]

    out_state: full_state_t = full_state_t(
        sB=state.sB,
        cB=state.cB,
        sA=state.sA,
        cA=state.cA,
        sAsB=state.sAsB,
        cAsB=state.cAsB,
        sAcB=state.sAcB,
        cAcB=state.cAcB,
        yincC=state.cA >> 8,
        yincS=state.sA >> 8,
        xincX=state.cB >> 8,
        xincY=state.sAsB >> 8,
        xincZ=state.cAsB >> 8,
    )

    if sig.end_of_frame:
        # Magic-circle DDA rotation (14-bit precision)
        # R(s, x, y): x = x-(y>>s); y = y+(x>>s)  — second line uses updated x
        # Pass 1: R(5,...) — cA axis
        new_cA: int16_t = state.cA - (state.sA >> 5)
        new_sA: int16_t = state.sA + (new_cA >> 5)
        new_cAsB: int16_t = state.cAsB - (state.sAsB >> 5)
        new_sAsB: int16_t = state.sAsB + (new_cAsB >> 5)
        new_cAcB: int16_t = state.cAcB - (state.sAcB >> 5)
        new_sAcB: int16_t = state.sAcB + (new_cAcB >> 5)
        # Pass 2: R(6,...) — cB axis, using pass-1 results where applicable
        new_cB: int16_t = state.cB - (state.sB >> 6)
        new_sB: int16_t = state.sB + (new_cB >> 6)
        new_cAcB2: int16_t = new_cAcB - (new_cAsB >> 6)
        new_cAsB2: int16_t = new_cAsB + (new_cAcB2 >> 6)
        new_sAcB2: int16_t = new_sAcB - (new_sAsB >> 6)
        new_sAsB2: int16_t = new_sAsB + (new_sAcB2 >> 6)
        state = full_state_t(
            sB=new_sB,
            cB=new_cB,
            sA=new_sA,
            cA=new_cA,
            sAsB=new_sAsB2,
            cAsB=new_cAsB2,
            sAcB=new_sAcB2,
            cAcB=new_cAcB2,
            yincC=state.cA >> 8,
            yincS=state.sA >> 8,
            xincX=state.cB >> 8,
            xincY=state.sAsB >> 8,
            xincZ=state.cAsB >> 8,
        )

    # Power-on init — overrides zero-init from Reg[T] (last-write wins)
    if not initialized:
        initialized = 1
        state = full_state_t(
            sB=0,
            cB=16384,
            sA=11583,
            cA=11583,
            sAsB=0,
            cAsB=0,
            sAcB=11583,
            cAcB=11583,
            yincC=45,
            yincS=45,
            xincX=64,
            xincY=0,
            xincZ=0,
        )
        out_state = state

    return out_state


def render_pixel(sig: vga_timing_signals_t, state: full_state_t) -> sim_px_t:
    cx: int16_t = (sig.pos.x << 1) - (FRAME_WIDTH + 1)
    cy: int16_t = (FRAME_HEIGHT + 1) - (sig.pos.y << 1)

    r: uint8_t = 0
    g: uint8_t = 0
    b: uint8_t = 0

    if (cx > 0) and (cx < 500) and (cy < 180) and (cy > -180):
        lz: int16_t = donut(cx, cy, state)
        if lz > 0:
            r = lz >> 5  # 8-bit; same shift as original C uint8_t, lz_max~5960 -> 0-186
            g = lz >> 6  # 8-bit; lz_max~5960 -> 0-93; both safe from uint8 wraparound

    return sim_px_t(r=r, g=g, b=b, hs=sig.hsync, vs=sig.vsync)


@MAIN(vga_timing.pixel_clk_mhz)
def vga_donut():
    """Top-level hardware process: generate timing, compute pixel colour, drive board output."""
    sig = vga_timing()
    state = full_update(sig)  # updates once per frame
    px = render_pixel(sig, state)
    board_vga.vga_pmod = vga_12bpp_t(
        r=px.r[7:4], g=px.g[7:4], b=px.b[7:4], hs=px.hs, vs=px.vs
    )
    capture_pixel(sig, px)
