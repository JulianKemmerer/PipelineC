from pypeline import *

# Minimal fixture for mux_fanout_planning_test.py's
# DROP_NON_DEEPENING_PLACEMENTS coverage: two independent (parallel) adders
# feeding a third (serial) adder, the smallest shape that reproduces the
# real bug's topology -- a candidate register on one parallel branch can be
# "free" (adds no pipeline stage) once the OTHER parallel branch already
# bounds the shared downstream consumer's readiness, exactly the mux
# select-fanout cliff's "MUX_uint5_t_if_eff_amt registered on top of an
# already-registered MUX_uint64_t_if_w costs nothing" shape, minus the mux
# semantics (any two raw-HDL leaves reproduce it -- GET_PIPELINE_MAP's
# stage-of-readiness scheduling doesn't care what kind of leaf it is).
x: Input[uint8_t]
y: Input[uint8_t]
p: Input[uint8_t]
q: Input[uint8_t]
result: Output[uint8_t]


@MAIN(100)
def redundant_cut_main():
    a: uint8_t = x + y
    b: uint8_t = p + q
    result = a + b
