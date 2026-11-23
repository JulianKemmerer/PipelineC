# pyright: reportInvalidTypeForm=none
"""Known-issue fixture (#402): a module-level struct or array constant
used directly in a hardware function does not elaborate. Each line of main()
fails on its own, with a different error:

- array_to_uint_le(K.lanes): "Cannot emit non-int Python value as hardware: [1, 2]"
- ok = K:                    "Module global 'K' (pair_t) is not a hardware-usable value"
- ot = T[i]:                 "Unknown reference base 'T'"
- ow = T:                    "Module global 'T' (list) is not a hardware-usable value"
- sel = row, in a loop over the module-level list ROWS (a table-driven decoder's
  shape): "Cannot emit non-int Python value as hardware: pair_t(a=4, lanes=[5, 6])"

Each constant has a declared type (K's class, T's annotation), and the same
values work through a typed local (`x: uint8_t[2] = T`, or `r: pair_t = row`
in the loop). Registered in known_issues_tests.py (expect_fail) with --comb
--no_synth. The build stops at the first failing line, so it passes only when
all five elaborate.
"""

import os
import sys
from typing import NamedTuple

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Input, Output, array_to_uint_le, struct, uint1_t, uint8_t, uint16_t


@struct
class pair_t(NamedTuple):
    a: uint8_t
    lanes: uint8_t[2]


K = pair_t(a=3, lanes=[1, 2])
T: uint8_t[2] = [1, 2]
ROWS = [(0, pair_t(a=4, lanes=[5, 6])), (1, pair_t(a=7, lanes=[8, 9]))]

i: Input[uint1_t]
op: Output[uint16_t]
ok: Output[pair_t]
ot: Output[uint8_t]
ow: Output[uint8_t[2]]
orow: Output[pair_t]


@MAIN
def main():
    op = array_to_uint_le(K.lanes)
    ok = K
    ot = T[i]
    ow = T
    sel: pair_t = pair_t(a=0, lanes=[0, 0])
    for key, row in ROWS:
        if i == key:
            sel = row
    orow = sel
