"""Known issue #413: a Feedback edge paired with an equally wide forward edge.

`stage_reg` feeds `stage_b` directly and through `stage_a`, and `stage_b`
feeds `stage_reg` back through a Feedback. The diagram should draw the three
blocks in three columns: stage_reg, stage_a, stage_b. See
diagram_feedback_pair_test.py.
"""

from pypeline import *


@hw_func
def stage_a(pc: uint32_t) -> uint32_t:
    return pc + 1


@hw_func
def stage_b(pc: uint32_t, x: uint32_t) -> uint32_t:
    return pc + x


@hw_func
def stage_reg(next_pc: uint32_t) -> uint32_t:
    pc: Reg[uint32_t]
    rv = pc
    pc = next_pc
    return rv


@MAIN
def top() -> uint32_t:
    nxt: Feedback[uint32_t]
    pc = stage_reg(next_pc=nxt)
    x = stage_a(pc=pc)
    nxt = stage_b(pc=pc, x=x)
    return pc
