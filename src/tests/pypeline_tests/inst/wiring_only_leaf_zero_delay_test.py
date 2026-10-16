#!/usr/bin/env python3
# SYN.LOGIC_IS_ZERO_DELAY on user functions with no submodules: a stateless
# one is only wiring and never timed. Issue #373: timing a cast-only helper on
# Gowin let the planned sweep cut inside it. Issue #288: a constant-only
# function has no timing path at all. The design is parsed in-process via
# PY_TO_LOGIC.PARSE_FILE, like wires_contract_test.py.
import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC
import SYN

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

_SRC = """
import sys
sys.path.insert(0, {repo_root!r})
from pypeline import MAIN, Reg, hw_func, int24_t, int32_t, uint8_t


@hw_func
def sext24(x: int32_t) -> int32_t:
    r: int24_t = x
    return r


@hw_func
def seven() -> uint8_t:
    return 7


@hw_func
def delay_one(x: int32_t) -> int32_t:
    saved: Reg[int32_t]
    result: int32_t = saved
    saved = x
    return result


@hw_func
def add_one(x: int32_t) -> int32_t:
    return x + 1


@MAIN
def top(a: int32_t, b: int32_t) -> int32_t:
    x: int32_t = sext24(a + b)
    return add_one(delay_one(x) + b) + seven()
"""


def _parse():
    with tempfile.TemporaryDirectory(
        prefix="wiring_only_leaf_zero_delay_test_"
    ) as tmpdir:
        path = os.path.join(tmpdir, "wiring_only_leaf_design.py")
        with open(path, "w") as f:
            f.write(_SRC.format(repo_root=os.path.abspath(REPO_ROOT)))
        return PY_TO_LOGIC.PARSE_FILE(path)


_PARSER_STATE = None


def _logic(func_name):
    global _PARSER_STATE
    if _PARSER_STATE is None:
        _PARSER_STATE = _parse()
    logic = _PARSER_STATE.FuncLogicLookupTable[func_name]
    return logic, _PARSER_STATE


def test_stateless_function_without_submodules_is_zero_delay():
    logic, parser_state = _logic("sext24")
    assert not logic.submodule_instances, logic.submodule_instances
    assert SYN.LOGIC_IS_ZERO_DELAY(logic, parser_state)


def test_constant_only_function_is_zero_delay():
    logic, parser_state = _logic("seven")
    assert not logic.submodule_instances, logic.submodule_instances
    assert SYN.LOGIC_IS_ZERO_DELAY(logic, parser_state)


def test_stateful_function_without_submodules_is_timed():
    logic, parser_state = _logic("delay_one")
    assert not logic.submodule_instances, logic.submodule_instances
    assert logic.state_regs
    assert not SYN.LOGIC_IS_ZERO_DELAY(logic, parser_state, allow_none_delay=True)


def test_function_with_an_operator_is_timed():
    logic, parser_state = _logic("add_one")
    assert logic.submodule_instances
    assert not SYN.LOGIC_IS_ZERO_DELAY(logic, parser_state, allow_none_delay=True)
    for func_name in logic.submodule_instances.values():
        leaf = parser_state.FuncLogicLookupTable[func_name]
        assert leaf.is_c_built_in, func_name
        assert not SYN.LOGIC_IS_ZERO_DELAY(leaf, parser_state), func_name


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
