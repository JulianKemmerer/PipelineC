# pyright: reportInvalidTypeForm=none
"""Scalar integer call arguments whose type differs from the callee's parameter.

A call's input port wire used to be declared with the ARGUMENT's type (ex. the
uint9 of `c + 100`) instead of the parameter's (uint16_t). The instance port
map then connected an unsigned(8 downto 0) signal to an unsigned(15 downto 0)
port, which GHDL rejects ("actual constraints don't match formal ones") -- in
simulation and synthesis alike. Native sim always cast arguments to their
annotated types (_sim_type_wrap). Each call below differs from its parameter
in a different way; the cycle diff proves VHDL now converts exactly like the
native cast (the same VHDL.TYPE_RESOLVE_ASSIGNMENT_RHS conversion an
assignment to a declared local gets).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
from pypeline import (
    MAIN,
    Reg,
    hw_func,
    int8_t,
    int16_t,
    sim_assert,
    sim_finish,
    sim_print,
    uint1_t,
    uint8_t,
    uint16_t,
)


@hw_func
def pass_u16(x: uint16_t) -> uint16_t:
    return x


@hw_func
def pass_i16(x: int16_t) -> int16_t:
    return x


@hw_func
def pass_u8(x: uint8_t) -> uint8_t:
    return x


@hw_func
def add_u16(a: uint16_t, b: uint16_t) -> uint16_t:
    return a + b


@MAIN
def call_arg_width_test() -> uint16_t:
    c: Reg[uint8_t]
    done: Reg[uint1_t]
    if done:
        sim_finish()
    # Unsigned expression (uint9) widened into uint16_t
    widened: uint16_t = pass_u16(c + 100)
    # Negative int8_t local sign-extended into int16_t
    s8: int8_t = c
    neg8: int8_t = s8 - 5
    extended: int16_t = pass_i16(neg8)
    # Wider uint16_t local truncated into uint8_t (c >= 6 exceeds 255)
    big: uint16_t = c
    big = big + 250
    truncated: uint8_t = pass_u8(big)
    # Unsigned local into a signed parameter
    unsigned_to_signed: int16_t = pass_i16(c)
    # Keyword-bound narrower arguments
    summed: uint16_t = add_u16(b=c, a=c + 1000)
    # Signed oracles computed without any call (c - 5 alone is unsigned
    # uint8_t arithmetic and could never equal a negative int16_t)
    expected_extended: int16_t = c
    expected_extended = expected_extended - 5
    expected_u2s: int16_t = c
    if c < 12:
        sim_assert(widened == c + 100, "uint9 expression -> uint16_t")
        sim_assert(extended == expected_extended, "int8_t -> int16_t sign extension")
        sim_assert(truncated == (c + 250) & 255, "uint16_t -> uint8_t truncation")
        sim_assert(unsigned_to_signed == expected_u2s, "uint8_t -> int16_t")
        sim_assert(summed == c + c + 1000, "keyword arguments")
        sim_print(
            f"c={c} widened={widened} extended={extended} truncated={truncated} "
            f"u2s={unsigned_to_signed} summed={summed}",
            debug=True,
        )
    if c == 11:
        done = 1
    c = c + 1
    return widened
