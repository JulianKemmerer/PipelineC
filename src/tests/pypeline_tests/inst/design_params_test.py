#!/usr/bin/env python3
# pyright: reportInvalidTypeForm=none
"""In-process unit tests for design parameters (pypeline.param, -D NAME=VALUE):
  - precedence: -D, then the env= variable (only when set and non-empty),
    then the default;
  - conversion by type (bool spellings, int incl. 0x, float, str, tuple/list
    from comma lists, literal-or-string without a type) and the errors, which
    name the parameter, where the value came from and the declaration site;
  - choices, duplicate declarations, a bare -D NAME, invalid names;
  - one resolution per process (a later environment change is not seen) and a
    new -D table resets it;
  - injected globals: every -D name is installed in builtins, a new table
    restores what it replaced, and the post-import checks catch an unused
    name (with a suggestion), a module-level shadow and a declared name read
    as a bare global, while a real injected read passes;
  - PARSE_FILE re-registers declarations on each parse with the same values,
    and the report/banner/--list_params text and source_provenance.json carry
    every value and its source.
See design_params_build_test.py for the pypelinec / pypeline_sim.py drivers."""
import builtins
import json
import os
import sys
import tempfile
import textwrap

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(THIS_DIR, "..", "..", ".."))
sys.path.insert(0, os.path.join(THIS_DIR, "..", "..", "..", "..", "include", "pypeline"))

import pypeline
import pypeline_sim
from pypeline import DesignParamError, param

ENV = "PYPELINE_DESIGN_PARAMS_TEST_ENV"


def _expect_error(fn, *fragments):
    try:
        fn()
    except DesignParamError as e:
        for fragment in fragments:
            assert fragment in str(e), (fragment, str(e))
        return str(e)
    raise AssertionError(f"expected DesignParamError containing {fragments}")


def test_precedence():
    os.environ.pop(ENV, None)
    pypeline.SET_DESIGN_PARAMS({})
    assert param("A", 1, env=ENV) == 1
    assert pypeline.DESIGN_PARAM_VALUES()["A"] == (1, "default")

    os.environ[ENV] = ""  # set but empty counts as unset
    pypeline.SET_DESIGN_PARAMS({})
    assert param("A", 1, env=ENV) == 1

    os.environ[ENV] = "7"
    pypeline.SET_DESIGN_PARAMS({})
    assert param("A", 1, env=ENV) == 7
    assert pypeline.DESIGN_PARAM_VALUES()["A"] == (7, "env:" + ENV)

    pypeline.SET_DESIGN_PARAMS({"A": "5"})
    assert param("A", 1, env=ENV) == 5
    assert pypeline.DESIGN_PARAM_VALUES()["A"] == (5, "-D")
    os.environ.pop(ENV)


def test_types():
    cases = [
        (True, "on", True), (True, "No", False), (False, "1", True), (False, "FALSE", False),
        (8, "12", 12), (8, "0x10", 16), (2.5, "30", 30.0), ("a", "b,c", "b,c"),
        ((16, 64), "1, 2,3", (1, 2, 3)), ((16,), "[4,5]", (4, 5)), (["x"], "p,q", ["p", "q"]),
        ((), "", ()), ((True,), "1,0", (True, False)),
    ]
    for default, text, expected in cases:
        pypeline.SET_DESIGN_PARAMS({"T": text})
        got = param("T", default)
        assert got == expected and type(got) is type(expected), (default, text, got)
    for text, expected in (("3", 3), ("abc", "abc"), ("(1, 2)", (1, 2)), ("'q'", "q")):
        pypeline.SET_DESIGN_PARAMS({"T": text})
        assert param("T") == expected, (text, param("T"))
    pypeline.SET_DESIGN_PARAMS({"T": "abc"})
    assert param("T", "x", type=str.upper) == "ABC"
    pypeline.SET_DESIGN_PARAMS({"T": "maybe"})
    msg = _expect_error(lambda: param("T", False), "Design parameter T", "'maybe' is not a valid value",
                        "-D on the command line", "design_params_test.py:")
    pypeline.SET_DESIGN_PARAMS({"T": "6.5"})
    _expect_error(lambda: param("T", 8), "'6.5' is not a valid value")
    os.environ[ENV] = "zz"
    pypeline.SET_DESIGN_PARAMS({})
    _expect_error(lambda: param("T", 8, env=ENV), "environment variable " + ENV)
    os.environ.pop(ENV)
    assert msg


def test_choices_duplicates_bare():
    pypeline.SET_DESIGN_PARAMS({"C": "12"})
    _expect_error(lambda: param("C", 8, choices=(8, 16)), "12 is not one of (8, 16)", "-D on the command line")
    _expect_error(lambda: param("D", 3, choices=(8, 16)), "default 3 is not one of (8, 16)")

    pypeline.SET_DESIGN_PARAMS({})
    assert param("E", 4) == 4
    assert param("E", 4) == 4  # an identical second declaration is fine
    _expect_error(lambda: param("E", 5), "param('E') is declared differently at")

    pypeline.SET_DESIGN_PARAMS({"FLAG": True, "N": True})
    assert param("FLAG", False) is True
    assert param("FLAG2") is None  # undeclared default
    _expect_error(lambda: param("N", 3), "needs a value: -D N=...")


def test_names_and_parsing():
    assert pypeline.PARSE_DESIGN_PARAM_DEFINES(["A=1", "B", "C=", "A=1", "D=x=y"]) == {
        "A": "1", "B": True, "C": "", "D": "x=y"
    }
    _expect_error(lambda: pypeline.PARSE_DESIGN_PARAM_DEFINES(["A=1", "A=2"]), "given twice")
    for bad in ("1x", "class", "len", "__x", "a-b"):
        _expect_error(lambda: pypeline.PARSE_DESIGN_PARAM_DEFINES([bad + "=1"]), repr(bad))
    _expect_error(lambda: param("not ok", 1), "is not a Python identifier")
    # -D could never set a builtin's name, so declaring one is an error too
    _expect_error(lambda: param("min", 1), "would shadow the Python builtin")


def test_once_per_process():
    os.environ[ENV] = "1"
    pypeline.SET_DESIGN_PARAMS({})
    assert param("P", 0, env=ENV) == 1
    os.environ[ENV] = "2"
    pypeline.RESET_DESIGN_PARAM_DECLARATIONS()  # a later import, same process
    assert param("P", 0, env=ENV) == 1
    pypeline.SET_DESIGN_PARAMS({})  # a new table starts over
    assert param("P", 0, env=ENV) == 2
    os.environ.pop(ENV)


def test_injection():
    marker = object()
    builtins.PYPELINE_TEST_PREVIOUS = marker  # an earlier, unrelated builtin
    try:
        pypeline.SET_DESIGN_PARAMS({"INJ_X": "3", "INJ_S": "abc", "INJ_B": True})
        assert (builtins.INJ_X, builtins.INJ_S, builtins.INJ_B) == (3, "abc", True)
        pypeline.SET_DESIGN_PARAMS({"INJ_Y": "(1, 2)"})
        assert not hasattr(builtins, "INJ_X") and builtins.INJ_Y == (1, 2)
        pypeline.SET_DESIGN_PARAMS({})
        assert not hasattr(builtins, "INJ_Y")
        assert builtins.PYPELINE_TEST_PREVIOUS is marker
    finally:
        del builtins.PYPELINE_TEST_PREVIOUS


def _write(directory, name, text):
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write(textwrap.dedent(text))
    return path


def _import_fresh(path):
    # pypelinec evicts a design's modules between imports; do the same here
    for name in [m for m in sys.modules if m.startswith("dp_")]:
        del sys.modules[name]
    return pypeline_sim._import_design(path)


def test_injected_name_checks():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "dp_cfg.py", """
            from pypeline import param
            WIDTH = param("WIDTH", 8)
        """)
        good = _write(tmp, "dp_good.py", """
            from pypeline import MAIN, make_uint_t
            import dp_cfg
            data_t = make_uint_t(dp_cfg.WIDTH)
            def helper():
                return INJ_INC  # read in a nested scope counts
            @MAIN
            def dp_good_main(x: data_t) -> data_t:
                return x + INJ_INC
        """)
        pypeline.SET_DESIGN_PARAMS({"WIDTH": "16", "INJ_INC": "2"})
        _import_fresh(good)
        assert pypeline.DESIGN_PARAM_VALUES()["WIDTH"] == (16, "-D")

        typo = _write(tmp, "dp_typo.py", """
            from pypeline import MAIN, make_uint_t
            import dp_cfg
            u_t = make_uint_t(INJ_WIDTH)
        """)
        pypeline.SET_DESIGN_PARAMS({"INJ_WIDHT": "16", "INJ_WIDTH": "16"})
        _expect_error(lambda: _import_fresh(typo),
                      "-D INJ_WIDHT: nothing in this design uses it", "Did you mean INJ_WIDTH?",
                      "Declared parameters: WIDTH.")

        shadow = _write(tmp, "dp_shadow.py", """
            import dp_cfg
            x = 1
            INJ_WIDTH = 8
        """)
        pypeline.SET_DESIGN_PARAMS({"INJ_WIDTH": "16"})
        _expect_error(lambda: _import_fresh(shadow),
                      "dp_shadow.py:4 assigns INJ_WIDTH at module level",
                      "INJ_WIDTH = param('INJ_WIDTH', <default>)")

        bare = _write(tmp, "dp_bare.py", """
            import dp_cfg
            def width():
                return WIDTH
            W = width()
        """)
        pypeline.SET_DESIGN_PARAMS({"WIDTH": "16"})
        _expect_error(lambda: _import_fresh(bare),
                      "dp_bare.py reads WIDTH as a bare global", "dp_cfg.py:3")
        # The library and the standard library are never checked
        files = pypeline.DESIGN_PARAM_SOURCE_FILES(["os", "pypeline", "stream.stream"], bare)
        assert files == [os.path.abspath(bare)], files
    pypeline.SET_DESIGN_PARAMS({})


def test_parse_file_report_and_provenance():
    import PY_TO_LOGIC

    design = os.path.join(THIS_DIR, "design_params_design.py")
    pypeline.SET_DESIGN_PARAMS({"WIDTH": "16", "STEP": "3"})
    with tempfile.TemporaryDirectory() as out_dir:
        PY_TO_LOGIC.FREEZE_DESIGN_SOURCES(out_dir)
        PY_TO_LOGIC.PARSE_FILE(design)
        first = pypeline.DESIGN_PARAM_VALUES()
        assert set(pypeline.DESIGN_PARAM_DECLARATIONS()) == {"WIDTH", "GOAL_MHZ", "STEP"}
        PY_TO_LOGIC.PARSE_FILE(design)  # a pin-and-confirm re-parse
        assert pypeline.DESIGN_PARAM_VALUES() == first
        assert set(pypeline.DESIGN_PARAM_DECLARATIONS()) == {"WIDTH", "GOAL_MHZ", "STEP"}

        report = {r["name"]: r for r in pypeline.DESIGN_PARAM_REPORT()}
        assert report["WIDTH"]["value"] == 16 and report["WIDTH"]["source"] == "-D"
        assert report["WIDTH"]["choices"] == [8, 12, 16] and report["WIDTH"]["type"] == "int"
        assert report["GOAL_MHZ"]["source"] == "default" and report["GOAL_MHZ"]["value"] == 100.0
        assert report["STEP"]["declared_at"].endswith("design_params_design.py:9")
        banner = "\n".join(pypeline.DESIGN_PARAM_BANNER_LINES())
        assert "WIDTH    = 16 (-D)" in banner, banner
        listing = pypeline.DESIGN_PARAM_LIST_TEXT(design)
        assert "WIDTH: int = 16 (-D); default 8; one of 8, 12, 16" in listing, listing
        assert "data path width in bits" in listing

        PY_TO_LOGIC.WRITE_SOURCE_PROVENANCE()
        with open(os.path.join(out_dir, "source_provenance.json")) as f:
            provenance = json.load(f)
        recorded = {r["name"]: r for r in provenance["design_params"]}
        assert recorded["STEP"]["value"] == 3 and recorded["STEP"]["source"] == "-D"
        PY_TO_LOGIC._freeze_output_dir = None  # no atexit rewrite into the deleted dir
    pypeline.SET_DESIGN_PARAMS({})


if __name__ == "__main__":
    test_precedence()
    test_types()
    test_choices_duplicates_bare()
    test_names_and_parsing()
    test_once_per_process()
    test_injection()
    test_injected_name_checks()
    test_parse_file_report_and_provenance()
    print("All design parameter tests passed.")
