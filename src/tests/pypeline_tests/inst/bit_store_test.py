# pyright: reportInvalidTypeForm=none
"""Integer bit stores, x[hi:lo] = v and x[i] = v, in native simulation and GHDL.

Native simulation rewrites each store so it rebinds the name, since a SimVal is
an immutable int (pypeline._TypedAnnAssignRewriter Rule 7, and
_GlobalWireRewriter for a scalar wire). Elaboration builds a bit_assign
instance (PY_TO_LOGIC._try_elab_bit_slice_assign). The @MAINs store into each
kind of integer name:

- a typed local: a one-bit slice, a slice, a single bit with a literal index
  and with a named constant index, and a constant slice object;
- a signed typed local, whose stored sign bit makes it negative;
- an untyped local;
- a helper's parameter;
- a Reg: a slice and a single bit;
- a scalar global wire, after a whole write.

top also runs the workaround that the error for a hardware bit index suggests
(uint_to_array_le, a store at a hardware index, array_to_uint_le).

Registered twice:

- native_vs_vhdl_sim (pypeline_sim_debug.py, --comb): native simulation and
  cocotb + GHDL print the same debug values every cycle, and the sim_asserts on
  the last cycle hold in both. Before the fix, native simulation raised
  "'SimVal' object does not support item assignment" at the first store
  (#408), and elaboration stopped at the single-bit store with "substring not
  found" (#362).
- native_sim (this file run directly): the test_* functions check that the
  rewrite keeps Python's meaning for a subscript store that is not a bit
  store, and that a bit store into an array element (which neither layer
  supports) is a clear error. Their hw_funcs are defined inside the tests, so
  elaboration of this file never sees them.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    Reg,
    Wire,
    array_to_uint_le,
    hex,
    hw_func,
    int8_t,
    sim_assert,
    sim_call,
    sim_finish,
    sim_print,
    uint1_t,
    uint5_t,
    uint8_t,
    uint32_t,
    uint_to_array_le,
)

BIT3 = 3  # a named constant bit index
BYTE2 = slice(23, 16)  # a constant slice object
LAST = 37  # the cycle the sim_asserts check, then finish

stored: Wire[uint32_t]


@hw_func
def set_byte1(x: uint32_t, b: uint8_t) -> uint32_t:
    x[15:8] = b  # a parameter
    return x


@MAIN
def wire_writer():
    c: Reg[uint8_t]
    stored = 0x11223344
    stored[7:0] = c  # a scalar global wire
    c = c + 1


@MAIN
def top():
    c: Reg[uint8_t]  # the cycle count, as in wire_writer
    r: Reg[uint32_t]
    y: uint32_t = 0xFFFFFFFF
    y[0:0] = 0  # a one-bit slice
    y[15:8] = c  # a slice
    y[BIT3] = 0  # a single bit, named constant index
    y[31] = c[0]  # a single bit, literal index
    y[BYTE2] = c ^ 0xFF  # a constant slice object
    s: int8_t = 0
    s[7] = c[0]  # the sign bit
    s[6:0] = c[6:0]
    u = y  # an untyped local
    u[27:24] = c[3:0]
    p: uint32_t = set_byte1(u, ~c)
    i: uint5_t = c[4:0]  # a hardware bit index, through the workaround
    bits: uint1_t[32] = uint_to_array_le(p, 1)
    bits[i] = 0
    w: uint32_t = array_to_uint_le(bits)
    sim_print(
        f"c={c} y={hex(y)} s={s} u={hex(u)} p={hex(p)} w={hex(w)} r={hex(r)} "
        f"stored={hex(stored)}",
        debug=True,
    )
    if c == LAST:
        # c = 37 = 0x25: odd, so bit 31 of y and the sign bit of s are set
        sim_assert(y == 0xFFDA25F6, "stores into a typed local")
        sim_assert(s == -91, "stores into a signed local (0xA5)")
        sim_assert(u == 0xF5DA25F6, "a slice store into an untyped local")
        sim_assert(p == 0xF5DADAF6, "a slice store into a parameter")
        sim_assert(w == 0xF5DADAD6, "bit 5 cleared at a hardware index")
        sim_assert(r == 0x00000024, "stores into a Reg, on the cycle before")
        sim_assert(stored == 0x11223325, "a slice store into a wire")
        sim_finish()
    r[7:0] = c  # a slice of a Reg
    r[31] = c[0]  # a single bit of a Reg
    c = c + 1


def test_list_local_store_is_in_place():
    """An untyped local holding a Python list is stored into in place, so an
    alias of the list sees the store, as in plain Python."""

    @hw_func
    def f(x: uint8_t) -> uint8_t:
        t = [0, 0]
        alias = t
        t[1] = x
        return alias[1]

    assert int(sim_call(f, 7)) == 7


def test_nested_def_stores_into_enclosing_local():
    """A nested def's store into a list of the enclosing function is left as
    Python: rebinding the name would make it local to the nested def."""

    @hw_func
    def f(x: uint8_t) -> uint8_t:
        t = [0]

        def put(v):
            t[0] = v

        put(x)
        return t[0]

    assert int(sim_call(f, 9)) == 9


def test_element_bit_store_is_an_error():
    """A bit store into an array element is not supported (elaboration rejects
    it too, #362). Native simulation says so, instead of iterating the integer
    element through SimVal.__getitem__ without end until memory runs out."""

    @hw_func
    def f(x: uint8_t) -> uint8_t:
        a: uint8_t[2] = [x, x]
        a[1][0] = 0
        return a[1]

    try:
        sim_call(f, 3)
    except TypeError as e:
        assert "bit store into a struct field or an array element" in str(e), e
    else:
        raise AssertionError("a bit store into an array element ran")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
