# pyright: reportInvalidTypeForm=none
# Five Feedback wires, declared out of alphabetical order: the emitted
# feedback_vars_t record must list its fields in declaration order, not sorted
# and not in the hash-seeded iteration order of a set of names. Built under two
# PYTHONHASHSEEDs by generated_naming_build_test.py.
from pypeline import MAIN, Feedback, uint8_t


@MAIN
def feedback_vars_order(x: uint8_t) -> uint8_t:
    fd: Feedback[uint8_t]
    fa: Feedback[uint8_t]
    fe: Feedback[uint8_t]
    fb: Feedback[uint8_t]
    fc: Feedback[uint8_t]
    s: uint8_t = fa + fb + fc + fd + fe  # read before the writes below
    fa = x
    fb = x + 1
    fc = x + 2
    fd = x + 3
    fe = x + 4
    return s
