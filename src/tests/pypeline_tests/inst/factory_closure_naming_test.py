# pyright: reportInvalidTypeForm=none
import ast
import functools
import inspect
import math
import os
import sys
import typing

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)

import PY_TO_LOGIC as P
import pypeline as PL

# Regression tests for readable, hierarchical canonical names of factory-
# closure functions (replacing opaque SHA-256 hashes for callable-valued
# closure params) -- see docs/PY_TO_LOGIC_DESIGN.md "Canonical function name
# format". These are pure-unit tests against _canonical_func_name /
# _callable_canonical_name / _collapse_overflow_name directly, since the bug
# being guarded against is silent/semantic (an uninformative-but-otherwise-
# valid name), not a syntax/toolchain rejection.


def round_a(x):
    return x + 1


def round_b(x):
    return x * 2 + 3


def make_quarter_round(a, b, c, d):
    def quarter_round(s):
        return s + a + b + c + d

    return quarter_round


def make_wrapper(func):
    def func_stream(x):
        return func(x)

    return func_stream


def make_negative_offset(amount):
    def offset_adder(s):
        return s + amount

    return offset_adder


def make_dot(coeffs):
    n = len(coeffs)

    def dot(arr):
        acc = 0
        for j in range(n):
            acc = acc + arr[j] * coeffs[j]
        return acc

    return dot


_module_level_lambda = lambda x: x + 1  # noqa: E731


MODULE_GLOBALS = {
    "round_a": round_a,
    "round_b": round_b,
    "make_quarter_round": make_quarter_round,
    "make_wrapper": make_wrapper,
    "make_negative_offset": make_negative_offset,
    "make_dot": make_dot,
}


def _closure_ns(fn):
    ns = {}
    if fn.__code__.co_freevars and fn.__closure__:
        for var, cell in zip(fn.__code__.co_freevars, fn.__closure__):
            ns[var] = cell.cell_contents
    return ns


def test_nested_factory_instances_get_distinct_readable_names():
    # The chacha20.py shape: two instantiations of the same inner factory,
    # closed over by nothing else -- must be distinct AND readable (not a
    # bare hash), matching quarter_round.py's now-removed manual __name__
    # override.
    qr1 = make_quarter_round(0, 4, 8, 12)
    qr2 = make_quarter_round(1, 5, 9, 13)
    name1 = P._canonical_func_name(qr1, _closure_ns(qr1), MODULE_GLOBALS)
    name2 = P._canonical_func_name(qr2, _closure_ns(qr2), MODULE_GLOBALS)
    assert name1 == "quarter_round_a_0_b_4_c_8_d_12", name1
    assert name2 == "quarter_round_a_1_b_5_c_9_d_13", name2
    assert name1 != name2
    print("test_nested_factory_instances_get_distinct_readable_names PASS")


def test_top_level_callable_closure_param_is_readable():
    # func_stream(func=round_a)-shaped case: the closed-over callable is a
    # plain top-level function -- its own name must appear, not a hash.
    fw_a = make_wrapper(round_a)
    fw_b = make_wrapper(round_b)
    name_a = P._canonical_func_name(fw_a, _closure_ns(fw_a), MODULE_GLOBALS)
    name_b = P._canonical_func_name(fw_b, _closure_ns(fw_b), MODULE_GLOBALS)
    assert "round_a" in name_a, name_a
    assert "round_b" in name_b, name_b
    assert name_a != name_b
    assert "_" + P._callable_hash(round_a) not in name_a  # no hash-only fallback
    print("test_top_level_callable_closure_param_is_readable PASS")


def test_nested_callable_closure_param_recurses_and_stays_unique():
    # func_stream(func=<quarter_round instance>)-shaped case (the actual
    # wireguard-fpga stream_pipeline shape): the closed-over callable is
    # ITSELF a differently-parameterized factory closure -- two different
    # instances must still be distinguishable through the outer name.
    qr1 = make_quarter_round(0, 4, 8, 12)
    qr2 = make_quarter_round(1, 5, 9, 13)
    fw1 = make_wrapper(qr1)
    fw2 = make_wrapper(qr2)
    name1 = P._canonical_func_name(fw1, _closure_ns(fw1), MODULE_GLOBALS)
    name2 = P._canonical_func_name(fw2, _closure_ns(fw2), MODULE_GLOBALS)
    assert "quarter_round_a_0_b_4_c_8_d_12" in name1, name1
    assert "quarter_round_a_1_b_5_c_9_d_13" in name2, name2
    assert name1 != name2
    print("test_nested_callable_closure_param_recurses_and_stays_unique PASS")


def make_shared_typed_helper(T):
    def shared_typed_helper(x: T) -> T:
        return x

    return shared_typed_helper


def test_function_type_params_are_not_mistaken_for_hardware_annotations():
    T = typing.TypeVar("T")

    def generic_identity(value):
        return value

    generic_identity.__type_params__ = (T,)
    func_def = ast.parse("def generic_identity(value: T) -> T: pass").body[0]
    assert not P._is_hardware_func(
        func_def, {"generic_identity": generic_identity}
    )

    if hasattr(typing, "override"):
        override_def = P._parsed_func_def(typing.override)
        assert not P._is_hardware_func(override_def, vars(typing))
    print("test_function_type_params_are_not_mistaken_for_hardware_annotations PASS")


def test_annotation_only_param_recovered_into_closure_ns():
    # Regression: a factory param used only in annotations (never in the
    # function body, e.g. the T in "x: T") is not captured as a Python
    # closure cell -- only _recover_annotation_closure_vars's AST-based
    # recovery finds it. A prior version of _callable_canonical_name's
    # recursive closure_ns construction skipped this step entirely, silently
    # dropping such params from nested names.
    helper = make_shared_typed_helper(PL.uint32_t)
    closure_ns = P._closure_cells_ns(helper)
    assert closure_ns == {}, closure_ns  # T not referenced in the body
    func_def = P._parsed_func_def(helper)
    P._recover_annotation_closure_vars(func_def, helper, closure_ns)
    assert closure_ns == {"T": PL.uint32_t}, closure_ns
    print("test_annotation_only_param_recovered_into_closure_ns PASS")


def test_recursive_naming_uses_callables_own_globals_and_recovers_annotations():
    # Regression: found via the full synth_tests.py suite (float32_add_test),
    # where a closed-over callable (make_abs's abs_val, imported from a
    # different module than the one currently being elaborated) got TWO
    # different names depending on whether it was named via the recursive
    # callable-closure path (using the CALLER's module_globals, which didn't
    # contain make_abs) or via its own direct top-level elaboration (using
    # its OWN module's globals, which did) -- a naming-consistency bug, not
    # just a readability one. Fixed by resolving the factory in the
    # callable's OWN __globals__, not whatever module_globals the caller
    # passes in. Also exercises annotation-only recovery (T is never
    # referenced in shared_typed_helper's body).
    helper = make_shared_typed_helper(PL.uint32_t)
    fw = make_wrapper(helper)
    # Deliberately empty module_globals: must not matter, since helper's own
    # __globals__ (this test module, which has make_shared_typed_helper) is
    # used instead.
    name = P._canonical_func_name(fw, _closure_ns(fw), {})
    assert "shared_typed_helper" in name, name
    assert "uint32_t" in name, name
    print(
        "test_recursive_naming_uses_callables_own_globals_and_recovers_annotations PASS"
    )


def test_same_factory_same_args_dedups():
    # Same factory + same args from two call sites must still produce the
    # SAME canonical name (cache-hit / dedup behavior unchanged).
    qr1a = make_quarter_round(0, 4, 8, 12)
    qr1b = make_quarter_round(0, 4, 8, 12)
    name1a = P._canonical_func_name(qr1a, _closure_ns(qr1a), MODULE_GLOBALS)
    name1b = P._canonical_func_name(qr1b, _closure_ns(qr1b), MODULE_GLOBALS)
    assert name1a == name1b
    print("test_same_factory_same_args_dedups PASS")


def test_functools_partial_closure_param_no_crash():
    p = functools.partial(round_a)
    fw_p = make_wrapper(p)
    name = P._canonical_func_name(fw_p, _closure_ns(fw_p), MODULE_GLOBALS)
    assert "round_a" in name, name
    print("test_functools_partial_closure_param_no_crash PASS")


def test_lambda_closure_param_is_valid_identifier_with_hash():
    # Module-level (short-qualname) lambda so the outer name doesn't overflow
    # _MAX_MANGLE_NAME_LEN and get hash-collapsed for an unrelated reason.
    fw_lam = make_wrapper(_module_level_lambda)
    name = P._canonical_func_name(fw_lam, _closure_ns(fw_lam), MODULE_GLOBALS)
    assert name.isidentifier(), name
    # Lambdas carry no distinguishing readable name, so a hash suffix is
    # expected here (the one deliberate remaining fallback case).
    assert P._callable_hash(_module_level_lambda) in name, name
    print("test_lambda_closure_param_is_valid_identifier_with_hash PASS")


@PL.hw_func
def hw_round_a(x: PL.uint32_t) -> PL.uint32_t:
    return x + 1


def test_hw_func_wrapped_closure_param_unwraps_before_recursing():
    # Regression for a real bug caught by the full synth suite (float32_add_test):
    # a closed-over @hw_func-decorated callable is the _sim_type_wrap WRAPPER, not
    # the original function -- the wrapper is itself a '.<locals>.'-qualified
    # closure (over _sim_type_wrap's own locals like 'ann', an annotations dict),
    # which is NOT a factory-closure param and must never be treated as one.
    # _callable_canonical_name must inspect.unwrap() before recursing, exactly
    # like _elaborate_live_func does for the top-level func.
    fw = make_wrapper(hw_round_a)
    name = P._canonical_func_name(fw, _closure_ns(fw), MODULE_GLOBALS)
    assert "hw_round_a" in name, name
    assert name.isidentifier(), name
    print("test_hw_func_wrapped_closure_param_unwraps_before_recursing PASS")


def test_builtin_closure_param_is_readable():
    fw_sqrt = make_wrapper(math.sqrt)
    name = P._canonical_func_name(fw_sqrt, _closure_ns(fw_sqrt), MODULE_GLOBALS)
    assert "sqrt" in name, name
    print("test_builtin_closure_param_is_readable PASS")


def test_cycle_guard_falls_back_to_hash_not_infinite_recursion():
    fw_a = make_wrapper(round_a)
    seen_containing_self = {id(fw_a)}
    result = P._callable_canonical_name(
        fw_a, MODULE_GLOBALS, _seen=seen_containing_self, _depth=0
    )
    assert result.isidentifier(), result
    print("test_cycle_guard_falls_back_to_hash_not_infinite_recursion PASS")


def test_overflow_collapse_keeps_readable_prefix():
    full = "inner_" + ("param_value_" * 20)
    collapsed = P._collapse_overflow_name(full, "inner")
    assert len(collapsed) <= P._MAX_MANGLE_NAME_LEN
    assert collapsed.startswith("inner")
    import hashlib

    expected_hash = hashlib.sha256(full.encode()).hexdigest()[:8]
    assert collapsed.endswith(expected_hash), collapsed
    print("test_overflow_collapse_keeps_readable_prefix PASS")


def test_negative_int_closure_param_has_no_bare_minus():
    # Regression: a negative-valued named closure constant used to bake a
    # bare '-' into the canonical name (invalid inside a VHDL basic
    # identifier) -- see the 'neg' prefix fix in _canonical_func_name and the
    # BIAS_PLUS_M_LEN workaround it replaces in floating_point.py.
    neg_instance = make_negative_offset(-5)
    name = P._canonical_func_name(
        neg_instance, _closure_ns(neg_instance), MODULE_GLOBALS
    )
    assert "-" not in name, name
    assert name.isidentifier(), name
    assert name == "offset_adder_amount_neg5", name
    print("test_negative_int_closure_param_has_no_bare_minus PASS")


def test_list_closure_param_is_readable_and_distinct():
    # The FIR-library shape: a factory parameterized by a coefficient list
    # (make_fir(coeffs)-style). Two instantiations with different coefficient
    # lists must get distinct, readable canonical names instead of the
    # elaborator rejecting list-valued closure params outright.
    dot_a = make_dot([3, -5, 7, 2])
    dot_b = make_dot([1, 1, -1, 4])
    name_a = P._canonical_func_name(dot_a, _closure_ns(dot_a), MODULE_GLOBALS)
    name_b = P._canonical_func_name(dot_b, _closure_ns(dot_b), MODULE_GLOBALS)
    assert name_a == "dot_coeffs_3_neg5_7_2", name_a
    assert name_b == "dot_coeffs_1_1_neg1_4", name_b
    assert name_a != name_b
    print("test_list_closure_param_is_readable_and_distinct PASS")


def test_list_closure_param_same_values_dedups():
    dot_a = make_dot([3, -5, 7, 2])
    dot_a2 = make_dot([3, -5, 7, 2])
    name_a = P._canonical_func_name(dot_a, _closure_ns(dot_a), MODULE_GLOBALS)
    name_a2 = P._canonical_func_name(dot_a2, _closure_ns(dot_a2), MODULE_GLOBALS)
    assert name_a == name_a2
    print("test_list_closure_param_same_values_dedups PASS")


def test_nested_list_closure_param_is_valid_identifier():
    dot_2d = make_dot([[1, 2], [3, -4]])
    name = P._canonical_func_name(dot_2d, _closure_ns(dot_2d), MODULE_GLOBALS)
    assert name == "dot_coeffs_1_2_3_neg4", name
    assert name.isidentifier(), name
    print("test_nested_list_closure_param_is_valid_identifier PASS")


def test_empty_list_closure_param_no_crash():
    dot_empty = make_dot([])
    name = P._canonical_func_name(dot_empty, _closure_ns(dot_empty), MODULE_GLOBALS)
    assert name == "dot_coeffs_empty", name
    print("test_empty_list_closure_param_no_crash PASS")


def test_tuple_closure_param_encoded_same_as_list():
    dot_list = make_dot([3, -5, 7, 2])
    dot_tuple = make_dot((3, -5, 7, 2))
    name_list = P._canonical_func_name(dot_list, _closure_ns(dot_list), MODULE_GLOBALS)
    name_tuple = P._canonical_func_name(
        dot_tuple, _closure_ns(dot_tuple), MODULE_GLOBALS
    )
    assert name_list == name_tuple == "dot_coeffs_3_neg5_7_2", (name_list, name_tuple)
    print("test_tuple_closure_param_encoded_same_as_list PASS")


def test_list_closure_param_float_element_is_readable():
    # Regression: a list element that isn't an int/bool/nested list (e.g. a
    # float) used to raise ElaborationError from _canonical_func_name --
    # encode_param_value now supports float directly (see
    # docs/PY_TO_LOGIC_DESIGN.md), so a float-valued coefficient list gets a
    # readable, distinct name instead of failing to elaborate at all.
    dot_float = make_dot([1, 2.5, 3])
    name = P._canonical_func_name(dot_float, _closure_ns(dot_float), MODULE_GLOBALS)
    assert name == "dot_coeffs_1_2p5_3", name
    assert name.isidentifier(), name
    print("test_list_closure_param_float_element_is_readable PASS")


def test_unencodable_closure_param_gets_labeled_hash_not_error():
    # A closure value of a type encode_param_value has no dedicated encoding
    # for (e.g. an arbitrary object) must still produce a valid identifier --
    # a labeled hash of its address-stripped repr -- rather than raising, so
    # an unusual factory parameter type never blocks elaboration outright.
    class Weird:
        pass

    def make_weird_holder(w):
        def weird_holder(x):
            return (x, w)  # reference w so it's captured as a closure cell

        return weird_holder

    local_globals = dict(MODULE_GLOBALS, make_weird_holder=make_weird_holder)
    holder = make_weird_holder(Weird())
    name = P._canonical_func_name(holder, _closure_ns(holder), local_globals)
    assert name.isidentifier(), name
    assert name.startswith("weird_holder_w_Weird_"), name
    print("test_unencodable_closure_param_gets_labeled_hash_not_error PASS")


def test_ast_meta_src_file_and_line_point_to_true_definition():
    # Regression for the _elaborate_live_func ast_meta bug: for a factory
    # closure, Logic.ast_meta.src_file/.line must point at the closure's own
    # true defining file/line (used by SYN.GET_OUTPUT_DIRECTORY to place
    # generated VHDL), not the enclosing elaboration context's file or a
    # dedent-relative line number.
    import tempfile

    import SYN
    from multi_cycle_path import make_valid_ready_mcp  # noqa: F401

    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="factory_closure_naming_test_")
    test_file = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "two_factory_wrappers_test.py")
    )
    parser_state = P.PARSE_FILE(test_file)

    import multi_cycle_path

    expected_file = os.path.abspath(inspect.getsourcefile(multi_cycle_path))
    _, expected_line = inspect.getsourcelines(multi_cycle_path.make_valid_ready_mcp)
    # func_mcp is defined a few lines into make_valid_ready_mcp's body; just
    # assert the file matches and the line falls within that function's body
    # (not, e.g., line 1 of a re-parsed/dedented snippet, and not the test
    # file that called make_valid_ready_mcp).
    found = False
    for logic in parser_state.FuncLogicLookupTable.values():
        if logic.ast_meta is not None and "func_mcp" in (logic.func_name or ""):
            assert logic.ast_meta.src_file == expected_file, logic.ast_meta.src_file
            assert logic.ast_meta.line > expected_line, (
                logic.ast_meta.line,
                expected_line,
            )
            found = True
    assert found, "no func_mcp-derived Logic() found in FuncLogicLookupTable"
    print("test_ast_meta_src_file_and_line_point_to_true_definition PASS")


# Regression tests for struct()'s automatic canonical-name disambiguation --
# a struct defined directly inside a factory function gets its canonical name
# suffixed, unconditionally, with that factory's own declared parameters
# (mirroring _canonical_func_name's closure-param handling for @hw_func
# factories -- a pure function of the call's own inputs, with no shared
# state, so the result never depends on elaboration order). This fixes the
# case where two distinct parameter combinations collapse to the same field
# type (e.g. a fixed-point factory where int_bits+frac_bits alone sizes the
# only field, so (4, 8) and (8, 4) would otherwise produce identical struct
# names) without requiring any change at the @struct call site itself.


def _make_split_struct(int_bits, frac_bits):
    val_t = PL.make_int_t(int_bits + frac_bits)

    @PL.struct
    class split_t(PL.NamedTuple):
        val: val_t

    return split_t


def test_struct_factory_param_suffix_disambiguates_colliding_field_types():
    a = _make_split_struct(4, 8)
    b = _make_split_struct(8, 4)
    # Without the param suffix, both would collapse to split_t_val_int12_t.
    # Params appear in the factory's own DECLARATION order (int_bits then
    # frac_bits), not alphabetical -- see docs/PY_TO_LOGIC_DESIGN.md.
    assert (
        a._pypeline_ctype_name == "split_t_val_int12_t_int_bits_4_frac_bits_8"
    ), a._pypeline_ctype_name
    assert (
        b._pypeline_ctype_name == "split_t_val_int12_t_int_bits_8_frac_bits_4"
    ), b._pypeline_ctype_name
    assert a._pypeline_ctype_name != b._pypeline_ctype_name
    print("test_struct_factory_param_suffix_disambiguates_colliding_field_types PASS")


def test_struct_factory_param_suffix_deterministic_regardless_of_order():
    # Elaborate a bunch of unrelated "noise" structs first, then the same
    # (int_bits, frac_bits) combination as above -- the exact-string
    # assertions above already prove this is a pure function of the call's
    # own inputs (no registry / no shared state to be order-sensitive), but
    # this test pins that guarantee explicitly rather than relying on
    # reading the implementation.
    for i in range(5):
        _make_split_struct(i + 1, i + 2)
    a = _make_split_struct(8, 4)
    b = _make_split_struct(4, 8)
    assert (
        a._pypeline_ctype_name == "split_t_val_int12_t_int_bits_8_frac_bits_4"
    ), a._pypeline_ctype_name
    assert (
        b._pypeline_ctype_name == "split_t_val_int12_t_int_bits_4_frac_bits_8"
    ), b._pypeline_ctype_name
    print("test_struct_factory_param_suffix_deterministic_regardless_of_order PASS")


def test_struct_factory_param_suffix_same_args_same_name():
    a = _make_split_struct(4, 8)
    b = _make_split_struct(4, 8)
    assert a._pypeline_ctype_name == b._pypeline_ctype_name
    print("test_struct_factory_param_suffix_same_args_same_name PASS")


def test_struct_bare_decorator_unaffected():
    @PL.struct
    class point_t(PL.NamedTuple):
        x: PL.uint32_t
        y: PL.uint32_t

    assert (
        point_t._pypeline_ctype_name == "point_t_x_uint32_t_y_uint32_t"
    ), point_t._pypeline_ctype_name
    print("test_struct_bare_decorator_unaffected PASS")


def _make_elem_wrapper_struct(elem_t):
    @PL.struct
    class wrapper_t(PL.NamedTuple):
        elem: elem_t

    return wrapper_t


def test_struct_factory_param_suffix_scalar_ctype_value():
    a = _make_elem_wrapper_struct(PL.uint8_t)
    b = _make_elem_wrapper_struct(PL.uint16_t)
    assert (
        a._pypeline_ctype_name == "wrapper_t_elem_uint8_t_elem_t_uint8_t"
    ), a._pypeline_ctype_name
    assert (
        b._pypeline_ctype_name == "wrapper_t_elem_uint16_t_elem_t_uint16_t"
    ), b._pypeline_ctype_name
    print("test_struct_factory_param_suffix_scalar_ctype_value PASS")


def _make_offset_struct(offset):
    val_t = PL.make_int_t(16)

    @PL.struct
    class offset_t(PL.NamedTuple):
        val: val_t

    return offset_t


def test_struct_factory_param_suffix_negative_value_safe():
    t = _make_offset_struct(-5)
    assert "-" not in t._pypeline_ctype_name, t._pypeline_ctype_name
    assert t._pypeline_ctype_name.isidentifier(), t._pypeline_ctype_name
    assert (
        t._pypeline_ctype_name == "offset_t_val_int16_t_offset_neg5"
    ), t._pypeline_ctype_name
    print("test_struct_factory_param_suffix_negative_value_safe PASS")


def _make_many_param_struct(p0, p1, p2, p3, p4, p5, p6, p7, p8, p9):
    @PL.struct
    class overflow_t(PL.NamedTuple):
        val: PL.uint32_t

    return overflow_t


def test_struct_factory_param_suffix_overflow_collapses_safely():
    t = _make_many_param_struct(*range(10))
    assert len(t._pypeline_ctype_name) <= PL._MAX_MANGLE_NAME_LEN
    assert t._pypeline_ctype_name.isidentifier(), t._pypeline_ctype_name
    assert t._pypeline_ctype_name.startswith("overflow_t")
    print("test_struct_factory_param_suffix_overflow_collapses_safely PASS")


# ─────────────────────────────────────────────────────────────────────────
# Regression tests for the naming patterns found by auditing a real build's
# own output (wireguard-fpga generated-files-sim-pipe-shared-native/) -- see
# docs/PY_TO_LOGIC_DESIGN.md's "Canonical function name format" and
# "Submodule Instance Names" sections.
# ─────────────────────────────────────────────────────────────────────────


def test_hw_func_name_elides_redundant_module_prefix():
    # The stuttering "append_auth_tag_append_auth_tag" shape (a module's own
    # entry-point function sharing the module's name) drops its prefix.
    assert P._hw_func_name("append_auth_tag", "append_auth_tag") == "append_auth_tag"
    # A prefix-of shape also elides.
    assert P._hw_func_name("chacha20", "chacha20_block") == "chacha20_block"
    # A genuinely distinct pair still gets prefixed.
    assert P._hw_func_name("chacha20", "quarter_round") == "chacha20_quarter_round"
    print("test_hw_func_name_elides_redundant_module_prefix PASS")


def test_enum_sequential_values_elided_sparse_kept():
    import enum as _enum_mod

    @PL.enum
    class seq_state_t(_enum_mod.IntEnum):
        IDLE = 0
        RUNNING = 1
        DONE = 2

    @PL.enum
    class sparse_state_t(_enum_mod.IntEnum):
        A = 0
        B = 5

    assert seq_state_t._pypeline_ctype_name == "seq_state_t_IDLE_RUNNING_DONE", (
        seq_state_t._pypeline_ctype_name
    )
    assert sparse_state_t._pypeline_ctype_name == "sparse_state_t_A_0_B_5", (
        sparse_state_t._pypeline_ctype_name
    )
    assert seq_state_t._pypeline_ctype_name != sparse_state_t._pypeline_ctype_name
    print("test_enum_sequential_values_elided_sparse_kept PASS")


def test_overflow_collapse_never_lands_mid_token():
    # Regression for real garbage found in a build's own output: a
    # fixed-character-offset truncation used to cut a name right after the
    # first digit of an unrelated trailing hash, or mid-word.
    full_a = "cast_stream_intrf_data_t_chacha_shared_pipeline_out_t_8d070d63_fe_b1dab4d2"
    collapsed_a = P._collapse_overflow_name(full_a, "cast_stream_intrf")
    assert "_8_" not in collapsed_a, collapsed_a
    assert not collapsed_a.split("_")[-2].isdigit() or len(collapsed_a.split("_")[-2]) != 1, (
        collapsed_a
    )
    full_b = "cast_stream_intrf_data_t_ndarray_fragment_t_a0f67613_feedback_t_uint1_t_76c61b8e"
    collapsed_b = P._collapse_overflow_name(full_b, "cast_stream_intrf")
    assert "_fe_" not in collapsed_b, collapsed_b
    print("test_overflow_collapse_never_lands_mid_token PASS")


def test_generic_call_site_alias_labels_instance_with_callee_name():
    # multi_cycle_path.make_valid_ready_mcp's generated wrapper calls the
    # caller-supplied function through a closure variable literally named
    # `func` -- real production code exercising exactly the generic-alias
    # shape _elab_submodule_instance now substitutes. Reuses
    # two_factory_wrappers_test.py (round_a/round_b via make_valid_ready_mcp)
    # rather than building a new design, since it already elaborates this
    # exact shape.
    import tempfile

    import SYN

    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="generic_alias_test_")
    test_file = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "two_factory_wrappers_test.py")
    )
    parser_state = P.PARSE_FILE(test_file)

    inst_labels = set()
    for logic in parser_state.FuncLogicLookupTable.values():
        inst_labels.update(logic.submodule_instances.keys())

    bare_func_labels = [l for l in inst_labels if l.startswith("func[")]
    assert not bare_func_labels, (
        f"expected no bare 'func[...]' instance labels, got {bare_func_labels}"
    )
    assert any(l.startswith("round_a[") for l in inst_labels), sorted(inst_labels)
    assert any(l.startswith("round_b[") for l in inst_labels), sorted(inst_labels)
    print("test_generic_call_site_alias_labels_instance_with_callee_name PASS")


def test_loc_str_omits_el_for_single_line_keeps_for_multiline():
    import types as _types_mod

    single = _types_mod.SimpleNamespace(
        lineno=10, col_offset=4, end_lineno=10, end_col_offset=20
    )
    multi = _types_mod.SimpleNamespace(
        lineno=10, col_offset=4, end_lineno=12, end_col_offset=8
    )
    single_str = P._loc_str("myfile.py", single)
    multi_str = P._loc_str("myfile.py", multi)
    assert single_str == "myfile_py_l10_c4_ec20", single_str
    assert "_el" not in single_str, single_str
    assert multi_str == "myfile_py_l10_c4_el12_ec8", multi_str
    # Two distinct nodes (different end_lineno) must never collide, even
    # though both start at the same (line, col) -- the original bug this
    # location suffix format guards against.
    other_multi = _types_mod.SimpleNamespace(
        lineno=10, col_offset=4, end_lineno=13, end_col_offset=8
    )
    assert P._loc_str("myfile.py", other_multi) != multi_str
    print("test_loc_str_omits_el_for_single_line_keeps_for_multiline PASS")


# ─────────────────────────────────────────────────────────────────────────
# Regression tests for built-in operator entity naming (_bin_func_name /
# _unary_func_name, PY_TO_LOGIC.py:1044-1063) -- not factory-closure
# canonical names like the rest of this file, but the smallest existing home
# for a pure-unit test against a private PY_TO_LOGIC naming helper. Array-typed
# operands (e.g. uint1_t[16] == / != uint1_t[16]) used to f-string-interpolate
# the raw C type string unsanitized into the BIN_OP_*/UNARY_OP_* entity name,
# producing e.g. "BIN_OP_EQ_uint1_t[16]_uint1_t[16]" -- illegal in a VHDL
# entity declaration. Real-synthesis regression:
# inst/array_compare_bracket_name_test.py (synth_tests.py). In-process check:
# operator_scope_test.py's test_array_equality_operator_names_are_bracket_free.
# ─────────────────────────────────────────────────────────────────────────


def test_bin_func_name_sanitizes_array_brackets():
    name = P._bin_func_name("EQ", "uint1_t[16]", "uint1_t[16]")
    assert "[" not in name and "]" not in name, name
    assert name.isidentifier(), name
    assert name == "BIN_OP_EQ_uint1_t_16_uint1_t_16", name
    print("test_bin_func_name_sanitizes_array_brackets PASS")


def test_unary_func_name_sanitizes_array_brackets():
    name = P._unary_func_name("NOT", "uint1_t[16]")
    assert "[" not in name and "]" not in name, name
    assert name.isidentifier(), name
    assert name == "UNARY_OP_NOT_uint1_t_16", name
    print("test_unary_func_name_sanitizes_array_brackets PASS")


def test_bin_func_name_scalar_types_unaffected():
    # Sanitization must be a no-op for the common scalar case -- guards
    # against a fix that reshapes every built-in operator's entity name,
    # not just array operands.
    name = P._bin_func_name("PLUS", "uint32_t", "uint32_t")
    assert name == "BIN_OP_PLUS_uint32_t_uint32_t", name
    print("test_bin_func_name_scalar_types_unaffected PASS")


def test_bin_func_name_builtin_op_info_keeps_unsanitized_types():
    # parser_state.pypeline_builtin_op_info's value tuple must keep the TRUE
    # (unsanitized) operand C type strings -- AUTOFSM._soft_equivalent_callable
    # (AUTOFSM.py:1061) reads this back out to ask the soft-operator library
    # for a decomposable equivalent; a bracket-stripped string is not a valid
    # C type to look up.
    class _FakeParserState:
        def __init__(self):
            self.pypeline_builtin_op_info = {}

    ps = _FakeParserState()
    name = P._bin_func_name("EQ", "uint1_t[16]", "uint1_t[16]", ps)
    op_name, operand_types = ps.pypeline_builtin_op_info[name]
    assert op_name == "EQ", op_name
    assert operand_types == ["uint1_t[16]", "uint1_t[16]"], operand_types
    print("test_bin_func_name_builtin_op_info_keeps_unsanitized_types PASS")


if __name__ == "__main__":
    test_nested_factory_instances_get_distinct_readable_names()
    test_top_level_callable_closure_param_is_readable()
    test_nested_callable_closure_param_recurses_and_stays_unique()
    test_function_type_params_are_not_mistaken_for_hardware_annotations()
    test_annotation_only_param_recovered_into_closure_ns()
    test_recursive_naming_uses_callables_own_globals_and_recovers_annotations()
    test_same_factory_same_args_dedups()
    test_functools_partial_closure_param_no_crash()
    test_hw_func_wrapped_closure_param_unwraps_before_recursing()
    test_lambda_closure_param_is_valid_identifier_with_hash()
    test_builtin_closure_param_is_readable()
    test_cycle_guard_falls_back_to_hash_not_infinite_recursion()
    test_overflow_collapse_keeps_readable_prefix()
    test_negative_int_closure_param_has_no_bare_minus()
    test_list_closure_param_is_readable_and_distinct()
    test_list_closure_param_same_values_dedups()
    test_nested_list_closure_param_is_valid_identifier()
    test_empty_list_closure_param_no_crash()
    test_tuple_closure_param_encoded_same_as_list()
    test_list_closure_param_float_element_is_readable()
    test_unencodable_closure_param_gets_labeled_hash_not_error()
    test_ast_meta_src_file_and_line_point_to_true_definition()
    test_struct_factory_param_suffix_disambiguates_colliding_field_types()
    test_struct_factory_param_suffix_deterministic_regardless_of_order()
    test_struct_factory_param_suffix_same_args_same_name()
    test_struct_bare_decorator_unaffected()
    test_struct_factory_param_suffix_scalar_ctype_value()
    test_struct_factory_param_suffix_negative_value_safe()
    test_struct_factory_param_suffix_overflow_collapses_safely()
    test_hw_func_name_elides_redundant_module_prefix()
    test_enum_sequential_values_elided_sparse_kept()
    test_overflow_collapse_never_lands_mid_token()
    test_generic_call_site_alias_labels_instance_with_callee_name()
    test_loc_str_omits_el_for_single_line_keeps_for_multiline()
    test_bin_func_name_sanitizes_array_brackets()
    test_unary_func_name_sanitizes_array_brackets()
    test_bin_func_name_scalar_types_unaffected()
    test_bin_func_name_builtin_op_info_keeps_unsanitized_types()
    print("All factory_closure_naming tests passed.")
