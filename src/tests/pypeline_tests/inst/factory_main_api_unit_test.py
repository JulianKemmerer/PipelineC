# pyright: reportInvalidTypeForm=none
"""In-process checks of @MAIN registration, the API that lets code make
@MAINs (factories, loops, generated functions):

- MAIN's forms: @MAIN, @MAIN(mhz), @MAIN(mhz=), @MAIN(name=), @MAIN(mhz,
  name=), and MAIN(fn, name=, mhz=) called on a function, each recorded as
  the wrapper's _pypeline_main (name, named, rate, origin);
- the default name (module-prefixed Python name, or the function's own
  @hw_func(name=)) and name= checks;
- errors: one function registered twice, MAIN() during a simulation run,
  something that is not a function;
- the duplicate-name message (ignoring case, naming both origins);
- the name helpers PY_TO_LOGIC aliases from pypeline;
- native sim's name -> MAIN map for build results (pypeline_sim);
- ELABORATE_LIVE_ROOTS keys a @MAIN root by its MAIN name.

Every test restores pypeline._main_registry. Registered in unit_tests.py.
"""

import contextlib
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import pypeline
from pypeline import MAIN, Reg, hw_func, uint8_t

THIS_FILE = os.path.basename(__file__)


@contextlib.contextmanager
def _registry():
    """Run with the MAIN registry restored afterwards."""
    saved = list(pypeline._main_registry)
    try:
        yield
    finally:
        pypeline._main_registry[:] = saved


def make_lane(i):
    @hw_func
    def lane() -> uint8_t:
        n: Reg[uint8_t]
        rv = n
        n += i + 1
        return rv

    return lane


def make_named_lane(i):
    @hw_func(name=f"lane_{i}")
    def lane() -> uint8_t:
        return i

    return lane


def _expect(exc_type, fn, *tokens):
    try:
        fn()
    except exc_type as e:
        msg = str(e)
        for token in tokens:
            assert token in msg, (token, msg)
        return msg
    raise AssertionError(f"expected {exc_type.__name__}")


def test_decorator_forms():
    with _registry():

        @MAIN
        def bare() -> uint8_t:
            return 1

        @MAIN(100.0)
        def positional() -> uint8_t:
            return 1

        @MAIN(mhz=50.0)
        def keyword() -> uint8_t:
            return 1

        @MAIN(name="named0")
        def named() -> uint8_t:
            return 1

        @MAIN(25.0, name="named1")
        def rated_named() -> uint8_t:
            return 1

        got = {
            f._pypeline_main[:3]
            for f in (bare, positional, keyword, named, rated_named)
        }
        assert got == {
            ("bare", False, None),
            ("positional", False, 100.0),
            ("keyword", False, 50.0),
            ("named0", True, None),
            ("named1", True, 25.0),
        }, got
        assert pypeline._main_registry[-5:] == [
            bare,
            positional,
            keyword,
            named,
            rated_named,
        ]
    print("test_decorator_forms PASS")


def test_call_form_registers_a_factory_function():
    with _registry():
        lanes = [MAIN(make_lane(i), name=f"lane{i}") for i in range(3)]
        assert [f._pypeline_main.name for f in lanes] == ["lane0", "lane1", "lane2"]
        assert all(pypeline.is_hw_func(f) for f in lanes)
        assert pypeline._main_registry[-3:] == lanes
        origin = lanes[0]._pypeline_main.origin
        assert origin.startswith(THIS_FILE + ":"), origin
    print("test_call_form_registers_a_factory_function PASS")


def test_call_form_keeps_mhz():
    with _registry():
        lane = MAIN(make_lane(0), name="fast", mhz=125.0)
        assert lane._pypeline_main.mhz == 125.0, lane._pypeline_main
    print("test_call_form_keeps_mhz PASS")


def test_name_must_be_a_vhdl_identifier():
    with _registry():
        _expect(ValueError, lambda: MAIN(make_lane(0), name="bad__name"), "MAIN")
        _expect(ValueError, lambda: MAIN(make_lane(0), name="process"), "reserved")
        _expect(TypeError, lambda: MAIN(make_lane(0), name=3), "must be a str")
    print("test_name_must_be_a_vhdl_identifier PASS")


def test_default_name_is_the_function_name():
    with _registry():
        # A closure made in this script: unprefixed, like the top design file
        lane = MAIN(make_lane(0))
        assert lane._pypeline_main[:2] == ("lane", False), lane._pypeline_main
    print("test_default_name_is_the_function_name PASS")


def test_default_name_has_the_module_prefix():
    with _registry():
        ns = {"__name__": "pkg.lanes", "hw_func": hw_func, "uint8_t": uint8_t}
        exec(
            "def make():\n"
            "    @hw_func\n"
            "    def lane() -> uint8_t:\n"
            "        return 1\n"
            "    return lane\n"
            "def pkg_lanes_main() -> uint8_t:\n"
            "    return 1\n",
            ns,
        )
        assert MAIN(ns["make"]())._pypeline_main.name == "pkg_lanes_lane"
        # The prefix is not repeated when the name already starts with it
        main = MAIN(ns["pkg_lanes_main"])
        assert main._pypeline_main.name == "pkg_lanes_main"
    print("test_default_name_has_the_module_prefix PASS")


def test_default_name_is_the_functions_own_name():
    with _registry():
        lane = MAIN(make_named_lane(2))
        assert lane._pypeline_main[:2] == ("lane_2", True), lane._pypeline_main
    print("test_default_name_is_the_functions_own_name PASS")


def test_one_function_registered_twice_is_an_error():
    with _registry():
        lane = make_lane(0)
        MAIN(lane, name="first")
        _expect(
            TypeError,
            lambda: MAIN(lane, name="second"),
            "already is the @MAIN 'first'",
            "call the factory once per @MAIN",
        )
    print("test_one_function_registered_twice_is_an_error PASS")


def test_main_during_a_simulation_run_is_an_error():
    with _registry():
        pypeline._sim_run_in_progress = True
        try:
            _expect(
                RuntimeError,
                lambda: MAIN(make_lane(0), name="late"),
                "during a simulation run",
            )
        finally:
            pypeline._sim_run_in_progress = False
    print("test_main_during_a_simulation_run_is_an_error PASS")


def test_main_of_a_non_function_is_an_error():
    with _registry():
        _expect(TypeError, lambda: MAIN(uint8_t, name="t"), "must be a function")
    print("test_main_of_a_non_function_is_an_error PASS")


def test_duplicate_names_message():
    with _registry():
        a = MAIN(make_lane(0))
        b = MAIN(make_lane(1))
        msg = pypeline._duplicate_main_names([a, b])
        assert "Two @MAINs are named 'lane'" in msg, msg
        assert msg.count(THIS_FILE + ":") == 2, msg
        assert "MAIN(fn, name=...)" in msg, msg
        c = MAIN(make_lane(2), name="Lane")
        msg = pypeline._duplicate_main_names([a, c])
        assert "named 'lane' and 'Lane', one name in VHDL" in msg, msg
        d = MAIN(make_lane(3), name="other")
        assert pypeline._duplicate_main_names([a, d]) is None
    print("test_duplicate_names_message PASS")


def test_name_helpers_are_shared_with_the_compiler():
    import PY_TO_LOGIC

    assert PY_TO_LOGIC.HW_FUNC_NAME is pypeline._hw_func_name
    assert PY_TO_LOGIC._sanitize_vhdl_name is pypeline._sanitize_vhdl_name
    assert PY_TO_LOGIC.HW_FUNC_NAME("io", "_main") == "io_v_main"
    assert pypeline._module_prefix("pypeline_design") is None
    assert pypeline._module_prefix("__main__") is None
    assert pypeline._module_prefix("a.b") == "a_b"
    print("test_name_helpers_are_shared_with_the_compiler PASS")


def test_build_results_find_mains_by_name():
    import pypeline_sim

    with _registry():
        lanes = [MAIN(make_lane(i), name=f"lane{i}") for i in range(2)]
        assert pypeline_sim._mains_by_name(lanes) == {
            "lane0": lanes[0],
            "lane1": lanes[1],
        }
    print("test_build_results_find_mains_by_name PASS")


def test_live_root_main_is_keyed_by_its_name():
    import PY_TO_LOGIC

    with _registry():
        lane = MAIN(make_lane(0), name="lane0")
        state = PY_TO_LOGIC.ELABORATE_LIVE_ROOTS([lane])
        assert list(state.main_mhz) == ["lane0"], list(state.main_mhz)
        assert state.FuncLogicLookupTable["lane0"].func_name == "lane0"
    print("test_live_root_main_is_keyed_by_its_name PASS")


if __name__ == "__main__":
    test_decorator_forms()
    test_call_form_registers_a_factory_function()
    test_call_form_keeps_mhz()
    test_name_must_be_a_vhdl_identifier()
    test_default_name_is_the_function_name()
    test_default_name_has_the_module_prefix()
    test_default_name_is_the_functions_own_name()
    test_one_function_registered_twice_is_an_error()
    test_main_during_a_simulation_run_is_an_error()
    test_main_of_a_non_function_is_an_error()
    test_duplicate_names_message()
    test_name_helpers_are_shared_with_the_compiler()
    test_build_results_find_mains_by_name()
    test_live_root_main_is_keyed_by_its_name()
    print("factory_main_api_unit_test: all PASS")
