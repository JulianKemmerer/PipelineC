"""Manual Artix-7 probe for the AUTO_PIPELINE lowering used by FSM units.

    python3 src/pypelinec src/tests/pypeline_tests/qor/multiplier/inferred_pipeline_unit.py \\
        -D WIDTH=17 -D UNIT_REGS=1 --out_dir <new directory> -j 1

Repeat at WIDTH=34 and UNIT_REGS=0/1/2. The same inferred multiply is
surrounded by registers; no DSP primitive is instantiated explicitly. Read
DSP48E1, LUT and FF utilization and the absorbed arithmetic-register messages
from Vivado's synthesis log. Timing is post-synthesis, not routed.
"""

from pypeline import AUTO_PIPELINE, MAIN, PART, Reg, hw_func, make_uint_t, param, uint1_t
from operators.soft_mult import make_inferred_mult

# Same device and speed grade as the Poly1305 fixtures.
PART("xc7a200tffg1156-2")
# Probe inputs are ordinary design parameters, not compiler policy options.
WIDTH = param("WIDTH", 17)
UNIT_REGS = param("UNIT_REGS", 1)
MHZ = param("MHZ", 80)
word_t = make_uint_t(WIDTH)
product_t = make_uint_t(2*WIDTH)
# Pin multiplication to the existing inferred VHDL operator implementation.
multiply = make_inferred_mult(word_t, word_t)


@hw_func
def selected_product(selected: uint1_t, a: word_t, b: word_t, c: word_t, d: word_t) -> product_t:
    left: word_t[2]
    right: word_t[2]
    left[0] = a
    left[1] = c
    right[0] = b
    right[1] = d
    return multiply(left[selected], right[selected])


# FSM-selected units use this same constrained region and lowering machinery.
UNIT = AUTO_PIPELINE(selected_product, latency=UNIT_REGS)


@MAIN(MHZ)
def probe(selected: uint1_t, a: word_t, b: word_t, c: word_t, d: word_t) -> product_t:
    sr: Reg[uint1_t]
    ar: Reg[word_t]
    br: Reg[word_t]
    cr: Reg[word_t]
    dr: Reg[word_t]
    result: Reg[product_t]
    previous: product_t = result
    result = UNIT(sr, ar, br, cr, dr)
    sr = selected
    ar = a
    br = b
    cr = c
    dr = d
    return previous
