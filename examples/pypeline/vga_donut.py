# pyright: reportInvalidTypeForm=none
"""VGA donut — hardware design + simulation display.

Hardware: compiles with pipelinec to drive a VGA monitor via the Arty A7 PMOD connectors.
Simulation: run with pypeline_sim.py for a live matplotlib display.

    python3 src/pypeline_sim.py examples/pypeline/vga_donut.py --run <cycles>

Cycles per frame by resolution:
    640×480   (VGA_640_480)  : 800  × 525  =   420 000
    1280×720  (VGA_1280_720) : 1650 × 750  = 1 237 500
    1920×1080 (VGA_1920_1080): 2200 × 1125 = 2 475 000
"""

import sys, os
import atexit
import math

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "include", "pypeline"
    ),
)

from pypeline import *

# Board info:
import board.arty.part100t  # sets PART pragma for this board
import board.arty.vga_pmod_ja_jb as board_vga

# VGA info:
from vga.types import vga_timing_signals_t, vga_12bpp_t
from vga.timing import (
    make_vga_timing,
    VGA_640_480,
    VGA_800_600,
    VGA_1280_720,
    VGA_1920_1080,
)

# ── CONFIG ──────────────────────────────────────────────────────────────────
RESOLUTION = VGA_640_480  # swapable
CALC_FRAC_BITS = 0  # Extra CORDIC precision bits (0 = blocky/minimum, 4-8 = smooth)
NCORDIC = 6  # CORDIC iterations per call  (6 = original; 8+ = smoother)
NITERS = 16  # ray-march steps             (16 = original; 24+ = smoother)
CORDIC_DZ = 5  # ray-sphere offset
SCALE = 1  # coordinate units per pixel  (2 = original; 1 = 2x larger donut)
BOUNCE = True  # True = emit bounce-animation hardware
BOUNCE_SPEED_X = 3  # pixels per frame (horizontal)
BOUNCE_SPEED_Y = 2  # pixels per frame (vertical)
DITHER = True  # Bayer ordered dither: smooth 4-bit PMOD output

# ── Derived elaboration-time values ──────────────────────────────────────────
TORUS_R1I = RESOLUTION.frame_height // 3  # tube radius x 256
TORUS_R2I = TORUS_R1I * 2  # ring radius x 256
FRAME_WIDTH = RESOLUTION.frame_width
FRAME_HEIGHT = RESOLUTION.frame_height

# 1. Calculate precise physics and rendering bounds from Torus geometry
MAX_GEOMETRY = TORUS_R1I + TORUS_R2I
RAY_STEP_RATIO = 2  # Derived from (xincX max 64) >> 5

BOUNCE_RADIUS = MAX_GEOMETRY // (RAY_STEP_RATIO * SCALE)
DONUT_PX = (
    BOUNCE_RADIUS + 5
)  # Add a 5px safety margin so the edge anti-aliasing doesn't clip
DONUT_BOUND = DONUT_PX * SCALE

BOUNCE_MAX_X = FRAME_WIDTH // 2 - BOUNCE_RADIUS
BOUNCE_MAX_Y = FRAME_HEIGHT // 2 - BOUNCE_RADIUS

# lz magnitude ~5960 max with default trig-state scale; >>5 -> 0-186, fits uint8_t.
LZ_SHIFT = 5

# 2. Auto-calculate minimum screen coordinate width
max_coord_val = max(FRAME_WIDTH, FRAME_HEIGHT)
COORD_WIDTH = int(math.ceil(math.log2(max_coord_val))) + 1

# 3. Auto-calculate safe CORDIC math width based on the newly derived bounds
max_calc_val = (DONUT_BOUND * 128) + 32768
min_calc_width = int(math.ceil(math.log2(max_calc_val))) + 1  # +1 for signed
CALC_WIDTH = min_calc_width + CALC_FRAC_BITS

# ── Configuration Validation ────────────────────────────────────────────────
# Validate Bounce limits
if BOUNCE:
    if BOUNCE_RADIUS > FRAME_WIDTH // 2 or BOUNCE_RADIUS > FRAME_HEIGHT // 2:
        raise ValueError(
            f"BOUNCE_RADIUS ({BOUNCE_RADIUS}) is too large for a {FRAME_WIDTH}x{FRAME_HEIGHT} screen."
        )

# ── Hardware types ────────────────────────────────────────────────────────────
coord_t = make_int(COORD_WIDTH)
calc_t = make_int(CALC_WIDTH)

# Sim start line: skip blank rows above the donut to reach pixels of interest sooner.
# Set to 0 for a complete frame (hardware always uses 0 via the default).
SIM_V_START = max(0, FRAME_HEIGHT // 3)
vga_timing = make_vga_timing(RESOLUTION, v_start=SIM_V_START)
DISPLAY_8BIT = False  # False = match 4-bit PMOD output; True = smooth 8-bit sim display

# ── Sim-only display state (plain Python) ────────────────────────────────────
img_data = None
ax_img = None
fig = None
ax = None


@sim_output
def capture_pixel(sig, px):
    """Accumulate pixels into a numpy image; refresh display each scan line."""
    global img_data, ax_img, fig, ax
    if fig is None:
        import matplotlib.pyplot as plt
        import numpy as np

        plt.ion()
        fig, ax = plt.subplots(figsize=(8, 6))
        img_data = np.zeros(
            (RESOLUTION.frame_height, RESOLUTION.frame_width, 3), dtype="uint8"
        )
        ax_img = ax.imshow(img_data, vmin=0, vmax=255)
        ax.axis("off")
        plt.tight_layout()
        plt.show(block=False)
        fig.canvas.flush_events()
    if int(sig.active):
        x, y = int(sig.pos.x), int(sig.pos.y)
        if 0 <= x < RESOLUTION.frame_width and 0 <= y < RESOLUTION.frame_height:
            if DISPLAY_8BIT:
                img_data[y, x, 0] = int(px.r) & 0xFF
                img_data[y, x, 1] = int(px.g) & 0xFF
                img_data[y, x, 2] = int(px.b) & 0xFF
            else:
                v = (int(px.r) & 0xFF) >> 4
                img_data[y, x, 0] = (v << 4) | v
                v = (int(px.g) & 0xFF) >> 4
                img_data[y, x, 1] = (v << 4) | v
                v = (int(px.b) & 0xFF) >> 4
                img_data[y, x, 2] = (v << 4) | v
    if int(sig.pos.y) > 0 and int(sig.pos.x) == 0:
        print("line done.", x, y, px.r, px.g, px.b)
        ax_img.set_data(img_data)
        fig.canvas.flush_events()


@atexit.register
def show_final():
    if fig is not None:
        import matplotlib.pyplot as plt

        plt.ioff()
        ax.set_title("VGA Donut — done")
        plt.show()


# ── Donut raymarcher ─────────────────────────────────────────────────────────
# Ported from: https://github.com/JulianKemmerer/PipelineC-Graphics/blob/main/donut.cpp


@struct
class sim_px_t(NamedTuple):
    r: uint8_t
    g: uint8_t
    b: uint8_t
    hs: uint1_t
    vs: uint1_t


@struct
class pair_t(NamedTuple):
    a: calc_t
    b: calc_t


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
    # Derived per-frame increment values (trig >> 8, computed pre-rotation)
    yincC: int16_t
    yincS: int16_t
    xincX: int16_t
    xincY: int16_t
    xincZ: int16_t
    # Donut screen-centre in pixel coordinates (FRAME_WIDTH//2, FRAME_HEIGHT//2 = centred)
    pos_x: int16_t
    pos_y: int16_t


def make_length_cordic(c_t, ncordic):
    @hw_func
    def length_cordic(x: c_t, y: c_t, x2: c_t, y2: c_t) -> pair_t:
        cx: c_t
        cx2: c_t
        if x < 0:
            cx = -x
            cx2 = -x2
        else:
            cx = x
            cx2 = x2
        cy: c_t = y
        cy2: c_t = y2
        for i in range(ncordic):
            t: c_t = cx
            t2: c_t = cx2
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
        ra: c_t = (cx >> 1) + (cx >> 3) - (cx >> 6)
        rb: c_t = (
            (cx2 >> 1) + (cx2 >> 3) - (cx >> 6)
        )  # last term cx not cx2 (matches C)
        return pair_t(a=ra, b=rb)

    return length_cordic


def make_donut(c_t, co_t, lc_fn, niters, r1i, r2i, scale):
    @hw_func
    def donut(cx: co_t, cy: co_t, state: full_state_t) -> c_t:
        # cx/cy are pixel offsets from donut centre; scale converts to internal coordinate space
        # X-axis math requires the 256 offset to center the CORDIC projection
        i: c_t = (cx * scale) + 256
        # Y-axis mathematical center natively rests at 0
        j: c_t = cy * scale
        t: c_t = 512
        vxi14: c_t = i * state.xincX - (state.cB + state.sB)
        vyi14: c_t = (j * state.yincC + state.sAsB - state.sAcB) - i * state.xincY
        vzi14: c_t = (j * state.yincS - state.cAsB + state.cAcB) + i * state.xincZ
        p0x: c_t = state.sB * CORDIC_DZ >> 6
        p0y: c_t = state.sAcB * CORDIC_DZ >> 6
        p0z: c_t = -state.cAcB * CORDIC_DZ >> 6
        px: c_t = p0x + (vxi14 >> 5)
        py: c_t = p0y + (vyi14 >> 5)
        pz: c_t = p0z + (vzi14 >> 5)
        lx0: c_t = state.sB >> 2
        ly0: c_t = state.sAcB - state.cA >> 2
        lz0: c_t = -state.cAcB - state.sA >> 2
        d: c_t = 0
        lz: c_t = 0
        for iter in range(niters):
            lx: c_t = lx0
            ly: c_t = ly0
            lz = lz0
            lc0: pair_t = lc_fn(px, py, lx, ly)
            t0: c_t = lc0.a
            lx = lc0.b
            t1: c_t = t0 - r2i
            lc1: pair_t = lc_fn(pz, t1, lz, lx)
            t2: c_t = lc1.a
            lz = lc1.b
            d = t2 - r1i
            t = t + d
            if (t < 2048) and not (d < 2):
                px = px + (d * vxi14 >> 14)
                py = py + (d * vyi14 >> 14)
                pz = pz + (d * vzi14 >> 14)
        result: c_t = lz
        if d > 2:
            result = -1
        return result

    return donut


length_cordic = make_length_cordic(calc_t, NCORDIC)
donut = make_donut(calc_t, coord_t, length_cordic, NITERS, TORUS_R1I, TORUS_R2I, SCALE)


@hw_func
def full_update(sig: vga_timing_signals_t) -> full_state_t:
    state: Reg[full_state_t] = full_state_t(
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
        pos_x=FRAME_WIDTH // 2,
        pos_y=FRAME_HEIGHT // 2,
    )
    bounce_vel_x: Reg[int16_t] = BOUNCE_SPEED_X if BOUNCE else 0
    bounce_vel_y: Reg[int16_t] = BOUNCE_SPEED_Y if BOUNCE else 0

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
        pos_x=state.pos_x,
        pos_y=state.pos_y,
    )

    if sig.end_of_frame:
        # Magic-circle DDA rotation: R(s, x, y): x = x-(y>>s); y = y+(x>>s)
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

        new_pos_x: int16_t = state.pos_x
        new_pos_y: int16_t = state.pos_y
        if BOUNCE:
            new_pos_x = state.pos_x + bounce_vel_x
            new_pos_y = state.pos_y + bounce_vel_y
            new_vel_x: int16_t = bounce_vel_x
            new_vel_y: int16_t = bounce_vel_y
            if (new_pos_x > FRAME_WIDTH // 2 + BOUNCE_MAX_X) or (
                new_pos_x < FRAME_WIDTH // 2 - BOUNCE_MAX_X
            ):
                new_vel_x = -bounce_vel_x
            if (new_pos_y > FRAME_HEIGHT // 2 + BOUNCE_MAX_Y) or (
                new_pos_y < FRAME_HEIGHT // 2 - BOUNCE_MAX_Y
            ):
                new_vel_y = -bounce_vel_y
            bounce_vel_x = new_vel_x
            bounce_vel_y = new_vel_y

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
            pos_x=new_pos_x,
            pos_y=new_pos_y,
        )

    return out_state


def dither4(v: uint8_t, x: uint12_t, y: uint12_t) -> uint4_t:
    # 4x4 Bayer ordered dither matrix (thresholds 0-15), row-major flattened
    bayer: uint4_t[16] = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]  # type: ignore[name-defined]
    thresh: uint4_t = 0
    for row in range(4):
        for col in range(4):
            if (y[1:0] == row) and (x[1:0] == col):
                thresh = bayer[row * 4 + col]
    q4: uint4_t = v[7:4]
    frac: uint4_t = v[3:0]
    result: uint4_t = q4
    if (frac > thresh) and (q4 < 15):
        result = q4 + 1
    return result


@hw_func
def render_pixel(sig: vga_timing_signals_t, state: full_state_t) -> sim_px_t:
    px_s: int16_t = sig.pos.x
    py_s: int16_t = sig.pos.y
    cx: coord_t = px_s - state.pos_x  # pixel offset from donut centre, rightward +
    cy: coord_t = state.pos_y - py_s  # pixel offset from donut centre, upward +

    r: uint8_t = 0
    g: uint8_t = 0
    b: uint8_t = 0

    if (cx > -DONUT_PX) and (cx < DONUT_PX) and (cy > -DONUT_PX) and (cy < DONUT_PX):
        # if True:
        lz_raw: calc_t = donut(cx, cy, state)
        if lz_raw > 0:
            lz: uint8_t = lz_raw >> LZ_SHIFT
            r = lz
            g = lz >> 1

    return sim_px_t(r=r, g=g, b=b, hs=sig.hsync, vs=sig.vsync)


@MAIN(vga_timing.pixel_clk_mhz)
def vga_donut():
    """Top-level hardware process: generate timing, compute pixel colour, drive board output."""
    sig = vga_timing()
    state = full_update(sig)
    px = render_pixel(sig, state)

    if DITHER:
        r4: uint4_t = dither4(px.r, sig.pos.x, sig.pos.y)
        g4: uint4_t = dither4(px.g, sig.pos.x, sig.pos.y)
        b4: uint4_t = dither4(px.b, sig.pos.x, sig.pos.y)
    else:
        r4: uint4_t = px.r[7:4]
        g4: uint4_t = px.g[7:4]
        b4: uint4_t = px.b[7:4]

    board_vga.vga_pmod = vga_12bpp_t(r=r4, g=g4, b=b4, hs=px.hs, vs=px.vs)
    capture_pixel(sig, px)
