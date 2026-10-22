"""In-process checks of @MAINs made in code (MAIN(fn, name=...)): each design
below is written to a temp .py file and parsed with PY_TO_LOGIC.PARSE_FILE,
then checked against the parser state or the raised ElaborationError (the
pattern of global_fifo_elab_test.py).

Built: four lanes made in a loop (keys, rates, ports, source description,
wire users); a factory MAIN in an imported module (module-prefixed default
name); a pure-factory library's function registered by the design; a
top-level MAIN renamed with name=; a plain def passed to MAIN(), with and
without name=; a bare made MAIN takes its rate through a wire; a factory
closure that writes a wire is recorded as a wire user under its table key;
a re-parse gives the same MAIN names. Errors: two MAINs with one name, a
MAIN named like a function, a MAIN whose module holds hardware but was
imported only inside a function.
"""

import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
from pypeline import *

"""

# Four counter lanes made in a loop, each driving its own element of vals,
# and a checker on 100 MHz reading them all
_LANES = """
vals: Wire[uint8_t[4]]


def make_lane(i):
    @hw_func
    def lane(step: uint8_t) -> uint8_t:
        n: Reg[uint8_t]
        vals[i] = n
        n += step + i
        return n

    return lane


lanes = [MAIN(make_lane(i), name=f"lane{i}") for i in range(4)]


@MAIN(100.0)
def check() -> uint8_t:
    return vals[0] + vals[1] + vals[2] + vals[3]
"""


def _write(tmpdir, name, text):
    path = os.path.join(tmpdir, name)
    with open(path, "w") as f:
        f.write(_HEADER.format(repo_root=os.path.abspath(REPO_ROOT)) + text)
    return path


def _parse(src, name, extra_files=None):
    with tempfile.TemporaryDirectory(prefix="factory_main_elab_test_") as tmpdir:
        for fname, text in (extra_files or {}).items():
            _write(tmpdir, fname, text)
        return PY_TO_LOGIC.PARSE_FILE(_write(tmpdir, name, src))


def _expect_error(src, name, must_contain, extra_files=None):
    try:
        _parse(src, name, extra_files)
    except PY_TO_LOGIC.ElaborationError as e:
        msg = str(e)
        for token in must_contain:
            assert (
                token.lower() in msg.lower()
            ), f"{name}: expected the error to mention {token!r}, got: {msg}"
        print(f"{name} PASS  ({msg})")
        return
    raise AssertionError(f"{name}: expected an ElaborationError, PARSE_FILE succeeded")


def test_lanes_made_in_a_loop():
    state = _parse(_LANES, "lanes_test.py")
    table = state.FuncLogicLookupTable
    for i in range(4):
        name = f"lane{i}"
        assert name in state.main_mhz, sorted(state.main_mhz)
        assert table[name].func_name == name
        # Ports lane<i>_step and lane<i>_return_output
        assert table[name].inputs == ["step"], table[name].inputs
        # The factory description gives its VHDL a -- Python: comment
        assert state.pypeline_name_descriptions.get(name), name
    assert "lane" not in state.main_mhz
    users = state.global_vars["vals"].used_in_funcs
    assert users == {"lane0", "lane1", "lane2", "lane3", "check"}, users
    print("test_lanes_made_in_a_loop PASS")


def test_bare_made_main_takes_rate_through_a_wire():
    state = _parse(_LANES, "lanes_rate_test.py")
    rates = {f"lane{i}": state.main_mhz[f"lane{i}"] for i in range(4)}
    assert set(rates.values()) == {100.0}, rates
    print("test_bare_made_main_takes_rate_through_a_wire PASS")


def test_imported_factory_main_gets_the_module_prefix():
    lib = """
lib_out: Wire[uint8_t]


def make_lane():
    @hw_func
    def lane():
        lib_out = 3

    return lane


MAIN(make_lane())
"""
    top = """
import lane_lib


@MAIN
def top() -> uint8_t:
    return lane_lib.lib_out
"""
    state = _parse(top, "imported_test.py", {"lane_lib.py": lib})
    assert "lane_lib_lane" in state.main_mhz, sorted(state.main_mhz)
    users = state.global_vars["lane_lib_lib_out"].used_in_funcs
    assert users == {"lane_lib_lane", "top"}, users
    print("test_imported_factory_main_gets_the_module_prefix PASS")


def test_pure_factory_library_function_registered_by_the_design():
    lib = """
def make_counter(step):
    @hw_func
    def counter() -> uint8_t:
        n: Reg[uint8_t]
        n += step
        return n

    return counter
"""
    top = """
import pure_lib

ctr = MAIN(pure_lib.make_counter(3), name="ctr")
"""
    state = _parse(top, "pure_lib_test.py", {"pure_lib.py": lib})
    assert list(state.main_mhz) == ["ctr"], list(state.main_mhz)
    print("test_pure_factory_library_function_registered_by_the_design PASS")


def test_renamed_top_level_main():
    src = """
@MAIN(name="top0")
def top() -> uint8_t:
    return 1
"""
    state = _parse(src, "renamed_test.py")
    assert list(state.main_mhz) == ["top0"], list(state.main_mhz)
    assert "top" not in state.FuncLogicLookupTable
    print("test_renamed_top_level_main PASS")


def test_plain_def_passed_to_main():
    src = """
def foo(x: uint8_t) -> uint8_t:
    return x + 1


MAIN(foo)
"""
    state = _parse(src, "plain_def_test.py")
    assert list(state.main_mhz) == ["foo"], list(state.main_mhz)
    print("test_plain_def_passed_to_main PASS")


def test_plain_def_passed_to_main_with_a_name():
    src = """
def bar(x: uint8_t) -> uint8_t:
    return x


MAIN(bar, name="bar0")
"""
    state = _parse(src, "plain_def_named_test.py")
    assert list(state.main_mhz) == ["bar0"], list(state.main_mhz)
    # Elaborated once, as the MAIN
    assert "bar" not in state.FuncLogicLookupTable
    print("test_plain_def_passed_to_main_with_a_name PASS")


def test_factory_closure_wire_users_use_its_key():
    src = """
acc: Wire[uint8_t]


def make_writer(k):
    @hw_func
    def writer():
        acc = k

    return writer


w5 = make_writer(5)


@MAIN
def drive():
    w5()


@MAIN
def read() -> uint8_t:
    return acc
"""
    state = _parse(src, "closure_wire_test.py")
    users = state.global_vars["acc"].used_in_funcs
    assert all(f in state.FuncLogicLookupTable for f in users), users
    assert "writer" not in users and "read" in users, users
    assert any(f.startswith("writer") for f in users), users
    print("test_factory_closure_wire_users_use_its_key PASS")


def test_reparse_gives_the_same_main_names():
    with tempfile.TemporaryDirectory(prefix="factory_main_elab_test_") as tmpdir:
        path = _write(tmpdir, "reparse_test.py", _LANES)
        first = sorted(PY_TO_LOGIC.PARSE_FILE(path).main_mhz)
        second = sorted(PY_TO_LOGIC.PARSE_FILE(path).main_mhz)
    assert first == second == ["check", "lane0", "lane1", "lane2", "lane3"], (
        first,
        second,
    )
    print("test_reparse_gives_the_same_main_names PASS")


def test_two_mains_with_one_name():
    src = _LANES.replace('MAIN(make_lane(i), name=f"lane{i}")', "MAIN(make_lane(i))")
    _expect_error(
        src,
        "duplicate_name_test.py",
        ["Two @MAINs are named 'lane'", "duplicate_name_test.py:", "name=..."],
    )


def test_main_named_like_a_function():
    src = """
@hw_func
def helper(x: uint8_t) -> uint8_t:
    return x


def make_lane():
    @hw_func
    def lane(x: uint8_t) -> uint8_t:
        return helper(x)

    return lane


MAIN(make_lane(), name="helper")
"""
    _expect_error(src, "clash_test.py", ["'helper'", "already uses", "clash_test.py:"])


def test_main_in_an_undiscovered_module_with_hardware():
    lost = """
lost_out: Wire[uint8_t]


def make_lane():
    @hw_func
    def lane():
        lost_out = 1

    return lane


MAIN(make_lane(), name="lost0")
"""
    top = """
def _load():
    import lost_lanes


_load()


@MAIN
def top() -> uint8_t:
    return 1
"""
    _expect_error(
        top,
        "lost_test.py",
        ["lost0", "lost_lanes", "import that module at module level"],
        {"lost_lanes.py": lost},
    )


if __name__ == "__main__":
    test_lanes_made_in_a_loop()
    test_bare_made_main_takes_rate_through_a_wire()
    test_imported_factory_main_gets_the_module_prefix()
    test_pure_factory_library_function_registered_by_the_design()
    test_renamed_top_level_main()
    test_plain_def_passed_to_main()
    test_plain_def_passed_to_main_with_a_name()
    test_factory_closure_wire_users_use_its_key()
    test_reparse_gives_the_same_main_names()
    test_two_mains_with_one_name()
    test_main_named_like_a_function()
    test_main_in_an_undiscovered_module_with_hardware()
    print("factory_main_elab_test: all PASS")
