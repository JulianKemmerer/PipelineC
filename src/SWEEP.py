#!/usr/bin/env python
"""
Planned throughput sweep: autopipelining driven by a static delay model
("slice landscape") plus synthesis feedback attribution, replacing the old
multiplier-driven middle-out sweep.

Terminology (see docs/SYN_DESIGN.md):
  cut         - a planned register position along a module's combinational
                delay. Cuts become fractional "slices" fed to the existing
                recursive slicing mechanism in SYN.py. The number of cuts
                requested and the pipeline latency that results are related
                but intentionally NOT the same number.
  cut subtree - a maximal subtree of the instance hierarchy that can accept
                added latency: either a sliceable pure-comb function, or a
                region reached through AUTOPIPELINE tagged call sites
                underneath stateful (feedback/state reg) containers.
  landscape   - the flattened delay axis of one cut subtree, each delay unit
                tagged legal (a cut here lands in some sliceable raw HDL leaf)
                or illegal (only unsliceable/locked logic here), with weights
                used for stage budgeting and calibration.
  floor       - the predicted maximum achievable fmax of a subtree: set by its
                longest run of illegal (unsliceable) delay. Reported up front,
                before any synthesis runs.

The refinement loop runs ONE full-design synthesis per iteration and reacts
using approximate attribution of the critical path (function name fragments in
register/netlist names - post synthesis names below the top level MAIN are
mangled differently by every tool, so exact hierarchical matching is
intentionally never attempted).
"""

import copy
import json
import math
import os
import re
import sys
from datetime import timedelta
from multiprocessing.pool import ThreadPool
from timeit import default_timer as timer

import C_TO_LOGIC
import RAW_VHDL
import SYN

# Max full-design synthesis runs in the refinement loop
# (generous: budgets start at the fewest-stages guess and converge from
#  below, which takes more, cheaper-to-accept iterations than overshooting)
MAX_SWEEP_ITERS = 12
# Calibration clip ranges: how much a single iteration may scale delay weights
FUNC_SCALE_MIN_STEP = 1.05
FUNC_SCALE_MAX_STEP = 3.0
GLOBAL_SCALE_MIN_STEP = 1.05
GLOBAL_SCALE_MAX_STEP = 2.0
# Consecutive same-hotspot attributions before an isolated mini sweep
MINISWEEP_HOTSPOT_STREAK = 3
MAX_MINISWEEPS = 2
# Extra single-latency syn runs spent bisecting a mini sweep result down to
# its proven-minimal latency before locking it
MINISWEEP_TRIM_PROBES = 3
# Achieved fmax within this fraction of the predicted floor counts as
# "at the floor" (can't do better by adding registers)
FLOOR_TOLERANCE = 0.95


def AT_PREDICTED_FLOOR(curr_mhz, floor, target_mhz, tolerance=FLOOR_TOLERANCE):
    """True if curr_mhz has plateaued NEAR a predicted floor - a symmetric
    band, not merely "at or above" it. A curr_mhz far ABOVE a stale or
    under-predicted floor (seen for real: 124.18 MHz measured against a
    ~71.6 MHz predicted floor, 73% above it) means the prediction was
    simply wrong, not that a real ceiling was reached; without the upper
    bound this mislabeled a real, still-improvable result as a floor
    plateau and stopped the sweep short of goals it was already exceeding
    toward. `floor` must additionally sit below `target_mhz` (a floor above
    the goal is not a reason to stop)."""
    return (
        floor is not None
        and floor < target_mhz
        and curr_mhz >= tolerance * floor
        and curr_mhz <= floor / tolerance
    )


def BEST_SNAPSHOT_MET_ALL_GOALS(best_score):
    """True if best_score - the worst-case achieved/target ratio from
    whichever iteration best_tpl/best_plan_cuts were captured from (both
    are only ever updated together, at the same point in the sweep loop) -
    shows every reported clock group in that snapshot actually met its
    goal. Used when restoring best_tpl as the final result: without this
    check, a build could restore a snapshot that measured well above its
    goal (seen for real: 244.72 MHz against a 147.00 MHz target) and still
    report TIMING NOT MET, because met_timing was last written by a later,
    worse iteration (e.g. one a floor-stop landed on afterward) and never
    re-checked against the snapshot actually being written out."""
    return best_score is not None and best_score >= 1.0
# NOTE on trimming: reported slack is NOT used to detect over-pipelining -
# synthesis tools stop optimizing as soon as slack crosses zero, so a met
# design shows near-zero slack no matter how over-registered it is. Instead
# the trim uses cut-count history: bisect between the last known FAILING cut
# count and the met cut count, or probe below a met count that never had a
# failing data point (minimality unproven).


def WHY_NOT_SLICEABLE(logic, parser_state):
    # Mirror of C_TO_LOGIC.Logic.CAN_HAVE_ADDED_LATENCY clause by clause
    import SW_LIB

    if logic.func_name in parser_state.func_fixed_latency:
        return "fixed_latency"
    if logic.vhdl_module_text is not None:
        return "vhdl_module_text"
    if logic.is_vhdl_func:
        return "vhdl_func"
    if logic.is_vhdl_expr:
        return "vhdl_expr"
    if logic.is_clock_crossing:
        return "clock_crossing"
    if logic.uses_nonvolatile_state_regs:
        return "state_regs"
    if SW_LIB.IS_MEM(logic):
        return "memory"
    if logic.func_name in parser_state.func_marked_blackbox:
        return "blackbox"
    if len(logic.feedback_vars) > 0:
        return "feedback_vars"
    return "not_sliceable"


# Atomic segment reasons that make only a SOFT floor: a stateful module's
# measured delay mixes internal reg-to-reg paths (uncuttable) with IO paths
# that pipeline registers at the module's boundary CAN cut - so its span is
# not a guaranteed fmax ceiling (the wireguard append_auth_tag case: 31 ns
# module delay yet the design met 12.5 ns). Hard floors are pure comb spans
# no register can ever land in (raw VHDL text leaves, comb logic trapped
# inside a stateful container between its registers).
SOFT_FLOOR_REASONS = ("state_regs", "feedback_vars", "fixed_latency")


class Segment:
    """One leaf-most piece of a cut subtree's delay axis."""

    # kind values
    SLICEABLE = "sliceable"  # raw HDL leaf that can hold added registers anywhere
    # raw HDL leaf whose own generator only ever places its logic in ONE
    # stage no matter the latency (RAW_VHDL.SPLIT_KIND_1LL: MUX/AND/OR/XOR/
    # NOT/NEGATE/MULT) - only its own two BOUNDARY units are legal cut
    # positions (an input-only or output-only register; both together with
    # a 2nd cut), its interior is atomic like a genuinely unsliceable span.
    # See SliceLandscape.finalize().
    SLICEABLE_1LL = "sliceable_1ll"
    ATOMIC = "atomic"  # unsliceable logic, cuts cannot land inside
    LOCKED = "locked"  # params_are_fixed (ex. mini sweep result), no new cuts

    def __init__(self, inst_path, func_name, start, end, kind, reason=""):
        self.inst_path = inst_path
        self.func_name = func_name
        self.start = start  # float, subtree root zero clk pipeline map units
        self.end = end  # float, exclusive
        self.kind = kind
        self.reason = reason
        self.hard = reason not in SOFT_FLOOR_REASONS
        # func names of this segment's ancestors within the subtree (incl. own)
        # used for approximate attribution and calibration
        self.ancestor_funcs = set()
        # SLICEABLE only: RAW_VHDL.GET_LEAF_BIT_WIDTH(sub_logic, ...), or
        # None if unavailable (uncapped, matching pre-existing behavior).
        # An N-bit leaf can hold at most N-1 interior registers (N stages) -
        # SliceLandscape.finalize() uses this to cap how many of this
        # segment's units are ever marked legal, so PLAN_CUTS can't request
        # more cuts than GET_BITS_PER_STAGE_DICT can usefully honor without
        # producing interior zero-bit (bare register, no logic) stages.
        self.max_legal_units = None

    def __str__(self):
        return f"[{self.start:.1f},{self.end:.1f}) {self.kind} {self.inst_path.split(C_TO_LOGIC.SUBMODULE_MARKER)[-1]}({self.reason})"


class SliceLandscape:
    """Flattened delay axis of one cut subtree with per-unit legality/weight."""

    def __init__(self, subtree_root_inst, total_units, units_to_ns):
        self.subtree_root_inst = subtree_root_inst
        self.total_units = total_units  # int number of delay units
        self.units_to_ns = units_to_ns  # ns per (unweighted) delay unit
        self.segments = []
        # Rasterized per delay unit (filled by finalize()):
        self.legal = None  # bool per unit: cut here produces >= 1 register
        self.weight = None  # float per unit: stage budget cost (calibrated)
        self.blame = None  # Segment or None per unit (atomic cause)
        self.floor_ns = 0.0  # predicted min stage delay = worst illegal run
        self.floor_blame = None  # Segment causing the floor
        # Hard floor: worst illegal run of HARD atomic units only (soft
        # stateful spans break the run - their boundaries can take registers)
        self.hard_floor_ns = 0.0
        self.hard_floor_blame = None

    def finalize(self, func_delay_scale):
        n = self.total_units
        self.legal = [False] * n
        covered = [False] * n
        locked_only = [True] * n
        self.blame = [None] * n
        scale = [1.0] * n
        for seg in self.segments:
            lo = max(0, int(math.floor(seg.start)))
            hi = min(n, int(math.ceil(seg.end)))
            # An N-bit SLICEABLE leaf can hold at most N-1 interior
            # registers (N stages) - more legal positions than that lets
            # PLAN_CUTS request cuts GET_BITS_PER_STAGE_DICT can only honor
            # with interior zero-bit (bare register, no logic) stages.
            # Evenly spread the allowed cap across the segment's own span
            # (None = uncapped: width unavailable, or no cap needed).
            bits_cap_units = None
            if (
                seg.kind == Segment.SLICEABLE
                and seg.max_legal_units is not None
                and seg.max_legal_units - 1 < hi - lo
            ):
                cap = max(0, seg.max_legal_units - 1)
                span = hi - lo
                bits_cap_units = set()
                for k in range(1, cap + 1):
                    u = lo + int(round(k * span / float(cap + 1))) - 1
                    bits_cap_units.add(max(lo, min(hi - 1, u)))
            seg_scale = 1.0
            for f in seg.ancestor_funcs:
                if f in func_delay_scale:
                    seg_scale = max(seg_scale, func_delay_scale[f])
            for u in range(lo, hi):
                covered[u] = True
                if seg.kind != Segment.LOCKED:
                    locked_only[u] = False
                if seg.kind == Segment.SLICEABLE:
                    if bits_cap_units is None or u in bits_cap_units:
                        self.legal[u] = True
                elif seg.kind == Segment.SLICEABLE_1LL:
                    # Only the leaf's own two boundary units are real cut
                    # positions (stage_for_1ll: latency 1 = one boundary
                    # register, latency 2 = both) - its interior never
                    # shrinks no matter how many cuts land there, so it
                    # blames/floors like ATOMIC (a 3rd+ cut is provably a
                    # bare register around unchanged logic).
                    if u == lo or u == hi - 1:
                        self.legal[u] = True
                    elif self.blame[u] is None:
                        self.blame[u] = seg
                elif seg.kind == Segment.ATOMIC and self.blame[u] is None:
                    self.blame[u] = seg
                scale[u] = max(scale[u], seg_scale)
        self.weight = [0.0] * n
        for u in range(n):
            if covered[u] and locked_only[u]:
                # Internally pipelined already - costs no stage budget
                self.weight[u] = 0.0
            else:
                self.weight[u] = scale[u]
        # Predicted floor = worst weighted run of illegal units
        # (and the hard-only variant used for the give-up decision)
        run_w = 0.0
        run_blame = None
        best_w = 0.0
        best_blame = None
        hard_run_w = 0.0
        hard_run_blame = None
        hard_best_w = 0.0
        hard_best_blame = None
        for u in range(n):
            if not self.legal[u] and self.weight[u] > 0.0:
                run_w += self.weight[u]
                if self.blame[u] is not None:
                    run_blame = self.blame[u]
                if run_w > best_w:
                    best_w = run_w
                    best_blame = run_blame
                if self.blame[u] is not None and self.blame[u].hard:
                    hard_run_w += self.weight[u]
                    hard_run_blame = self.blame[u]
                    if hard_run_w > hard_best_w:
                        hard_best_w = hard_run_w
                        hard_best_blame = hard_run_blame
                else:
                    hard_run_w = 0.0
                    hard_run_blame = None
            else:
                run_w = 0.0
                run_blame = None
                hard_run_w = 0.0
                hard_run_blame = None
        self.floor_ns = best_w * self.units_to_ns
        self.floor_blame = best_blame
        self.hard_floor_ns = hard_best_w * self.units_to_ns
        self.hard_floor_blame = hard_best_blame

    def floor_mhz(self):
        if self.floor_ns <= 0.0:
            return None
        return 1000.0 / self.floor_ns

    def hard_floor_mhz(self):
        if self.hard_floor_ns <= 0.0:
            return None
        return 1000.0 / self.hard_floor_ns


def COLLECT_CUT_SUBTREES(main_inst, parser_state):
    """Maximal sliceable subtrees reachable from a main func: the main itself
    if pure comb, otherwise regions reached through AUTOPIPELINE tagged call
    sites under stateful containers."""
    subtrees = []

    def rec(inst, logic):
        if logic.CAN_HAVE_ADDED_LATENCY(parser_state):
            if SYN.FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL(
                logic.func_name, parser_state
            ):
                subtrees.append(inst)
            return
        # Stateful container: descend only through autopipeline tagged paths
        for sub_inst_local in logic.submodule_instances:
            if logic.SUB_HAS_AUTOPIPELINE_IN_HIER(sub_inst_local, parser_state):
                sub_func = logic.submodule_instances[sub_inst_local]
                sub_logic = parser_state.FuncLogicLookupTable[sub_func]
                rec(inst + C_TO_LOGIC.SUBMODULE_MARKER + sub_inst_local, sub_logic)

    main_logic = parser_state.LogicInstLookupTable[main_inst]
    rec(main_inst, main_logic)
    return subtrees


def BUILD_SLICE_LANDSCAPE(
    subtree_root_inst, parser_state, TimingParamsLookupTable, func_delay_scale
):
    root_logic = parser_state.LogicInstLookupTable[subtree_root_inst]
    if root_logic.delay is None or root_logic.delay <= 0:
        return None
    root_map = SYN.GET_ZERO_ADDED_CLKS_PIPELINE_MAP(
        subtree_root_inst, root_logic, parser_state
    )
    total_units_f = float(root_map.zero_clk_max_delay)
    if total_units_f <= 0.0:
        return None
    # SLICE_DOWN maps fraction f to offset floor(f*map_total); real time size of
    # one map unit follows from the root's (possibly measured) delay
    units_to_ns = (root_logic.delay / SYN.DELAY_UNIT_MULT) / total_units_f
    landscape = SliceLandscape(subtree_root_inst, int(round(total_units_f)), units_to_ns)

    def rec(inst, logic, abs_start, unit_scale, ancestor_funcs):
        pm = SYN.GET_ZERO_ADDED_CLKS_PIPELINE_MAP(inst, logic, parser_state)
        for sub_inst_local in pm.zero_clk_submodule_start_offset:
            start_off = pm.zero_clk_submodule_start_offset[sub_inst_local]
            sub_func = logic.submodule_instances[sub_inst_local]
            sub_logic = parser_state.FuncLogicLookupTable[sub_func]
            if sub_logic.delay is None or sub_logic.delay <= 0:
                continue
            child_inst = inst + C_TO_LOGIC.SUBMODULE_MARKER + sub_inst_local
            s = abs_start + unit_scale * start_off
            e = s + unit_scale * sub_logic.delay
            child_ancestors = ancestor_funcs | {sub_logic.func_name}

            child_timing_params = TimingParamsLookupTable[child_inst]
            # Same descend rule as SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES
            descend_ok = logic.SUB_HAS_AUTOPIPELINE_IN_HIER(
                sub_inst_local, parser_state
            ) or (
                logic.CAN_HAVE_ADDED_LATENCY(parser_state)
                and sub_logic.CAN_HAVE_ADDED_LATENCY(parser_state)
            )

            seg = None
            if child_timing_params.params_are_fixed:
                seg = Segment(child_inst, sub_logic.func_name, s, e, Segment.LOCKED)
            elif not descend_ok:
                # Child may itself be sliceable comb but blocked by its
                # stateful container (which can't absorb the added latency)
                if sub_logic.CAN_HAVE_ADDED_LATENCY(parser_state):
                    reason = (
                        "inside_"
                        + WHY_NOT_SLICEABLE(logic, parser_state)
                        + "_container"
                    )
                else:
                    reason = WHY_NOT_SLICEABLE(sub_logic, parser_state)
                seg = Segment(
                    child_inst,
                    sub_logic.func_name,
                    s,
                    e,
                    Segment.ATOMIC,
                    reason,
                )
            elif len(sub_logic.submodule_instances) == 0:
                # Raw HDL leaf
                if sub_logic.CAN_HAVE_ADDED_LATENCY(parser_state):
                    split_kind = RAW_VHDL.GET_LEAF_SPLIT_KIND(sub_logic)
                    seg_kind = (
                        Segment.SLICEABLE_1LL
                        if split_kind == RAW_VHDL.SPLIT_KIND_1LL
                        else Segment.SLICEABLE
                    )
                    seg = Segment(child_inst, sub_logic.func_name, s, e, seg_kind)
                    if seg_kind == Segment.SLICEABLE:
                        seg.max_legal_units = RAW_VHDL.GET_LEAF_BIT_WIDTH(
                            sub_logic, parser_state
                        )
                else:
                    seg = Segment(
                        child_inst,
                        sub_logic.func_name,
                        s,
                        e,
                        Segment.ATOMIC,
                        WHY_NOT_SLICEABLE(sub_logic, parser_state),
                    )
            elif sub_logic.vhdl_module_text is not None:
                seg = Segment(
                    child_inst,
                    sub_logic.func_name,
                    s,
                    e,
                    Segment.ATOMIC,
                    "vhdl_module_text",
                )
            else:
                # Hierarchical - recurse with rescale into child map coordinates
                child_map = SYN.GET_ZERO_ADDED_CLKS_PIPELINE_MAP(
                    child_inst, sub_logic, parser_state
                )
                child_total = float(child_map.zero_clk_max_delay)
                if child_total <= 0.0:
                    continue
                rec(
                    child_inst,
                    sub_logic,
                    s,
                    unit_scale * sub_logic.delay / child_total,
                    child_ancestors,
                )
                continue
            seg.ancestor_funcs = child_ancestors
            landscape.segments.append(seg)

    rec(
        subtree_root_inst,
        root_logic,
        0.0,
        1.0,
        {root_logic.func_name},
    )
    landscape.finalize(func_delay_scale)
    return landscape


# PLAN_CUTS boundary-snap tolerance: how much EXTRA weight (as a fraction of
# the per-stage budget) the walk may accumulate past where it would
# otherwise cut, in order to reach a real "run boundary" (see below) instead
# of committing mid-segment. Found necessary by testing the real divider
# design against real sky130 synthesis: a low cut count spread by uniform
# weight alone repeatedly left a SLICEABLE_1LL segment (a MUX between two
# repeated loop iterations) with no cut anywhere near it, merging it into
# one iteration's tail and the next iteration's head - one ~11ns stage,
# worse than an unsliced one-cut-per-iteration reference design achieves.
# _RUN_BOUNDARY_UNITS pre-filters to exactly one meaningful candidate per
# gap, so this only needs to cover "the rest of the current repeated unit",
# not an arbitrary distance - 1.0 (a full extra budget) turned out to
# overshoot PAST that and wait for the boundary of the *next* repeated unit
# instead when the trigger point fell early in a unit, silently skipping
# every other one; 0.75 fell just barely short in a real case (~5.47ns of
# tolerance needed against a 5.45ns allowance) and merged two repeated
# units into one stage - the actual failure this whole mechanism exists to
# prevent. 0.85 covers the same real case with room, found by testing
# against real sky130 synthesis and the design's own repeated-unit shape.
PLAN_CUTS_BOUNDARY_SNAP_FRAC = 0.85


def _RUN_BOUNDARY_UNITS(landscape):
    """Unit positions marking 'just before the next wide SLICEABLE ("bits")
    leaf begins' - i.e. one unit before each SLICEABLE segment's own start.
    Deliberately NOT derived by walking landscape.segments in list order:
    that list is appended in a structural/recursive traversal order, not
    sorted by position, and real designs have PARALLEL branches (e.g. one
    divider loop iteration's NOT and MUX both read MINUS's output directly
    and don't depend on each other, so their segments overlap on the axis
    instead of following one another) - "the next segment in the list"
    is not reliably "the next thing at this position". Anchoring on
    SLICEABLE segment START positions instead sidesteps that entirely: it
    doesn't matter how many small (SLICEABLE_1LL/ATOMIC/LOCKED) segments,
    serial or parallel/overlapping, occupy the gap before the next wide
    leaf - only where that next wide leaf itself begins. The very end of
    the landscape also always qualifies (nothing further to skip)."""
    n = landscape.total_units
    starts = sorted(
        seg.start for seg in landscape.segments if seg.kind == Segment.SLICEABLE
    )
    units = set()
    for s in starts:
        # ceil(s) - 1, not floor(s) - 1: a segment's own legal boundary
        # unit (finalize()'s "hi - 1") is built from ceil(that segment's
        # OWN .end), and a directly-adjacent preceding segment's .end
        # equals this SLICEABLE segment's .start - so matching finalize()'s
        # own rounding (ceil, not floor) here is what makes the two line
        # up bit-for-bit instead of landing one unit apart.
        b = min(int(math.ceil(s)) - 1, n - 1)
        while b >= 0 and not landscape.legal[b]:
            b -= 1
        if b >= 0:
            units.add(b)
    if n - 1 >= 0 and landscape.legal[n - 1]:
        units.add(n - 1)
    return sorted(units)


def PLAN_CUTS(landscape, budget_units):
    """Place cuts along the landscape: walk the delay axis accumulating
    (calibrated) weight and cut at the last legal unit each time the stage
    budget fills. Runs of illegal units longer than the budget get their own
    stage (they set the floor). Returns list of int unit offsets.

    Boundary-snap: when the budget fills strictly inside a segment (most
    often a wide SLICEABLE "bits" leaf, where every unit is legal), cutting
    exactly there is not free - whatever follows next on the axis (often a
    SLICEABLE_1LL leaf, which only ever gets isolated by a cut landing at
    its own edge) stays merged into the stage that starts here. So the walk
    checks whether the nearest _RUN_BOUNDARY_UNITS position ahead is within
    PLAN_CUTS_BOUNDARY_SNAP_FRAC of one budget's worth of extra weight, and
    if so waits for it instead of cutting immediately - still respecting
    the existing legal[]/weight[] model, just choosing among the legal
    positions available rather than always taking the first one budget
    allows. Found necessary by testing the real divider design against
    real sky130 synthesis: without it, a low cut count merged an entire
    loop iteration's tail, a small SLICEABLE_1LL leaf, and the next
    iteration's head into one stage far slower than any single iteration."""
    n = landscape.total_units
    if n <= 0:
        return []
    budget = max(budget_units, 0.5)
    boundary_units = _RUN_BOUNDARY_UNITS(landscape)

    cuts = []
    acc = 0.0
    last_legal = None
    pending = False  # budget exceeded, waiting for a legal unit
    snap_target = None  # boundary unit committed to wait for, if any
    for u in range(n):
        if landscape.legal[u]:
            last_legal = u
        acc += landscape.weight[u]
        budget_full = acc >= budget or pending
        if budget_full and snap_target is None:
            for b in boundary_units:
                if b <= u:
                    continue
                extra = sum(landscape.weight[v] for v in range(u + 1, b + 1))
                if extra <= PLAN_CUTS_BOUNDARY_SNAP_FRAC * budget:
                    snap_target = b
                break  # only the nearest qualifying boundary is considered
        if snap_target is not None and u < snap_target:
            continue  # waiting for the snap target - keep accumulating
        if not budget_full:
            continue
        cut_pos = snap_target if snap_target is not None else last_legal
        if cut_pos is not None and (len(cuts) == 0 or cut_pos > cuts[-1]):
            cuts.append(cut_pos)
            # Residual weight after the cut position carries into next stage
            acc = 0.0
            for v in range(cut_pos + 1, u + 1):
                acc += landscape.weight[v]
            pending = acc >= budget
        else:
            pending = True
        snap_target = None
    # Drop a trailing cut that leaves a nearly empty final stage
    if len(cuts) > 0 and cuts[-1] >= n - 1:
        cuts = cuts[:-1]
    return cuts


def CUTS_TO_SLICES(cuts, landscape):
    # Center each cut within its delay unit so SLICE_DOWN's floor() recovers
    # the intended offset without float boundary ambiguity
    return [(u + 0.5) / float(landscape.total_units) for u in cuts]


def SUMMARIZE_SUBTREE_PIPELINE(
    main_inst, subtrees, TimingParamsLookupTable, parser_state
):
    """Describe how many pipeline register stages the sweep built into a
    main's cut subtrees, and where.

    A main's own GET_TOTAL_LATENCY only counts registers on its *monolithic*
    (non-decoupled) input-to-output path: a flow-controlled/AUTOPIPELINE
    submodule reports latency 0 to its container by design
    (GET_SUBMODULE_LATENCY), so its stages are invisible there. Reporting only
    the main latency (0 for a pure stream) or only the deepest single instance
    (one block_step, not the whole chacha pipeline) both understate the depth.

    So walk the subtrees and add up every decoupled region's own
    latency alongside the monolithic part:
      monolithic  = register stages sliced directly into the cut subtree roots
                    (the disjoint maximal sliceable regions - a pure-comb main
                    is its own subtree; unlabeled naturally-pipelinable logic is
                    sliced here too). A subtree root's own latency already
                    excludes any decoupled child it contains.
      regions     = func_name -> {count, latency, total} for each decoupled
                    (autopipeline-tagged) region instance carrying latency
      total_stages= monolithic + sum of every decoupled region instance's
                    latency = total slices inserted for the
                    main (== input-to-output depth when the regions sit in
                    series, as in a stream pipeline)
    Returns (monolithic, regions, total_stages)."""
    marker = C_TO_LOGIC.SUBMODULE_MARKER
    # Cut subtrees are disjoint maximal sliceable subtrees, so summing their
    # own latencies never double counts. (A decoupled child inside a subtree
    # root reports 0 to it and is added separately below.)
    monolithic = sum(
        TimingParamsLookupTable[d].GET_TOTAL_LATENCY(
            parser_state, TimingParamsLookupTable
        )
        for d in subtrees
    )

    def in_subtree(inst):
        return any(inst == d or inst.startswith(d + marker) for d in subtrees)

    regions = {}
    for inst_name, logic in parser_state.LogicInstLookupTable.items():
        if not logic.sub_inst_to_autopipeline_depth:
            continue
        if not in_subtree(inst_name):
            continue
        for local_sub in logic.sub_inst_to_autopipeline_depth:
            sub_inst = inst_name + marker + local_sub
            sub_timing_params = TimingParamsLookupTable.get(sub_inst)
            if sub_timing_params is None:
                continue
            latency = sub_timing_params.GET_TOTAL_LATENCY(
                parser_state, TimingParamsLookupTable
            )
            if latency <= 0:
                continue
            sub_func = parser_state.LogicInstLookupTable[sub_inst].func_name
            region = regions.setdefault(
                sub_func, {"count": 0, "latency": latency, "total": 0}
            )
            region["count"] += 1
            region["latency"] = max(region["latency"], latency)
            region["total"] += latency

    total_stages = monolithic + sum(r["total"] for r in regions.values())
    return monolithic, regions, total_stages


def GET_SUBTREE_PIPELINE_STAGES(plan, TimingParamsLookupTable, parser_state):
    # NOTE despite the name (kept for call-site compatibility), this returns
    # total SLICES built into the plan's subtrees, not comb-region
    # pipeline stage count (= slices + 1) - the physically meaningful
    # "how deep did this get pipelined" number - see
    # SUMMARIZE_SUBTREE_PIPELINE for why the main's own latency alone is
    # not it. Callers that
    # report a "pipeline_stages" figure to the user must add 1 themselves
    # (see the sweep iteration print/history entry).
    _monolithic, _regions, total_stages = SUMMARIZE_SUBTREE_PIPELINE(
        plan.main_inst, plan.subtrees, TimingParamsLookupTable, parser_state
    )
    return total_stages


def PRINT_PIPELINE_DEPTH_SUMMARY(parser_state, TimingParamsLookupTable):
    """Print, for every main, how deeply the FINAL emitted design was
    autopipelined: total pipeline register stages and the decoupled regions
    that carry them. Runs at 'Writing Results' on the actually-written table,
    so it reflects the design as built regardless of which path produced it -
    a full sweep, an AUTOPIPELINE confirmation pass, or the coarse sweep - and
    picks up any deepening the pin-and-confirm re-elaboration introduced.
    Recomputes each main's cut subtrees (path-independent). Mains with nothing
    autopipelinable are noted in one line each."""
    printed_header = False
    for main_inst in parser_state.main_mhz:
        main_logic = parser_state.LogicInstLookupTable[main_inst]
        main_func = main_logic.func_name
        # Zero-delay mains (FUNC_WIRES rewiring, bit manipulation, clock
        # crossing, ...) carry no pipeline - omit them so the summary isn't
        # buried under dozens of pmod-wire "connect" mains.
        if SYN.LOGIC_IS_ZERO_DELAY(main_logic, parser_state, allow_none_delay=True):
            continue
        subtrees = COLLECT_CUT_SUBTREES(main_inst, parser_state)
        if not printed_header:
            print("[sweep] Pipeline depth summary:", flush=True)
            printed_header = True
        if len(subtrees) == 0:
            print(
                f"[sweep]   {main_func}: not autopipelined "
                "(nothing sliceable; meets its goal as written if at all)",
                flush=True,
            )
            continue
        monolithic, regions, total_stages = SUMMARIZE_SUBTREE_PIPELINE(
            main_inst, subtrees, TimingParamsLookupTable, parser_state
        )
        print(
            f"[sweep]   {main_func}: {total_stages} pipeline register stage(s) total "
            f"({total_stages + 1} pipeline stages: comb regions separated by "
            "those slices)",
            flush=True,
        )
        if monolithic > 0 and regions:
            print(
                f"[sweep]     {monolithic} in the subtree's own (monolithic) pipeline",
                flush=True,
            )
        for region_func in sorted(regions):
            r = regions[region_func]
            lat_str = (
                f"{r['latency']}"
                if r["total"] == r["latency"] * r["count"]
                else f"up to {r['latency']}"
            )
            print(
                f"[sweep]     {region_func}: {lat_str} clk(s) deep "
                f"x {r['count']} instance(s) = {r['total']} stage(s)",
                flush=True,
            )
        if regions:
            print(
                "[sweep]     (decoupled regions above sum to the end-to-end "
                "pipeline depth when in series, as in a stream pipeline)",
                flush=True,
            )


def PRINT_TIMING_FAILURES(multimain_timing_params) -> bool:
    """Print one ERROR line per main that missed its timing goal. Returns True if
    any failure was reported, so the caller can decide whether to fail the build --
    results are still written for debugging either way."""
    timing_failures = getattr(multimain_timing_params, "sweep_timing_failures", None)
    if not timing_failures:
        return False
    print(
        "================== TIMING NOT MET ================================",
        flush=True,
    )
    for main_func_name, goal_mhz, achieved_mhz, why in timing_failures:
        achieved_str = (
            f"{achieved_mhz:.2f} MHz" if achieved_mhz is not None else "unknown"
        )
        print(
            f"ERROR: TIMING NOT MET: {main_func_name} achieved {achieved_str} "
            f"vs {goal_mhz:.2f} MHz goal ({why})",
            flush=True,
        )
    print(
        "Results were written for debugging; skipping simulation/bitstream.",
        flush=True,
    )
    return True


def PREDICTED_STAGE_NS(cuts, landscape):
    # Worst stage delay implied by the cuts (weighted units -> ns)
    bounds = [-1] + list(cuts) + [landscape.total_units - 1]
    worst = 0.0
    for i in range(len(bounds) - 1):
        w = 0.0
        for u in range(bounds[i] + 1, bounds[i + 1] + 1):
            w += landscape.weight[u]
        worst = max(worst, w)
    return worst * landscape.units_to_ns


def CHECK_CUTS_VS_LATENCY(
    subtree_root_inst, TimingParamsLookupTable, parser_state, n_cuts, landscape=None
):
    """Every planned cut must materialize as at least one slice in some raw
    HDL leaf of the subtree - registers only physically exist as leaf
    slices (or IO regs). Zero leaf slices means every cut was silently lost
    descending the hierarchy (the old Finding #1 failure mode) - always fatal.

    Beyond that, strictness depends on the subtree's landscape:
    - Fully sliceable subtree (every delay unit legal - pure comb, a register
      can go anywhere): no planned cut may be LOST, so fewer leaf slices
      than cuts means the slicing machinery is broken and the build stops.
      MORE leaf slices than cuts is normal even here: a cut is a stage
      boundary line across the dataflow, and where it crosses parallel
      branches each branch materializes its own leaf register.
    - Subtree with unsliceable spans (atomic/locked segments): planned cuts
      legitimately shift/merge around those spans on the way down, so a
      shortfall is expected - one informational line only.

    Note the subtree root's own rebuilt latency is NOT compared against the
    cut count: autopipeline tagged submodules report latency 0 to their
    containers by design, so a root whose cuts pass through tagged boundaries
    can legitimately have total latency 0 while its interior is pipelined.
    Latency may also legitimately exceed the cut count (misaligned child
    cuts, IO regs on locked insts, factory internal autopipelines)."""
    total_leaf_slices = 0
    sliced_leaves = []
    prefix = subtree_root_inst + C_TO_LOGIC.SUBMODULE_MARKER
    for inst in TimingParamsLookupTable:
        if inst == subtree_root_inst or inst.startswith(prefix):
            timing_params = TimingParamsLookupTable[inst]
            if len(timing_params._slices) == 0:
                continue
            logic = parser_state.LogicInstLookupTable[inst]
            if len(logic.submodule_instances) == 0:
                total_leaf_slices += len(timing_params._slices)
                sliced_leaves.append((inst, list(timing_params._slices)))
    if total_leaf_slices == 0 and n_cuts > 0:
        # Every cut vanished - the Finding #1 failure class (slicing descended
        # into logic that silently dropped the slices). Never acceptable.
        raise Exception(
            f"Planned {n_cuts} cuts for {subtree_root_inst} but NO raw HDL "
            f"leaf slices materialized: cuts were lost descending the "
            f"hierarchy (sliceability model out of sync with SLICE_DOWN?)"
        )
    strict = landscape is not None and all(landscape.legal)
    if strict and total_leaf_slices < n_cuts:
        # Nothing in this subtree may shift or absorb a cut - a shortfall
        # means a planned stage boundary was lost and slicing descent is
        # broken. (More slices than cuts is fine: parallel branch fan-out.)
        leaf_lines = []
        for inst, slices in sliced_leaves[0:5]:
            # Leaf name only - full instance paths are hundreds of chars
            short = inst.split(C_TO_LOGIC.SUBMODULE_MARKER)[-1]
            leaf_lines.append(f"  .../{short}: {slices}")
        if len(sliced_leaves) > 5:
            leaf_lines.append(f"  ... and {len(sliced_leaves) - 5} more")
        raise Exception(
            f"Planned {n_cuts} cuts for fully sliceable subtree "
            f"{subtree_root_inst} but only {total_leaf_slices} leaf slices "
            f"materialized - the subtree is pure comb logic (a register can "
            f"go anywhere) so no planned stage boundary may be lost. "
            f"{len(sliced_leaves)} sliced leaves, first few:\n" + "\n".join(leaf_lines)
        )
    if not strict and total_leaf_slices < n_cuts:
        # Expected drift: cuts shift/merge around the subtree's unsliceable
        # spans on the way down. The refinement loop's timing feedback
        # compensates - informational only.
        print(
            f"[sweep] note: planned {n_cuts} cuts for {subtree_root_inst}, "
            f"{total_leaf_slices} leaf slices materialized "
            f"(cuts shift/merge around unsliceable spans - expected)",
            flush=True,
        )
    return total_leaf_slices


class MainSweepPlan:
    def __init__(self, main_inst, target_mhz):
        self.main_inst = main_inst
        self.target_mhz = target_mhz
        self.target_period_ns = 1000.0 / target_mhz
        self.subtrees = []  # list of subtree root inst names
        self.landscapes = {}  # subtree root inst -> SliceLandscape
        self.cuts = {}  # subtree root inst -> [int offsets]
        self.func_delay_scale = {}  # func name -> learned weight multiplier
        self.global_scale = 1.0  # budget divisor when attribution fails
        self.locked = {}  # inst -> (slices, has_in_regs, has_out_regs)
        self.hotspot_streak = {}  # func name -> consecutive attributions
        self.minisweeps_used = 0
        self.met_timing = False
        self.stopped_reason = None
        self.last_mhz = None
        self.last_achieved_mhz = None  # most recent eval (met or not)
        self.same_mhz_count = 0
        # Cut-count history for minimality: largest total cut count known to
        # FAIL timing, and the total planned this iteration
        self.last_failing_total_cuts = None
        self.prev_total_cuts = None
        self.trim_pending = False  # probing fewer cuts after having met
        # (func_name, reason) when the critical path was attributed to a
        # func autopipelining cannot subdivide
        self.unpipelinable_blame = None
        self.history = []  # dicts for sweep_history.json

    def predicted_floor(self):
        # (floor_mhz, blame Segment) worst over subtrees, None if all sliceable
        worst = None
        blame = None
        for landscape in self.landscapes.values():
            if landscape is None:
                continue
            f = landscape.floor_mhz()
            if f is not None and (worst is None or f < worst):
                worst = f
                blame = landscape.floor_blame
        return worst, blame

    def predicted_hard_floor(self):
        # Hard floor only: pure comb spans no register can land in
        worst = None
        blame = None
        for landscape in self.landscapes.values():
            if landscape is None:
                continue
            f = landscape.hard_floor_mhz()
            if f is not None and (worst is None or f < worst):
                worst = f
                blame = landscape.hard_floor_blame
        return worst, blame


def ATTRIBUTE_PATH_TO_FUNC(path_report, plan, parser_state):
    """Approximate critical path attribution: score function name fragments
    against register/netlist resource names from the timing report. Post
    synthesis names below the MAIN are mangled tool-dependently, so this is
    intentionally substring scoring, never exact hierarchical matching.
    Returns (func_name or None, local_stage_info string for logging)."""
    name_strs = []
    for s in [path_report.start_reg_name, path_report.end_reg_name]:
        if s is not None:
            name_strs.append(s.lower())
    for r in path_report.netlist_resources:
        name_strs.append(r.lower())
    if len(name_strs) == 0:
        return None, ""
    # Candidate funcs = every func inside this plan's subtrees (from segments)
    # EXCEPT the subtree roots and the main itself: the flattened netlist
    # prefixes every register name with the top/main entity name, so the
    # root would match everything and always win - a meaningless
    # attribution. Only a proper interior func is a usable hotspot; when
    # none matches the caller falls back to global rescaling.
    excluded = set()
    excluded.add(parser_state.LogicInstLookupTable[plan.main_inst].func_name)
    for subtree_root in plan.subtrees:
        excluded.add(parser_state.LogicInstLookupTable[subtree_root].func_name)
    candidates = set()
    for landscape in plan.landscapes.values():
        if landscape is None:  # locked subtree root
            continue
        for seg in landscape.segments:
            candidates |= seg.ancestor_funcs
    candidates -= excluded
    scores = {}
    for func_name in candidates:
        fl = func_name.lower()
        s = 0
        for st in name_strs:
            if fl in st:
                s += len(fl)
        if s > 0:
            scores[func_name] = s
    if len(scores) == 0:
        return None, ""
    # Highest score wins; longer (more specific) name breaks ties
    best = sorted(scores.items(), key=lambda kv: (kv[1], len(kv[0])))[-1][0]
    # Entity-local pipeline stage numbers (REG_STAGEn_...) for logging only
    stage_info = ""
    stages = []
    for s in [path_report.start_reg_name, path_report.end_reg_name]:
        if s is not None:
            m = re.search(r"stage(\d+)", s.lower())
            if m:
                stages.append(m.group(1))
    if len(stages) > 0:
        stage_info = " local_stages=" + "->".join(stages)
    return best, stage_info


def _INSTS_CONFLICT(inst_a, inst_b):
    m = C_TO_LOGIC.SUBMODULE_MARKER
    return (
        inst_a == inst_b
        or inst_a.startswith(inst_b + m)
        or inst_b.startswith(inst_a + m)
    )


def HOTSPOT_IS_LOCKED(hotspot_func, plan, parser_state):
    if hotspot_func not in parser_state.FuncToInstances:
        return False
    insts = parser_state.FuncToInstances[hotspot_func]
    return len(insts) > 0 and all(inst in plan.locked for inst in insts)


def RUN_HOTSPOT_MINISWEEP(hotspot_func, plan, parser_state):
    """Isolated coarse sweep of one hotspot func; on success lock its slices
    (with IO regs) on all instances so top level planning treats it as an
    internally pipelined black box."""
    if HOTSPOT_IS_LOCKED(hotspot_func, plan, parser_state):
        return False  # already locked, sweeping it again changes nothing
    # Never mini-sweep a subtree root (or the main): "isolating" the whole
    # subtree is just this sweep with even slices instead of planned cuts,
    # and locking the root would freeze the entire plan
    root_funcs = set(
        parser_state.LogicInstLookupTable[d].func_name for d in plan.subtrees
    )
    root_funcs.add(parser_state.LogicInstLookupTable[plan.main_inst].func_name)
    if hotspot_func in root_funcs:
        return False
    func_logic = parser_state.FuncLogicLookupTable[hotspot_func]
    if not func_logic.CAN_HAVE_ADDED_LATENCY(parser_state):
        return False
    if not SYN.FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL(
        hotspot_func, parser_state
    ):
        return False
    if hotspot_func not in parser_state.FuncToInstances:
        return False
    inst = sorted(parser_state.FuncToInstances[hotspot_func])[0]
    # The coarse sweep's initial guess divides this func's delay by the
    # target period and only ever grows from there - an inflated estimated
    # delay would over-pipeline the lock from the start. Measure for real
    # (MEASURE_DELAYS skips stateful-subtree funcs; those keep the estimate
    # for the guess and the coarse loop self-corrects from below).
    if func_logic.delay_is_estimated:
        SYN.MEASURE_DELAYS([hotspot_func], parser_state)
    print(
        f"[sweep] Isolated coarse sweep of hotspot: {hotspot_func} "
        f"(goal {plan.target_mhz:.2f} MHz)",
        flush=True,
    )
    inst_sweep_state = SYN.InstSweepState()
    (
        inst_sweep_state,
        working_slices,
        _,
    ) = SYN.DO_COARSE_THROUGHPUT_SWEEP(
        inst,
        plan.target_mhz,
        inst_sweep_state,
        parser_state,
        starting_guess_latency=None,
        do_incremental_guesses=True,
        max_allowed_latency_mult=SYN.MAX_ALLOWED_LATENCY_MULT,
        stop_at_n_worse_result=4,
    )
    if not inst_sweep_state.met_timing or working_slices is None:
        print(
            f"[sweep] Hotspot {hotspot_func} could not meet timing in isolation.",
            flush=True,
        )
        return False
    # Prove (near-)minimality before locking: the coarse loop stops at the
    # first PASSING latency, which may have overshot (its growth steps can
    # jump). Bisect between the largest known-FAILING latency and the met
    # one - reported slack is not usable for this (tools stop optimizing at
    # slack ~0), only pass/fail data points are.
    met_latency = len(working_slices)
    initial_guess = inst_sweep_state.initial_guess_latency
    if met_latency > initial_guess:
        lo = initial_guess  # initial guess ran and failed
    else:
        lo = 0  # met on the first try - nothing below is proven
    hi = met_latency
    probes = 0
    while hi - lo > 1 and probes < MINISWEEP_TRIM_PROBES:
        probes += 1
        mid = (lo + hi) // 2
        print(
            f"[sweep] Hotspot minimality probe: {hotspot_func} at {mid} clks "
            f"(known failing: {lo}, met: {hi})",
            flush=True,
        )
        probe_state = SYN.InstSweepState()
        (
            probe_state,
            probe_slices,
            _,
        ) = SYN.DO_COARSE_THROUGHPUT_SWEEP(
            inst,
            plan.target_mhz,
            probe_state,
            parser_state,
            starting_guess_latency=mid,
            do_incremental_guesses=False,
            stop_at_latency=mid,
        )
        if probe_state.met_timing and probe_slices is not None:
            hi = len(probe_slices)
            working_slices = probe_slices
        else:
            lo = mid
    needs_io_regs = hotspot_func not in parser_state.func_marked_no_add_io_regs
    # Replace any conflicting (nested/containing) older locks
    for func_inst in sorted(parser_state.FuncToInstances[hotspot_func]):
        for locked_inst in list(plan.locked.keys()):
            if _INSTS_CONFLICT(func_inst, locked_inst):
                del plan.locked[locked_inst]
        plan.locked[func_inst] = (
            list(working_slices),
            needs_io_regs,
            needs_io_regs,
        )
    print(
        f"[sweep] Locked {hotspot_func} at cuts={len(working_slices)} "
        f"(+{2 * needs_io_regs} IO regs) on "
        f"{len(parser_state.FuncToInstances[hotspot_func])} instance(s)",
        flush=True,
    )
    return True


def APPLY_LOCKS(plan, parser_state, TimingParamsLookupTable):
    for locked_inst in sorted(plan.locked.keys()):
        slices, in_regs, out_regs = plan.locked[locked_inst]
        locked_logic = parser_state.LogicInstLookupTable[locked_inst]
        TimingParamsLookupTable = (
            SYN.ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(
                locked_inst,
                locked_logic,
                slices,
                parser_state,
                TimingParamsLookupTable,
                write_files=False,
            )
        )
        if type(TimingParamsLookupTable) is int:
            raise Exception(f"Bad locked slices for {locked_inst}: {slices}")
        timing_params = TimingParamsLookupTable[locked_inst]
        timing_params.SET_HAS_IN_REGS(in_regs)
        timing_params.SET_HAS_OUT_REGS(out_regs)
        timing_params.params_are_fixed = True
    return TimingParamsLookupTable


def GET_MAIN_INSTS_FOR_PATH_REPORT(path_report, parser_state, multimain_timing_params):
    # Same resolution + degradation behavior as the old sweep: single main
    # designs and tools without reg names (PYRTL) assume all mains
    all_main_insts = list(parser_state.main_mhz.keys())
    if len(all_main_insts) == 1:
        return set(all_main_insts)
    if path_report.start_reg_name is None or path_report.end_reg_name is None:
        print(
            "WARNING: No start/end reg name in timing report! "
            "Assuming all clock domains had critical paths..."
        )
        return set(all_main_insts)
    return SYN.GET_MAIN_INSTS_FROM_PATH_REPORT(
        path_report, parser_state, multimain_timing_params.TimingParamsLookupTable
    )


def PRINT_FLOOR_REPORT(plan, parser_state):
    for subtree_root in plan.subtrees:
        landscape = plan.landscapes.get(subtree_root)
        if landscape is None:
            continue
        root_logic = parser_state.LogicInstLookupTable[subtree_root]
        total_ns = landscape.total_units * landscape.units_to_ns
        floor = landscape.floor_mhz()
        msg = (
            f"[sweep] main={parser_state.LogicInstLookupTable[plan.main_inst].func_name} "
            f"subtree={root_logic.func_name} comb delay ~{total_ns:.1f} ns, "
            f"target {plan.target_period_ns:.1f} ns ({plan.target_mhz:.1f} MHz)"
        )
        if floor is None:
            msg += ", no unsliceable spans"
        else:
            blame = landscape.floor_blame
            is_hard = blame is not None and blame.hard
            blame_str = ""
            if blame is not None:
                blame_str = f" due to {blame.inst_path.split(C_TO_LOGIC.SUBMODULE_MARKER)[-1]} ({blame.reason}, {landscape.floor_ns:.1f} ns unsliceable)"
            soft_str = "" if is_hard else " (soft)"
            msg += f", predicted fmax floor{soft_str} ~{floor:.1f} MHz{blame_str}"
            if floor < plan.target_mhz:
                if is_hard:
                    msg += f"\n[sweep] WARNING: predicted floor {floor:.1f} MHz is below the {plan.target_mhz:.1f} MHz goal - timing cannot be met by adding registers alone"
                else:
                    msg += (
                        f"\n[sweep] WARNING: predicted soft floor {floor:.1f} MHz is below the {plan.target_mhz:.1f} MHz goal - "
                        "goal may be unreachable (stateful submodule delay; boundary registers may still cut its IO paths)"
                    )
        print(msg, flush=True)


def RUN_AS_WRITTEN_CHECKS(goal_mains, parser_state):
    """Planless goal-having mains (nothing autopipelining can help) still get
    one standalone whole-module synthesis so the user can see whether the
    module meets timing as written. The reported number is NOT stored as the
    func's delay: a stateful module's report is an internal critical path,
    not the input-to-output through-delay that estimates must use (see the
    measurement frontier rule). Informational only - the in-context
    full-design timing reports decide pass/fail for the build."""
    if len(goal_mains) == 0:
        return
    zero_clk_tpl = SYN.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)
    num_processes = int(
        open(C_TO_LOGIC.EXE_ABS_DIR() + "/../config/num_processes.cfg", "r").readline()
    )
    my_thread_pool = ThreadPool(processes=num_processes)
    main_inst_to_async_result = {}
    for main_inst, target_mhz in goal_mains:
        main_logic = parser_state.LogicInstLookupTable[main_inst]
        print(
            f"Synthesizing function: {main_logic.func_name} (as-written timing check)",
            flush=True,
        )
        main_inst_to_async_result[main_inst] = my_thread_pool.apply_async(
            SYN.SYN_TOOL.SYN_AND_REPORT_TIMING,
            (main_inst, main_logic, parser_state, zero_clk_tpl),
        )
    for main_inst, target_mhz in goal_mains:
        main_logic = parser_state.LogicInstLookupTable[main_inst]
        parsed_timing_report = main_inst_to_async_result[main_inst].get()
        path_reports = list(parsed_timing_report.path_reports.values())
        if len(path_reports) != 1 or path_reports[0].path_delay_ns is None:
            print(
                f"[sweep] WARNING: as-written check for {main_logic.func_name} "
                "did not report a usable timing path",
                flush=True,
            )
            continue
        mhz = 1000.0 / path_reports[0].path_delay_ns
        if mhz >= target_mhz:
            verdict = "PASS"
        else:
            verdict = "FAIL: restructure the design or lower the clock goal"
        print(
            f"[sweep] {main_logic.func_name} synthesized as written "
            f"(standalone check): {mhz:.2f} MHz vs {target_mhz:.2f} MHz goal "
            f"- {verdict}",
            flush=True,
        )


def DO_PLANNED_THROUGHPUT_SWEEP(parser_state, multimain_timing_params):
    """Replaces the old middle-out sweep. One full-design synthesis per
    iteration; landscape planning decides where registers go, timing report
    attribution decides what to change when timing fails."""
    # Build a plan per main that has a target and something cuttable
    plans = {}
    planless_goal_mains = []
    for main_inst in parser_state.main_mhz:
        target_mhz = SYN.GET_TARGET_MHZ(main_inst, parser_state)
        if target_mhz is None:
            continue
        subtrees = COLLECT_CUT_SUBTREES(main_inst, parser_state)
        if len(subtrees) == 0:
            main_logic = parser_state.LogicInstLookupTable[main_inst]
            # A zero-delay main (FUNC_WIRES rewiring, bit manipulation, clock
            # crossing, ...) trivially meets any goal and has no timing path
            # worth synthesizing - skip it silently (no as-written check, no
            # "nothing autopipelining can help" note).
            if SYN.LOGIC_IS_ZERO_DELAY(main_logic, parser_state, allow_none_delay=True):
                continue
            print(
                f"[sweep] {main_logic.func_name} has a {target_mhz:.2f} MHz goal but "
                "contains nothing autopipelining can help (no sliceable logic and "
                "no AUTOPIPELINE regions) - the goal is met only if the design "
                "meets timing as written (checked below).",
                flush=True,
            )
            planless_goal_mains.append((main_inst, target_mhz))
            continue
        plan = MainSweepPlan(main_inst, target_mhz)
        plan.subtrees = subtrees
        plans[main_inst] = plan

    # One standalone synthesis each so the user sees whether "as written"
    # holds - result is informational and never stored as the func's delay.
    # --no_sweep skips this too: it is purely informational, not needed to
    # produce the first planned guess.
    if not SYN.NO_SWEEP:
        RUN_AS_WRITTEN_CHECKS(planless_goal_mains, parser_state)

    # NOTE on budget calibration: cut counts are anchored to reality by the
    # "measurement frontier" in the presynth wave (SYN.FUNC_IS_TOPMOST_COMB):
    # the topmost fully-combinational funcs get one real synthesis run each,
    # so the estimated delays of everything above them (stateful containers,
    # subtree roots, mains - which are NEVER synthesized per-module, their
    # synthesized number would be an internal critical path, not an
    # input-to-output through delay) are built from measured totals. No
    # subtree-root synthesis happens here.

    best_tpl = None
    best_score = None
    measured_fallback_done = False
    iteration = 0
    # main_inst -> (curr_mhz, met, target_mhz) for goal-having mains with no
    # plan (nothing cuttable) - their failing reports must still fail the build
    planless_results = {}
    # Post-met stage trimming state (--pipeline_min_effort)
    trim_iters_used = 0
    met_snapshot_tpl = None
    met_snapshot_cuts = None
    met_snapshot_plan_cuts = None
    best_plan_cuts = None

    while True:
        iteration += 1
        # Fresh zero-clock table, then locks, then planned cuts
        tpl = SYN.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)
        for plan in plans.values():
            tpl = APPLY_LOCKS(plan, parser_state, tpl)
        for plan in plans.values():
            # Build landscapes (locked subtree roots already carry their
            # pipeline from the lock - planning/slicing them again is illegal)
            for subtree_root in plan.subtrees:
                if tpl[subtree_root].params_are_fixed:
                    plan.landscapes[subtree_root] = None
                    plan.cuts[subtree_root] = []
                    continue
                plan.landscapes[subtree_root] = BUILD_SLICE_LANDSCAPE(
                    subtree_root, parser_state, tpl, plan.func_delay_scale
                )
            # Plan cuts. Replanning an unresolved plan to the identical cut
            # list would waste a whole synthesis run (a small budget change
            # can be eaten by cut quantization) - nudge the scale until the
            # plan actually changes. Direction follows intent: more cuts when
            # timing failed, fewer when probing down after having met (trim).
            plan_unresolved = (
                not plan.met_timing
                and plan.stopped_reason is None
                and plan.prev_total_cuts is not None
            )
            total_cuts = 0
            for attempt in range(8):
                total_cuts = 0
                for subtree_root in plan.subtrees:
                    landscape = plan.landscapes.get(subtree_root)
                    if landscape is None:
                        continue
                    budget = (
                        plan.target_period_ns / landscape.units_to_ns
                    ) / plan.global_scale
                    plan.cuts[subtree_root] = PLAN_CUTS(landscape, budget)
                    total_cuts += len(plan.cuts[subtree_root])
                if not plan_unresolved or total_cuts != plan.prev_total_cuts:
                    break
                if plan.trim_pending:
                    plan.global_scale /= 1.1  # probing down - even fewer
                else:
                    plan.global_scale *= 1.1  # failing - force more cuts
            plan.prev_total_cuts = total_cuts
            # Apply the cuts
            for subtree_root in plan.subtrees:
                landscape = plan.landscapes.get(subtree_root)
                cuts = plan.cuts.get(subtree_root, [])
                if landscape is None or len(cuts) == 0:
                    continue
                root_logic = parser_state.LogicInstLookupTable[subtree_root]
                slices = CUTS_TO_SLICES(cuts, landscape)
                tpl = (
                    SYN.ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(
                        subtree_root,
                        root_logic,
                        slices,
                        parser_state,
                        tpl,
                        write_files=False,
                    )
                )
                if type(tpl) is int:
                    raise Exception(
                        f"Planned cut produced a bad slice in {subtree_root}: slice index {tpl} of {slices}"
                    )
                CHECK_CUTS_VS_LATENCY(
                    subtree_root, tpl, parser_state, len(cuts), landscape
                )
        if iteration == 1:
            for plan in plans.values():
                PRINT_FLOOR_REPORT(plan, parser_state)

        multimain_timing_params.TimingParamsLookupTable = tpl

        # Instances above the modified (sliced/locked) ones still carry stale
        # zero clock hash/latency caches - refresh them and rewrite their
        # entities since the names of their instantiated children changed
        ancestor_insts = SYN.INVALIDATE_MODIFIED_INST_ANCESTOR_CACHES(tpl, parser_state)

        # Write output files and run the one full-design synthesis
        print("Updating output files...", flush=True)
        SYN.WRITE_ALL_NON_ZERO_CLK_VHDL_FILES(tpl, parser_state, ancestor_insts)
        SYN.WRITE_REGISTERS_ESTIMATE_FILE(parser_state, multimain_timing_params)

        if SYN.NO_SWEEP:
            # First planned guess only -- no sweep synthesis iterations.
            # Timing is NOT verified; raise the @MAIN mhz target for more
            # pipeline stages.
            print(
                "--no_sweep: writing the first planned guess without "
                "verifying it against real synthesis. Timing is NOT "
                "confirmed -- raise the @MAIN mhz target for more pipeline "
                "stages.",
                flush=True,
            )
            for plan in plans.values():
                main_func_name = parser_state.LogicInstLookupTable[
                    plan.main_inst
                ].func_name
                _mono, _regions, total_stages = SUMMARIZE_SUBTREE_PIPELINE(
                    plan.main_inst, plan.subtrees, tpl, parser_state
                )
                print(
                    f"[sweep] {main_func_name}: --no_sweep guess, "
                    f"{total_stages} pipeline register stage(s) built "
                    f"({total_stages + 1} pipeline stages), "
                    f"cuts={sum(len(c) for c in plan.cuts.values())} "
                    "(UNVERIFIED)",
                    flush=True,
                )
            multimain_timing_params.sweep_timing_failures = []
            return multimain_timing_params

        # What's about to be synthesized, printed BEFORE the long wait below
        # (previously this only appeared after synthesis finished, alongside
        # the achieved MHz - leaving "how many slices/stages did it even try"
        # unknown for the whole duration of a long syn run).
        for plan in plans.values():
            main_func_name = parser_state.LogicInstLookupTable[
                plan.main_inst
            ].func_name
            _mono, _regions, total_stages = SUMMARIZE_SUBTREE_PIPELINE(
                plan.main_inst, plan.subtrees, tpl, parser_state
            )
            print(
                f"[sweep] {main_func_name}: about to synthesize, "
                f"cuts={sum(len(c) for c in plan.cuts.values())}, "
                f"{total_stages} pipeline register stage(s) "
                f"({total_stages + 1} pipeline stages)",
                flush=True,
            )

        print(
            f"Running syn w timing params... (sweep iteration {iteration})",
            flush=True,
        )
        print(f"Elapsed time: {str(timedelta(seconds=(timer() - SYN.START_TIME)))}...")
        timing_report = SYN.SYN_TOOL.SYN_AND_REPORT_TIMING_MULTIMAIN(
            parser_state, multimain_timing_params
        )
        if len(timing_report.path_reports) == 0:
            print(timing_report.orig_text)
            print("Using a bad syn log file?")
            sys.exit(-1)

        # Evaluate each reported clock group
        made_change = False
        overall_score = None
        evaluated_plans = set()  # main insts implicated in some path report
        any_report_failed = False
        for reported_clock_group in timing_report.path_reports:
            path_report = timing_report.path_reports[reported_clock_group]
            curr_mhz = 1000.0 / path_report.path_delay_ns
            main_insts = GET_MAIN_INSTS_FOR_PATH_REPORT(
                path_report, parser_state, multimain_timing_params
            )
            if len(main_insts) == 0:
                print(
                    "Path group:",
                    reported_clock_group,
                    "is likely only limited by built in FIFO implementations...",
                )
                continue
            for main_inst in main_insts:
                main_logic = parser_state.LogicInstLookupTable[main_inst]
                target_mhz = SYN.GET_TARGET_MHZ(main_inst, parser_state)
                if target_mhz is None:
                    continue
                met = curr_mhz >= target_mhz
                if not met:
                    any_report_failed = True
                score = curr_mhz / target_mhz
                if overall_score is None or score < overall_score:
                    overall_score = score
                if main_inst in plans:
                    evaluated_plans.add(main_inst)
                if main_inst not in plans:
                    # Nothing cuttable for this main
                    planless_results[main_inst] = (curr_mhz, met, target_mhz)
                    if not met:
                        print(
                            f"[sweep] WARNING: {main_logic.func_name} fails timing "
                            f"({curr_mhz:.2f} MHz vs {target_mhz:.2f} MHz goal) and autopipelining "
                            "cannot help it (no sliceable logic and no AUTOPIPELINE regions in this main) - "
                            "restructure the design or lower the clock goal."
                        )
                        print("START: ", path_report.start_reg_name, "=>")
                        print(" ~", path_report.path_delay_ns, "ns of logic+routing ~")
                        print("END: =>", path_report.end_reg_name, flush=True)
                    continue
                plan = plans[main_inst]
                plan.last_achieved_mhz = curr_mhz
                plan.trim_pending = False
                total_cuts = sum(len(c) for c in plan.cuts.values())
                latency = tpl[main_inst].GET_TOTAL_LATENCY(parser_state, tpl)
                deepest = GET_SUBTREE_PIPELINE_STAGES(plan, tpl, parser_state)
                predicted_ns = 0.0
                for subtree_root, cuts in plan.cuts.items():
                    landscape = plan.landscapes.get(subtree_root)
                    if landscape is not None:
                        predicted_ns = max(
                            predicted_ns, PREDICTED_STAGE_NS(cuts, landscape)
                        )
                hotspot_func = None
                stage_info = ""
                action = "met" if met else "?"
                if met:
                    plan.met_timing = True
                    plan.stopped_reason = None
                else:
                    plan.met_timing = False
                    # Record largest known-failing cut count (for minimality
                    # bisection after timing is met)
                    if (
                        plan.last_failing_total_cuts is None
                        or total_cuts > plan.last_failing_total_cuts
                    ):
                        plan.last_failing_total_cuts = total_cuts
                    # Same result twice in a row? (relative tolerance: 1% of
                    # the target - e.g. 62.92 vs 62.99 MHz IS the same result)
                    if (
                        plan.last_mhz is not None
                        and abs(curr_mhz - plan.last_mhz) < 0.01 * target_mhz
                    ):
                        plan.same_mhz_count += 1
                    else:
                        plan.same_mhz_count = 0
                    # At a predicted floor?
                    # Hard floors (pure comb spans) stop immediately; soft
                    # floors (stateful module delays incl. cuttable IO paths)
                    # only stop once the achieved fmax has actually stagnated
                    # there - they are pessimistic estimates, not ceilings.
                    hard_floor, hard_blame = plan.predicted_hard_floor()
                    soft_floor, soft_blame = plan.predicted_floor()
                    # See AT_PREDICTED_FLOOR's own docstring for the
                    # symmetric-tolerance-band rationale.
                    at_hard_floor = AT_PREDICTED_FLOOR(curr_mhz, hard_floor, target_mhz)
                    # A soft floor built from ESTIMATED spans is not evidence
                    # enough to give up: measure the real delays first (the
                    # ladder's escalation - fallback, minisweep - broke
                    # identical plateaus before). Only stop at a soft floor
                    # once no estimates are in play.
                    any_estimates_in_play = any(
                        l.delay_is_estimated
                        for l in parser_state.FuncLogicLookupTable.values()
                    )
                    at_soft_floor = (
                        AT_PREDICTED_FLOOR(curr_mhz, soft_floor, target_mhz)
                        and plan.same_mhz_count >= 1
                        and (
                            measured_fallback_done
                            or not any_estimates_in_play
                            # "prim" mode: estimates are always in play and
                            # never measured for real -- treat as if the
                            # fallback already ran so the sweep can still
                            # reach its floor stop instead of densifying
                            # forever.
                            or SYN.HIER_SYN_MODE == "prim"
                        )
                    )
                    if at_hard_floor or at_soft_floor:
                        floor = hard_floor if at_hard_floor else soft_floor
                        floor_blame = hard_blame if at_hard_floor else soft_blame
                        blame_str = ""
                        if floor_blame is not None:
                            blame_str = f" due to {floor_blame.inst_path.split(C_TO_LOGIC.SUBMODULE_MARKER)[-1]} ({floor_blame.reason})"
                        kind_str = "predicted" if at_hard_floor else "empirical (soft)"
                        print(
                            f"[sweep] WARNING: {main_logic.func_name} at {kind_str} fmax floor "
                            f"(~{floor:.1f} MHz{blame_str}); cannot improve by adding registers. Keeping best result.",
                            flush=True,
                        )
                        plan.stopped_reason = (
                            "predicted_floor" if at_hard_floor else "empirical_floor"
                        )
                        action = "stop_at_floor"
                    else:
                        hotspot_func, stage_info = ATTRIBUTE_PATH_TO_FUNC(
                            path_report, plan, parser_state
                        )
                        # Can autopipelining even help the blamed func?
                        unpipelinable_reason = None
                        if hotspot_func is not None:
                            h_logic = parser_state.FuncLogicLookupTable[hotspot_func]
                            if not h_logic.CAN_HAVE_ADDED_LATENCY(parser_state):
                                unpipelinable_reason = WHY_NOT_SLICEABLE(
                                    h_logic, parser_state
                                )
                            elif not SYN.FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL(
                                hotspot_func, parser_state
                            ):
                                unpipelinable_reason = "no sliceable logic beneath it"
                        if (
                            hotspot_func is not None
                            and unpipelinable_reason is not None
                        ):
                            # The critical path is somewhere register insertion
                            # cannot reach. Boundary registers placed around the
                            # func can still cut its IO paths, so rescale once -
                            # but if fmax then stagnates, tell the user plainly
                            # that the tool cannot help this path.
                            plan.unpipelinable_blame = (
                                hotspot_func,
                                unpipelinable_reason,
                            )
                            if plan.same_mhz_count >= 1:
                                print(
                                    f"[sweep] WARNING: {main_logic.func_name} cannot meet {target_mhz:.2f} MHz: "
                                    f"the critical path is in function {hotspot_func}, which cannot be "
                                    f"autopipelined ({unpipelinable_reason}). Adding pipeline registers cannot "
                                    f"subdivide this path - restructure {hotspot_func} or lower the clock goal. "
                                    "Keeping best result.",
                                    flush=True,
                                )
                                plan.stopped_reason = "unpipelinable_hotspot"
                                action = f"stop(unpipelinable {hotspot_func})"
                            else:
                                print(
                                    f"[sweep] NOTE: {main_logic.func_name} critical path attributed to "
                                    f"{hotspot_func}, which cannot be autopipelined internally ({unpipelinable_reason}); "
                                    "registers at its boundaries may still help - replanning.",
                                    flush=True,
                                )
                                step = min(
                                    max(
                                        (target_mhz / curr_mhz) * 1.05,
                                        GLOBAL_SCALE_MIN_STEP,
                                    ),
                                    GLOBAL_SCALE_MAX_STEP,
                                )
                                plan.global_scale *= step
                                action = f"replan(global x{plan.global_scale:.2f}, {hotspot_func} unpipelinable)"
                                made_change = True
                        elif hotspot_func is not None and HOTSPOT_IS_LOCKED(
                            hotspot_func, plan, parser_state
                        ):
                            # The blamed func is already locked at its best
                            # isolated result - nothing more to change inside
                            # it. If this repeats the sweep stops (same mhz /
                            # no change) keeping the best result.
                            if plan.same_mhz_count >= 1:
                                print(
                                    f"[sweep] WARNING: {main_logic.func_name} limited by "
                                    f"already-locked {hotspot_func} (best isolated pipelining applied); "
                                    "cannot improve further. Keeping best result.",
                                    flush=True,
                                )
                                plan.stopped_reason = "locked_hotspot_limit"
                                action = f"stop(locked {hotspot_func})"
                            else:
                                step = min(
                                    max(
                                        (target_mhz / curr_mhz) * 1.05,
                                        GLOBAL_SCALE_MIN_STEP,
                                    ),
                                    GLOBAL_SCALE_MAX_STEP,
                                )
                                plan.global_scale *= step
                                action = f"replan(global x{plan.global_scale:.2f}, hotspot {hotspot_func} locked)"
                                made_change = True
                        elif hotspot_func is not None:
                            plan.hotspot_streak[hotspot_func] = (
                                plan.hotspot_streak.get(hotspot_func, 0) + 1
                            )
                            # Other funcs' streaks reset
                            for f in list(plan.hotspot_streak.keys()):
                                if f != hotspot_func:
                                    plan.hotspot_streak[f] = 0
                            # Mini sweep + lock is the LAST resort: while
                            # estimated delays are still in play the cut
                            # placement (not the total) is the prime suspect
                            # - fix the delay model first (the stagnation /
                            # no-change fallback measures for real), and only
                            # escalate to locking if that didn't help
                            any_estimates = any(
                                l.delay_is_estimated
                                for l in parser_state.FuncLogicLookupTable.values()
                            )
                            if (
                                plan.hotspot_streak[hotspot_func]
                                >= MINISWEEP_HOTSPOT_STREAK
                                and plan.minisweeps_used < MAX_MINISWEEPS
                                and (
                                    measured_fallback_done
                                    or not any_estimates
                                    or SYN.HIER_SYN_MODE == "prim"
                                )
                            ):
                                plan.minisweeps_used += 1
                                if RUN_HOTSPOT_MINISWEEP(
                                    hotspot_func, plan, parser_state
                                ):
                                    action = f"minisweep({hotspot_func})"
                                    plan.hotspot_streak[hotspot_func] = 0
                                    made_change = True
                                else:
                                    # Couldn't fix in isolation: densify anyway
                                    step = min(
                                        max(
                                            (target_mhz / curr_mhz) * 1.05,
                                            FUNC_SCALE_MIN_STEP,
                                        ),
                                        FUNC_SCALE_MAX_STEP,
                                    )
                                    plan.func_delay_scale[hotspot_func] = (
                                        plan.func_delay_scale.get(hotspot_func, 1.0)
                                        * step
                                    )
                                    action = f"densify({hotspot_func} x{plan.func_delay_scale[hotspot_func]:.2f})"
                                    made_change = True
                            else:
                                step = min(
                                    max(
                                        (target_mhz / curr_mhz) * 1.05,
                                        FUNC_SCALE_MIN_STEP,
                                    ),
                                    FUNC_SCALE_MAX_STEP,
                                )
                                plan.func_delay_scale[hotspot_func] = (
                                    plan.func_delay_scale.get(hotspot_func, 1.0) * step
                                )
                                action = f"densify({hotspot_func} x{plan.func_delay_scale[hotspot_func]:.2f})"
                                made_change = True
                        else:
                            # No attribution (PYRTL etc.): scale global budget
                            step = min(
                                max(
                                    (target_mhz / curr_mhz) * 1.05,
                                    GLOBAL_SCALE_MIN_STEP,
                                ),
                                GLOBAL_SCALE_MAX_STEP,
                            )
                            plan.global_scale *= step
                            action = f"replan(global x{plan.global_scale:.2f})"
                            made_change = True
                    plan.last_mhz = curr_mhz
                bottleneck_str = (
                    f" bottleneck={hotspot_func}{stage_info}" if hotspot_func else ""
                )
                # deepest = SLICES (see GET_SUBTREE_PIPELINE_STAGES);
                # pipeline_stages is comb regions separated by those slices,
                # i.e. slices + 1 (0 slices = 1 stage, 1 slice = 2
                # stages, ...) - conflating the two here previously made
                # e.g. "cuts=30 main_latency=30 pipeline_stages=30" look like
                # 30 cuts bought 0 extra stages.
                pipeline_stages = deepest + 1
                print(
                    f"[sweep] iter={iteration} main={main_logic.func_name} "
                    f"goal={target_mhz:.2f}MHz got={curr_mhz:.2f}MHz ({path_report.path_delay_ns:.2f}ns) "
                    f"cuts={total_cuts} main_latency={latency} pipeline_stages={pipeline_stages} "
                    f"predicted_stage={predicted_ns:.2f}ns"
                    f"{bottleneck_str} action={action}",
                    flush=True,
                )
                plan.history.append(
                    {
                        "iter": iteration,
                        "main": main_logic.func_name,
                        "goal_mhz": target_mhz,
                        "achieved_mhz": round(curr_mhz, 3),
                        "cuts": total_cuts,
                        "main_latency": latency,
                        "pipeline_stages": pipeline_stages,
                        "predicted_stage_ns": round(predicted_ns, 3),
                        "bottleneck": hotspot_func,
                        "action": action,
                    }
                )

        # Track best result so far (largest worst-case achieved/target ratio)
        if overall_score is not None and (
            best_score is None or overall_score > best_score
        ):
            best_score = overall_score
            best_tpl = copy.deepcopy(tpl)
            best_plan_cuts = {mi: copy.deepcopy(p.cuts) for mi, p in plans.items()}

        # Plans never implicated in a failing path report have no timing
        # signal to react to - when every reported path meets its goal they
        # are done too (the per clock group report only shows the worst path,
        # which can live in a different main of the same clock group)
        if not any_report_failed:
            for main_inst, plan in plans.items():
                if (
                    main_inst not in evaluated_plans
                    and not plan.met_timing
                    and plan.stopped_reason is None
                ):
                    print(
                        f"[sweep] {parser_state.LogicInstLookupTable[main_inst].func_name}: "
                        "no failing timing path reported for this main; assuming met.",
                        flush=True,
                    )
                    plan.met_timing = True

        # Termination
        all_done = (
            all(p.met_timing or p.stopped_reason is not None for p in plans.values())
            and len(plans) > 0
        )
        if len(plans) == 0:
            # Nothing was cuttable: one syn run characterized the design
            break
        if all_done:
            all_met = all(p.met_timing for p in plans.values())
            if all_met:
                # Timing met - but with how many registers? Meeting timing by
                # over-pipelining is worse than a few more iterations. Slack
                # is NOT the signal (tools stop optimizing at slack ~0, so a
                # met design reports near-zero slack no matter how many
                # excess registers it carries). Instead use cut-count
                # history: bisect between the last known FAILING cut count
                # and the met count, or probe below a met count whose
                # minimality was never proven by a failing data point.
                total_cuts_now = sum(
                    sum(len(c) for c in p.cuts.values()) for p in plans.values()
                )
                if met_snapshot_cuts is None or total_cuts_now < met_snapshot_cuts:
                    met_snapshot_cuts = total_cuts_now
                    met_snapshot_tpl = copy.deepcopy(tpl)
                    met_snapshot_plan_cuts = {
                        mi: copy.deepcopy(p.cuts) for mi, p in plans.items()
                    }
                trim_candidates = []
                for p in plans.values():
                    if p.stopped_reason is not None:
                        continue
                    met_cuts = sum(len(c) for c in p.cuts.values())
                    if met_cuts <= 1:
                        continue
                    if p.last_failing_total_cuts is None:
                        # Never seen failing - minimality unproven, probe down
                        desired = met_cuts - max(1, met_cuts // 8)
                    elif met_cuts > p.last_failing_total_cuts + 1:
                        # Bisect the gap toward the fewest passing count
                        desired = (met_cuts + p.last_failing_total_cuts) // 2
                    else:
                        continue  # minimal within one cut - proven
                    if desired <= 0 or desired >= met_cuts:
                        continue
                    trim_candidates.append((p, met_cuts, desired))
                if (
                    trim_iters_used < SYN.PIPELINE_MIN_EFFORT
                    and len(trim_candidates) > 0
                ):
                    trim_iters_used += 1
                    for p, met_cuts, desired in trim_candidates:
                        # cuts scale ~linearly with global_scale
                        p.global_scale *= desired / float(met_cuts)
                        p.met_timing = False  # must re-prove at fewer cuts
                        p.trim_pending = True
                        print(
                            f"[sweep] Trimming stages: {parser_state.LogicInstLookupTable[p.main_inst].func_name} "
                            f"met at {met_cuts} cuts (known failing: {p.last_failing_total_cuts}), "
                            f"retrying at ~{desired} cuts (trim {trim_iters_used}/{SYN.PIPELINE_MIN_EFFORT})",
                            flush=True,
                        )
                    continue
                print("Met timing...", flush=True)
            break
        # A trim attempt overshot (previously-met plan now failing): restore
        # the fewest-stage met result and finish
        if met_snapshot_tpl is not None and trim_iters_used > 0:
            print(
                f"[sweep] Trim attempt failed timing; restoring met result with {met_snapshot_cuts} cuts...",
                flush=True,
            )
            tpl = met_snapshot_tpl
            multimain_timing_params.TimingParamsLookupTable = tpl
            for mi, p in plans.items():
                if mi in met_snapshot_plan_cuts:
                    p.cuts = met_snapshot_plan_cuts[mi]
            ancestor_insts = SYN.INVALIDATE_MODIFIED_INST_ANCESTOR_CACHES(
                tpl, parser_state
            )
            SYN.WRITE_ALL_NON_ZERO_CLK_VHDL_FILES(tpl, parser_state, ancestor_insts)
            for p in plans.values():
                if p.stopped_reason is None:
                    p.met_timing = True
            print("Met timing...", flush=True)
            break
        # Fmax stuck at the same value while cuts keep growing means the
        # landscape geometry is wrong (cuts not landing on the real critical
        # path) - if estimates are in play they are the prime suspect
        fmax_stagnant = any(
            p.same_mhz_count >= 1 and not p.met_timing and p.stopped_reason is None
            for p in plans.values()
        )
        if iteration >= MAX_SWEEP_ITERS or not made_change or fmax_stagnant:
            # Automatic fallback: if estimates are still in play, measure for
            # real once and keep sweeping - an estimate must never be the
            # reason the sweep fails
            if not measured_fallback_done and SYN.HIER_SYN_MODE == "leaf":
                estimated_funcs = [
                    f
                    for f, l in parser_state.FuncLogicLookupTable.items()
                    if l.delay_is_estimated
                ]
                if len(estimated_funcs) > 0:
                    print(
                        "[sweep] Falling back to full hierarchy synthesis: replacing "
                        f"{len(estimated_funcs)} estimated delays with measured results...",
                        flush=True,
                    )
                    SYN.MEASURE_DELAYS(estimated_funcs, parser_state)
                    measured_fallback_done = True
                    # Fresh signal: the delay model changed, stagnation
                    # bookkeeping no longer applies
                    for p in plans.values():
                        p.same_mhz_count = 0
                        p.last_mhz = None
                    # Grant at least two more iterations to replan with the
                    # measured (no longer estimated) delays
                    iteration = min(iteration, MAX_SWEEP_ITERS - 2)
                    continue
            if not (iteration >= MAX_SWEEP_ITERS or not made_change):
                # Only stagnation brought us here and the fallback already
                # ran - keep iterating within the normal budget
                continue
            for plan in plans.values():
                if not plan.met_timing and plan.stopped_reason is None:
                    plan.stopped_reason = (
                        "iteration_limit" if made_change else "no_legal_adjustment"
                    )
                    culprit_str = ""
                    if plan.unpipelinable_blame is not None:
                        blamed_func, blame_reason = plan.unpipelinable_blame
                        culprit_str = (
                            f" Critical path was attributed to {blamed_func}, which cannot be "
                            f"autopipelined ({blame_reason}) - restructure it or lower the clock goal."
                        )
                    print(
                        f"[sweep] WARNING: {parser_state.LogicInstLookupTable[plan.main_inst].func_name} "
                        f"stopped without meeting timing ({plan.stopped_reason}). Keeping best result.{culprit_str}",
                        flush=True,
                    )
            break

    # Use the best seen params if the last iteration wasn't the best
    if best_tpl is not None and not all(p.met_timing for p in plans.values()):
        multimain_timing_params.TimingParamsLookupTable = best_tpl
        if best_plan_cuts is not None:
            for mi, p in plans.items():
                if mi in best_plan_cuts:
                    p.cuts = best_plan_cuts[mi]
        best_ancestors = SYN.INVALIDATE_MODIFIED_INST_ANCESTOR_CACHES(
            best_tpl, parser_state
        )
        SYN.WRITE_ALL_NON_ZERO_CLK_VHDL_FILES(best_tpl, parser_state, best_ancestors)
        if BEST_SNAPSHOT_MET_ALL_GOALS(best_score):
            for p in plans.values():
                p.met_timing = True
                p.stopped_reason = None

    # Final summary + history dump
    for plan in plans.values():
        main_func_name = parser_state.LogicInstLookupTable[plan.main_inst].func_name
        outcome = (
            "met timing" if plan.met_timing else f"stopped ({plan.stopped_reason})"
        )
        _mono, _regions, total_stages = SUMMARIZE_SUBTREE_PIPELINE(
            plan.main_inst,
            plan.subtrees,
            multimain_timing_params.TimingParamsLookupTable,
            parser_state,
        )
        print(
            f"[sweep] {main_func_name}: {outcome}, {total_stages} pipeline register "
            f"stage(s) built ({total_stages + 1} pipeline stages), "
            f"cuts={sum(len(c) for c in plan.cuts.values())}, "
            f"locked={len(plan.locked)} inst(s), iterations={iteration}",
            flush=True,
        )
    try:
        out_dir = SYN.SYN_OUTPUT_DIRECTORY + "/" + SYN.TOP_LEVEL_MODULE
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        history_path = out_dir + "/sweep_history.json"
        with open(history_path, "w") as f:
            json.dump(
                {
                    parser_state.LogicInstLookupTable[p.main_inst].func_name: p.history
                    for p in plans.values()
                },
                f,
                indent=1,
            )
        print(f"[sweep] History: {history_path}", flush=True)
    except Exception as e:
        print("[sweep] Could not write sweep history:", e)

    # Record unmet timing goals so the build can FAIL (non zero exit) instead
    # of silently writing results and running simulation on a design that
    # does not meet its clocks (pipelinec gates on this after writing files)
    timing_failures = []
    for plan in plans.values():
        if plan.met_timing:
            continue
        main_func_name = parser_state.LogicInstLookupTable[plan.main_inst].func_name
        achieved = None
        for h in plan.history:
            if h.get("achieved_mhz") is not None:
                if achieved is None or h["achieved_mhz"] > achieved:
                    achieved = h["achieved_mhz"]
        why = plan.stopped_reason or "unknown"
        if plan.unpipelinable_blame is not None:
            blamed_func, blame_reason = plan.unpipelinable_blame
            why += f": {blamed_func}, {blame_reason}"
        timing_failures.append((main_func_name, plan.target_mhz, achieved, why))
    # Mains with a goal but no plan (nothing cuttable) whose last timing
    # report failed also count
    for main_inst, (pl_curr, pl_met, pl_target) in planless_results.items():
        if not pl_met:
            timing_failures.append(
                (
                    parser_state.LogicInstLookupTable[main_inst].func_name,
                    pl_target,
                    pl_curr,
                    "nothing_autopipelinable",
                )
            )
    multimain_timing_params.sweep_timing_failures = timing_failures

    return multimain_timing_params
