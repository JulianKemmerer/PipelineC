#!/usr/bin/env python3
# In-process regression tests for PY_TO_LOGIC._validate_wires_funcs: a @wires
# function must synthesize to nothing but wires -- no registers and no logic
# anywhere in its hierarchy -- because SYN.LOGIC_IS_ZERO_DELAY believes the tag
# and the compiler never times the function.
#
# The bug this guards: a WireGuard synthesizable testbench MAIN (Reg counters,
# adders, compares, ROM muxes, a stateful byte source/sink) was tagged
# @MAIN @wires. Its real 9.55 ns path was synthesized and measured, but the
# sweep treated the MAIN as having nothing to time, so sweep_history.json gave
# it no timing verdict (met: null, "unverified") in a passing build.
#
# Each design is written to its own temp .py file and parsed directly via
# PY_TO_LOGIC.PARSE_FILE, like global_wire_errors_test.py.
import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

_HEADER = """
import sys
sys.path.insert(0, {repo_root!r})
from typing import NamedTuple
from pypeline import (MAIN, Input, Output, Reg, Wire, cast, hw_func, sim_finish,
                      sim_print, struct, uint1_t, uint2_t, uint4_t, uint8_t,
                      uint16_t, uint32_t, vhdl, wires)

@struct
class pair_t(NamedTuple):
    a: uint8_t
    b: uint8_t

"""


def _parse(src, name):
    with tempfile.TemporaryDirectory(prefix="wires_contract_test_") as tmpdir:
        path = os.path.join(tmpdir, name)
        with open(path, "w") as f:
            f.write(_HEADER.format(repo_root=os.path.abspath(REPO_ROOT)))
            f.write(src)
        return PY_TO_LOGIC.PARSE_FILE(path)


def _expect_elaboration_error(src, name, must_contain):
    try:
        _parse(src, name)
    except PY_TO_LOGIC.ElaborationError as e:
        msg = str(e)
        for token in ["@wires", "is not just wires"] + must_contain:
            assert token.lower() in msg.lower(), (
                f"{name}: expected ElaborationError message to mention "
                f"{token!r}, got: {msg}"
            )
        print(f"{name} PASS  ({msg})")
        return
    raise AssertionError(f"{name}: expected an ElaborationError, but PARSE_FILE succeeded")


def test_stateful_testbench_main_is_not_wires():
    # The WireGuard encrypt_syn_tb shape: a wiring-looking MAIN with registers
    # and counter logic driving a DUT through a global wire
    src = """
to_dut: Wire[uint8_t]

@MAIN
@wires
def tb_like_main():
    count: Reg[uint8_t]
    to_dut = count
    count = count + 1

@MAIN
def dut_main() -> uint8_t:
    return to_dut
"""
    _expect_elaboration_error(
        src, "stateful_tb_test.py", ["tb_like_main", "register", "count"]
    )


def test_logic_is_not_wires():
    src = """
@wires
def add_wires(a: uint8_t, b: uint8_t) -> uint8_t:
    return a + b

@MAIN
def add_main(a: uint8_t, b: uint8_t) -> uint8_t:
    return add_wires(a, b)
"""
    _expect_elaboration_error(
        src, "logic_test.py", ["add_wires", "BIN_OP_PLUS", "logic_test.py:"]
    )


def test_stateful_callee_is_not_wires():
    # A register one call level down still makes the wrapper more than wires
    src = """
@hw_func
def accumulate(x: uint8_t) -> uint8_t:
    acc: Reg[uint8_t]
    acc = acc ^ x
    return acc

@wires
def wrap_accumulate(x: uint8_t) -> uint8_t:
    return accumulate(x)

@MAIN
def wrap_main(x: uint8_t) -> uint8_t:
    return wrap_accumulate(x)
"""
    _expect_elaboration_error(
        src,
        "stateful_callee_test.py",
        ["wrap_accumulate", "accumulate", "register", "acc"],
    )


def test_variable_index_is_not_wires():
    src = """
@wires
def pick(arr: uint8_t[4], i: uint2_t) -> uint8_t:
    return arr[i]

@MAIN
def pick_main(arr: uint8_t[4], i: uint2_t) -> uint8_t:
    return pick(arr, i)
"""
    _expect_elaboration_error(src, "variable_index_test.py", ["pick", "instantiates"])


def test_logic_feeding_an_output_and_a_sim_builtin_is_not_wires():
    # Logic reaching only sim_print would be simulation-only; this AND also
    # drives the output, so it is real hardware
    src = """
@MAIN
@wires
def both_main(a: uint1_t, b: uint1_t) -> uint1_t:
    x: uint1_t = a & b
    sim_print(f"x={x}")
    return x
"""
    _expect_elaboration_error(src, "sim_and_output_test.py", ["both_main", "BIN_OP_AND"])


def test_auto_wrapped_cast_with_logic_is_not_wires():
    # @cast wraps a plain function with @wires; real logic needs @hw_func
    src = """
@struct
class wide_t(NamedTuple):
    v: uint16_t

@cast
def wide_from_uint8(x: uint8_t) -> wide_t:
    return wide_t(v=x + 1)

@MAIN
def cast_main(x: uint8_t) -> wide_t:
    return wide_t(x)
"""
    _expect_elaboration_error(src, "cast_logic_test.py", ["wide_from_uint8", "@hw_func"])


def test_untagged_raw_vhdl_callee_is_not_wires():
    src = """
@hw_func
def raw_passthrough(x: uint8_t) -> uint8_t:
    vhdl(
        '''
        begin
        return_output <= x;
        '''
    )

@wires
def calls_raw(x: uint8_t) -> uint8_t:
    return raw_passthrough(x)

@MAIN
def raw_main(x: uint8_t) -> uint8_t:
    return calls_raw(x)
"""
    _expect_elaboration_error(
        src, "untagged_raw_vhdl_test.py", ["calls_raw", "raw-VHDL", "raw_passthrough"]
    )


def test_genuine_wires_are_accepted():
    # Every legitimate @wires shape in one design: rewiring, bit slices,
    # concat, constant shifts, casts, constant indexing, global
    # Wire/Input/Output connections (WireGuard's *_io_wires MAINs), nested
    # @wires, sim_print of a wire, `if flag: sim_finish()` (WireGuard's finish
    # checkers -- its clock-enable mux only feeds sim_finish), and raw-VHDL
    # @wires bodies, which can't be inspected and are trusted.
    src = """
done_flag: Wire[uint1_t]
port_in: Input[uint8_t]
port_out: Output[uint8_t]
to_core: Wire[uint8_t]

@wires
def pair_to_bytes(p: pair_t) -> uint8_t[2]:
    return [p.a, p.b]

@wires
def swap_nibbles(x: uint8_t) -> uint8_t:
    return (x[3:0], x[7:4])

@wires
def shift_and_cast(x: uint16_t) -> uint8_t:
    y: uint16_t = x << 2
    return uint8_t(y)

@wires
def first_byte(p: pair_t) -> uint8_t:
    b: uint8_t[2] = pair_to_bytes(p)
    return b[0]

@wires
def raw_wires(x: uint8_t) -> uint8_t:
    vhdl(
        '''
        begin
        return_output <= x;
        '''
    )

@wires
def calls_raw_wires(x: uint8_t) -> uint8_t:
    return raw_wires(x)

@MAIN
@wires
def io_wires():
    to_core = port_in
    sim_print(f"in={port_in}")

@MAIN
def core_main(p: pair_t, w: uint16_t) -> uint8_t:
    done: Reg[uint1_t]
    done_flag = done
    done = 1
    port_out = swap_nibbles(to_core)
    return first_byte(p) ^ shift_and_cast(w) ^ calls_raw_wires(raw_wires(to_core))

@MAIN
@wires
def finish_checker():
    if done_flag:
        sim_finish()
"""
    parser_state = _parse(src, "genuine_wires_test.py")
    expected = {
        "pair_to_bytes",
        "swap_nibbles",
        "shift_and_cast",
        "first_byte",
        "raw_wires",
        "calls_raw_wires",
        "io_wires",
        "finish_checker",
    }
    assert expected <= parser_state.func_marked_wires, parser_state.func_marked_wires
    unchecked = expected - set(parser_state.FuncToInstances)
    assert not unchecked, f"not instantiated, so never checked: {unchecked}"
    print("genuine_wires_test.py PASS")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"All {len(tests)} @wires contract tests passed.")
