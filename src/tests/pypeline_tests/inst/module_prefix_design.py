# pyright: reportInvalidTypeForm=none
"""Fixture for module_prefix_build_test.py: one source whose builds with
-D VARIANT=2 and -D VARIANT=3 declare the same VHDL names with different text.

  scale             the same entity name in both builds (both constants are 2
                    bits wide, and a name carries only the timing hash), with
                    a different body
  tagged_t          the same record name with a different layout, so the two
                    c_structs_pkg declare different types
  prefix_debug      a top-level output port whose width follows VARIANT: the two
                    global_wires_pkg declare different records
  fifo              raw vhdl() text that instantiates the built-in FIFO entity
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "include", "pypeline"))

from pypeline import (
    MAIN,
    NamedTuple,
    Output,
    hw_func,
    make_uint_t,
    param,
    struct,
    uint1_t,
    uint8_t,
)

from fifo import make_fifo

VARIANT = param("VARIANT", 2, choices=(2, 3), help="the constant scale adds")

# uint8_t or uint9_t: the layout of tagged_t, not its name, depends on it
word_t = make_uint_t(6 + VARIANT)


@struct
class tagged_t(NamedTuple):
    tag: uint1_t
    word: word_t


fifo = make_fifo(uint8_t, 4)

prefix_debug: Output[word_t]


@hw_func
def scale(x: uint8_t) -> uint8_t:
    return x + VARIANT


@MAIN(100.0)
def module_prefix_core(x: uint8_t, valid: uint1_t) -> tagged_t:
    popped = fifo(1, scale(x), valid)
    prefix_debug = popped.data_out
    r: tagged_t
    r.tag = popped.data_out_valid
    r.word = popped.data_out
    return r
