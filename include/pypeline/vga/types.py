# pyright: reportInvalidTypeForm=none
from pypeline import *

uint12_t = make_uint_t(12)
uint4_t = make_uint_t(4)


@struct
class vga_pos_t(NamedTuple):
    x: uint12_t
    y: uint12_t


@struct
class vga_timing_signals_t(NamedTuple):
    """Output of vga_timing() — position, sync (polarity already applied), active window."""

    pos: vga_pos_t
    hsync: uint1_t
    vsync: uint1_t
    active: uint1_t
    start_of_frame: uint1_t
    end_of_frame: uint1_t


@struct
class vga_12bpp_t(NamedTuple):
    """12-bit colour (4R + 4G + 4B) plus sync — the VGA PMOD logical interface."""

    r: uint4_t
    g: uint4_t
    b: uint4_t
    hs: uint1_t
    vs: uint1_t
