import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from typing import NamedTuple

from pypeline import (
    MAIN,
    char_array_to_str,
    char_t,
    hw_func,
    sim_call,
    sim_reset,
    str_to_char_array,
    strlen,
    struct,
    uint8_t,
    uint32_t,
)


# ── struct with a char-array field ───────────────────────────────────────────


@struct
class named_val_t(NamedTuple):
    name: char_t[16]
    value: uint32_t


# ── struct with both a char_t[16] and a uint8_t[16] field (name-mangling
#    distinctness sanity check -- these must not collide on a canonical name) ──


@struct
class mixed_arrays_t(NamedTuple):
    label: char_t[16]
    bytes: uint8_t[16]


# ── hardware functions ───────────────────────────────────────────────────────


@MAIN
def local_str_init() -> char_t[16]:
    s: char_t[16] = "hello"
    return s


@MAIN
def str_literal_exact_fit() -> char_t[5]:
    s: char_t[5] = "hello"
    return s


@MAIN
def passthrough_char_array(s: char_t[16]) -> char_t[16]:
    return s


@MAIN
def increment_chars(s: char_t[16]) -> char_t[16]:
    """Real per-element arithmetic on char array elements (each char + 1), not just
    passthrough/constant wiring -- exercises char_t scalar addition and gives
    synthesis timing analysis actual logic paths to measure."""
    out: char_t[16] = s
    for i in range(16):
        out[i] = s[i] + 1
    return out


@hw_func
def echo_name(name: char_t[16]) -> char_t[16]:
    return name


@MAIN
def call_with_str_literal_arg() -> char_t[16]:
    return echo_name("Current:")


@MAIN
def make_named_val(v: uint32_t) -> named_val_t:
    n: named_val_t
    n.name = "id"
    n.value = v
    return n


@MAIN
def strlen_of_char_array(s: char_t[16]) -> uint8_t:
    return strlen(s)


@MAIN
def strlen_of_uint_array(a: uint8_t[8]) -> uint8_t:
    return strlen(a)


@MAIN
def passthrough_grid(g: char_t[3][3]) -> char_t[3][3]:
    return g


@MAIN
def passthrough_mixed(m: mixed_arrays_t) -> mixed_arrays_t:
    return m


# NOTE: Reg[char_t[N]] = "literal" (or any int/list initializer for a Reg[T] whose
# leaf element type is "char") is not supported -- it hits a pre-existing VHDL.py
# code-generation bug (CONST_VAL_STR_TO_VHDL's char branch assumes a quoted C-AST
# character-literal token, not a plain Python-int-derived value; reproduces even for
# a bare `Reg[char_t] = 65` with no arrays/strings involved). Fixing it would require
# editing VHDL.py, which is out of scope. Reg[char_t[N]] with no initializer
# (zero-init) is unaffected and works normally through the generic Reg[T] machinery.


# ── simulation tests ─────────────────────────────────────────────────────────


def test_local_str_init():
    sim_reset()
    r = sim_call(local_str_init)
    assert char_array_to_str(r) == "hello", char_array_to_str(r)
    assert [int(x) for x in r][5:] == [0] * 11, [int(x) for x in r]
    print("test_local_str_init PASS")


def test_str_literal_exact_fit():
    sim_reset()
    r = sim_call(str_literal_exact_fit)
    assert char_array_to_str(r) == "hello", char_array_to_str(r)
    print("test_str_literal_exact_fit PASS")


def test_passthrough():
    sim_reset()
    v = str_to_char_array("world!", 16)
    r = sim_call(passthrough_char_array, s=v)
    assert char_array_to_str(r) == "world!", char_array_to_str(r)
    print("test_passthrough PASS")


def test_increment_chars():
    sim_reset()
    v = str_to_char_array("hello", 16)
    r = sim_call(increment_chars, s=v)
    got = [int(x) for x in r]
    expected = [c + 1 for c in [int(x) for x in v]]
    assert got == expected, (got, expected)
    print("test_increment_chars PASS")


def test_call_with_str_literal_arg():
    sim_reset()
    r = sim_call(call_with_str_literal_arg)
    assert char_array_to_str(r) == "Current:", char_array_to_str(r)
    print("test_call_with_str_literal_arg PASS")


def test_struct_field():
    sim_reset()
    r = sim_call(make_named_val, v=42)
    assert char_array_to_str(r.name) == "id", char_array_to_str(r.name)
    assert int(r.value) == 42
    print("test_struct_field PASS")


def test_strlen():
    sim_reset()
    # strlen() returns declared capacity (16), NOT content length -- deliberate
    # parity with PipelineC's C_AST_STRLEN_FUNC_CALL_TO_LOGIC. Pin this down so a
    # future "fix" can't silently regress it into content-length semantics.
    r = sim_call(strlen_of_char_array, s=str_to_char_array("hi", 16))
    assert int(r) == 16, int(r)
    print("test_strlen PASS")


def test_strlen_not_char_gated():
    sim_reset()
    r = sim_call(strlen_of_uint_array, a=[0, 0, 0, 0, 0, 0, 0, 0])
    assert int(r) == 8, int(r)
    print("test_strlen_not_char_gated PASS")


def test_2d_grid():
    sim_reset()
    grid = [str_to_char_array(row, 3) for row in ["ab", "cd", "ef"]]
    r = sim_call(passthrough_grid, g=grid)
    assert [char_array_to_str(row) for row in r] == ["ab", "cd", "ef"], r
    print("test_2d_grid PASS")


def test_mixed_arrays_struct():
    sim_reset()
    m = mixed_arrays_t(label=str_to_char_array("x", 16), bytes=[0] * 16)
    r = sim_call(passthrough_mixed, m=m)
    assert char_array_to_str(r.label) == "x", char_array_to_str(r.label)
    print("test_mixed_arrays_struct PASS")


def test_conversion_helpers():
    v = str_to_char_array("ok", 4)
    assert [int(x) for x in v] == [111, 107, 0, 0], [int(x) for x in v]
    assert char_array_to_str(v) == "ok"
    print("test_conversion_helpers PASS")


if __name__ == "__main__":
    test_local_str_init()
    test_str_literal_exact_fit()
    test_passthrough()
    test_increment_chars()
    test_call_with_str_literal_arg()
    test_struct_field()
    test_strlen()
    test_strlen_not_char_gated()
    test_2d_grid()
    test_mixed_arrays_struct()
    test_conversion_helpers()
    print("All char array tests passed.")
