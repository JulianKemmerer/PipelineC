# pyright: reportInvalidTypeForm=none
"""
pico-ice VGA PMOD — PMOD0 + PMOD1 connector pair.

Output port names are ICE_XX physical pin names matching top.sv and ice40.pcf:
  PMOD_0A: ICE_4 (O1), ICE_2 (O2), ICE_47 (O3), ICE_45 (O4)  → R[0-3]
  PMOD_0B: ICE_3 (O1), ICE_48 (O2), ICE_46 (O3), ICE_44 (O4) → B[0-3]
  PMOD_1A: ICE_31(O1), ICE_34(O2), ICE_38 (O3), ICE_43 (O4)  → G[0-3]
  PMOD_1B: ICE_28(O1/HS), ICE_32(O2/VS)

Board swap: replace board.arty.vga_pmod_ja_jb import with this file.
"""

from pypeline import *
from vga.types import vga_12bpp_t
from pmod.types import pmod8_t

vga_pmod: Wire[vga_12bpp_t]

pmod_a_wire: Wire[pmod8_t]
pmod_b_wire: Wire[pmod8_t]

# PMOD0A → R[0-3], PMOD0B → B[0-3]
ICE_4: Output[uint1_t]
ICE_2: Output[uint1_t]
ICE_47: Output[uint1_t]
ICE_45: Output[uint1_t]
ICE_3: Output[uint1_t]
ICE_48: Output[uint1_t]
ICE_46: Output[uint1_t]
ICE_44: Output[uint1_t]
# PMOD1A → G[0-3], PMOD1B → HS, VS
ICE_31: Output[uint1_t]
ICE_34: Output[uint1_t]
ICE_38: Output[uint1_t]
ICE_43: Output[uint1_t]
ICE_28: Output[uint1_t]  # HS
ICE_32: Output[uint1_t]  # VS


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
def pmod8_to_ice_pins():
    ICE_4 = pmod_a_wire.p1
    ICE_2 = pmod_a_wire.p2
    ICE_47 = pmod_a_wire.p3
    ICE_45 = pmod_a_wire.p4
    ICE_3 = pmod_a_wire.p5
    ICE_48 = pmod_a_wire.p6
    ICE_46 = pmod_a_wire.p7
    ICE_44 = pmod_a_wire.p8
    ICE_31 = pmod_b_wire.p1
    ICE_34 = pmod_b_wire.p2
    ICE_38 = pmod_b_wire.p3
    ICE_43 = pmod_b_wire.p4
    ICE_28 = pmod_b_wire.p5
    ICE_32 = pmod_b_wire.p6
