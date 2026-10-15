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
PY_TO_LOGIC.PARSE_FILE on it directly, so the scenarios (struct
overflow, function overflow, same-spelling definitions and forced collision) never interact with each
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


def test_same_named_closures_in_different_factories_are_distinct():
    with tempfile.TemporaryDirectory() as tmp:
        state = _parse(tmp, "d_collision", _COLLISION_SRC)
    widgets = [k for k in state.FuncLogicLookupTable if k.startswith("widget_")]
    assert len(widgets) == 2, widgets
    displayed = [state.pypeline_emission_names.identifier(k) for k in widgets]
    assert any("make_thing_a" in k for k in displayed), displayed
    assert any("make_thing_b" in k for k in displayed), displayed


def test_forced_canonical_collision_raises_naming_both_sources():
    from unittest.mock import patch

    original = PY_TO_LOGIC._canonical_func_name

    def collide(func, *args, **kwargs):
        if func.__name__ == "widget":
            return "widget_forced_collision"
        return original(func, *args, **kwargs)

    with tempfile.TemporaryDirectory() as tmp, patch.object(
        PY_TO_LOGIC, "_canonical_func_name", collide
    ):
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


# ── user names (name=) on hardware and AUTO tags ──
_USER_NAMES_SRC = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {repo!r})
    from enum import IntEnum
    from pypeline import (
        MAIN, NamedTuple, hw_func, struct, enum, uint8_t, uint16_t, AUTO_PIPELINE,
    )

    def make_pair_t(n):
        @struct(name=f"pair{{n}}_t")
        class pair_t(NamedTuple):
            a: uint8_t
            b: uint8_t
        return pair_t

    def make_adder(k):
        @hw_func(name=f"add_{{k}}")
        def adder(x: uint8_t) -> uint8_t:
            return x + k
        return adder

    pair4_t = make_pair_t(4)
    add3 = make_adder(3)
    add5 = make_adder(5)

    @hw_func
    def square(x: uint16_t) -> uint16_t:
        return x * x

    enc = AUTO_PIPELINE(square, name="square_encrypt")
    dec = AUTO_PIPELINE(square, name="square_decrypt")

    @MAIN
    def top(x: uint8_t, y: uint16_t) -> uint16_t:
        p = pair4_t(a=add3(x), b=add5(x))
        return enc(y) + dec(y) + p.a + p.b
    """
).format(repo=REPO_SRC)


def test_user_names_section_and_named_groups():
    import pypeline

    with tempfile.TemporaryDirectory() as tmp:
        state = _parse(tmp, "d_user_names", _USER_NAMES_SRC)
        SYN.WRITE_NAME_INDEX_LOG(state)
        with open(os.path.join(SYN.SYN_OUTPUT_DIRECTORY, "name_index.log")) as f:
            index = f.read()
    section = index.split("USER NAMES\n", 1)[1].split("\n\n", 1)[0]
    for line in (
        "  add_3 (function)",
        "    vhdl:     add_3",
        "    replaces: adder_k_3_s",
        "  pair4_t (struct)",
        "    replaces: pair_t_a_uint8_t_b_uint8_t_n_4",
        "  square_encrypt (AUTO_PIPELINE)",
        "    key:      square_decrypt",
    ):
        assert line in section, (line, section)
    names = state.pypeline_emission_names
    assert names.identifier(
        next(k for k in state.FuncLogicLookupTable if k.startswith("add_3_s"))
    ) == "add_3"
    # The automatic description stays in the index
    assert "function: adder_from_d_user_names_k_3" in index
    assert "user name: add_3" in index
    # Two names on one function: two instances (never collapsed as duplicate
    # calls of one function), with the callee's call-site labels and separate tags
    top = state.FuncLogicLookupTable["top"]
    keys = {
        top.sub_inst_to_auto_pipeline_key[inst]: inst
        for inst in top.sub_inst_to_auto_pipeline_key
        if inst in top.submodule_instances
    }
    assert sorted(keys) == ["square_decrypt", "square_encrypt"], keys
    for key, inst in keys.items():
        assert inst.startswith("square["), (key, inst)
    pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()


def test_conflicting_auto_pipeline_name_names_both_sites():
    src = _USER_NAMES_SRC.replace(
        'dec = AUTO_PIPELINE(square, name="square_decrypt")',
        'dec = AUTO_PIPELINE(square, name="square_encrypt", max_latency=4)',
    )
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _parse(tmp, "d_name_conflict", src)
        except TypeError as e:
            msg = str(e)
            assert msg.count("d_name_conflict.py:") == 2, msg
            assert "one latency group" in msg, msg
            return
    raise AssertionError("Expected TypeError for two different square_encrypt tags")


def test_auto_tag_names_preserve_instance_hierarchy():
    """Names on a direct tag and a stream factory preserve emitted labels."""
    import pypeline

    src = textwrap.dedent("""
        import sys
        sys.path.insert(0, {repo!r})
        sys.path.insert(0, {library!r})
        from pypeline import MAIN, hw_func, uint8_t, AUTO_PIPELINE
        from stream.stream_auto_pipeline import make_stream_auto_pipeline

        @hw_func
        def square(x: uint8_t) -> uint8_t:
            return x * x

        TAG = AUTO_PIPELINE(square{direct})
        stream_core = make_stream_auto_pipeline(square{stream})

        @MAIN
        def direct_top(x: uint8_t) -> uint8_t:
            return TAG(x)

        @MAIN
        def stream_top(stream_in_if: stream_core.in_fwd_t, stream_out_if: stream_core.out_fb_t) -> stream_core.return_t:
            return stream_core(stream_in_if, stream_out_if)
    """)
    with tempfile.TemporaryDirectory() as tmp:
        def parse(named):
            return _parse(tmp, "neutral", src.format(
                repo=REPO_SRC, library=os.path.join(REPO_SRC, "..", "include", "pypeline"),
                direct=', name="direct_group"' if named else "",
                stream=', name="stream_group"' if named else ""))
        plain = parse(False)
        named = parse(True)
        def instances(state):
            # Inline expressions have no VHDL instance: their internal names
            # contain factory-derived type identities, which may include a tag key.
            return sorted(i for i, logic in state.LogicInstLookupTable.items()
                          if not (logic.is_vhdl_expr or logic.is_vhdl_func))
        assert instances(plain) == instances(named)
        def labels(state):
            trie = SYN._VHDL_INSTANCE_TRIE(state)
            result = []
            def walk(node, path):
                inst = node.get(SYN._PATH_TRIE_INST)
                if inst in instances(state):
                    result.append(path)
                for label, child in node.items():
                    if label != SYN._PATH_TRIE_INST:
                        walk(child, path + (label,))
            for main, node in trie.items():
                walk(node, (main,))
            return sorted(result)
        assert labels(plain) == labels(named)
    pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
