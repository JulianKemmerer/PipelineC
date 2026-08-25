#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit coverage for the mux select-fanout cliff fix.

Found for real on a synthetic sky130 A/B (soft_shift_rot's funnel-shift
muxes) and reproduced end to end (105.95 -> 377.41 MHz at an unchanged
target, same real sky130 liberty STA): a planned pipeline register can
materialize (a real register was set) without deepening the design's
schedule at all, when it lands on a parallel branch whose sibling already
bounds a shared downstream consumer's readiness. The old scorer had no way
to see this -- only the real, post-lowering synchronous schedule
(SYN.GET_PIPELINE_MAP, via TimingParams.GET_TOTAL_LATENCY) can. Separately,
a selected packed-MUX output bank's select fanout can be halved for free
(same depth, same cut count) by chunking it, which used to be reachable
only after a measured failure -- so --no_sweep (no measurement, ever) could
never get it.

Two fixture styles, by necessity:
  - SWEEP.DROP_NON_DEEPENING_PLACEMENTS needs a REAL synchronous schedule
    (SYN.GET_PIPELINE_MAP is a genuine graph-BFS over wire-driven-by data,
    not something safe to hand-fake) -- see mux_fanout_planning_design.py,
    parsed for real via PY_TO_LOGIC.PARSE_FILE. No synthesis tool is
    invoked; GET_TOTAL_LATENCY only needs register topology, never ns
    delays.
  - SWEEP.CHUNK_SELECTED_MUX_OUTPUT_BANKS / BUILD_CHUNKED_MUX_REFINEMENT
    are pure landscape-level transforms (no TimingParamsLookupTable
    involved), safely covered by the FakeLogic/FakeParserState +
    SliceLandscape pattern from typed_pipeline_placement_test.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../"))

import C_TO_LOGIC
import PY_TO_LOGIC
import RAW_VHDL
import SWEEP
import SYN

_DESIGN_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "mux_fanout_planning_design.py"
)


# ─── SWEEP.DROP_NON_DEEPENING_PLACEMENTS (real parsed design) ────────────


def _parse_redundant_cut_design():
    return PY_TO_LOGIC.PARSE_FILE(_DESIGN_PATH)


def _classify_adders(main_logic, adder_locals, marker):
    """Split mux_fanout_planning_design.py's three adders into the one
    downstream of the other two (its own inputs trace back through
    wire_driven_by to another adder's output port) and the two independent,
    parallel ones. Walking wire_driven_by rather than hardcoding the
    source's line-number-suffixed instance names keeps this robust to
    reformatting the fixture."""

    def _walk(wire, driven_by, max_hops=10):
        seen = set()
        for _ in range(max_hops):
            if wire not in driven_by or wire in seen:
                return wire
            seen.add(wire)
            wire = driven_by[wire]
        return wire

    downstream = None
    parallel = []
    for local in adder_locals:
        srcs = (
            _walk(local + marker + "left", main_logic.wire_driven_by),
            _walk(local + marker + "right", main_logic.wire_driven_by),
        )
        depends_on_other_adder = any(
            marker in src
            and any(other != local and src.startswith(other + marker) for other in adder_locals)
            for src in srcs
        )
        if depends_on_other_adder:
            downstream = local
        else:
            parallel.append(local)
    assert downstream is not None and len(parallel) == 2, (downstream, parallel)
    return downstream, parallel


def _fixture():
    """(main_inst, parser_state, tpl, a_inst, b_inst, c_inst) for the
    parsed design -- a, b independent/parallel; c downstream of both."""
    parser_state = _parse_redundant_cut_design()
    main_inst = list(parser_state.main_mhz.keys())[0]
    main_logic = parser_state.LogicInstLookupTable[main_inst]
    marker = C_TO_LOGIC.SUBMODULE_MARKER
    adder_locals = [
        local
        for local, func in main_logic.submodule_instances.items()
        if func == "BIN_OP_PLUS_uint8_t_uint8_t"
    ]
    assert len(adder_locals) == 3, adder_locals
    downstream, parallel = _classify_adders(main_logic, adder_locals, marker)
    tpl = SYN.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)
    return (
        main_inst,
        parser_state,
        tpl,
        main_inst + marker + parallel[0],
        main_inst + marker + parallel[1],
        main_inst + marker + downstream,
    )


def test_non_deepening_cut_is_dropped():
    # a and b are independent (parallel) adders both feeding c. Registering
    # BOTH costs the same one pipeline stage as registering just one -- the
    # real bug's shape (MUX_uint5_t_if_eff_amt registered on top of an
    # already-registered MUX_uint64_t_if_w). Must fail against master
    # (DROP_NON_DEEPENING_PLACEMENTS doesn't exist there).
    main_inst, parser_state, tpl, a_inst, b_inst, _c_inst = _fixture()
    placements = [
        SWEEP.PipelinePlacement(
            SWEEP.PipelinePlacement.INSTANCE_OUTPUT,
            a_inst, "BIN_OP_PLUS_uint8_t_uint8_t", 0, 0.5,
        ),
        SWEEP.PipelinePlacement(
            SWEEP.PipelinePlacement.INSTANCE_OUTPUT,
            b_inst, "BIN_OP_PLUS_uint8_t_uint8_t", 1, 1.5,
        ),
    ]
    tpl = SWEEP.APPLY_PIPELINE_PLACEMENTS(placements, parser_state, tpl)
    new_cuts, new_placements = SWEEP.DROP_NON_DEEPENING_PLACEMENTS(
        main_inst, [0, 1], placements, parser_state, tpl
    )
    assert len(new_placements) == 1, new_placements
    assert new_placements[0].inst_path in (a_inst, b_inst)
    assert new_cuts == [new_placements[0].axis_unit]
    tpl[main_inst].INVALIDATE_CACHE()
    assert tpl[main_inst].GET_TOTAL_LATENCY(parser_state, tpl) == 1


def test_deepening_cut_is_kept():
    # a (parallel) + c (serial, downstream of a and b): c's own register is
    # a genuine second stage, not a duplicate of a's -- both cuts earn their
    # keep and must survive unchanged.
    main_inst, parser_state, tpl, a_inst, _b_inst, c_inst = _fixture()
    placements = [
        SWEEP.PipelinePlacement(
            SWEEP.PipelinePlacement.INSTANCE_OUTPUT,
            a_inst, "BIN_OP_PLUS_uint8_t_uint8_t", 0, 0.5,
        ),
        SWEEP.PipelinePlacement(
            SWEEP.PipelinePlacement.INSTANCE_OUTPUT,
            c_inst, "BIN_OP_PLUS_uint8_t_uint8_t", 5, 5.5,
        ),
    ]
    tpl = SWEEP.APPLY_PIPELINE_PLACEMENTS(placements, parser_state, tpl)
    cuts = [0, 5]
    new_cuts, new_placements = SWEEP.DROP_NON_DEEPENING_PLACEMENTS(
        main_inst, cuts, placements, parser_state, tpl
    )
    assert new_placements is placements, "a well-formed plan must be returned unchanged"
    assert new_cuts == cuts


def test_locked_region_slices_are_not_counted_as_unplanned():
    # The wireguard decrypt shape (see docs/SYN_DESIGN.md's dated result):
    # a mini-sweep lock contributes realized slices with NO plannable cuts
    # of its own for that subtree (plan.cuts[subtree_root] == [] and
    # plan.landscapes[subtree_root] is None, so the real caller in SWEEP.py
    # never even reaches this function for a locked subtree -- see its own
    # "if landscape is None or len(placements) == 0: continue" guard). This
    # confirms the function's own empty-input fast path never misreads that
    # structural "nothing planned here" state as a mismatch.
    main_inst, parser_state, tpl, _a_inst, _b_inst, _c_inst = _fixture()
    cuts, placements = SWEEP.DROP_NON_DEEPENING_PLACEMENTS(
        main_inst, [], [], parser_state, tpl
    )
    assert cuts == [] and placements == []


_STREAM_PIPELINE_DESIGN_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "stream_pipeline_test.py"
)


def test_placement_inside_an_autopipeline_region_is_not_dropped():
    # Regression: found by the real-build suite (autopipeline_latency_test)
    # while verifying this fix, not by inspection. stream_pipeline_test_top
    # (div_inv's AUTOPIPELINE'd soft_div_radix core) failed with cuts=0 for
    # all 12 sweep iterations -- every real register this function was ever
    # given got deleted. Cause: SYN.GET_SUBMODULE_LATENCY deliberately
    # reports an AUTOPIPELINE-tagged region's own depth as 0 to ITS
    # container (SUMMARIZE_SUBTREE_PIPELINE's own docstring documents this
    # convention), so subtree_root's own monolithic GET_TOTAL_LATENCY alone
    # is always 0 regardless of what is registered inside such a region --
    # and BUILD_SLICE_LANDSCAPE's own SUB_HAS_AUTOPIPELINE_IN_HIER check
    # already permits candidates to live inside exactly this kind of
    # region. Every real placement therefore looked "non-deepening" under a
    # monolithic-only comparison. Must fail (drop the placement down to 0)
    # against a version of DROP_NON_DEEPENING_PLACEMENTS that does not add
    # each such region's own latency back in.
    parser_state = PY_TO_LOGIC.PARSE_FILE(_STREAM_PIPELINE_DESIGN_PATH)
    main_inst = list(parser_state.main_mhz.keys())[0]
    marker = C_TO_LOGIC.SUBMODULE_MARKER
    region_inst = next(
        inst_name + marker + local_sub
        for inst_name, logic in parser_state.LogicInstLookupTable.items()
        if logic.sub_inst_to_autopipeline_depth
        and (inst_name == main_inst or inst_name.startswith(main_inst + marker))
        for local_sub in logic.sub_inst_to_autopipeline_depth
    )
    leaf = next(
        inst_name
        for inst_name, logic in parser_state.LogicInstLookupTable.items()
        if (inst_name == region_inst or inst_name.startswith(region_inst + marker))
        and len(logic.submodule_instances) == 0
        and logic.CAN_HAVE_ADDED_LATENCY(parser_state)
    )
    tpl = SYN.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)
    placements = [
        SWEEP.PipelinePlacement(
            SWEEP.PipelinePlacement.INSTANCE_OUTPUT,
            leaf, parser_state.LogicInstLookupTable[leaf].func_name, 0, 0.5,
        ),
    ]
    tpl = SWEEP.APPLY_PIPELINE_PLACEMENTS(placements, parser_state, tpl)
    new_cuts, new_placements = SWEEP.DROP_NON_DEEPENING_PLACEMENTS(
        main_inst, [0], placements, parser_state, tpl
    )
    assert new_placements == placements, "a real register inside an AUTOPIPELINE region must survive"
    assert new_cuts == [0]


# ─── SWEEP.CHUNK_SELECTED_MUX_OUTPUT_BANKS / BUILD_CHUNKED_MUX_REFINEMENT ─


class FakeMuxLogic:
    def __init__(self, func_name, width):
        self.func_name = func_name
        self.inputs = ["sel", "a", "b"]
        self.outputs = ["out"]
        self.submodule_instances = {}
        c_type = f"uint{width}_t"
        self.wire_to_c_type = {"a": c_type, "b": c_type, "out": c_type}


class FakeParserState:
    def __init__(self, inst_to_logic):
        self.LogicInstLookupTable = dict(inst_to_logic)


def _mux_landscape(*, wide=True, narrow=True):
    logics = {}
    landscape = SWEEP.SliceLandscape("main", 100, 1.0)
    if wide:
        logics["main__wide"] = FakeMuxLogic("MUX_uint64_t", 64)
        landscape.segments.append(
            SWEEP.Segment(
                "main__wide", "MUX_uint64_t", 10.0, 20.0,
                SWEEP.Segment.SLICEABLE_1LL, "mux_packed_bank",
            )
        )
    if narrow:
        logics["main__narrow"] = FakeMuxLogic("MUX_uint8_t", 8)
        landscape.segments.append(
            SWEEP.Segment(
                "main__narrow", "MUX_uint8_t", 30.0, 40.0,
                SWEEP.Segment.SLICEABLE_1LL, "mux_packed_bank",
            )
        )
    landscape.finalize({})
    parser_state = FakeParserState(logics)
    return landscape, parser_state


def test_selected_mux_output_banks_are_chunked_by_default():
    # A selected wide (>= DEFAULT_MUX_CHUNK_MIN_WIDTH) bank is chunked at
    # plan-build time -- the ordinary lowering now, not a measured-failure
    # fallback -- same latency contribution, same cut COUNT (the axis
    # position itself moves to the leaf's own geometric midpoint; see
    # _LOWER_CHUNKED_MUX_TARGETS's own docstring).
    landscape, parser_state = _mux_landscape()
    placements = list(landscape.candidates)
    chunked = SWEEP.CHUNK_SELECTED_MUX_OUTPUT_BANKS(placements, landscape, parser_state)
    assert chunked is not placements
    by_inst = {p.inst_path: p for p in chunked}
    assert by_inst["main__wide"].kind == SWEEP.PipelinePlacement.BIT_INTERNAL
    assert by_inst["main__narrow"].kind == SWEEP.PipelinePlacement.INSTANCE_OUTPUT
    assert len(chunked) == len(placements)
    assert len({p.axis_unit for p in chunked}) == len({p.axis_unit for p in placements})


def test_narrow_bank_is_not_chunked_by_default():
    # wireguard's own MUX candidates are all 8-bit; churning them for no
    # measured benefit is exactly what DEFAULT_MUX_CHUNK_MIN_WIDTH exists to
    # avoid.
    landscape, parser_state = _mux_landscape(wide=False, narrow=True)
    placements = list(landscape.candidates)
    unchanged = SWEEP.CHUNK_SELECTED_MUX_OUTPUT_BANKS(placements, landscape, parser_state)
    assert unchanged is placements


def test_terminal_mux_split_still_requires_the_measured_escalation():
    # (i) alone touches only the already-selected bank; it must never reach
    # out and register a DIFFERENT, unselected candidate -- that is (ii)'s
    # job, and (ii) is only ever invoked from the measured `not met` branch
    # (never under --no_sweep).
    landscape, parser_state = _mux_landscape()
    wide = next(p for p in landscape.candidates if p.inst_path == "main__wide")
    only_wide_selected = [wide]

    chunked_i_only = SWEEP.CHUNK_SELECTED_MUX_OUTPUT_BANKS(
        only_wide_selected, landscape, parser_state
    )
    assert {p.inst_path for p in chunked_i_only} == {"main__wide"}

    _cuts, chunked_i_and_ii = SWEEP.BUILD_CHUNKED_MUX_REFINEMENT(
        only_wide_selected, landscape, parser_state
    )
    assert {p.inst_path for p in chunked_i_and_ii} == {"main__wide", "main__narrow"}
    assert all(
        p.kind == SWEEP.PipelinePlacement.BIT_INTERNAL for p in chunked_i_and_ii
    )


def test_chunked_mux_refinement_is_none_when_nothing_selected():
    landscape, parser_state = _mux_landscape()
    assert SWEEP.BUILD_CHUNKED_MUX_REFINEMENT([], landscape, parser_state) is None


# ─── Segment.hard / SOFT_FLOOR_REASONS honesty ────────────────────────────


def test_mux_packed_bank_floor_is_soft_with_a_real_reason():
    seg = SWEEP.Segment(
        "main__wide", "MUX_uint64_t", 0.0, 10.0,
        SWEEP.Segment.SLICEABLE_1LL, "mux_packed_bank",
    )
    assert seg.reason == "mux_packed_bank"
    assert not seg.hard
    assert "mux_packed_bank" in SWEEP.SOFT_FLOOR_REASONS


def test_1ll_atomic_floor_stays_hard():
    seg = SWEEP.Segment(
        "main__and", "AND", 0.0, 10.0,
        SWEEP.Segment.SLICEABLE_1LL, "1ll_atomic",
    )
    assert seg.hard
    assert "1ll_atomic" not in SWEEP.SOFT_FLOOR_REASONS


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
