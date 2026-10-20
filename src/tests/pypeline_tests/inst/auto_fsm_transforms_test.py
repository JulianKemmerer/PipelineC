"""Proof/refusal cases for balanced selectors, width adapters and closed fusion."""

import copy
import sys
import tempfile
from pathlib import Path

# Compiler imports for the standalone in-process regression.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "include" / "pypeline"))

import AUTO
import AUTO_FSM as transforms
import LOGIC
import AUTO_FSM


def node(entity, op, left, right, port_type="uint8_t", out_type=None):
    return dict(
        kind="binop",
        op=dict(kind="binop", op=op),
        entity=entity,
        operands=[left, right],
        casts=[[], []],
        port_types=[port_type] * 2,
        out_type=out_type or port_type,
        delay_du=1,
    )


def graph(nodes, output):
    return dict(
        nodes=nodes,
        output=["node", output],
        output_casts=[],
        out_type=nodes[output]["out_type"],
    )


def primitive(parser, entity, op, ctype):
    parser.pypeline_builtin_op_info[entity] = (op, (ctype, ctype))
    logic = LOGIC.Logic()
    logic.func_name = entity
    logic.delay = 1
    parser.FuncLogicLookupTable[entity] = logic


def parser_state():
    parser = LOGIC.ParserState()
    # The Python frontend normally creates this original-operation table.
    parser.pypeline_builtin_op_info = {}
    return parser


def selection_graph(constants=(1, 2, 3), index_type="uint4_t"):
    parser = parser_state()
    primitive(parser, "eq", "EQ", index_type)
    nodes = {}
    result = ["in", "default"]
    for i, value in enumerate(constants):
        nodes[f"eq{i}"] = node(
            "eq",
            "==",
            ["in", "index"],
            ["lit", value, index_type],
            index_type,
            "uint1_t",
        )
        nodes[f"mux{i}"] = dict(
            kind="mux",
            op=dict(kind="mux"),
            entity="MUX_uint8_t",
            operands=[["node", f"eq{i}"], ["in", f"value{i}"], result],
            casts=[[], [], []],
            port_types=["uint1_t", "uint8_t", "uint8_t"],
            out_type="uint8_t",
            delay_du=1,
        )
        result = ["node", f"mux{i}"]
    return parser, graph(nodes, f"mux{len(constants)-1}")


def test_distinct_equalities_have_one_balanced_selection_with_default():
    parser, dag = selection_graph()
    matches = transforms._selection_chains(dag, parser, "root")
    outer = next(match for match in matches if match[0] == "mux2")
    assert outer[2] == ("uint4_t", "uint8_t", [3, 2, 1])
    assert outer[5] == ["in", "default"]
    fn = transforms._selection_function(outer[2], AUTO._TypeResolver())
    import pypeline

    for index in range(16):
        expected = {1: 31, 2: 21, 3: 11}.get(index, 77)
        assert int(pypeline.sim_call(fn, index, 77, 11, 21, 31)) == expected


def test_priority_and_unproved_index_chains_are_retained():
    parser, dag = selection_graph((1, 1))
    assert not transforms._selection_chains(dag, parser, "root")
    for ctype in ("int4_t", "uint65_t"):
        parser, dag = selection_graph((1, 2), ctype)
        assert not transforms._selection_chains(dag, parser, "root")


def test_real_field_read_chain_is_prepared_before_scheduling():
    import PY_TO_LOGIC

    source = """
from pypeline import AUTO_FSM, MAIN, NamedTuple, hw_func, struct, uint1_t, uint3_t, uint16_t
@struct
class input_t(NamedTuple):
    index: uint3_t
    values: uint16_t[4]
@hw_func
def choose(x: input_t) -> uint16_t:
    value: uint16_t = 12345
    for k in range(4):
        if x.index == k:
            value = x.values[k]
    return value
FSM = AUTO_FSM(choose)
@MAIN(5.0)
def top(x: input_t, valid: uint1_t) -> uint16_t:
    request: FSM.in_stream_t
    request.data = x
    request.valid = valid
    response = FSM(request)
    return response.data
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "field_selection.py"
        path.write_text(source)
        parser = PY_TO_LOGIC.PARSE_FILE(str(path))
        ((key, tag),) = AUTO_FSM.GET_TAGS(parser).items()
        assert len(parser.pypeline_auto_fsm_selections) == 1
        schedule = AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.9)
        assert schedule["cleanup"]["balanced_selections"] == 1


def test_prepared_fusion_matches_the_cleaned_scheduling_graph():
    import PY_TO_LOGIC

    source = """
from pypeline import AUTO_FSM, INFERRED, MAIN, NamedTuple, hw_func, register_operator, struct, uint1_t, uint16_t, uint32_t
@struct
class input_t(NamedTuple):
    values: uint16_t[4]
    b: uint16_t
    bias: uint32_t
@hw_func
def compute(x: input_t) -> uint32_t:
    total: uint32_t = 0
    for k in range(4):
        product: uint32_t = x.values[k] * x.b
        joined: uint32_t = product + x.bias
        total += joined
    return total
register_operator("INFERRED_MULT", uint16_t, uint16_t, INFERRED, scope=compute)
register_operator("PLUS", uint32_t, uint32_t, INFERRED, scope=compute)
FSM = AUTO_FSM(compute)
@MAIN(5.0)
def top(x: input_t, valid: uint1_t) -> uint32_t:
    request: FSM.in_stream_t
    request.data = x
    request.valid = valid
    response = FSM(request)
    return response.data
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fusion_preparation.py"
        path.write_text(source)
        parser = PY_TO_LOGIC.PARSE_FILE(str(path))
        ((key, tag),) = AUTO_FSM.GET_TAGS(parser).items()
        schedule = AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.9)
        matches = AUTO_FSM._pair_matches(
            {"nodes": schedule["nodes"], "output": schedule["output"]}, parser
        )
        assert matches and set(matches) <= set(parser.pypeline_auto_fsm_fusions)


def test_measurement_roots_are_trimmed_like_instantiated_logic():
    """A scheduled FSM later instantiates its generated candidates, and the
    design trims what it instantiates: an untrimmed measurement root gets
    different entity text under the same name, so it is synthesized twice."""
    import PY_TO_LOGIC

    source = """
from pypeline import AUTO_FSM, MAIN, hw_func, uint1_t, uint8_t
@hw_func
def offset(a: uint8_t, b: uint1_t) -> uint8_t:
    return a + b
@hw_func
def work(x: uint8_t) -> uint8_t:
    return offset(x, 1)
FSM = AUTO_FSM(work)
@MAIN(5.0)
def top(x: uint8_t, valid: uint1_t) -> uint8_t:
    request: FSM.in_stream_t
    request.data = x
    request.valid = valid
    response = FSM(request)
    return response.data
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "constant_wrapper.py"
        path.write_text(source)
        parser = PY_TO_LOGIC.PARSE_FILE(str(path))
        roots = AUTO_FSM.AUTO_FSM_MEASURE_ENTITIES(parser)
        assert any(r.startswith("auto_fsm_constant_") for r in roots), roots
        for name in sorted(roots):
            logic = parser.FuncLogicLookupTable[name]
            retrimmed = copy.deepcopy(logic)
            LOGIC._TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE_done_cache.discard(name)
            LOGIC.TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE(retrimmed, parser)
            assert retrimmed.wire_driven_by == logic.wire_driven_by, name


def test_unsigned_adapters_preserve_original_result_width():
    for op, name, result in (
        ("+", "PLUS", "uint8_t"),
        ("-", "MINUS", "uint8_t"),
        ("*", "INFERRED_MULT", "uint16_t"),
        ("<", "LT", "uint1_t"),
    ):
        parser = parser_state()
        primitive(parser, "narrow", name, "uint8_t")
        primitive(parser, "wide", name, "uint16_t")
        a = node("narrow", op, ["in", "a"], ["in", "b"], out_type=result)
        wide_result = (
            "uint32_t" if op == "*" else "uint1_t" if op == "<" else "uint16_t"
        )
        b = node("wide", op, ["in", "c"], ["in", "d"], "uint16_t", wide_result)
        dag = graph(
            dict(
                a=a,
                b=b,
                result=dict(
                    kind="assemble",
                    op=dict(kind="assemble", paths=[["a"], ["b"]]),
                    entity="assembly",
                    operands=[["node", "a"], ["node", "b"]],
                    casts=[[], []],
                    port_types=[result, wide_result],
                    out_type="pair",
                    delay_du=0,
                ),
            ),
            "result",
        )
        assert transforms._merge_choices(dag, parser) == [("narrow", "wide")]
        merged, count = transforms._merge_widths(
            copy.deepcopy(dag), [("narrow", "wide")], parser, {}
        )
        assert count == 1
        adapted = merged["nodes"]["a"]
        assert (
            adapted["out_type"] == result
            and adapted["physical_out_type"] == wide_result
        )
        assert adapted["result_casts"][-1] == result
        assert adapted["casts"] == [["uint8_t", "uint8_t"], ["uint8_t", "uint8_t"]]


def test_signed_and_nonmodular_operator_merges_are_refused():
    for ctype, op in (("int8_t", "+"), ("uint8_t", "^"), ("uint8_t", "/")):
        parser = parser_state()
        primitive(parser, "narrow", "PLUS", ctype)
        primitive(parser, "wide", "PLUS", "uint16_t")
        dag = graph(
            dict(
                a=node("narrow", op, ["in", "a"], ["in", "b"], ctype),
                b=node("wide", op, ["node", "a"], ["in", "c"], "uint16_t"),
            ),
            "b",
        )
        assert not transforms._merge_choices(dag, parser)


def test_search_merges_step_to_the_next_wider_unit():
    # Every compatible pair stays legal, but the search proposes only the next
    # wider unit: chains are reached over steps, and many widths no longer
    # multiply the neighborhood.
    parser = parser_state()
    for name, ctype in (("w8", "uint8_t"), ("w12", "uint12_t"), ("w16", "uint16_t")):
        primitive(parser, name, "PLUS", ctype)
    dag = graph(
        dict(
            a=node("w8", "+", ["in", "a"], ["in", "b"], "uint8_t"),
            b=node("w12", "+", ["in", "c"], ["in", "d"], "uint12_t"),
            c=node("w16", "+", ["in", "e"], ["in", "f"], "uint16_t"),
        ),
        "c",
    )
    assert transforms._merge_choices(dag, parser) == [
        ("w12", "w16"),
        ("w8", "w12"),
        ("w8", "w16"),
    ]
    assert transforms._local_merge_choices(dag, parser) == [
        ("w12", "w16"),
        ("w8", "w12"),
    ]


def test_fusion_requires_recurring_closed_pairs():
    parser = parser_state()
    primitive(parser, "multiply", "INFERRED_MULT", "uint8_t")
    primitive(parser, "plus", "PLUS", "uint8_t")
    primitive(parser, "xor", "XOR", "uint8_t")
    nodes = {}
    for i in range(2):
        nodes[f"p{i}"] = node("multiply", "*", ["in", f"a{i}"], ["in", "b"])
        nodes[f"c{i}"] = node("plus", "+", ["node", f"p{i}"], ["in", "c"])
    nodes["sum"] = node("plus", "+", ["node", "c0"], ["node", "c1"])
    dag = graph(nodes, "sum")
    assert len(transforms._pair_matches(dag, parser)) == 1
    nodes["outside"] = node("xor", "^", ["node", "p0"], ["node", "sum"])
    dag["output"] = ["node", "outside"]
    assert not transforms._pair_matches(dag, parser)


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
