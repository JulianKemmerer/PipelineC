"""A local first assigned inside a runtime `if` is unknown after the `if`.

Each MAIN is valid Python, and native simulation runs it as a mux. Elaboration
stops with "Unknown name 'value'" on the first one. The ternary lowers to the
same `if`. Declaring `value: uint8_t` before the `if` elaborates.
"""

from pypeline import MAIN, uint1_t, uint8_t


@MAIN
def choose_if(sel: uint1_t, a: uint8_t, b: uint8_t) -> uint8_t:
    if sel:
        value = a
    else:
        value = b
    return value


@MAIN
def choose_ternary(sel: uint1_t, a: uint8_t, b: uint8_t) -> uint8_t:
    value = a if sel else b
    return value
