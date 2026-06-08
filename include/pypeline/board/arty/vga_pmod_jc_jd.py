# pyright: reportInvalidTypeForm=none
"""
Arty A7 VGA PMOD — JC + JD connector pair.

Identical layer structure to vga_pmod_ja_jb.py; only the Output pin names differ.
Demonstrates 1-import-line connector swap:
  import board.arty.vga_pmod_ja_jb as board_vga   →   vga_pmod_ja_jb
  import board.arty.vga_pmod_jc_jd as board_vga   →   this file

Output port names match board.vhd:
  jc_1(0) => jc(1), jc_2(0) => jc(2), ... jd_5(0) => jd(5)
Note: jc_0 is not mapped in stock board.vhd (used for tristate); JD is fully available.
"""

from pypeline import *
from vga.types import vga_12bpp_t
from pmod.types import pmod8_t

vga_pmod: Wire[vga_12bpp_t]

pmod_a_wire: Wire[pmod8_t]
pmod_b_wire: Wire[pmod8_t]

# JC upper row → R[0-3], JC lower row → B[0-3]
jc_1: Output[uint1_t]
jc_2: Output[uint1_t]
jc_3: Output[uint1_t]
jc_4: Output[uint1_t]  # Note: jc_0 skipped
jc_5: Output[uint1_t]
jc_6: Output[uint1_t]
jc_7: Output[uint1_t]
# JD upper row → G[0-3], JD lower row → HS, VS
jd_0: Output[uint1_t]
jd_1: Output[uint1_t]
jd_2: Output[uint1_t]
jd_3: Output[uint1_t]
jd_4: Output[uint1_t]
jd_5: Output[uint1_t]


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


@MAIN
def pmod8_to_jc_jd():
    jc_1 = pmod_a_wire.p1
    jc_2 = pmod_a_wire.p2
    jc_3 = pmod_a_wire.p3
    jc_4 = pmod_a_wire.p4
    jc_5 = pmod_a_wire.p5
    jc_6 = pmod_a_wire.p6
    jc_7 = pmod_a_wire.p7
    jd_0 = pmod_b_wire.p1
    jd_1 = pmod_b_wire.p2
    jd_2 = pmod_b_wire.p3
    jd_3 = pmod_b_wire.p4
    jd_4 = pmod_b_wire.p5
    jd_5 = pmod_b_wire.p6
