"""An omitted default hardware input is not wired; explicit input is a control.

Native Python applies rst=0. HDL elaboration currently leaves the rst port
undriven and fails in trimming. Build with -D DEFAULT_ARG_EXPLICIT=1 for the
otherwise identical passing control. DSP converters pass reset explicitly.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from pypeline import MAIN, Reg, hw_func, param, uint1_t, uint8_t

EXPLICIT = param("DEFAULT_ARG_EXPLICIT", False)


@hw_func
def with_default(data: uint8_t, rst: uint1_t = 0) -> uint8_t:
    count: Reg[uint8_t]
    if rst:
        count = 0
    else:
        count += data
    return count


@MAIN(125.0)
def default_arg_main(data: uint8_t, enable: uint1_t) -> uint8_t:
    value: Reg[uint8_t]
    if enable:
        if EXPLICIT:
            value = with_default(data, 0)
        else:
            value = with_default(data)
    return value
