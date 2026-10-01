#!/usr/bin/env python3
# In-process unit tests for the AUTO_PIPELINE .latency machinery:
#   - AUTO_PIPELINE.HARVEST_AUTO_PIPELINE_LATENCIES grouping + divergence detection
#   - AUTO_PIPELINE.SEED_TIMING_PARAMS_FROM_PREVIOUS concrete replay + the
#     unseeded-auto_pipeline-instance (call-site-set-changed) detection
#   - PY_TO_LOGIC.CANONICAL_CALLABLE_KEY determinism
#   - pypeline.AUTO_PIPELINE latency cache + read-flag behavior
#   - AUTO_PIPELINE(func, latency= / start_latency= / max_latency=): constructor
#     validation, identity suffixes (unconstrained names unchanged), build-mode
#     dependent .latency, served-value pass-2 skip, realized-constraint check
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import pickle

import C_TO_LOGIC
import PY_TO_LOGIC
import AUTO_PIPELINE as AUTO_PIPELINE_MODULE  # aliased: the pypeline tag has the same name
import pypeline
import pypeline_names
from pypeline import AUTO_PIPELINE, hw_func, uint8_t

M = C_TO_LOGIC.SUBMODULE_MARKER


class FakeParserState:
    def __init__(self):
        self.LogicInstLookupTable = {}
        self.func_fixed_latency = {}
        self.func_marked_blackbox = set()


class FakeTimingParams:
    def __init__(self, latency, slices=None, in_regs=False, out_regs=False):
        self._latency = latency
        self._exact_bit_boundaries = None
        self.params_are_fixed = False
        self._slices = list(slices or [])
        self._has_input_regs = in_regs
        self._has_output_regs = out_regs

    def GET_TOTAL_LATENCY(self, parser_state, TimingParamsLookupTable=None):
        return self._latency

    def IS_EMPTY(self):
        return (
            len(self._slices) == 0
            and not self._has_input_regs
            and not self._has_output_regs
        )

    def SET_SLICES(self, value):
        self._slices = value[:]

    def SET_HAS_IN_REGS(self, value):
        self._has_input_regs = value

    def SET_HAS_OUT_REGS(self, value):
        self._has_output_regs = value

    def INVALIDATE_CACHE(self):
        # SEED_TIMING_PARAMS_FROM_PREVIOUS unconditionally invalidates every
        # entry so no cache computed against the previous pass survives
        self.cache_invalidated = True


def make_logic(func_name, auto_pipeline_subs=None):
    logic = C_TO_LOGIC.Logic()
    logic.func_name = func_name
    for local_sub, key in (auto_pipeline_subs or {}).items():
        logic.sub_inst_to_auto_pipeline_key[local_sub] = key
        logic.sub_inst_to_auto_pipeline_latency[local_sub] = (
            C_TO_LOGIC.AutoPipelineLatency()
        )
    return logic


def test_harvest_agreeing_instances():
    ps = FakeParserState()
    parent = make_logic("parent_func", {"core0": "keyA"})
    ps.LogicInstLookupTable["main1"] = parent
    ps.LogicInstLookupTable["main2"] = parent  # same func instantiated twice
    ps.LogicInstLookupTable["main1" + M + "core0"] = make_logic("core_func")
    ps.LogicInstLookupTable["main2" + M + "core0"] = make_logic("core_func")
    tpl = {
        "main1" + M + "core0": FakeTimingParams(6),
        "main2" + M + "core0": FakeTimingParams(6),
    }
    latencies, divergences = AUTO_PIPELINE_MODULE.HARVEST_AUTO_PIPELINE_LATENCIES(ps, tpl)
    assert latencies == {"keyA": 6}, latencies
    assert divergences == {}, divergences


def test_harvest_divergent_instances():
    ps = FakeParserState()
    parent = make_logic("parent_func", {"core0": "keyA"})
    ps.LogicInstLookupTable["main1"] = parent
    ps.LogicInstLookupTable["main2"] = parent
    tpl = {
        "main1" + M + "core0": FakeTimingParams(6),
        "main2" + M + "core0": FakeTimingParams(9),  # sweep gave it more stages
    }
    latencies, divergences = AUTO_PIPELINE_MODULE.HARVEST_AUTO_PIPELINE_LATENCIES(ps, tpl)
    assert latencies == {}, latencies
    assert "keyA" in divergences and len(divergences["keyA"]) == 2, divergences


def test_harvest_no_auto_pipeline_is_empty():
    ps = FakeParserState()
    ps.LogicInstLookupTable["main"] = make_logic("plain_func")
    latencies, divergences = AUTO_PIPELINE_MODULE.HARVEST_AUTO_PIPELINE_LATENCIES(ps, {})
    assert latencies == {} and divergences == {}


def test_seed_exact_path_function_fallback_and_unseeded_detection():
    # Previous pass: main -> wrapper_v1 -> core (core sliced to 6 stages)
    prev = FakeParserState()
    prev.LogicInstLookupTable["main"] = make_logic("main_func")
    prev.LogicInstLookupTable["main" + M + "wrap"] = make_logic("wrapper_v1")
    prev.LogicInstLookupTable["main" + M + "wrap" + M + "core"] = make_logic(
        "core_func"
    )
    prev_tpl = {
        "main": FakeTimingParams(0, slices=[0.5]),  # exact-path seed
        "main" + M + "wrap": FakeTimingParams(0),
        "main" + M + "wrap" + M + "core": FakeTimingParams(6, slices=[0.2, 0.4]),
    }
    # New pass: wrapper renamed (closure value change renames its entity and
    # every instance path underneath), core func name unchanged, plus a brand
    # new auto-pipeline-tagged func never seen before.
    new = FakeParserState()
    new.LogicInstLookupTable["main"] = make_logic("main_func")
    new.LogicInstLookupTable["main" + M + "wrap2"] = make_logic(
        "wrapper_v2", {"core": "keyA", "newcore": "keyB"}
    )
    new.LogicInstLookupTable["main" + M + "wrap2" + M + "core"] = make_logic(
        "core_func"
    )
    new.LogicInstLookupTable["main" + M + "wrap2" + M + "newcore"] = make_logic(
        "brand_new_func"
    )
    new_tpl = {
        "main": FakeTimingParams(0),
        "main" + M + "wrap2": FakeTimingParams(0),
        "main" + M + "wrap2" + M + "core": FakeTimingParams(0),
        "main" + M + "wrap2" + M + "newcore": FakeTimingParams(0),
    }
    seeded, unseeded = AUTO_PIPELINE_MODULE.SEED_TIMING_PARAMS_FROM_PREVIOUS(
        prev, prev_tpl, new, new_tpl
    )
    # Exact path
    assert seeded["main"]._slices == [0.5]
    # Untagged-previous fallback: the only previous core, despite the renamed ancestor path
    assert seeded["main" + M + "wrap2" + M + "core"]._slices == [0.2, 0.4]
    # brand_new_func didn't exist last pass -> flagged (call-site set changed)
    assert unseeded == ["main" + M + "wrap2" + M + "newcore"], unseeded
    # Every seeded entry's caches were invalidated (no pass-1-derived cached
    # hash/name strings may cross the re-elaboration boundary)
    for tp in seeded.values():
        assert getattr(tp, "cache_invalidated", False)


def test_seed_preserves_relative_instances_and_independent_mains():
    def state(wrapper):
        ps = FakeParserState()
        table = {}
        for main in ("enc", "dec"):
            root = main + M + wrapper + M + "core"
            ps.LogicInstLookupTable[main] = make_logic("main_" + main)
            ps.LogicInstLookupTable[main + M + wrapper] = make_logic(wrapper, {"core": "same_key"})
            ps.LogicInstLookupTable[root] = make_logic("same_core")
            for local in ("first", "second"):
                ps.LogicInstLookupTable[root + M + local] = make_logic("same_leaf")
        table = {i: FakeTimingParams(0) for i in ps.LogicInstLookupTable}
        return ps, table
    prev, old = state("wrapper_v1")
    new, fresh = state("wrapper_v2")
    old["enc" + M + "wrapper_v1" + M + "core" + M + "first"]._has_output_regs = True
    dec_leaf = old["dec" + M + "wrapper_v1" + M + "core" + M + "second"]
    dec_leaf._slices = [0.3]
    dec_leaf._exact_bit_boundaries = (3,)
    dec_leaf.params_are_fixed = True
    seeded, missing = AUTO_PIPELINE_MODULE.SEED_TIMING_PARAMS_FROM_PREVIOUS(prev, old, new, fresh)
    assert not missing
    for inst, tp in old.items():
        other = seeded[inst.replace("wrapper_v1", "wrapper_v2")]
        for attr in ("_slices", "_has_input_regs", "_has_output_regs", "_exact_bit_boundaries", "params_are_fixed"):
            assert getattr(tp, attr) == getattr(other, attr), (inst, attr)


def test_seed_ambiguous_region_implementations():
    # Same-key replicas share one harvested depth, so differing placements
    # replay the most common one (then the first path), deterministically.
    # Without a shared key, differing placements are an error instead.
    def run(new_key, counts):
        prev, new = FakeParserState(), FakeParserState()
        prev.LogicInstLookupTable["main"] = make_logic("main_func")
        new.LogicInstLookupTable["main"] = make_logic("main_func")
        for name in counts:
            prev.LogicInstLookupTable["main" + M + name] = make_logic(name, {"core": "key"})
            prev.LogicInstLookupTable["main" + M + name + M + "core"] = make_logic("core")
        new.LogicInstLookupTable["main" + M + "renamed"] = make_logic("renamed", {"core": new_key})
        new.LogicInstLookupTable["main" + M + "renamed" + M + "core"] = make_logic("core")
        old = {i: FakeTimingParams(0) for i in prev.LogicInstLookupTable}
        for name, in_regs in counts.items():
            old["main" + M + name + M + "core"]._has_input_regs = in_regs
            old["main" + M + name + M + "core"]._has_output_regs = not in_regs
        fresh = {i: FakeTimingParams(0) for i in new.LogicInstLookupTable}
        seeded, _ = AUTO_PIPELINE_MODULE.SEED_TIMING_PARAMS_FROM_PREVIOUS(prev, old, new, fresh)
        return seeded["main" + M + "renamed" + M + "core"]

    tie = run("key", {"left": True, "right": False})
    assert tie._has_input_regs and not tie._has_output_regs  # first path
    majority = run("key", {"a": True, "b": False, "c": False})
    assert majority._has_output_regs and not majority._has_input_regs
    try:
        run("other_key", {"left": True, "right": False})
    except AUTO_PIPELINE_MODULE.SeedReplayError as exc:
        assert "different placements" in str(exc)
    else:
        raise AssertionError("untagged fallback picked one of differing placements")


def test_seed_rejects_changed_region_interior():
    prev, new = FakeParserState(), FakeParserState()
    for state, leaf in ((prev, "leaf"), (new, "renamed_leaf")):
        state.LogicInstLookupTable["main"] = make_logic("main_func", {"core": "key"})
        state.LogicInstLookupTable["main" + M + "core"] = make_logic("core")
        state.LogicInstLookupTable["main" + M + "core" + M + leaf] = make_logic("leaf")
    old = {i: FakeTimingParams(0) for i in prev.LogicInstLookupTable}
    fresh = {i: FakeTimingParams(0) for i in new.LogicInstLookupTable}
    try:
        AUTO_PIPELINE_MODULE.SEED_TIMING_PARAMS_FROM_PREVIOUS(prev, old, new, fresh)
    except AUTO_PIPELINE_MODULE.SeedReplayError as exc:
        assert "must not depend on .latency" in str(exc)
    else:
        raise AssertionError("changed region interior was replayed")


def test_mcp_seed_only_passes_do_not_use_the_pass_budget():
    # Scripted AUTO_PIPELINE latency passes: each confirmation result is
    # (met, AUTO_PIPELINE latencies, AUTO_MULTI_CYCLE counts) after that pass.
    # met=None is a pass that isolated MCP seeding ended before synthesis.
    from types import SimpleNamespace
    from unittest.mock import patch
    from contextlib import ExitStack
    import AUTO_MULTI_CYCLE, SWEEP, SYN

    def run(script):
        state = {"lat": {"k": 3}, "mcp": {"m": 3}}
        calls = []

        def confirm(ps, params):
            met, state["lat"], state["mcp"] = script[len(calls)]
            calls.append(met)
            return params, met

        noop = lambda *a, **kw: None
        with ExitStack() as stack:
            for obj, name, value in [
                (AUTO_PIPELINE_MODULE, "HARVEST_AUTO_PIPELINE_LATENCIES", lambda *a: (dict(state["lat"]), {})),
                (AUTO_PIPELINE_MODULE, "CHECK_AUTO_PIPELINE_CONSTRAINTS_REALIZED", noop),
                (AUTO_PIPELINE_MODULE, "SEED_TIMING_PARAMS_FROM_PREVIOUS", lambda a, b, c, d: ({}, [])),
                (AUTO_PIPELINE_MODULE, "GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP", lambda ps: {}),
                (AUTO_PIPELINE_MODULE, "REENFORCE_AUTO_PIPELINE_REGIONS", lambda ps, t: t),
                (AUTO_MULTI_CYCLE, "HARVEST_AUTO_MULTI_CYCLE_NCYCLES", lambda *a: dict(state["mcp"])),
                (AUTO_MULTI_CYCLE, "AUTO_MULTI_CYCLE_BUILT_MATCHES_ELABORATED", lambda *a: False),
                (AUTO_MULTI_CYCLE, "PRINT_AUTO_MULTI_CYCLE_NCYCLES", noop),
                (pypeline, "SET_AUTO_PIPELINE_LATENCY_CACHE", noop),
                (pypeline, "SET_AUTO_MULTI_CYCLE_LATENCY_CACHE", noop),
                (PY_TO_LOGIC, "PARSE_FILE", lambda f: SimpleNamespace()),
                (C_TO_LOGIC, "WRITE_0_ADDED_CLKS_INIT_FILES", noop),
                (SYN, "ADD_PATH_DELAY_TO_LOOKUP", lambda ps: ps),
                (SWEEP, "DO_SEEDED_CONFIRM_OR_SWEEP", confirm),
            ]:
                stack.enter_context(patch.object(obj, name, value))
            params = SimpleNamespace(TimingParamsLookupTable={})
            try:
                AUTO_PIPELINE_MODULE.DO_AUTO_PIPELINE_LATENCY_PASSES(SimpleNamespace(), params, "d.py")
            except SystemExit as exc:
                return calls, str(exc)
        return calls, None

    cap = AUTO_PIPELINE_MODULE.AUTO_PIPELINE_MAX_LATENCY_PASSES
    assert cap == 3
    # The standalone 80 MHz shape: seeding changes a consumed count, so the
    # next pass confirms the rebuilt handshake.
    assert run([(None, {"k": 3}, {"m": 7}), (True, {"k": 3}, {"m": 7})]) == ([None, True], None)
    # A skipped pass does not use the budget: two synthesized passes remain.
    assert run([(None, {"k": 3}, {"m": 7}), (True, {"k": 4}, {"m": 7}), (True, {"k": 4}, {"m": 7})]) == ([None, True, True], None)
    # Endless seeding is still bounded.
    calls, error = run([(None, {"k": 3}, {"m": n}) for n in range(10, 20)])
    assert calls == [None] * (cap + 1) and "consecutive re-elaborations" in error, (calls, error)


def test_hash_ext_is_content_aware():
    # Two designs with IDENTICAL io regs + slices but a renamed child func
    # must produce different hash exts: the hash names both written entity
    # files (skip-if-exists) and synthesis log files (exists -> replay), so a
    # slices-only hash serves stale artifacts after an AUTO_PIPELINE pass-2
    # rename (stale confirmation replay + shared-build GHDL failure).
    def make_state(child_func_name):
        ps = FakeParserState()
        parent = make_logic("user_named_parent")
        parent.submodule_instances = {"child0": child_func_name}
        child = make_logic(child_func_name)
        ps.LogicInstLookupTable["main"] = parent
        ps.LogicInstLookupTable["main" + M + "child0"] = child
        tpl = {
            "main": AUTO_PIPELINE_MODULE.TimingParams("main", parent),
            "main" + M + "child0": AUTO_PIPELINE_MODULE.TimingParams("main" + M + "child0", child),
        }
        return ps, parent, tpl

    ps_a, parent_a, tpl_a = make_state("stream_auto_pipeline_func_3fbe923e")
    ps_b, parent_b, tpl_b = make_state("stream_auto_pipeline_func_4f1dcd36")
    hash_a = tpl_a["main"].BUILD_HASH_EXT("main", parent_a, tpl_a, ps_a)
    hash_b = tpl_b["main"].BUILD_HASH_EXT("main", parent_b, tpl_b, ps_b)
    assert hash_a != hash_b, (
        "renamed child func did not change the parent hash ext "
        f"({hash_a} == {hash_b})"
    )
    # And determinism: identical content -> identical hash
    ps_c, parent_c, tpl_c = make_state("stream_auto_pipeline_func_3fbe923e")
    hash_c = tpl_c["main"].BUILD_HASH_EXT("main", parent_c, tpl_c, ps_c)
    assert hash_a == hash_c


def test_canonical_callable_key_deterministic():
    @hw_func
    def some_core(x: uint8_t) -> uint8_t:
        return x + 1

    k1 = PY_TO_LOGIC.CANONICAL_CALLABLE_KEY(some_core)
    k2 = PY_TO_LOGIC.CANONICAL_CALLABLE_KEY(some_core)
    assert k1 == k2 and isinstance(k1, str) and len(k1) > 0


def test_auto_pipeline_latency_cache_and_read_flag():
    @hw_func
    def some_core(x: uint8_t) -> uint8_t:
        return x + 1

    pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})
    pypeline.CLEAR_AUTO_PIPELINE_LATENCY_READ_FLAG()
    ap = AUTO_PIPELINE(some_core)
    assert not pypeline.AUTO_PIPELINE_LATENCY_WAS_READ()
    assert ap.latency == 0  # empty cache -> 0
    assert pypeline.AUTO_PIPELINE_LATENCY_WAS_READ()  # the read was tracked
    # AUTO_PIPELINE repr must be address-free (feeds canonical-name hashing)
    assert "0x" not in repr(ap), repr(ap)

    key = ap.canonical_key
    pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({key: 7})
    ap2 = AUTO_PIPELINE(some_core)
    assert ap2.latency == 7  # cache hit on an identically-keyed construction
    assert ap2(3) == 4  # __call__ stays an identity passthrough
    # Restore module state for any tests running after this one in-process
    pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})
    pypeline.CLEAR_AUTO_PIPELINE_LATENCY_READ_FLAG()


@hw_func
def constrained_core(x: uint8_t) -> uint8_t:
    return x + 1


def _restore_auto_pipeline_state():
    pypeline.SET_AUTO_PIPELINE_BUILD_MODE(None)
    pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})
    pypeline.CLEAR_AUTO_PIPELINE_LATENCY_READ_FLAG()


def test_auto_pipeline_constructor_validation():
    bad = [
        ({"latency": -1}, ValueError),
        ({"latency": True}, TypeError),
        ({"latency": 1.5}, TypeError),
        ({"start_latency": -2}, ValueError),
        ({"max_latency": "3"}, TypeError),
        ({"latency": 2, "max_latency": 3}, ValueError),
        ({"latency": 2, "start_latency": 2}, ValueError),
        ({"start_latency": 4, "max_latency": 3}, ValueError),
        ({"depth": 2}, TypeError),  # renamed to latency=
        ({"bogus": 1}, TypeError),
    ]
    for kwargs, exc in bad:
        try:
            AUTO_PIPELINE(constrained_core, **kwargs)
        except exc as err:
            if "depth" in kwargs:
                assert "latency=" in str(err), str(err)
        else:
            raise AssertionError(f"AUTO_PIPELINE accepted {kwargs}")
    try:
        AUTO_PIPELINE(constrained_core, 2)  # the old positional depth
    except TypeError:
        pass
    else:
        raise AssertionError("AUTO_PIPELINE accepted a positional latency")
    AUTO_PIPELINE(constrained_core, start_latency=3, max_latency=3)


def test_auto_pipeline_latency_suffixes_and_identity():
    cases = [
        ({}, ""),
        ({"latency": 0}, "_latency_0"),
        ({"latency": 3}, "_latency_3"),
        ({"start_latency": 2}, "_start_latency_2"),
        ({"max_latency": 5}, "_max_latency_5"),
        ({"start_latency": 2, "max_latency": 5}, "_start_latency_2_max_latency_5"),
    ]
    base_key = PY_TO_LOGIC.CANONICAL_CALLABLE_KEY(constrained_core)
    identities = set()
    for kwargs, suffix in cases:
        ap = AUTO_PIPELINE(constrained_core, **kwargs)
        assert ap.latency_suffix() == suffix, (kwargs, ap.latency_suffix())
        constraint = C_TO_LOGIC.AutoPipelineLatency.from_tag(ap)
        # C_TO_LOGIC's copy of the suffix rule must agree with pypeline's
        assert constraint.key_suffix() == suffix, (kwargs, constraint)
        assert constraint.is_unconstrained() == (not kwargs)
        assert pickle.loads(pickle.dumps(constraint)) == constraint
        # Unconstrained keys are exactly the wrapped function's key (so no
        # existing entity name moved); constraints append their suffix
        assert ap.canonical_key == base_key + suffix, (kwargs, ap.canonical_key)
        name = PY_TO_LOGIC._callable_canonical_name(ap, {})
        assert name.endswith(suffix) and name.startswith("AUTO_PIPELINE_"), name
        assert pypeline.encode_param_value(ap).endswith(suffix)
        if suffix:
            assert suffix.replace("_", "=", 0) and "latency=" in repr(ap), repr(ap)
        else:
            assert "latency" not in repr(ap) and "depth" not in repr(ap), repr(ap)
            assert pypeline_names.stable_key(ap)[2] == ()
        identities.add(pypeline_names.identity(ap))
    assert len(identities) == len(cases), "constraints must be identity"
    assert C_TO_LOGIC.AutoPipelineLatency(latency=2).conflict_with_fixed(2) is None
    assert C_TO_LOGIC.AutoPipelineLatency(max_latency=1).conflict_with_fixed(2)


def test_auto_pipeline_build_modes_and_served_values():
    try:
        pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})
        for mode, expected in (
            (None, (3, 0, 0)),
            ("fixed_only", (3, 0, 0)),
            ("sweep", (3, 2, 0)),
        ):
            pypeline.SET_AUTO_PIPELINE_BUILD_MODE(mode)
            pypeline.CLEAR_AUTO_PIPELINE_LATENCY_READ_FLAG()
            fixed = AUTO_PIPELINE(constrained_core, latency=3)
            started = AUTO_PIPELINE(constrained_core, start_latency=2, max_latency=4)
            capped = AUTO_PIPELINE(constrained_core, max_latency=4)
            got = (fixed.latency, started.latency, capped.latency)
            assert got == expected, (mode, got)
            # Served values are recorded only inside a pypelinec build
            assert (len(pypeline._auto_pipeline_served) == 3) == (mode is not None)

        pypeline.SET_AUTO_PIPELINE_BUILD_MODE("sweep")
        pypeline.CLEAR_AUTO_PIPELINE_LATENCY_READ_FLAG()
        started = AUTO_PIPELINE(constrained_core, start_latency=2)
        assert started.latency == 2
        served = pypeline.AUTO_PIPELINE_SERVED_LATENCIES()
        key = started.canonical_key
        assert served == {key: {2}}, served
        assert AUTO_PIPELINE_MODULE.AUTO_PIPELINE_SERVED_VALUES_MATCH(served, {key: 2})
        assert not AUTO_PIPELINE_MODULE.AUTO_PIPELINE_SERVED_VALUES_MATCH(served, {key: 3})
        assert AUTO_PIPELINE_MODULE.AUTO_PIPELINE_SERVED_VALUES_MATCH(served, {})  # not elaborated
        assert not AUTO_PIPELINE_MODULE.AUTO_PIPELINE_SERVED_VALUES_MATCH({key: {0, 2}}, {key: 2})

        # A harvested cache overrides start/max values; a fixed latency must
        # agree with it
        fixed_key = AUTO_PIPELINE(constrained_core, latency=3).canonical_key
        pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({fixed_key: 3, key: 5})
        assert AUTO_PIPELINE(constrained_core, latency=3).latency == 3
        assert AUTO_PIPELINE(constrained_core, start_latency=2).latency == 5
        pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({fixed_key: 4})
        try:
            AUTO_PIPELINE(constrained_core, latency=3)
        except ValueError:
            pass
        else:
            raise AssertionError("fixed latency accepted a different harvest")
        try:
            pypeline.SET_AUTO_PIPELINE_BUILD_MODE("bogus")
        except ValueError:
            pass
        else:
            raise AssertionError("unknown build mode accepted")
    finally:
        _restore_auto_pipeline_state()


def test_check_auto_pipeline_constraints_realized():
    AL = C_TO_LOGIC.AutoPipelineLatency
    ps = FakeParserState()
    parent = make_logic("parent_func")
    parent.sub_inst_to_auto_pipeline_latency = {
        "fixed0": AL(latency=2),
        "cap0": AL(max_latency=3),
        "free0": AL(),
        "start0": AL(start_latency=1),
    }
    ps.LogicInstLookupTable["main"] = parent
    tpl = {
        "main" + M + "fixed0": FakeTimingParams(2),
        "main" + M + "cap0": FakeTimingParams(3),
        "main" + M + "free0": FakeTimingParams(9),
        "main" + M + "start0": FakeTimingParams(7),
    }
    AUTO_PIPELINE_MODULE.CHECK_AUTO_PIPELINE_CONSTRAINTS_REALIZED(ps, tpl)
    for local_sub, built in (("fixed0", 1), ("fixed0", 3), ("cap0", 4)):
        bad = dict(tpl)
        bad["main" + M + local_sub] = FakeTimingParams(built)
        try:
            AUTO_PIPELINE_MODULE.CHECK_AUTO_PIPELINE_CONSTRAINTS_REALIZED(ps, bad)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"{local_sub} built {built} clks passed the check")


if __name__ == "__main__":
    test_harvest_agreeing_instances()
    test_harvest_divergent_instances()
    test_harvest_no_auto_pipeline_is_empty()
    test_seed_exact_path_function_fallback_and_unseeded_detection()
    test_seed_preserves_relative_instances_and_independent_mains()
    test_seed_ambiguous_region_implementations()
    test_seed_rejects_changed_region_interior()
    test_mcp_seed_only_passes_do_not_use_the_pass_budget()
    test_hash_ext_is_content_aware()
    test_canonical_callable_key_deterministic()
    test_auto_pipeline_latency_cache_and_read_flag()
    test_auto_pipeline_constructor_validation()
    test_auto_pipeline_latency_suffixes_and_identity()
    test_auto_pipeline_build_modes_and_served_values()
    test_check_auto_pipeline_constraints_realized()
    print("All AUTO_PIPELINE harvest/seed unit tests passed.")
