# pyright: reportInvalidTypeForm=none
"""
Arty A7 VGA PMOD — JA + JB connector pair.

Layer A (@MAIN vga_to_pmod8):   vga_12bpp_t  →  pmod8_t pair
Layer B (@MAIN pmod8_to_ja_jb): pmod8_t pair →  individual Output pins

Output port names match board.vhd exactly:
  ja_0(0) => ja(0), ja_1(0) => ja(1), ... jb_5(0) => jb(5)

Board swap:  replace this import with board.arty.vga_pmod_jc_jd
             or board.pico_ice.vga_pmod01 etc.
"""

from pypeline import *
from vga.types import vga_12bpp_t
from pmod.types import pmod8_t

# ── App interface (written by the app @MAIN via board_vga.vga_pmod = ...) ────
vga_pmod: Wire[vga_12bpp_t]

# ── Internal intermediates (module-prefixed, invisible outside this file) ────
pmod_a_wire: Wire[pmod8_t]  # carries R[0-3] (upper row) + B[0-3] (lower row)
pmod_b_wire: Wire[pmod8_t]  # carries G[0-3] (upper row) + HS, VS (lower row)

# ── Board Output pins — no module prefix (I/O rule) → VHDL ports ja_0..jb_5 ─
ja_0: Output[uint1_t]
ja_1: Output[uint1_t]
ja_2: Output[uint1_t]
ja_3: Output[uint1_t]
ja_4: Output[uint1_t]
ja_5: Output[uint1_t]
ja_6: Output[uint1_t]
ja_7: Output[uint1_t]
jb_0: Output[uint1_t]
jb_1: Output[uint1_t]
jb_2: Output[uint1_t]
jb_3: Output[uint1_t]
jb_4: Output[uint1_t]
jb_5: Output[uint1_t]


# ── Layer A: vga_12bpp_t → typed PMOD struct pair ─────────────────────────────
@MAIN
def vga_to_pmod8():
    pmod_a_wire = pmod8_t(
        p1=vga_pmod.r[0],
        p2=vga_pmod.r[1],
        p3=vga_pmod.r[2],
        p4=vga_pmod.r[3],
        p5=vga_pmod.b[0],
        p6=vga_pmod.b[1],
        p7=vga_pmod.b[2],
        p8=vga_pmod.b[3],
    )
    pmod_b_wire = pmod8_t(
        p1=vga_pmod.g[0],
        p2=vga_pmod.g[1],
        p3=vga_pmod.g[2],
        p4=vga_pmod.g[3],
        p5=vga_pmod.hs,
        p6=vga_pmod.vs,
        p7=0,
        p8=0,
    )


# ── Layer B: typed PMOD struct pair → individual board pins ──────────────────
@MAIN
def pmod8_to_ja_jb():
    ja_0 = pmod_a_wire.p1
    ja_1 = pmod_a_wire.p2
    ja_2 = pmod_a_wire.p3
    ja_3 = pmod_a_wire.p4
    ja_4 = pmod_a_wire.p5
    ja_5 = pmod_a_wire.p6
    ja_6 = pmod_a_wire.p7
    ja_7 = pmod_a_wire.p8
    jb_0 = pmod_b_wire.p1
    jb_1 = pmod_b_wire.p2
    jb_2 = pmod_b_wire.p3
    jb_3 = pmod_b_wire.p4
    jb_4 = pmod_b_wire.p5
    jb_5 = pmod_b_wire.p6
