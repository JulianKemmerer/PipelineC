#!/usr/bin/env python3
# In-process unit tests for the AUTOPIPELINE .latency machinery:
#   - SYN.HARVEST_AUTOPIPELINE_LATENCIES grouping + divergence detection
#   - SYN.SEED_TIMING_PARAMS_FROM_PREVIOUS two-tier matching + the
#     unseeded-autopipeline-instance (call-site-set-changed) detection
#   - PY_TO_LOGIC.CANONICAL_CALLABLE_KEY determinism
#   - pypeline.AUTOPIPELINE latency cache + read-flag behavior
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import C_TO_LOGIC
import PY_TO_LOGIC
import SYN
import pypeline
from pypeline import AUTOPIPELINE, hw_func, uint8_t

M = C_TO_LOGIC.SUBMODULE_MARKER


class FakeParserState:
    def __init__(self):
        self.LogicInstLookupTable = {}


class FakeTimingParams:
    def __init__(self, latency, slices=None, in_regs=False, out_regs=False):
        self._latency = latency
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


def make_logic(func_name, autopipeline_subs=None):
    logic = C_TO_LOGIC.Logic()
    logic.func_name = func_name
    for local_sub, key in (autopipeline_subs or {}).items():
        logic.sub_inst_to_autopipeline_key[local_sub] = key
        logic.sub_inst_to_autopipeline_depth[local_sub] = -1
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
    latencies, divergences = SYN.HARVEST_AUTOPIPELINE_LATENCIES(ps, tpl)
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
    latencies, divergences = SYN.HARVEST_AUTOPIPELINE_LATENCIES(ps, tpl)
    assert latencies == {}, latencies
    assert "keyA" in divergences and len(divergences["keyA"]) == 2, divergences


def test_harvest_no_autopipeline_is_empty():
    ps = FakeParserState()
    ps.LogicInstLookupTable["main"] = make_logic("plain_func")
    latencies, divergences = SYN.HARVEST_AUTOPIPELINE_LATENCIES(ps, {})
    assert latencies == {} and divergences == {}


def test_seed_two_tier_matching_and_unseeded_detection():
    # Previous pass: main -> wrapper_v1 -> core (core sliced to 6 stages)
    prev = FakeParserState()
    prev.LogicInstLookupTable["main"] = make_logic("main_func")
    prev.LogicInstLookupTable["main" + M + "wrap"] = make_logic("wrapper_v1")
    prev.LogicInstLookupTable["main" + M + "wrap" + M + "core"] = make_logic(
        "core_func"
    )
    prev_tpl = {
        "main": FakeTimingParams(0, slices=[0.5]),  # exact-path (tier a) seed
        "main" + M + "wrap": FakeTimingParams(0),
        "main" + M + "wrap" + M + "core": FakeTimingParams(6, slices=[0.2, 0.4]),
    }
    # New pass: wrapper renamed (closure value change renames its entity and
    # every instance path underneath), core func name unchanged, plus a brand
    # new autopipeline-tagged func never seen before.
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
    seeded, unseeded = SYN.SEED_TIMING_PARAMS_FROM_PREVIOUS(
        prev, prev_tpl, new, new_tpl
    )
    # Tier a: exact path
    assert seeded["main"]._slices == [0.5]
    # Tier b: func-name match despite the renamed ancestor path
    assert seeded["main" + M + "wrap2" + M + "core"]._slices == [0.2, 0.4]
    # brand_new_func didn't exist last pass -> flagged (call-site set changed)
    assert unseeded == ["main" + M + "wrap2" + M + "newcore"], unseeded


def test_canonical_callable_key_deterministic():
    @hw_func
    def some_core(x: uint8_t) -> uint8_t:
        return x + 1

    k1 = PY_TO_LOGIC.CANONICAL_CALLABLE_KEY(some_core)
    k2 = PY_TO_LOGIC.CANONICAL_CALLABLE_KEY(some_core)
    assert k1 == k2 and isinstance(k1, str) and len(k1) > 0


def test_autopipeline_latency_cache_and_read_flag():
    @hw_func
    def some_core(x: uint8_t) -> uint8_t:
        return x + 1

    pypeline.SET_AUTOPIPELINE_LATENCY_CACHE({})
    pypeline.CLEAR_AUTOPIPELINE_LATENCY_READ_FLAG()
    ap = AUTOPIPELINE(some_core)
    assert not pypeline.AUTOPIPELINE_LATENCY_WAS_READ()
    assert ap.latency == 0  # empty cache -> 0
    assert pypeline.AUTOPIPELINE_LATENCY_WAS_READ()  # the read was tracked
    # AUTOPIPELINE repr must be address-free (feeds canonical-name hashing)
    assert "0x" not in repr(ap), repr(ap)

    key = ap.canonical_key
    pypeline.SET_AUTOPIPELINE_LATENCY_CACHE({key: 7})
    ap2 = AUTOPIPELINE(some_core)
    assert ap2.latency == 7  # cache hit on an identically-keyed construction
    assert ap2(3) == 4  # __call__ stays an identity passthrough
    # Restore module state for any tests running after this one in-process
    pypeline.SET_AUTOPIPELINE_LATENCY_CACHE({})
    pypeline.CLEAR_AUTOPIPELINE_LATENCY_READ_FLAG()


if __name__ == "__main__":
    test_harvest_agreeing_instances()
    test_harvest_divergent_instances()
    test_harvest_no_autopipeline_is_empty()
    test_seed_two_tier_matching_and_unseeded_detection()
    test_canonical_callable_key_deterministic()
    test_autopipeline_latency_cache_and_read_flag()
    print("All AUTOPIPELINE harvest/seed unit tests passed.")
