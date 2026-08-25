#!/usr/bin/env python3
"""In-process PARSE_FILE regression tests for the name_index.log side-tables
added alongside the generated-name readability work (see
docs/PY_TO_LOGIC_DESIGN.md / docs/SYN_DESIGN.md):
  - parser_state.pypeline_name_full: collapsed canonical func name -> full,
    uncollapsed name (populated only when collapsing actually happened).
  - parser_state.pypeline_type_canonical: same idea for @struct/@enum types.
  - parser_state.pypeline_canonical_name_owner: collision guard -- two
    genuinely different closures landing on the same canonical name must
    raise, not silently dedup onto the wrong Logic().

Each test writes its own small synthetic design to a temp .py file and runs
PY_TO_LOGIC.PARSE_FILE on it directly, so the three scenarios (struct
overflow, func-name overflow, genuine collision) never interact with each
other's elaboration.
"""
import os
import sys
import tempfile
import textwrap

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import PY_TO_LOGIC
import SYN

REPO_SRC = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)


def _parse(tmpdir, name, src):
    path = os.path.join(tmpdir, name + ".py")
    with open(path, "w") as f:
        f.write(src)
    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="name_index_test_out_")
    return PY_TO_LOGIC.PARSE_FILE(path)


# ── a @struct whose canonical name overflows _MAX_MANGLE_NAME_LEN (96) ──
_OVERFLOW_STRUCT_SRC = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {repo!r})
    from pypeline import MAIN, hw_func, struct, uint32_t, NamedTuple

    @struct
    class overflow_struct_t(NamedTuple):
        field_one_with_a_very_long_descriptive_name: uint32_t
        field_two_with_a_very_long_descriptive_name: uint32_t
        field_three_with_a_very_long_descriptive_name: uint32_t
        field_four_with_a_very_long_descriptive_name: uint32_t

    def make_wraps_overflow(t):
        @hw_func
        def wraps_overflow(x: t) -> t:
            return x
        return wraps_overflow

    overflow_user = make_wraps_overflow(overflow_struct_t)

    @MAIN
    def name_index_struct_top(x: overflow_struct_t) -> overflow_struct_t:
        return overflow_user(x)
    """
).format(repo=REPO_SRC)


def test_overflowing_struct_gets_full_name_recorded():
    with tempfile.TemporaryDirectory() as tmp:
        parser_state = _parse(tmp, "d_struct", _OVERFLOW_STRUCT_SRC)

    collapsed = [
        n
        for n in parser_state.pypeline_type_canonical
        if n.startswith("overflow_struct_t")
    ]
    assert collapsed, (
        "expected overflow_struct_t's canonical name to have collapsed and "
        f"been recorded; pypeline_type_canonical={parser_state.pypeline_type_canonical}"
    )
    full = parser_state.pypeline_type_canonical[collapsed[0]]
    assert "field_one_with_a_very_long_descriptive_name" in full, full
    assert full.startswith("overflow_struct_t"), full
    print("test_overflowing_struct_gets_full_name_recorded PASS")


# ── a factory-closure func whose canonical name overflows _MAX_MANGLE_NAME_LEN (128) ──
_OVERFLOW_FUNC_SRC = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {repo!r})
    from pypeline import MAIN, hw_func, uint32_t

    def make_many_params(
        p0, p1, p2, p3, p4, p5, p6, p7, p8, p9,
        p10, p11, p12, p13, p14, p15, p16, p17, p18, p19,
    ):
        @hw_func
        def many_params_user(x: uint32_t) -> uint32_t:
            return x
        return many_params_user

    overflow_func_user = make_many_params(*range(100, 120))

    @MAIN
    def name_index_func_top(x: uint32_t) -> uint32_t:
        return overflow_func_user(x)
    """
).format(repo=REPO_SRC)


def test_overflowing_func_name_gets_full_name_recorded():
    with tempfile.TemporaryDirectory() as tmp:
        parser_state = _parse(tmp, "d_func", _OVERFLOW_FUNC_SRC)

    collapsed = [
        n for n in parser_state.pypeline_name_full if n.startswith("many_params_user")
    ]
    assert collapsed, (
        "expected many_params_user's canonical name to have collapsed and been "
        f"recorded; pypeline_name_full keys={list(parser_state.pypeline_name_full)}"
    )
    full = parser_state.pypeline_name_full[collapsed[0]]
    assert "p0_100" in full and "p19_119" in full, full
    print("test_overflowing_func_name_gets_full_name_recorded PASS")


# ── genuine canonical-name collision: two different 0-param factories whose
# inner functions share a name collapse to the SAME canonical name ("widget")
# despite being different definitions at different source lines.
_COLLISION_SRC = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {repo!r})
    from pypeline import MAIN, uint32_t

    def make_thing_a():
        def widget(x: uint32_t) -> uint32_t:
            return x
        return widget

    def make_thing_b():
        def widget(x: uint32_t) -> uint32_t:
            return x + 1
        return widget

    thing_a = make_thing_a()
    thing_b = make_thing_b()

    @MAIN
    def name_index_collision_top(x: uint32_t) -> uint32_t:
        a = thing_a(x)
        b = thing_b(a)
        return b
    """
).format(repo=REPO_SRC)


def test_canonical_name_collision_raises_naming_both_sources():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _parse(tmp, "d_collision", _COLLISION_SRC)
        except PY_TO_LOGIC.ElaborationError as e:
            msg = str(e)
            assert "widget" in msg, msg
            assert "make_thing_a" in msg, msg
            assert "make_thing_b" in msg, msg
            print(f"test_canonical_name_collision_raises_naming_both_sources PASS  ({e})")
            return
    raise AssertionError("Expected ElaborationError for the widget/widget collision")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
