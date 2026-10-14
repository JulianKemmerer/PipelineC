#!/usr/bin/env python3
"""Independent latency pieces: identity, goal selection, recording, JSON and prune."""
import json
import os
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(THIS_DIR, "..", "..", ".."))

import AUTO_MULTI_CYCLE
import AUTO_PIPELINE
import LOGIC
import SWEEP
import SYN
import VHDL
import pypeline

AP, MC = "AUTO_PIPELINE", "AUTO_MULTI_CYCLE"


def write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(doc, f)
    return path


def expect_value_error(path, fragment):
    try:
        SWEEP.READ_LATENCY_TABLE(path)
    except ValueError as e:
        assert fragment in str(e), str(e)
    else:
        raise AssertionError(f"{path} was accepted")


def test_read_latency_table_formats(tmp):
    hints = write(
        os.path.join(tmp, "hints.json"),
        {AP: {"chacha20": 17, "poly1305_body_encrypt": 3}, MC: {"prologue": 6}},
    )
    table, meta = SWEEP.READ_LATENCY_TABLE(hints)
    assert {k: e["latency"] for k, e in table.items()} == {
        (AP, "chacha20"): 17,
        (AP, "poly1305_body_encrypt"): 3,
        (MC, "prologue"): 6,
    }
    assert meta == {"part": None, "tool": None}
    memory = write(
        os.path.join(tmp, "memory.json"),
        {
            "schema_version": 1,
            "part": "xc7a200t",
            "tool": "vivado",
            AP: {"k": {"latency": 2, "goal_mhz": 60.0, "achieved_mhz": 61.5}},
            MC: {},
        },
    )
    table, meta = SWEEP.READ_LATENCY_TABLE(memory)
    assert table[(AP, "k")]["goal_mhz"] == 60.0 and meta["tool"] == "vivado"
    profile = write(
        os.path.join(tmp, "profile.json"),
        {
            "schema_version": 1,
            "part": "p",
            "tool": "t",
            "mains": {},
            "entries": [
                {"kind": AP, "key": "a", "latency": 4, "verified": True},
                {"kind": MC, "key": "m", "latency": 2, "verified": False},
            ],
        },
    )
    table, _ = SWEEP.READ_LATENCY_TABLE(profile)
    assert sorted(table) == [(MC, "m"), (AP, "a")]
    for doc, fragment in (
        ([1, 2], "JSON object"),
        ({"AUTO_PIPELNE": {"x": 1}}, "unknown section"),
        ({AP: [1]}, "must map"),
        ({AP: {"x": -1}}, ">= 0"),
        ({AP: {"x": "3"}}, ">= 0"),
        ({AP: {"x": True}}, ">= 0"),
        ({MC: {"x": 0}}, ">= 1"),
        ({"entries": [{"kind": "AUTO_FSM", "key": "x", "latency": 1}]}, "bad entry"),
    ):
        expect_value_error(write(os.path.join(tmp, "bad.json"), doc), fragment)
    print("test_read_latency_table_formats PASS")


def test_build_latency_profile_verdicts_and_seeds():
    parser_state = SimpleNamespace(part="xc7a200t")
    owners = {
        (AP, "both_met"): ({"main_a", "main_b"}, LOGIC.AutoPipelineLatency(), "shape1"),
        (AP, "one_failed"): ({"main_a", "main_c"}, LOGIC.AutoPipelineLatency(start_latency=2), "shape2"),
        (AP, "lower_bound"): ({"main_d"}, None, "shape3"),
        (AP, "not_built"): ({"main_a"}, None, "shape4"),
        (MC, "mcp"): ({"main_a"}, LOGIC.AutoMultiCycleConstraint("mcp", None, 3), "shape5"),
    }
    history = {
        "mains": {
            "main_a": {"goal_mhz": 60.0, "final": {"met": True, "met_basis": "measured", "achieved_mhz": 61.0}},
            "main_b": {"goal_mhz": 80.0, "final": {"met": True, "met_basis": "measured", "achieved_mhz": 85.0}},
            "main_c": {"goal_mhz": 60.0, "final": {"met": False, "met_basis": "timing_failure", "achieved_mhz": 50.0}},
            "main_d": {"goal_mhz": 30.0, "final": {"met": True, "met_basis": "no_failing_path_reported", "achieved_mhz": None}},
        }
    }
    mtp = SimpleNamespace(TimingParamsLookupTable={})
    with patch.object(SWEEP, "_latency_owners", lambda ps: owners), patch.object(
        AUTO_PIPELINE,
        "HARVEST_AUTO_PIPELINE_LATENCIES",
        lambda ps, tpl: ({"both_met": 3, "one_failed": 4, "lower_bound": 0}, {}),
    ), patch.object(
        AUTO_MULTI_CYCLE, "HARVEST_AUTO_MULTI_CYCLE_NCYCLES", lambda ps, p: {"mcp": 5}
    ), patch.object(SYN, "SYN_TOOL", SYN.TOOL_MODULES["vivado"]), patch.dict(
        SWEEP.LATENCY_SEEDS_USED, {(AP, "both_met"): (3, "latency memory")}, clear=True
    ):
        profile = SWEEP.BUILD_LATENCY_PROFILE(parser_state, mtp, history)
        again = SWEEP.BUILD_LATENCY_PROFILE(parser_state, mtp, history)
    assert json.dumps(profile, sort_keys=True) == json.dumps(again, sort_keys=True)
    by_key = {(e["kind"], e["key"]): e for e in profile["entries"]}
    assert [(e["kind"], e["key"]) for e in profile["entries"]] == sorted(by_key)
    assert (AP, "not_built") not in by_key
    both = by_key[(AP, "both_met")]
    assert both["verified"] and both["latency"] == 3
    assert both["goal_mhz"] == 80.0 and both["achieved_mhz"] == 61.0
    assert both["mains"] == ["main_a", "main_b"]
    assert both["seed"] == {"latency": 3, "source": "latency memory"}
    assert both["shape"] == "shape1"
    assert by_key[(AP, "one_failed")]["verified"] is False
    assert by_key[(AP, "one_failed")]["constraint"] == "start_latency=2"
    assert by_key[(AP, "lower_bound")]["verified"] is True
    assert by_key[(MC, "mcp")]["latency"] == 5 and by_key[(MC, "mcp")]["seed"] is None
    assert profile["part"] == "xc7a200t" and profile["tool"] == "vivado"
    assert profile["mains"]["main_c"] == {"goal_mhz": 60.0, "achieved_mhz": 50.0, "met": False}
    # Without a sweep history nothing is verified
    with patch.object(SWEEP, "_latency_owners", lambda ps: owners), patch.object(
        AUTO_PIPELINE, "HARVEST_AUTO_PIPELINE_LATENCIES", lambda ps, tpl: ({"both_met": 3}, {})
    ), patch.object(
        AUTO_MULTI_CYCLE, "HARVEST_AUTO_MULTI_CYCLE_NCYCLES", lambda ps, p: {}
    ), patch.object(SYN, "SYN_TOOL", None):
        profile = SWEEP.BUILD_LATENCY_PROFILE(parser_state, mtp, None)
    assert [e["verified"] for e in profile["entries"]] == [False]
    print("test_build_latency_profile_verdicts_and_seeds PASS")


_NESTED_SRC = """
import sys
sys.path.insert(0, {src!r})
from pypeline import AUTO_PIPELINE, MAIN, hw_func, uint8_t

@hw_func
def leaf(x: uint8_t) -> uint8_t:
    return x * x

INNER = AUTO_PIPELINE(leaf, name="inner")

@hw_func
def holder(x: uint8_t) -> uint8_t:
    return INNER(x) + 1

OUTER = AUTO_PIPELINE(holder, name="outer")
PLAIN = AUTO_PIPELINE(leaf, name="plain")

@MAIN
def nested_main(x: uint8_t) -> uint8_t:
    return OUTER(x) ^ PLAIN(x)
"""


def test_seeded_tags_are_start_only_regions(tmp):
    """A seeded tag's sweep starts at its seed (a start-only region), except a
    callee holding another AUTO_PIPELINE, which stays as unconstrained as its
    source; unseeded unconstrained tags are never regions."""
    import PY_TO_LOGIC

    design = os.path.join(tmp, "nested_seed_design.py")
    with open(design, "w") as f:
        f.write(_NESTED_SRC.format(src=os.path.join(THIS_DIR, "..", "..", "..")))
    SYN.SYN_OUTPUT_DIRECTORY = os.path.join(tmp, "nested_out")
    os.makedirs(SYN.SYN_OUTPUT_DIRECTORY, exist_ok=True)
    try:
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE("sweep")
        pypeline.SET_LATENCY_SEEDS(
            {(AP, "inner"): (2, "hints h.json"), (AP, "outer"): (3, "hints h.json")}
        )
        parser_state = PY_TO_LOGIC.PARSE_FILE(design)
        regions = {r.key: r for r in AUTO_PIPELINE.COLLECT_AUTO_PIPELINE_REGIONS(parser_state)}
        assert sorted(regions) == ["inner"], sorted(regions)
        assert regions["inner"].constraint.start() == 2
        assert regions["inner"].start_pending
    finally:
        pypeline.SET_LATENCY_SEEDS({})
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE(None)
        pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
    print("test_seeded_tags_are_start_only_regions PASS")


def test_selection_and_store(tmp):
    def piece(goal, **kw):
        return dict(kind=AP, key="core", digest="d", goal_mhz=goal,
                    part="sky130", tool="device_models", latency=3, **kw)
    entries = [piece(30), piece(60), piece(85), dict(piece(60), digest="stale")]
    select = lambda goal, digest="d": SWEEP.SELECT_LATENCY_PIECE(
        entries, AP, "core", digest, goal, "sky130", "device_models")
    assert select(60)["goal_mhz"] == 60
    assert select(80)["goal_mhz"] == 60
    assert select(20) is None and select(60, "missing") is None
    assert SWEEP.SELECT_LATENCY_PIECE(entries, AP, "core", "d", 60, "other", "device_models") is None
    assert SWEEP.SELECT_LATENCY_PIECE(entries, AP, "core", "d", 60, "sky130", "vivado") is None
    with patch.object(SYN, "SYNTHESIS_STORE_DIR", os.path.join(tmp, "store")):
        path = SWEEP.LATENCY_MEMORY_STORE_PATH("device_models", "sky130", AP, "core")
        assert "/latency/v2/device_models/sky130/AUTO_PIPELINE/" in path
        assert len(os.path.basename(path)) == 21
        write(path, {"schema_version": 2, "pieces": entries})
        assert SWEEP._read_latency_pieces(path) == entries
        old = time.time() - 30 * 86400
        os.utime(path, (old, old))
        assert SYN.SYNTHESIS_STORE_PRUNE(7) == 1 and not os.path.exists(path)
    many = [dict(piece(30), digest=str(i)) for i in range(25)]
    merged = SWEEP.MERGE_LATENCY_PIECES(many, [dict(piece(60), latency=8)])
    assert len(merged) == SWEEP.LATENCY_MEMORY_MAX_ENTRIES
    assert merged[-1]["latency"] == 8
    # A failure records no replacement, preserving all previous variants.
    assert SWEEP.MERGE_LATENCY_PIECES(merged, []) == merged
    assert SWEEP._read_latency_pieces(write(os.path.join(tmp, "v1.json"),
                                          {"schema_version": 1, AP: {"core": 99}})) == []
    h1 = write(os.path.join(tmp, "h1.json"), {AP: {"core": 2}})
    h2 = write(os.path.join(tmp, "h2.json"), {AP: {"core": 4}})
    assert SWEEP.LOAD_LATENCY_SEEDS(tmp, [h1, h2])[(AP, "core")] == (4, "hints h2.json")


def test_digest_changes_only_ancestors(tmp):
    import PY_TO_LOGIC
    src = _NESTED_SRC.format(src=os.path.join(THIS_DIR, "..", "..", ".."))
    src = src.replace('PLAIN = AUTO_PIPELINE(leaf, name="plain")',
                      '@hw_func\ndef other(x: uint8_t) -> uint8_t:\n    return x + 2\nPLAIN = AUTO_PIPELINE(other, name="plain")')
    design = os.path.join(tmp, "digest_design.py")
    SYN.SYN_OUTPUT_DIRECTORY = os.path.join(tmp, "digest_out")
    SYN.TOP_LEVEL_MODULE = "top"
    pypeline.SET_AUTO_PIPELINE_BUILD_MODE("sweep")
    pypeline.SET_LATENCY_SEEDS({})
    try:
        def parse(text):
            with open(design, "w") as f:
                f.write(text)
            ps = PY_TO_LOGIC.PARSE_FILE(design)
            AUTO_PIPELINE.WRITE_0_ADDED_CLKS_INIT_FILES(ps)
            return ps, SWEEP.LATENCY_SUBTREE_DIGESTS(ps)
        ps, first = parse(src)
        ps._latency_subtree_digests = None
        assert first == SWEEP.LATENCY_SUBTREE_DIGESTS(ps)
        _same, same = parse(src)
        assert first == same
        _ps, second = parse(src.replace("return x * x", "return x + x"))
        assert first["other"] == second["other"]
        for name in ("leaf", "holder", "nested_main"):
            assert first[name] != second[name], name
    finally:
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE(None)
        pypeline.SET_LATENCY_SEEDS({})


def test_recording_per_piece_and_lock_roundtrip(tmp):
    ps = SimpleNamespace(part="sky130", main_mhz={"a": 50, "b": 60},
                         LogicInstLookupTable={"a": SimpleNamespace(func_name="a"),
                                               "b": SimpleNamespace(func_name="b")})
    identities = {(AP, "good"): dict(digest="d", mains={"a"}, goal_mhz=50),
                  (AP, "bad"): dict(digest="e", mains={"b"}, goal_mhz=60),
                  (AP, "shared"): dict(digest="f", mains={"a", "b"}, goal_mhz=50)}
    profile = {"entries": [dict(kind=AP, key=k, latency=3, achieved_mhz=55)
                           for k in ("good", "bad", "shared")]}
    history = {"mains": {"a": {"final": dict(met=True, met_basis="no_failing_path_reported")},
                         "b": {"final": dict(met=False, met_basis="timing_failure")}}}
    with patch.object(SWEEP, "_latency_piece_identities", lambda _: identities), patch.dict(
            SWEEP.CARRIED_LOCKS, {}, clear=True):
        pieces = SWEEP.BUILD_LATENCY_PIECES(ps, SimpleNamespace(), history, profile)
        assert [e["key"] for e in pieces] == ["good"]
    import PY_TO_LOGIC
    design = os.path.join(tmp, "lock_design.py")
    with open(design, "w") as f:
        f.write(_NESTED_SRC.format(src=os.path.join(THIS_DIR, "..", "..", "..")))
    SYN.SYN_OUTPUT_DIRECTORY = os.path.join(tmp, "lock_out")
    os.makedirs(SYN.SYN_OUTPUT_DIRECTORY)
    ps = PY_TO_LOGIC.PARSE_FILE(design)
    table = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(ps)
    inst = sorted(ps.FuncToInstances["leaf"])[0]
    snapshot = AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE(inst, table, ps)
    lock = SWEEP.MiniSweepLock([0.5], concrete=snapshot, model_fingerprint="fingerprint")
    decoded = json.loads(json.dumps(lock.to_dict()))
    normalized = SWEEP.NORMALIZE_CONCRETE_PIPELINE(decoded["concrete"])
    assert AUTO_PIPELINE.CONCRETE_PIPELINE_COMPATIBLE(inst, normalized, table, ps)
    AUTO_PIPELINE.RESTORE_CONCRETE_PIPELINE(inst, normalized, table, ps)


_DEPENDENT_SRC = """
import sys
sys.path.insert(0, {src!r})
sys.path.insert(0, {library!r})
from pypeline import MAIN, AUTO_PIPELINE, hw_func, uint8_t
from stream.stream_multi_cycle import make_stream_auto_multi_cycle
@hw_func
def body(x: uint8_t) -> uint8_t:
    return x * x
BODY = AUTO_PIPELINE(body, name="body_core")
def make_compute(n):
    @hw_func
    def compute(x: uint8_t) -> uint8_t:
        a: uint8_t = x
        for i in range(n):
            a = a * 3 + x
        return a
    return compute
MCP, mcp_t = make_stream_auto_multi_cycle(make_compute(BODY.latency + 2), name="dependent")
@MAIN(50.0)
def body_main(x: uint8_t) -> uint8_t:
    return BODY(x)
@MAIN(50.0)
def mcp_main(stream_in_if: MCP.in_fwd_t, stream_out_if: MCP.out_fb_t) -> mcp_t:
    return MCP(stream_in_if, stream_out_if)
"""


def test_replay_bounds_and_lower_goal_floor(tmp):
    """A changed cap rejects replay; a floor survives a smaller planned count."""
    import PY_TO_LOGIC

    design = os.path.join(THIS_DIR, "latency_memory_constraints_design.py")
    out_dir = os.path.join(tmp, "bounds_out")
    os.makedirs(out_dir)
    SYN.SYN_OUTPUT_DIRECTORY = out_dir
    SYN.TOP_LEVEL_MODULE = "top"
    original_tool = SYN.SYN_TOOL
    SYN.SYN_TOOL = SYN.TOOL_MODULES["vivado"]
    pypeline.SET_AUTO_PIPELINE_BUILD_MODE("sweep")

    def parse(cap, seeds=None):
        pypeline.SET_DESIGN_PARAMS({"MEMORY_CAP": str(cap)})
        pypeline.SET_LATENCY_SEEDS(seeds or {})
        ps = PY_TO_LOGIC.PARSE_FILE(design)
        ps.part = "xc7a35ticsg324-1l"
        AUTO_PIPELINE.WRITE_0_ADDED_CLKS_INIT_FILES(ps)
        return ps

    try:
        old = parse(2)
        main = next(m for m in old.main_mhz if old.LogicInstLookupTable[m].func_name not in old.func_marked_wires)
        wire_main = next(m for m in old.main_mhz if old.LogicInstLookupTable[m].func_name in old.func_marked_wires)
        assert SYN.GET_TARGET_MHZ(wire_main, old) == 50.0
        name = old.LogicInstLookupTable[main].func_name
        table = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(old)
        inst = next(iter(old.FuncToInstances["bounds_work"]))
        table[inst]._has_input_regs = True
        table[inst]._has_output_regs = True
        table[inst].INVALIDATE_CACHE()
        assert table[inst].GET_TOTAL_LATENCY(old, table) == 2
        assert not AUTO_PIPELINE.AUTO_PIPELINE_CONSTRAINTS_REALIZED_PROBLEMS(old, table)
        digest = SWEEP._latency_piece_identities(old)[("main", name)]["digest"]
        write(os.path.join(out_dir, "latency_memory.json"), dict(schema_version=2, pieces=[
            dict(kind="main", key=name, digest=digest, goal_mhz=50.0, part=old.part,
                 tool="vivado", concrete=AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE(main, table, old))]))
        # Bounds can change without changing the zero-clock VHDL or hierarchy.
        for cap, replay in ((1, False), (2, True)):
            SWEEP.LOAD_LATENCY_SEEDS(out_dir, [])
            ps = parse(cap)
            assert SWEEP._latency_piece_identities(ps)[("main", name)]["digest"] == digest
            ps = SWEEP.RESOLVE_LATENCY_MEMORY(ps, {}, lambda seeds: parse(cap, seeds))
            with patch.object(SWEEP, "DO_SEEDED_CONFIRM_OR_SWEEP", side_effect=lambda ps, p: (p, True)) as confirm:
                result = SWEEP.TRY_LATENCY_MEMORY_REPLAY(ps, None)
            assert (result is not None) == replay
            assert confirm.call_count == int(replay), "invalid replay reached synthesis"

        # Real placement/lowering, with deterministic weights rather than synthesis.
        # Start below a matched lower-goal floor to exercise enforcement itself,
        # rather than only observing the remembered initial guess.
        ps = parse(0, {(AP, "bounds_core"): (1, "fixture")})
        for logic in ps.FuncLogicLookupTable.values():
            logic.delay = int(SYN.DELAY_UNIT_MULT)
        for floor in (0, 1):
            table = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(ps)
            region = next(r for r in AUTO_PIPELINE.COLLECT_AUTO_PIPELINE_REGIONS(ps) if r.key == "bounds_core")
            region.landscape = SWEEP.BUILD_SLICE_LANDSCAPE(region.inst, ps, table, {})
            with patch.dict(SWEEP.LATENCY_MEMORY_AP_FLOORS, {"bounds_core": floor}, clear=True):
                table = AUTO_PIPELINE._ENFORCE_ONE_AUTO_PIPELINE_REGION(region, 0, ps, table, {})
                built = table[region.inst].GET_TOTAL_LATENCY(ps, table)
                assert built == floor, (floor, built)
                assert not AUTO_PIPELINE.AUTO_PIPELINE_CONSTRAINTS_REALIZED_PROBLEMS(ps, table)
        # A mini-sweep writes its winner before the lock sets the planner's
        # fixed flag, and a replay renders it already fixed. The entity's text
        # must not depend on that flag, so the replay's synthesis inputs match.
        logic = ps.LogicInstLookupTable[region.inst]
        texts = []
        for fixed in (False, True):
            render = dict(table)
            render[region.inst] = table[region.inst].DEEPCOPY()
            render[region.inst].params_are_fixed = fixed
            texts.append(VHDL.WRITE_LOGIC_ENTITY(region.inst, logic, out_dir, ps, render, return_text=True))
        assert texts[0] == texts[1], "the planner's fixed flag changed an entity's VHDL"
        # MAIN replay must respect the floor too, rather than bypassing the planner.
        SWEEP.LOAD_LATENCY_SEEDS(out_dir, [])
        ps = parse(0, {(AP, "bounds_core"): (2, "fixture")})
        zero = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(ps)
        SWEEP.LATENCY_MEMORY_MAIN_REPLAYS[name] = dict(source="fixture", goal_mhz=50.0,
            concrete=AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE(main, zero, ps), path="missing")
        with patch.dict(SWEEP.LATENCY_MEMORY_AP_FLOORS, {"bounds_core": 2}, clear=True), patch.object(
                SWEEP, "DO_SEEDED_CONFIRM_OR_SWEEP") as confirm:
            assert SWEEP.TRY_LATENCY_MEMORY_REPLAY(ps, None) is None
            confirm.assert_not_called()
        print("test_replay_bounds_and_lower_goal_floor PASS")
    finally:
        pypeline.SET_DESIGN_PARAMS({})
        pypeline.SET_LATENCY_SEEDS({})
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE(None)
        SWEEP.LATENCY_MEMORY_MAIN_REPLAYS.clear()
        SYN.SYN_TOOL = original_tool


def test_lower_goal_floor_only_for_regions(tmp):
    """A lower-goal depth floors only a region: a seeded tag whose callee holds
    another AUTO_PIPELINE is planned as if unseeded, so a floor there could
    never be enforced. The final-table check never reports floors."""
    import PY_TO_LOGIC

    design = os.path.join(tmp, "floor_regions.py")
    with open(design, "w") as f:
        f.write(_NESTED_SRC.format(src=os.path.join(THIS_DIR, "..", "..", ".."))
                .replace("@MAIN\ndef nested_main", "@MAIN(50.0)\ndef nested_main"))
    out_dir = os.path.join(tmp, "floor_regions_out")
    os.makedirs(out_dir)
    SYN.SYN_OUTPUT_DIRECTORY = out_dir
    SYN.TOP_LEVEL_MODULE = "top"
    original_tool = SYN.SYN_TOOL
    SYN.SYN_TOOL = SYN.TOOL_MODULES["vivado"]

    def parse(seeds):
        pypeline.SET_LATENCY_SEEDS(seeds)
        state = PY_TO_LOGIC.PARSE_FILE(design)
        state.part = "xc7a35ticsg324-1l"
        AUTO_PIPELINE.WRITE_0_ADDED_CLKS_INIT_FILES(state)
        return state

    try:
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE("sweep")
        first = parse({})
        identities = SWEEP._latency_piece_identities(first)
        write(os.path.join(out_dir, "latency_memory.json"), {"schema_version": 2, "pieces": [
            dict(kind=AP, key=key, digest=identities[(AP, key)]["digest"], goal_mhz=40.0,
                 part=first.part, tool="vivado", latency=latency)
            for key, latency in (("inner", 2), ("outer", 3))]})
        SWEEP.LOAD_LATENCY_SEEDS(out_dir, [])
        final = SWEEP.RESOLVE_LATENCY_MEMORY(parse({}), {}, parse)
        assert set(SWEEP.LATENCY_MEMORY_SELECTED) == {(AP, "inner"), (AP, "outer")}
        assert SWEEP.LATENCY_MEMORY_AP_FLOORS == {"inner": 2}, SWEEP.LATENCY_MEMORY_AP_FLOORS
        zero = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(final)
        assert not AUTO_PIPELINE.AUTO_PIPELINE_CONSTRAINTS_REALIZED_PROBLEMS(final, zero)
        problems = AUTO_PIPELINE.AUTO_PIPELINE_CONSTRAINTS_REALIZED_PROBLEMS(
            final, zero, memory_floors=True)
        assert len(problems) == 1 and "floor=2" in problems[0], problems
    finally:
        pypeline.SET_LATENCY_SEEDS({})
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE(None)
        SWEEP.LOAD_LATENCY_SEEDS(out_dir, [])
        SYN.SYN_TOOL = original_tool
    print("test_lower_goal_floor_only_for_regions PASS")


def test_dependent_piece_resolution(tmp):
    import PY_TO_LOGIC
    design = os.path.join(tmp, "dependent.py")
    with open(design, "w") as f:
        f.write(_DEPENDENT_SRC.format(src=os.path.abspath(os.path.join(THIS_DIR, "..", "..", "..")),
                                     library=os.path.abspath(os.path.join(THIS_DIR, "..", "..", "..", "..", "include", "pypeline"))))
    out_dir = os.path.join(tmp, "dependent_out")
    SYN.SYN_OUTPUT_DIRECTORY = out_dir
    SYN.TOP_LEVEL_MODULE = "top"
    os.makedirs(out_dir)
    calls = []
    original_tool = SYN.SYN_TOOL
    SYN.SYN_TOOL = SYN.TOOL_MODULES["vivado"]
    def parse(seeds):
        pypeline.SET_LATENCY_SEEDS(seeds)
        state = PY_TO_LOGIC.PARSE_FILE(design)
        state.part = "xc7a35ticsg324-1l"
        AUTO_PIPELINE.WRITE_0_ADDED_CLKS_INIT_FILES(state)
        return state
    try:
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE("sweep")
        served = {(AP, "body_core"): (3, "fixture"), (MC, "dependent"): (5, "fixture")}
        winning = parse(served)
        identities = SWEEP._latency_piece_identities(winning)
        records = [dict(kind=kind, key=key, digest=identities[(kind, key)]["digest"],
                        goal_mhz=50.0, part=winning.part, tool="vivado", latency=value[0])
                   for (kind, key), value in served.items()]
        write(os.path.join(out_dir, "latency_memory.json"), {"schema_version": 2, "pieces": records})
        SWEEP.LOAD_LATENCY_SEEDS(out_dir, [])
        initial = parse({})
        def reparse(seeds):
            calls.append(dict(seeds))
            return parse(seeds)
        final = SWEEP.RESOLVE_LATENCY_MEMORY(initial, {}, reparse)
        assert len(calls) == 2, calls
        assert (MC, "dependent") not in calls[0] and calls[1][(MC, "dependent")][0] == 5
        assert set(SWEEP.LATENCY_MEMORY_SELECTED) == set(served)
        assert AUTO_MULTI_CYCLE.ELABORATED_AUTO_MULTI_CYCLE_NCYCLES(final)["dependent"] == 5
        # Invalid JSON parameters must be rejected before they can reach VHDL.
        table = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(final)
        snapshot = AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE("body_main", table, final)
        snapshot[""]["slices"] = ["bad"]
        try:
            SWEEP.NORMALIZE_CONCRETE_PIPELINE(snapshot)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed concrete slices accepted")
    finally:
        pypeline.SET_LATENCY_SEEDS({})
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE(None)
        SWEEP.LATENCY_MEMORY_SELECTED.clear()
        SYN.SYN_TOOL = original_tool


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        test_read_latency_table_formats(tmp)
        test_build_latency_profile_verdicts_and_seeds()
        test_seeded_tags_are_start_only_regions(tmp)
        test_selection_and_store(tmp)
        test_digest_changes_only_ancestors(tmp)
        test_recording_per_piece_and_lock_roundtrip(tmp)
        test_replay_bounds_and_lower_goal_floor(tmp)
        test_lower_goal_floor_only_for_regions(tmp)
        test_dependent_piece_resolution(tmp)
    print("All latency memory unit tests passed.")
