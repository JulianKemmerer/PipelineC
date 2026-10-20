"""AUTO_FSM around a soft comparator prefix tree under a register-free MAIN.

The original comparator subtree, without Poly1305 arithmetic. Each nine-leaf
prefix helper inside it derives 12.8 ns from standalone leaves on Artix-7,
against a stored Vivado measurement of 2.3 ns, so:

- the scheduler must ask for a measurement of each helper an estimate would
  force apart, and keep the measured helper whole;
- the generated FSM stores array input elements individually, which must
  render as indexes rather than field names;
- the MAIN holds no state of its own, so only the scheduled re-parse knows it
  needs a clock enable for the FSM;
- a helper kept whole as a pipelined unit is not a blocked descent.

No synthesis runs here: the measurement hook records its request and supplies
the measured delay.
"""

from pathlib import Path
import sys
import tempfile

# Standalone compiler imports; TMPDIR is supplied by the runner.
sys.path[:0] = [
    str(Path(__file__).resolve().parents[3]),
    str(Path(__file__).resolve().parents[4] / "include" / "pypeline"),
]

import AUTO
import AUTO_FSM
import LOGIC
import PY_TO_LOGIC
import SYN
import VIVADO
import pypeline

SOURCE = """
from pypeline import AUTO_FSM, MAIN, PART, uint1_t, uint2_t
from operators.soft_cmp import _make_prefix_tree
PART("xc7a200tffg1156-2")
prefix = _make_prefix_tree(17, level=3)
FSM = AUTO_FSM(prefix)
@MAIN(80.0)
def top(value: uint2_t[17], valid: uint1_t) -> uint2_t:
    request: FSM.in_stream_t
    request.data = value
    request.valid = valid
    response = FSM(request)
    return response.data
"""
# Cached Artix-7 leaf delays of this build (du): one-bit NEQ/OR and a 2-bit MUX.
LEAF_DU = 10
MEASURED_HELPER_DU = 23


def cold_parse(tmp, mux_du=None):
    """Parse, then give the helpers the delays a cold delay scope derives.

    `mux_du(parser)` optionally overrides the measured 2-bit MUX leaf first.
    """
    SYN.SYN_TOOL = VIVADO
    path = Path(tmp) / "cold_hierarchy.py"
    path.write_text(SOURCE)
    parser = PY_TO_LOGIC.PARSE_FILE(str(path))
    ((key, tag),) = AUTO_FSM.GET_TAGS(parser).items()
    entity = AUTO._entity_key_for_callable(parser, tag.func)
    order = []

    def postorder(name):
        if name in order:
            return
        for child in parser.FuncLogicLookupTable[name].submodule_instances.values():
            postorder(child)
        order.append(name)

    postorder(entity)
    helpers = []
    for name in order:
        logic = parser.FuncLogicLookupTable[name]
        if SYN.PATH_DELAY_IS_PRIMITIVE(logic):
            zero = SYN.LOGIC_IS_ZERO_DELAY(logic, parser, allow_none_delay=True)
            logic.delay, logic.delay_is_estimated = (0 if zero else LEAF_DU), False
            if mux_du is not None and name.startswith("MUX_"):
                logic.delay = mux_du(parser)
        elif name != entity:
            helpers.append(name)
    SYN.ESTIMATE_HIER_PATH_DELAYS(helpers, parser, quiet=True)
    return parser, key, tag, entity, helpers


def measured_schedule(tmp):
    """The schedule once every helper carries its measurement."""
    parser, key, tag, _entity, helpers = cold_parse(tmp)
    for name in helpers:
        logic = parser.FuncLogicLookupTable[name]
        logic.delay, logic.delay_is_estimated = MEASURED_HELPER_DU, False
    return (
        parser,
        key,
        tag,
        AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, AUTO_FSM.DEFAULT_BUDGET_SCALE),
    )


def test_estimated_descent_is_measured_and_kept_whole():
    requested = []

    def measure(parser_state, entities):
        requested.append(sorted(entities))
        for name in entities:
            logic = parser_state.FuncLogicLookupTable[name]
            logic.delay, logic.delay_is_estimated = MEASURED_HELPER_DU, False
        return parser_state

    original = AUTO_FSM._measure_entities
    AUTO_FSM._measure_entities = measure
    try:
        with tempfile.TemporaryDirectory() as tmp:
            parser, key, tag, _entity, helpers = cold_parse(tmp)
            budget = AUTO_FSM._budget_du(parser, AUTO_FSM.DEFAULT_BUDGET_SCALE)
            too_slow = sorted(
                name
                for name in helpers
                if parser.FuncLogicLookupTable[name].delay + AUTO.MUX_PENALTY_DU
                > budget
            )
            assert too_slow, "the cold estimates no longer force any descent; the test lost its subject"
            cold = AUTO_FSM.BUILD_SCHEDULE(
                parser, key, tag, AUTO_FSM.DEFAULT_BUDGET_SCALE
            )
            assert not {
                node["entity"] for node in cold["nodes"].values() if node.get("fu")
            } & set(
                too_slow
            ), "precondition: the cold estimate splits the over-budget helpers apart"

            parser = AUTO_FSM._measure_schedule_inputs(parser, {}, None)
            measured = {name for batch in requested for name in batch}
            assert set(too_slow) & measured, (too_slow, requested)
            assert all(
                not parser.FuncLogicLookupTable[name].delay_is_estimated
                for name in measured
            )
            schedule = AUTO_FSM.BUILD_SCHEDULE(
                parser, key, tag, AUTO_FSM.DEFAULT_BUDGET_SCALE
            )
            bound = {
                node["entity"] for node in schedule["nodes"].values() if node.get("fu")
            }
            assert (
                set(too_slow) & bound
            ), "a measured helper that fits a state stays whole"
            assert bound <= measured | {
                name
                for name in bound
                if not parser.FuncLogicLookupTable[name].delay_is_estimated
            }
            assert set(schedule["measured_entities"]) >= bound
            assert schedule["entity"] == AUTO_FSM._schedule_entity_name(
                schedule["func_entity"], schedule
            )
            report = AUTO_FSM.DESCRIBE_SCHEDULE(parser, key, schedule)
            assert (
                f"operation delays: {len(bound)} of {len(bound)} unit kind(s) measured, 0 estimated"
                in report
            )
            floor = AUTO_FSM._chain_floor(schedule)
            assert (
                1 <= floor <= schedule["n_states"]
                and f"dependency floor: {floor} states" in report
            )

            # Units outside the function's subtree (generated wrappers) count
            # too: live measurements, and measurements a schedule carried.
            outside = sorted(measured)[0]
            assert AUTO_FSM._measured_entities(parser, {outside}, ()) == [outside]
            assert AUTO_FSM._measured_entities(
                parser, {"not_elaborated_unit"}, ["not_elaborated_unit"]
            ) == ["not_elaborated_unit"]

            # A second pass consults the carried measurement instead of measuring again.
            before = len(requested)
            for name in measured:
                parser.FuncLogicLookupTable[name].delay = None
            AUTO_FSM._measure_schedule_inputs(parser, {}, {key: schedule})
            assert len(requested) == before, requested[before:]

        # Nested descents: at a 0.6 budget both the nine-leaf helper and the
        # five-leaf helpers inside it would split on estimates. Only the outer
        # one is measured; once it fits a state, the inner decision never arises.
        requested.clear()
        with tempfile.TemporaryDirectory() as tmp:
            parser, key, tag, _entity, helpers = cold_parse(tmp)
            budget = AUTO_FSM._budget_du(parser, 0.6)
            nine, five = (
                next(name for name in helpers if f"n_leaves_{n}_" in name)
                for n in (9, 5)
            )
            assert all(
                parser.FuncLogicLookupTable[name].delay + AUTO.MUX_PENALTY_DU > budget
                for name in (nine, five)
            )
            AUTO_FSM._measure_schedule_inputs(parser, {key: 0.6}, None)
            assert requested and nine in requested[0], requested
            assert five not in {
                name for batch in requested for name in batch
            }, requested

        # A measured part already slower than a state settles the descent of
        # everything containing it: no helper above it is synthesized whole.
        requested.clear()
        with tempfile.TemporaryDirectory() as tmp:
            parser, key, tag, _entity, helpers = cold_parse(
                tmp,
                lambda parsed: AUTO_FSM._budget_du(
                    parsed, AUTO_FSM.DEFAULT_BUDGET_SCALE
                )
                + 1,
            )
            AUTO_FSM._measure_schedule_inputs(parser, {}, None)
            assert not {name for batch in requested for name in batch} & set(
                helpers
            ), requested
    finally:
        AUTO_FSM._measure_entities = original


def test_pipelined_helper_is_not_a_blocked_descent():
    """An over-budget helper kept whole as a pipelined unit is a choice whose
    stages fit; reporting it as a blocked descent misled a Poly1305 report."""
    with tempfile.TemporaryDirectory() as tmp:
        parser, _key, _tag, entity, helpers = cold_parse(tmp)
        budget = AUTO_FSM._budget_du(parser, AUTO_FSM.DEFAULT_BUDGET_SCALE)
        child = sorted(parser.FuncLogicLookupTable[entity].submodule_instances.values())
        slow = [
            name
            for name in helpers
            if name in child
            and parser.FuncLogicLookupTable[name].delay + AUTO.MUX_PENALTY_DU > budget
        ]
        assert slow, "precondition: a direct over-budget helper"
        dag = AUTO.BUILD_DAG(parser, entity, {}, budget, preserved=slow[:1])
        assert slow[0] not in {row[1] for row in dag["descend_blocked"]}, dag[
            "descend_blocked"
        ]
        assert any(n["entity"] == slow[0] for n in dag["nodes"].values())


def test_array_input_elements_render_as_indexes():
    with tempfile.TemporaryDirectory() as tmp:
        parser, _key, tag, schedule = measured_schedule(tmp)
        plan = AUTO_FSM._INPUT_STORAGE_PLAN(
            schedule["nodes"], schedule["output"], schedule["n_states"]
        )
        assert plan is not None and all(
            field["field"].isdigit() for field in plan["stored_fields"]
        ), plan
        name, source, _globals = AUTO_FSM.GENERATE_FSM_SOURCE(tag, schedule, parser)
        compile(source, name, "exec")
        assert "s.data[0]" in source and "s.data.0" not in source


def test_scheduled_fsm_drives_a_stateless_main_clock_enable():
    with tempfile.TemporaryDirectory() as tmp:
        parser, key, _tag, schedule = measured_schedule(tmp)
        ((main,),) = [tuple(parser.main_mhz)]
        assert not LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(
            parser.LogicInstLookupTable[main], parser
        ), "precondition: the bootstrap MAIN holds only the combinational passthrough"
        pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({key: schedule})
        try:
            scheduled = PY_TO_LOGIC.PARSE_FILE(str(Path(tmp) / "cold_hierarchy.py"))
        finally:
            pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({})
        assert LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(
            scheduled.LogicInstLookupTable[main], scheduled
        ), "the scheduled FSM's registers need the MAIN's clock enable"


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
