# pyright: reportInvalidTypeForm=none
from pypeline import *
from vga.types import vga_timing_signals_t, vga_pos_t
from dataclasses import dataclass


@dataclass
class VgaTimingSpec:
    frame_width: int
    frame_height: int
    h_fp: int  # horizontal front porch
    h_pw: int  # horizontal sync pulse width
    h_max: int  # total horizontal pixels per line
    v_fp: int  # vertical front porch
    v_pw: int  # vertical sync pulse width
    v_max: int  # total vertical lines per frame
    h_pol: int  # hsync polarity (0=active-low, 1=active-high)
    v_pol: int  # vsync polarity
    pixel_clk_mhz: float


VGA_640_480 = VgaTimingSpec(640, 480, 16, 96, 800, 10, 2, 525, 0, 0, 25.0)
VGA_800_600 = VgaTimingSpec(800, 600, 40, 128, 1056, 1, 4, 628, 1, 1, 40.0)
VGA_1280_720 = VgaTimingSpec(1280, 720, 110, 40, 1650, 5, 5, 750, 1, 1, 74.25)
VGA_1920_1080 = VgaTimingSpec(1920, 1080, 88, 44, 2200, 4, 5, 1125, 1, 1, 148.5)


def make_vga_timing(spec: VgaTimingSpec, h_start: int = 0, v_start: int = 0):
    """
    Returns a hw_func implementing beam-chase VGA timing for the given spec.

    Closure integer constants resolve as elaboration-time values via _try_eval_const,
    so no hardware comparator logic is emitted for threshold checks.
    Counter registers are sized to the minimum width for the resolution.
    Sync polarity is applied inside — callers receive correctly-polled signals.

    h_start / v_start: initial counter values (default 0,0 = normal start of frame).
    Set v_start to a mid-frame line to skip blank scan lines in simulation so pixels
    of interest are reached sooner. Has no effect in hardware when both are 0.
    """
    FRAME_WIDTH = spec.frame_width
    FRAME_HEIGHT = spec.frame_height
    H_SYNC_START = spec.frame_width + spec.h_fp
    H_SYNC_END = H_SYNC_START + spec.h_pw
    H_MAX = spec.h_max
    V_SYNC_START = spec.frame_height + spec.v_fp
    V_SYNC_END = V_SYNC_START + spec.v_pw
    V_MAX = spec.v_max
    H_POL = spec.h_pol
    V_POL = spec.v_pol
    H_START = h_start
    V_START = v_start
    # Size counters to the minimum bit-width needed for this resolution
    h_uint = make_uint_t(spec.h_max.bit_length())  # e.g. 800 → 10 bits
    v_uint = make_uint_t(spec.v_max.bit_length())  # e.g. 525 → 10 bits

    @hw_func
    def vga_timing() -> vga_timing_signals_t:
        h_cntr: Reg[h_uint] = H_START
        v_cntr: Reg[v_uint] = V_START

        # Derive all signals from CURRENT counter values (beam-chase: derive then advance)
        pos = vga_pos_t(x=h_cntr, y=v_cntr)
        active = (h_cntr < FRAME_WIDTH) & (v_cntr < FRAME_HEIGHT)
        hsync = ((h_cntr >= H_SYNC_START) & (h_cntr < H_SYNC_END)) ^ H_POL
        vsync = ((v_cntr >= V_SYNC_START) & (v_cntr < V_SYNC_END)) ^ V_POL
        start_of_frame = (h_cntr == 0) & (v_cntr == 0)
        end_of_frame = (h_cntr == (H_MAX - 1)) & (v_cntr == (V_MAX - 1))

        rv = vga_timing_signals_t(
            pos=pos,
            hsync=hsync,
            vsync=vsync,
            active=active,
            start_of_frame=start_of_frame,
            end_of_frame=end_of_frame,
        )

        # Advance counters after deriving
        if h_cntr == (H_MAX - 1):
            h_cntr = 0
            v_cntr = 0 if (v_cntr == (V_MAX - 1)) else (v_cntr + 1)
        else:
            h_cntr = h_cntr + 1

        return rv

    vga_timing.pixel_clk_mhz = spec.pixel_clk_mhz
    return vga_timing
