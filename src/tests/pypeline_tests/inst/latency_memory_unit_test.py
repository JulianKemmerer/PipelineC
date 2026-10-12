#!/usr/bin/env python3
"""Latency memory and hints (SWEEP.py "Latency memory"), without a synthesis tool:
  - READ_LATENCY_TABLE: the three accepted file shapes and every rejection;
  - LOAD_LATENCY_SEEDS: hints in order, the memory over them, the output
    directory's own memory over the store's copy, memory off, an unreadable
    memory file ignored;
  - what a build remembers: verified results replace, unverified ones keep the
    remembered value, tags the build no longer has are dropped;
  - BUILD_LATENCY_PROFILE: per-tag verdicts from the owning MAINs, the seed
    each tag started from, a deterministic document;
  - PRINT_LATENCY_SEEDS: applied seeds, unused hints, unused memory;
  - the --syn_cache store copy path and its prune.
See docs/SWEEP_DESIGN.md#5-latency-memory.
"""
import contextlib
import io
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
import C_TO_LOGIC
import SWEEP
import SYN
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


def test_load_latency_seeds_precedence(tmp):
    out_dir = os.path.join(tmp, "out")
    store = os.path.join(tmp, "store")
    h1 = write(os.path.join(tmp, "h1.json"), {AP: {"a": 1, "b": 1, "c": 1, "d": 1}})
    h2 = write(os.path.join(tmp, "h2.json"), {AP: {"b": 2, "c": 2, "d": 2}})
    with patch.object(SYN, "SYNTHESIS_STORE_DIR", store), patch.object(
        SWEEP, "LATENCY_MEMORY_ENABLED", True
    ):
        store_path = SWEEP.LATENCY_MEMORY_STORE_PATH(out_dir)
        assert store_path.startswith(os.path.join(store, "latency", "v1") + os.sep)
        assert store_path == SWEEP.LATENCY_MEMORY_STORE_PATH(out_dir + "/")
        assert store_path != SWEEP.LATENCY_MEMORY_STORE_PATH(out_dir + "_other")
        write(store_path, {"part": "p", "tool": "t", AP: {"c": {"latency": 3}, "d": 3}})
        write(
            os.path.join(out_dir, SWEEP.LATENCY_MEMORY_FILE),
            {"part": "p", "tool": "t", AP: {"d": {"latency": 4, "goal_mhz": 50.0}}},
        )
        old = time.time() - 30 * 86400
        os.utime(store_path, (old, old))
        seeds = SWEEP.LOAD_LATENCY_SEEDS(out_dir, [h1, h2])
        assert {k: v[0] for k, v in seeds.items()} == {
            (AP, "a"): 1,  # hints h1
            (AP, "b"): 2,  # a later hints file wins
            (AP, "c"): 3,  # the memory wins over hints
            (AP, "d"): 4,  # the output directory's own memory wins over the store
        }, seeds
        assert seeds[(AP, "a")][1] == "hints h1.json"
        assert seeds[(AP, "c")][1] == "latency memory (store): p/t"
        assert SWEEP.LATENCY_SEED_ORIGINS[(AP, "c")] == {
            "part": "p", "tool": "t", "goal_mhz": None, "shape": None
        }
        assert (AP, "a") not in SWEEP.LATENCY_SEED_ORIGINS  # hand-written hint
        assert seeds[(AP, "d")][1] == "latency memory: met a 50 MHz goal, p/t"
        # Reading the store's copy marks it used (SYNTHESIS_STORE_PRUNE)
        assert os.path.getmtime(store_path) > old + 86400
        # Memory off: hints only
        with patch.object(SWEEP, "LATENCY_MEMORY_ENABLED", False):
            seeds = SWEEP.LOAD_LATENCY_SEEDS(out_dir, [h1])
            assert {k: v[0] for k, v in seeds.items()} == {
                (AP, k): 1 for k in "abcd"
            }
        # An unreadable memory file is ignored with a warning
        with open(store_path, "w") as f:
            f.write("{not json")
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            seeds = SWEEP.LOAD_LATENCY_SEEDS(out_dir, [])
        assert "ignoring unreadable latency memory" in captured.getvalue()
        assert {k: v[0] for k, v in seeds.items()} == {(AP, "d"): 4}
    # An unreadable hints file is an error
    bad = write(os.path.join(tmp, "bad_hints.json"), {AP: {"x": -2}})
    try:
        SWEEP.LOAD_LATENCY_SEEDS(out_dir, [bad])
    except SystemExit as e:
        assert "--latency_hints" in str(e) and ">= 0" in str(e), str(e)
    else:
        raise AssertionError("bad hints accepted")
    with patch.object(SYN, "SYNTHESIS_STORE_DIR", None):
        assert SWEEP.LATENCY_MEMORY_STORE_PATH(out_dir) is None
    print("test_load_latency_seeds_precedence PASS")


def test_memory_merge_rules(tmp):
    path = write(
        os.path.join(tmp, "merge", SWEEP.LATENCY_MEMORY_FILE),
        {
            AP: {"kept": {"latency": 5, "goal_mhz": 60.0}, "gone": 9, "replaced": 1},
            MC: {"m": 4},
        },
    )
    profile = {
        "part": "p",
        "tool": "t",
        "entries": [
            {"kind": AP, "key": "kept", "latency": 7, "verified": False,
             "goal_mhz": 60.0, "achieved_mhz": 40.0},
            {"kind": AP, "key": "replaced", "latency": 2, "verified": True,
             "goal_mhz": 60.0, "achieved_mhz": 63.0, "shape": "abc"},
            {"kind": AP, "key": "new_unverified", "latency": 3, "verified": False,
             "goal_mhz": 60.0, "achieved_mhz": None},
            {"kind": MC, "key": "m", "latency": 3, "verified": True,
             "goal_mhz": 60.0, "achieved_mhz": None},
        ],
    }
    doc = SWEEP._merged_latency_memory(path, profile)
    assert doc[AP] == {
        "kept": {"latency": 5, "goal_mhz": 60.0, "achieved_mhz": None, "shape": None},
        "replaced": {"latency": 2, "goal_mhz": 60.0, "achieved_mhz": 63.0, "shape": "abc"},
    }, doc[AP]
    assert doc[MC] == {"m": {"latency": 3, "goal_mhz": 60.0, "achieved_mhz": None, "shape": None}}
    assert (doc["part"], doc["tool"], doc["schema_version"]) == ("p", "t", 1)
    # No previous memory: only the verified entries
    doc = SWEEP._merged_latency_memory(os.path.join(tmp, "absent.json"), profile)
    assert sorted(doc[AP]) == ["replaced"] and sorted(doc[MC]) == ["m"]
    print("test_memory_merge_rules PASS")


def test_build_latency_profile_verdicts_and_seeds():
    parser_state = SimpleNamespace(part="xc7a200t")
    owners = {
        (AP, "both_met"): ({"main_a", "main_b"}, C_TO_LOGIC.AutoPipelineLatency(), "shape1"),
        (AP, "one_failed"): ({"main_a", "main_c"}, C_TO_LOGIC.AutoPipelineLatency(start_latency=2), "shape2"),
        (AP, "lower_bound"): ({"main_d"}, None, "shape3"),
        (AP, "not_built"): ({"main_a"}, None, "shape4"),
        (MC, "mcp"): ({"main_a"}, C_TO_LOGIC.AutoMultiCycleConstraint("mcp", None, 3), "shape5"),
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


def test_print_latency_seeds():
    try:
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE("sweep")
        pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
        pypeline.SET_LATENCY_SEEDS(
            {
                (MC, "taken"): (4, "latency memory: met a 60 MHz goal, other_part/vivado"),
                (MC, "stale_hint"): (2, "hints h.json"),
                (MC, "gone"): (3, "latency memory: xc7a200t/vivado"),
            }
        )
        SWEEP.LATENCY_SEED_ORIGINS.clear()
        SWEEP.LATENCY_SEED_ORIGINS[(MC, "taken")] = {
            "part": "other_part", "tool": "vivado", "goal_mhz": 60.0, "shape": None
        }
        pypeline.AUTO_MULTI_CYCLE(start_latency=2, name="taken")
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            SWEEP.PRINT_LATENCY_SEEDS("xc7a200t", "vivado")
        out = captured.getvalue()
        assert "[latency memory] AUTO_MULTI_CYCLE taken: starts at 4 (latency memory" in out, out
        assert "NOTE: 1 latency hint(s) matched no" in out and "stale_hint (hints h.json)" in out, out
        assert "NOTE: 1 remembered latency matched no tag" in out, out
        assert "remembered for part other_part, tool vivado; this build is for part xc7a200t" in out, out
        assert SWEEP.LATENCY_SEEDS_USED == {(MC, "taken"): (4, "latency memory: met a 60 MHz goal, other_part/vivado")}
    finally:
        pypeline.SET_LATENCY_SEEDS({})
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE(None)
        pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
        SWEEP.LATENCY_SEEDS_USED.clear()
    print("test_print_latency_seeds PASS")


def test_store_prune_covers_latency_memory(tmp):
    store = os.path.join(tmp, "prune_store")
    with patch.object(SYN, "SYNTHESIS_STORE_DIR", store):
        fresh = write(SWEEP.LATENCY_MEMORY_STORE_PATH(os.path.join(tmp, "a")), {AP: {}})
        stale = write(SWEEP.LATENCY_MEMORY_STORE_PATH(os.path.join(tmp, "b")), {AP: {}})
        old = time.time() - 30 * 86400
        os.utime(stale, (old, old))
        assert SYN.SYNTHESIS_STORE_PRUNE(7) == 1
        assert os.path.exists(fresh) and not os.path.exists(stale)
    print("test_store_prune_covers_latency_memory PASS")


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


_GUARD_SRC = """
import sys
sys.path.insert(0, {src!r})
from pypeline import AUTO_PIPELINE, MAIN, hw_func, uint8_t

@hw_func
def leaf(x: uint8_t) -> uint8_t:
    return x * x

TAG = AUTO_PIPELINE(leaf, name="seeded_tag")

@MAIN(50.0)
def guard_main(x: uint8_t) -> uint8_t:
    return TAG(x)
"""


def test_guard_latency_seeds(tmp):
    """A seed steers the sweep only when recorded for this hardware, part,
    tool and goal; otherwise it only serves .latency."""
    import PY_TO_LOGIC

    design = os.path.join(tmp, "guard_seed_design.py")
    with open(design, "w") as f:
        f.write(_GUARD_SRC.format(src=os.path.join(THIS_DIR, "..", "..", "..")))
    SYN.SYN_OUTPUT_DIRECTORY = os.path.join(tmp, "guard_out")
    os.makedirs(SYN.SYN_OUTPUT_DIRECTORY, exist_ok=True)

    def parse():
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE("sweep")
        pypeline.SET_LATENCY_SEEDS({(AP, "seeded_tag"): (3, "latency memory")})
        ps = PY_TO_LOGIC.PARSE_FILE(design)
        ps.part = "sky130"
        return ps

    def regions(ps):
        return [r.key for r in AUTO_PIPELINE.COLLECT_AUTO_PIPELINE_REGIONS(ps)]

    try:
        with patch.object(SYN, "SYN_TOOL", SYN.TOOL_MODULES["device_models"]):
            ps = parse()
            shape = AUTO_MULTI_CYCLE.FUNCTION_SHAPE("leaf", ps)
            good = {"part": "sky130", "tool": "device_models", "goal_mhz": 50.0, "shape": shape}
            cases = [
                (None, []),  # a hand-written hint: an explicit start
                (good, []),
                (dict(good, shape="other"), ["its function changed"]),
                (dict(good, goal_mhz=60.0), ["recorded at a 60 MHz goal, not 50"]),
                (dict(good, part="xc7a35t"), ["recorded for part xc7a35t"]),
                (dict(good, tool="vivado"), ["recorded for tool vivado"]),
            ]
            for origin, reasons in cases:
                ps = parse()
                SWEEP.LATENCY_SEED_ORIGINS.clear()
                if origin is not None:
                    SWEEP.LATENCY_SEED_ORIGINS[(AP, "seeded_tag")] = origin
                captured = io.StringIO()
                with contextlib.redirect_stdout(captured):
                    demoted = SWEEP.GUARD_LATENCY_SEEDS(ps)
                assert demoted == ({"seeded_tag": reasons} if reasons else {}), (origin, demoted)
                assert regions(ps) == ([] if reasons else ["seeded_tag"]), (origin, regions(ps))
                # A re-elaboration (e.g. the RAM plan search) keeps the decision
                again = PY_TO_LOGIC.PARSE_FILE(design)
                assert regions(again) == ([] if reasons else ["seeded_tag"])
                assert pypeline.LATENCY_SEEDS_APPLIED()[(AP, "seeded_tag")][0] == 3
                if reasons:
                    assert "its sweep doesn't start at" in captured.getvalue()
    finally:
        pypeline.SET_LATENCY_SEEDS({})
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE(None)
        pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
        SWEEP.LATENCY_SEED_ORIGINS.clear()
    print("test_guard_latency_seeds PASS")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        test_read_latency_table_formats(tmp)
        test_load_latency_seeds_precedence(tmp)
        test_memory_merge_rules(tmp)
        test_build_latency_profile_verdicts_and_seeds()
        test_print_latency_seeds()
        test_store_prune_covers_latency_memory(tmp)
        test_seeded_tags_are_start_only_regions(tmp)
        test_guard_latency_seeds(tmp)
    print("All latency memory unit tests passed.")
