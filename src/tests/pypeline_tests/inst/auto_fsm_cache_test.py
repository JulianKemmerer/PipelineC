"""Carried schedule validity, pinned recipe integrity, model-only updates and
call sites new to a build (AUTO_FSM.REPARSE)."""

import copy
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import textwrap

# Standalone compiler imports; tests write only under the runner's TMPDIR.
sys.path[:0] = [
    str(Path(__file__).resolve().parents[3]),
    str(Path(__file__).resolve().parents[4] / "include" / "pypeline"),
]

import AUTO
import AUTO_FSM
import PY_TO_LOGIC
import pypeline

# Scope pins the written chain while keeping ordinary unsigned arithmetic.
DESIGN = textwrap.dedent("""
from pypeline import AUTO_FSM, INFERRED, MAIN, NamedTuple, hw_func, register_operator, struct, uint1_t, uint16_t
@struct
class input_t(NamedTuple):
    a: uint16_t
    b: uint16_t
    c: uint16_t
    d: uint16_t
@hw_func
def chain(x: input_t) -> uint16_t:
    a: uint16_t = x.a + x.b
    b: uint16_t = a + x.c
    return b + x.d
register_operator("PLUS", uint16_t, uint16_t, INFERRED, scope=chain)
FSM = AUTO_FSM(chain)
@MAIN(10.0)
def top(x: input_t, valid: uint1_t) -> uint16_t:
    request: FSM.in_stream_t
    request.data = x
    request.valid = valid
    response = FSM(request)
    return response.data
""")


def parse(path):
    parser = PY_TO_LOGIC.PARSE_FILE(path)
    ((key, tag),) = AUTO_FSM.GET_TAGS(parser).items()
    return parser, key, tag


def test_schedule_cache_rejects_stale_source_target_and_version():
    pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cache_design.py")
            Path(path).write_text(DESIGN)
            parser, key, tag = parse(path)
            for name, logic in parser.FuncLogicLookupTable.items():
                if name.startswith("BIN_OP_PLUS_"):
                    logic.delay = 30
            schedule = AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.9)
            pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({key: schedule})
            replay, replay_key, replay_tag = parse(path)
            assert replay_key == key and replay_tag.schedule is not None
            assert not replay.pypeline_auto_fsm_schedule_rejections
            AUTO_FSM.CHECK_SCHEDULES_APPLIED(replay)
            provenance = replay.pypeline_auto_fsm_provenance[key]
            source = replay_tag._generated._auto_fsm_generated_src
            assert len(provenance["lines"]) == len(source.splitlines())
            assert any(
                row["kind"] == "unit" and row["node_ids"] for row in provenance["lines"]
            )
            assert any(
                row["role"] == "work" for row in provenance["registers"].values()
            )

            stale = dict(schedule, version=schedule["version"] - 1)
            pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({key: stale})
            assert parse(path)[2].schedule is None

            target = copy.deepcopy(schedule)
            target["target_context"][2] = "different-part"
            pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({key: target})
            refused, _key, refused_tag = parse(path)
            assert refused_tag.schedule is None
            # A build re-parses only with schedules it has just produced, so
            # a refusal there is an internal error, never a silent passthrough.
            assert key in refused.pypeline_auto_fsm_schedule_rejections
            try:
                AUTO_FSM.CHECK_SCHEDULES_APPLIED(refused)
            except AUTO_FSM.AutoFsmInternalError as error:
                assert key in str(error)
            else:
                raise AssertionError("a refused schedule must not pass silently")

            Path(path).write_text(DESIGN.replace("return b + x.d", "return b - x.d"))
            pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({key: schedule})
            _parser, changed_key, changed = parse(path)
            assert changed_key == key and changed.schedule is None
    finally:
        pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({})


# An AUTO_FSM sized from an AUTO_PIPELINE depth, the shape of WireGuard's
# Poly1305 kernels (lanes = depth + 2): a different depth is a different function
# and so a different call site.
LATENCY_SIZED_DESIGN = textwrap.dedent("""
from pypeline import AUTO_FSM, AUTO_PIPELINE, MAIN, NamedTuple, hw_func, struct, uint1_t, uint8_t, uint16_t
@hw_func
def core(x: uint8_t) -> uint8_t:
    return x + 1
CORE = AUTO_PIPELINE(core)
CAPACITY = CORE.latency + 2
def make_lane_sum(capacity):
    @struct
    class lanes_t(NamedTuple):
        values: uint8_t[capacity]
    @hw_func
    def lane_sum(x: lanes_t) -> uint16_t:
        total: uint16_t = 0
        for i in range(capacity):
            total = total + x.values[i]
        return total
    return lanes_t, lane_sum
lanes_t, lane_sum = make_lane_sum(CAPACITY)
FSM = AUTO_FSM(lane_sum)
@MAIN(10.0)
def core_top(x: uint8_t) -> uint8_t:
    return CORE(x)
@MAIN(10.0)
def fsm_top(x: lanes_t, valid: uint1_t) -> uint16_t:
    request: FSM.in_stream_t
    request.data = x
    request.valid = valid
    response = FSM(request)
    return response.data
""")


def fake_delay_schedule(parser, key, tag):
    for name, logic in parser.FuncLogicLookupTable.items():
        if name.startswith("BIN_OP_PLUS_"):
            logic.delay = 30
    return AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.9)


def test_reparse_schedules_call_sites_new_to_the_build():
    # AUTO_PIPELINE pin-and-confirm pass 2 re-executes the design with the
    # built depth installed; the AUTO_FSM call site it creates has no schedule
    # (WireGuard's cold 40 MHz build stopped here with AutoFsmInternalError).
    pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({})
    pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "latency_sized_design.py")
            Path(path).write_text(LATENCY_SIZED_DESIGN)
            parser, old_key, tag = parse(path)
            assert old_key.startswith("lane_sum_capacity_2_"), old_key
            pypeline.SET_AUTO_FSM_SCHEDULE_CACHE(
                {old_key: fake_delay_schedule(parser, old_key, tag)}
            )
            (core_key,) = {
                key
                for logic in parser.FuncLogicLookupTable.values()
                for key in logic.sub_inst_to_auto_pipeline_key.values()
                if key is not None
            }
            pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({core_key: 1})
            calls = []

            def schedule_call_sites(state, keys):
                calls.append(list(keys))
                tags = AUTO_FSM.GET_TAGS(state)
                return state, {
                    key: fake_delay_schedule(state, key, tags[key]) for key in keys
                }

            state = AUTO_FSM.REPARSE(
                path, None, schedule_call_sites=schedule_call_sites
            )
            ((new_key, new_tag),) = AUTO_FSM.GET_TAGS(state).items()
            assert new_key.startswith("lane_sum_capacity_3_"), new_key
            assert calls == [[new_key]], calls
            assert new_tag.schedule is not None
            assert not state.pypeline_auto_fsm_schedule_rejections
            assert set(pypeline.AUTO_FSM_SCHEDULE_CACHE()) == {old_key, new_key}
    finally:
        pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({})
        pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})


def test_reparse_still_refuses_a_rejected_schedule():
    # Only a call site with no installed schedule is new. One whose schedule
    # was refused is never rescheduled: that is still an internal error.
    pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "refused_design.py")
            Path(path).write_text(DESIGN)
            parser, key, tag = parse(path)
            stale = fake_delay_schedule(parser, key, tag)
            stale["target_context"][2] = "different-part"
            pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({key: stale})
            calls = []

            def schedule_call_sites(state, keys):
                calls.append(list(keys))
                return state, {}

            try:
                AUTO_FSM.REPARSE(path, None, schedule_call_sites=schedule_call_sites)
            except AUTO_FSM.AutoFsmInternalError as error:
                assert key in str(error), error
            else:
                raise AssertionError("a refused schedule must not pass silently")
            assert calls == [], calls
    finally:
        pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({})


def test_call_site_created_during_a_pass_is_scheduled_blamed_and_tightened():
    # DO_SCHEDULE_PASSES with measurement, search and sweep stubbed. Pass 1's
    # sweep re-elaborates the design into a new call site (as AUTO_PIPELINE
    # pass 2 does for a function sized from a depth) and that FSM misses
    # timing. It must be scheduled from the requested budget scale, blamed,
    # tightened, and rescheduled by pass 2.
    from contextlib import ExitStack
    from types import SimpleNamespace
    from unittest.mock import patch

    import AUTO_PIPELINE
    import SWEEP
    import SYN

    design = ["old"]

    def state():
        key = design[0]
        logic = SimpleNamespace(sub_inst_to_auto_fsm_key={"fsm": key})
        return SimpleNamespace(
            part="part",
            pypeline_auto_fsm_tags={key: SimpleNamespace(schedule={})},
            pypeline_auto_fsm_schedule_rejections={},
            pypeline_auto_fsm_provenance={},
            FuncLogicLookupTable={"top": logic},
            LogicInstLookupTable={"top": logic},
        )

    harvested = []

    def harvest(parser, budget_scales, previous, keys=None, **_options):
        keys = sorted(parser.pypeline_auto_fsm_tags if keys is None else keys)
        scales = {
            key: budget_scales.get(key, AUTO_FSM.DEFAULT_BUDGET_SCALE) for key in keys
        }
        harvested.append(sorted(scales.items()))
        return {
            key: dict(
                entity="auto_fsm_" + key,
                budget_scale=scales[key],
                # Hardware that follows the budget, so a tightening changes it
                n_states=int(4 / scales[key]),
                worst_state_du=150,
                at_floor=False,
                latency_infeasible=False,
            )
            for key in keys
        }

    sweeps = []

    def sweep(parser, args, src_file, schedule_call_sites=None):
        sweeps.append(design[0])
        if len(sweeps) == 1:
            design[0] = "new"
            parser = AUTO_FSM.REPARSE(
                src_file, "part", schedule_call_sites=schedule_call_sites
            )
            failures = [("top", 100.0, 80.0, "auto_fsm_new")]
        else:
            failures = []
        return parser, SimpleNamespace(sweep_timing_failures=failures)

    def calibrate(parser, budget_scales, ctl, previous, keys=None):
        keys = parser.pypeline_auto_fsm_tags if keys is None else keys
        return parser, {key: {} for key in keys}

    noop = lambda *args, **kwargs: None
    args = SimpleNamespace(
        auto_fsm_budget_scale=2.5,
        auto_fsm_unshare=[],
        auto_fsm_open=[],
        auto_fsm_ctl="auto",
        auto_fsm_no_area_sweep=False,
        auto_fsm_sweep_debug=False,
    )
    pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({})
    try:
        with ExitStack() as stack:
            for obj, name, value in [
                (SYN, "ADD_PATH_DELAY_TO_LOOKUP", lambda parser: parser),
                (AUTO_FSM, "_measure_schedule_inputs", lambda parser, *a: parser),
                (AUTO_FSM, "_calibrate_controls", calibrate),
                (AUTO_FSM, "HARVEST_AUTO_FSM_SCHEDULES", harvest),
                (AUTO_FSM, "_confirm_unit_placements", lambda parser, s, h: s),
                (AUTO_FSM, "DESCRIBE_SCHEDULE", lambda *a: ""),
                (AUTO_FSM, "DESCRIBE_FUS", lambda schedule: []),
                (AUTO_FSM, "DUMP_GENERATED_SOURCE", noop),
                (AUTO_FSM, "_unit_measurements", lambda *a: {}),
                (AUTO_FSM, "_fsm_instance_aliases", lambda *a: ()),
                (
                    AUTO_FSM,
                    "_collect_timing_evidence",
                    lambda p, t, s: {k: [] for k in s},
                ),
                (AUTO_FSM, "_period_du", lambda parser: 100.0),
                (
                    PY_TO_LOGIC,
                    "PARSE_FILE",
                    lambda src_file, resolved_part=None: state(),
                ),
                (AUTO_PIPELINE, "WRITE_0_ADDED_CLKS_INIT_FILES", noop),
                (AUTO_PIPELINE, "DO_SWEEP_AND_AUTO_PIPELINE", sweep),
                (SWEEP, "RETAINED_OBSERVATION", noop),
            ]:
                stack.enter_context(patch.object(obj, name, value))
            AUTO_FSM.DO_SCHEDULE_PASSES(state(), args, "design.py")
            # 80 of 100 MHz, a 15 ns worst state against a 10 ns period
            tightened = AUTO_FSM.TIGHTENED_BUDGET_SCALE(state(), 2.5, 0.8, 150)
    finally:
        pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({})
    assert sweeps == ["old", "new"], sweeps
    assert harvested == [
        [("old", 2.5)],  # pass 1
        [("new", 2.5)],  # REPARSE, during pass 1's sweep
        [("new", tightened)],  # tightened after pass 1's miss
        [("new", tightened)],  # pass 2
    ], harvested


def test_unit_characterization_counts_repeated_serial_operations():
    import SYN

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "profile_design.py")
        Path(path).write_text(DESIGN)
        parser, key, tag = parse(path)
        # The build driver resolves the backend before characterizing units.
        # Otherwise the planner's first lazy tool selection changes context.
        SYN.PART_SET_TOOL(parser.part)
        entity = AUTO._entity_key_for_callable(parser, tag.func)
        logic = parser.FuncLogicLookupTable[entity]
        delays = {}
        for name, child in parser.FuncLogicLookupTable.items():
            if name.startswith("BIN_OP_PLUS_"):
                child.delay = 30
                delays[name] = 30
        logic.delay = None
        unit = dict(
            kind="call",
            op=dict(kind="call"),
            entity=entity,
            port_types=[pypeline.ctype_name(tag.in_type)],
            out_type="uint16_t",
        )
        profiles = AUTO_FSM._unit_profiles(parser, key, unit, delays)
        assert AUTO_FSM._unit_profiles(parser, key, unit, delays) is profiles
        first = next(profile for profile in profiles if profile["latency"] == 1)
        # Three serial 3 ns operations require at least 4.5 ns on one side
        # of a single cut. Summing unique entity kinds underpriced this as 3 ns.
        assert first["worst_stage_du"] >= 45, first
        parser.part = "xc7a200tffg1156-2"
        retargeted = AUTO_FSM._unit_profiles(parser, key, unit, delays)
        assert retargeted is not profiles
        assert {row["context"] for row in profiles}.isdisjoint(
            row["context"] for row in retargeted
        )


def test_sparse_unit_recipe_restores_implicit_zero_placements():
    import AUTO_PIPELINE

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sparse_recipe.py"
        path.write_text(DESIGN)
        parser, key, tag = parse(str(path))
        entity = AUTO._entity_key_for_callable(parser, tag.func)
        delays = {}
        for name, logic in parser.FuncLogicLookupTable.items():
            if name.startswith("BIN_OP_PLUS_"):
                logic.delay = 30
                delays[name] = 30
        parser.FuncLogicLookupTable[entity].delay = None
        node = dict(
            kind="call",
            op=dict(kind="call"),
            entity=entity,
            port_types=[pypeline.ctype_name(tag.in_type)],
            out_type="uint16_t",
        )
        implementation = AUTO_FSM._unit_profiles(parser, key, node, delays)[0]
        isolated, root = AUTO_FSM._unit_isolated_tree(parser, entity, delays)
        table = {
            inst: AUTO_PIPELINE.TimingParams(inst, logic)
            for inst, logic in isolated.LogicInstLookupTable.items()
        }
        retained = {root + row["path"] for row in implementation["timing"]}
        omitted = sorted(set(table) - retained)
        assert omitted, "fixture must contain an implicit zero placement"
        table[omitted[0]]._has_input_regs = True
        AUTO_FSM.RESTORE_UNIT_PLACEMENT(root, implementation, isolated, table)
        assert not table[omitted[0]]._has_input_regs
        assert all(params.params_are_fixed for params in table.values())
        assert AUTO_FSM._unit_timing_recipe(root, table) == implementation["timing"]


def test_model_only_updates_keep_hardware_identity():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "identity_design.py")
        Path(path).write_text(DESIGN)
        parser, key, tag = parse(path)
        schedule = AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.9)
        changed = copy.deepcopy(schedule)
        changed.update(
            budget_scale=0.75,
            worst_state_du=1234,
            est_area=12345,
            cleanup=dict(folded=987),
            repair_history=["diagnostic"],
            comb_opt_moves=["demanded/known-bit narrowing"],
        )
        for node in changed["nodes"].values():
            node["end_du"] = 999
        assert AUTO_FSM.SCHEDULES_EQUAL({key: schedule}, {key: changed})
        assert AUTO_FSM._schedule_entity_name(
            schedule["func_entity"], schedule
        ) == AUTO_FSM._schedule_entity_name(changed["func_entity"], changed)
        assert AUTO_FSM.SCHEDULE_CACHE_USABLE(changed)


def test_forced_schedule_is_applied_on_reelaboration():
    # --auto_fsm_unshare/--auto_fsm_open schedules carry a report flag added
    # after naming; hashing it made re-elaboration refuse every forced schedule.
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "forced_design.py")
        Path(path).write_text(DESIGN)
        parser, key, tag = parse(path)
        anchor = AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.9)
        entity = next(
            node["entity"] for node in anchor["nodes"].values() if node.get("fu")
        )
        forced = AUTO_FSM.FORCE_SCHEDULE(
            parser, key, tag, 0.9, unshare_patterns=[(entity, 2)]
        )
        assert forced["forced"] and AUTO_FSM.SCHEDULE_CACHE_USABLE(forced)


def test_malformed_carried_data_is_always_a_cache_miss():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "malformed.py")
        Path(path).write_text(DESIGN)
        parser, key, tag = parse(path)
        schedule = AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.9)
        for field, value in (
            ("node_order", [[]]),
            ("nodes", None),
            ("implementations", [None]),
            ("n_states", "3"),
            ("fu_order", [[]]),
        ):
            bad = dict(schedule, **{field: value})
            assert not AUTO_FSM.SCHEDULE_CACHE_USABLE(bad), (field, value)


def emit_deterministic_source():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "deterministic.py"
        path.write_text(DESIGN)
        parser, key, tag = parse(str(path))
        for name, logic in parser.FuncLogicLookupTable.items():
            if name.startswith("BIN_OP_PLUS_"):
                logic.delay = 30
        schedule = AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.9)
        _name, source, _globals = AUTO_FSM.GENERATE_FSM_SOURCE(tag, schedule, parser)
        print(
            "SOURCE_JSON=" + json.dumps(dict(entity=schedule["entity"], source=source))
        )


def test_different_hash_seeds_emit_identical_source():
    results = []
    for seed in ("1", "777"):
        completed = subprocess.run(
            [sys.executable, __file__, "--emit-source"],
            env=dict(os.environ, PYTHONHASHSEED=seed),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=True,
        )
        results.append(
            next(
                row
                for row in completed.stdout.splitlines()
                if row.startswith("SOURCE_JSON=")
            )
        )
    assert results[0] == results[1]


def test_corrected_unit_tries_its_pipeline_before_forced_descent():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "repair_pipeline.py"
        path.write_text(DESIGN)
        parser, key, tag = parse(str(path))
        for name, logic in parser.FuncLogicLookupTable.items():
            if name.startswith("BIN_OP_PLUS_"):
                logic.delay = 30
        previous = AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.9)
        entity = next(
            node["entity"] for node in previous["nodes"].values() if node.get("fu")
        )
        previous["corrected_entity_delays"] = {entity: 1000}
        repaired = AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.9, previous)
        assert entity in repaired["implementations"], repaired
        bound = [node for node in repaired["nodes"].values() if node.get("fu")]
        assert len(bound) == 3 and all(node["entity"] == entity for node in bound)
        assert not repaired["at_floor"]


def test_encoding_memo_does_not_reuse_a_different_select_arrival():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "encoding_model.py"
        path.write_text(DESIGN)
        parser, key, tag = parse(str(path))
        for name, logic in parser.FuncLogicLookupTable.items():
            if name.startswith("BIN_OP_PLUS_"):
                logic.delay = 30
        previous = dict(
            control_delays_snapshot={
                "binary": dict(ctl="v3", delay_du=10),
                "hot": dict(ctl="onehot", delay_du=100),
            }
        )
        memo = {}
        binary = AUTO_FSM.BUILD_SCHEDULE(
            parser, key, tag, 0.9, previous, ctl="v3", build_memo=memo
        )
        hot = AUTO_FSM.BUILD_SCHEDULE(
            parser, key, tag, 0.9, previous, ctl="onehot", build_memo=memo
        )
        fresh = AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.9, previous, ctl="onehot")
        assert (
            hot["worst_state_du"] == fresh["worst_state_du"] > binary["worst_state_du"]
        )


def test_binding_search_reuses_clean_graph_without_sharing_mutable_results():
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "graph_memo.py"
        path.write_text(DESIGN)
        parser, key, tag = parse(str(path))
        for name, logic in parser.FuncLogicLookupTable.items():
            if name.startswith("BIN_OP_PLUS_"):
                logic.delay = 30
        memo = {}
        with patch.object(AUTO, "cleanup", wraps=AUTO.cleanup) as cleanup:
            anchor = AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.9, _graph_memo=memo)
            entity = next(iter(anchor["fus"].values()))
            count = cleanup.call_count
            choices = dict(unshared=((entity, 2),))
            cached = AUTO_FSM.BUILD_SCHEDULE(
                parser, key, tag, 0.9, _graph_memo=memo, **choices
            )
            assert cleanup.call_count == count
            fresh = AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.9, **choices)
            assert AUTO_FSM.SCHEDULES_EQUAL({key: cached}, {key: fresh})
            cached["nodes"].clear()
            replay = AUTO_FSM.BUILD_SCHEDULE(
                parser, key, tag, 0.9, _graph_memo=memo, **choices
            )
            assert AUTO_FSM.SCHEDULES_EQUAL({key: replay}, {key: fresh})
            # Width merges rebind the cleaned graph; they do not clean it again.
            rebinding = dict(merged=(("absent_narrow", entity),))
            count = cleanup.call_count
            merged = AUTO_FSM.BUILD_SCHEDULE(
                parser, key, tag, 0.9, _graph_memo=memo, **rebinding
            )
            assert cleanup.call_count == count
            assert AUTO_FSM.SCHEDULES_EQUAL(
                {key: merged},
                {key: AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.9, **rebinding)},
            )
            count = cleanup.call_count
            AUTO_FSM.BUILD_SCHEDULE(parser, key, tag, 0.8, _graph_memo=memo)
            assert cleanup.call_count > count


if __name__ == "__main__":
    if "--emit-source" in sys.argv:
        emit_deterministic_source()
    else:
        from _test_main import run_module_tests

        run_module_tests()
