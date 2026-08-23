#!/usr/bin/env python
"""
Planned throughput sweep: autopipelining driven by a static delay model
("slice landscape") plus synthesis feedback attribution, replacing the old
multiplier-driven middle-out sweep.

Terminology (see docs/SYN_DESIGN.md):
  cut         - a planned register position along a module's combinational
                delay. Cuts select typed physical placements: an operation's
                output boundary or a genuine bit-internal leaf split. The
                number of cuts requested and the pipeline latency that
                results are related but intentionally NOT the same number.
  cut subtree - a maximal subtree of the instance hierarchy that can accept
                added latency: either a sliceable pure-comb function, or a
                region reached through AUTOPIPELINE tagged call sites
                underneath stateful (feedback/state reg) containers.
  landscape   - the flattened delay axis of one cut subtree, each delay unit
                tagged legal (a cut resolves to an operation-output boundary
                or a true bit-splittable raw-leaf site) or illegal (only
                unsliceable/locked logic here), with weights used for stage
                budgeting and calibration.
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
import hashlib
import json
import bisect
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
import VHDL

# Max full-design synthesis runs in the refinement loop
# (generous: budgets start at the fewest-stages guess and converge from
#  below, which takes more, cheaper-to-accept iterations than overshooting)
MAX_SWEEP_ITERS = 12
# Calibration clip ranges: how much a single iteration may scale delay weights
FUNC_SCALE_MIN_STEP = 1.05
FUNC_SCALE_MAX_STEP = 3.0
GLOBAL_SCALE_MIN_STEP = 1.05
GLOBAL_SCALE_MAX_STEP = 2.0
# Consecutive same-hotspot attributions before an isolated mini sweep.
#
# A repeatedly blamed hierarchical helper is stronger evidence than the
# current top-level geometry: its isolated sweep measures the helper before
# choosing any lock, while another global densify step can jump over the
# short, repeatable solution (Wireguard's ten block-step helpers are the
# motivating case).  Two independent full-design failures are enough to
# justify that bounded, measured probe.  The mini sweep remains capped and
# falls back to ordinary densification if it cannot produce an internal cut.
MINISWEEP_HOTSPOT_STREAK = 2
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
    # NOT/NEGATE/MULT). The typed planner exposes its output boundary; its
    # interior is atomic like a genuinely unsliceable span. The legacy raw
    # VHDL splitter can still represent input/output boundary slices when
    # used directly outside this planner. See SliceLandscape.finalize().
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
        # Optional planner-only relative delay (e.g. isolated combinational
        # component instead of full clk-to-q + logic + setup).  It is
        # normalized across the landscape before feedback scales are applied,
        # so the measured frontier total and initial cut-count budget stay
        # unchanged while relative placement geometry may move.
        self.planner_scale = 1.0

    def __str__(self):
        return f"[{self.start:.1f},{self.end:.1f}) {self.kind} {self.inst_path.split(C_TO_LOGIC.SUBMODULE_MARKER)[-1]}({self.reason})"


class PipelinePlacement:
    """One concrete, physically lowerable pipeline-register position.

    The old landscape planner returned only an integer position on a flattened
    delay axis.  Lowering that position recursively projected a fractional cut
    through every descendant overlapping the axis position.  That is useful as
    a fallback representation, but it loses the distinction between two very
    different pieces of hardware:

      * a register on a combinational operation instance's outputs; and
      * a genuine internal split in a bit-splittable raw-HDL leaf.

    A PipelinePlacement preserves that distinction all the way through
    lowering.  ``fixed`` means the placement was supplied by the internal
    experiment hook and must be retained while the remaining positions are
    planned; it does *not* freeze the whole instance subtree.
    """

    INSTANCE_INPUT = "instance_input"
    INSTANCE_OUTPUT = "instance_output"
    BIT_INTERNAL = "bit_internal"

    def __init__(
        self,
        kind,
        inst_path,
        func_name,
        axis_unit,
        axis_position,
        local_slice=None,
        registered_bits=None,
        hierarchy_depth=0,
        span_units=0.0,
        coherent_boundary=False,
        ancestor_funcs=None,
        fixed=False,
        source="planner",
        bit_width=None,
        bit_split_ordinal=None,
        bit_split_count=None,
        bit_boundary=None,
        bit_boundary_mode="equal_width",
        bit_boundaries=None,
        leaf_axis_start=None,
        leaf_axis_end=None,
        requested_axis_unit=None,
        requested_axis_position=None,
        requested_local_slice=None,
    ):
        if kind not in (
            self.INSTANCE_INPUT,
            self.INSTANCE_OUTPUT,
            self.BIT_INTERNAL,
        ):
            raise ValueError(f"Unknown pipeline placement kind: {kind}")
        if kind == self.BIT_INTERNAL:
            required = {
                "bit_width": bit_width,
                "bit_split_ordinal": bit_split_ordinal,
                "bit_split_count": bit_split_count,
                "bit_boundary": bit_boundary,
                "leaf_axis_start": leaf_axis_start,
                "leaf_axis_end": leaf_axis_end,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(
                    "Physical BIT_INTERNAL placement requires "
                    + ", ".join(missing)
                )
            bit_width = int(bit_width)
            bit_split_ordinal = int(bit_split_ordinal)
            bit_split_count = int(bit_split_count)
            bit_boundary = int(bit_boundary)
            if bit_boundary_mode not in ("equal_width", "exact"):
                raise ValueError(
                    f"Unknown bit-boundary mode: {bit_boundary_mode}"
                )
            if bit_width <= 0 or bit_split_count <= 0:
                raise ValueError(
                    f"Invalid physical bit split width/count: "
                    f"{bit_width}/{bit_split_count}"
                )
            if not 1 <= bit_split_ordinal <= bit_split_count:
                raise ValueError(
                    f"Invalid physical bit split ordinal "
                    f"{bit_split_ordinal}/{bit_split_count}"
                )
            if bit_boundary_mode == "exact":
                if bit_boundaries is None:
                    raise ValueError(
                        "Exact BIT_INTERNAL placement requires bit_boundaries"
                    )
                expected_boundaries = tuple(int(b) for b in bit_boundaries)
                if (
                    len(expected_boundaries) != bit_split_count
                    or expected_boundaries != tuple(sorted(set(expected_boundaries)))
                    or any(b <= 0 or b >= bit_width for b in expected_boundaries)
                ):
                    raise ValueError(
                        f"Invalid exact bit-boundary group {expected_boundaries} "
                        f"for {bit_width}-bit leaf"
                    )
            else:
                expected_boundaries = tuple(
                    RAW_VHDL.GET_EQUAL_WIDTH_BIT_BOUNDARIES(
                        bit_width, bit_split_count
                    )
                )
            expected_boundary = expected_boundaries[bit_split_ordinal - 1]
            if bit_boundary != expected_boundary:
                raise ValueError(
                    f"BIT_INTERNAL boundary {bit_boundary} does not match "
                    f"{bit_boundary_mode} boundary {expected_boundary} for ordinal "
                    f"{bit_split_ordinal}/{bit_split_count} of {bit_width} bits"
                )
            expected_local_slice = bit_boundary / float(bit_width)
            if (
                local_slice is not None
                and not math.isclose(
                    float(local_slice), expected_local_slice, rel_tol=0.0, abs_tol=1e-15
                )
            ):
                raise ValueError(
                    f"BIT_INTERNAL local slice {local_slice} does not match "
                    f"emitted bit boundary {bit_boundary}/{bit_width}"
                )
            local_slice = expected_local_slice
            leaf_axis_start = float(leaf_axis_start)
            leaf_axis_end = float(leaf_axis_end)
            if leaf_axis_end <= leaf_axis_start:
                raise ValueError(
                    f"Invalid BIT_INTERNAL leaf axis span "
                    f"[{leaf_axis_start}, {leaf_axis_end})"
                )
            expected_axis_position = leaf_axis_start + local_slice * (
                leaf_axis_end - leaf_axis_start
            )
            expected_axis_unit = int(math.ceil(expected_axis_position)) - 1
            if not math.isclose(
                float(axis_position), expected_axis_position, rel_tol=0.0, abs_tol=1e-12
            ):
                raise ValueError(
                    f"BIT_INTERNAL axis position {axis_position} does not match "
                    f"physical boundary position {expected_axis_position}"
                )
            if int(axis_unit) != expected_axis_unit:
                raise ValueError(
                    f"BIT_INTERNAL axis unit {axis_unit} does not contain "
                    f"physical boundary position {expected_axis_position} "
                    f"(expected unit {expected_axis_unit})"
                )
        self.kind = kind
        self.inst_path = inst_path
        self.func_name = func_name
        self.axis_unit = int(axis_unit)
        self.axis_position = float(axis_position)
        self.local_slice = (
            None if local_slice is None else float(local_slice)
        )
        self.registered_bits = registered_bits
        self.hierarchy_depth = int(hierarchy_depth)
        self.span_units = float(span_units)
        self.coherent_boundary = bool(coherent_boundary)
        self.ancestor_funcs = tuple(sorted(ancestor_funcs or ()))
        self.fixed = bool(fixed)
        self.source = source
        self.bit_width = bit_width
        self.bit_split_ordinal = bit_split_ordinal
        self.bit_split_count = bit_split_count
        self.bit_boundary = bit_boundary
        self.bit_boundary_mode = bit_boundary_mode
        self.bit_boundaries = (
            None if bit_boundaries is None else tuple(int(b) for b in bit_boundaries)
        )
        self.leaf_axis_start = leaf_axis_start
        self.leaf_axis_end = leaf_axis_end
        self.requested_axis_unit = requested_axis_unit
        self.requested_axis_position = requested_axis_position
        self.requested_local_slice = requested_local_slice

    @property
    def is_physical(self):
        return True

    @property
    def bits_per_stage(self):
        if self.kind != self.BIT_INTERNAL:
            return None
        if self.bit_boundary_mode == "exact":
            previous = 0
            chunks = []
            for boundary in self.bit_boundaries + (self.bit_width,):
                chunks.append(boundary - previous)
                previous = boundary
            return tuple(chunks)
        return tuple(RAW_VHDL.GET_EQUAL_WIDTH_BITS_PER_STAGE_DICT(
            self.bit_width, self.bit_split_count
        ).values())

    @property
    def candidate_id(self):
        # Instance paths are elaboration-stable.  Use a decimal representation
        # with enough precision to distinguish every legal local slice while
        # remaining byte-stable across runs/Python versions.
        rv = f"{self.kind}:{self.inst_path}"
        if self.kind == self.BIT_INTERNAL:
            rv += (
                f"#{self.bit_split_ordinal}/{self.bit_split_count}"
                f"@bit{self.bit_boundary}/{self.bit_width}"
            )
        elif self.local_slice is not None:
            rv += f"@{self.local_slice:.15g}"
        return rv

    def copy_with(self, fixed=None, source=None):
        rv = copy.copy(self)
        if fixed is not None:
            rv.fixed = bool(fixed)
        if source is not None:
            rv.source = source
        return rv

    def to_dict(self):
        rv = {
            "candidate_id": self.candidate_id,
            "kind": self.kind,
            "placement_role": "physical",
            "physical": True,
            "instance_path": self.inst_path,
            "function": self.func_name,
            "axis_unit": self.axis_unit,
            "axis_position": round(self.axis_position, 12),
            "local_slice": (
                None if self.local_slice is None else round(self.local_slice, 12)
            ),
            "registered_bits": self.registered_bits,
            "registered_bits_scope": (
                "leaf_width_proxy"
                if self.kind == self.BIT_INTERNAL
                else (
                    "local_input_bank"
                    if self.kind == self.INSTANCE_INPUT
                    else "local_output_bank"
                )
            ),
            "hierarchy_depth": self.hierarchy_depth,
            "span_units": round(self.span_units, 6),
            "coherent_boundary": self.coherent_boundary,
            "ancestor_functions": list(self.ancestor_funcs),
            "fixed": self.fixed,
            "source": self.source,
        }
        if self.kind == self.BIT_INTERNAL:
            rv.update(
                {
                    "bit_width": self.bit_width,
                    "bit_boundary": self.bit_boundary,
                    "bit_boundary_mode": self.bit_boundary_mode,
                    "bit_boundaries": (
                        None
                        if self.bit_boundaries is None
                        else list(self.bit_boundaries)
                    ),
                    "bit_split_ordinal": self.bit_split_ordinal,
                    "bit_split_count": self.bit_split_count,
                    "bits_per_stage": list(self.bits_per_stage),
                    "leaf_axis_start": round(self.leaf_axis_start, 12),
                    "leaf_axis_end": round(self.leaf_axis_end, 12),
                    "requested_axis_unit": self.requested_axis_unit,
                    "requested_axis_position": (
                        None
                        if self.requested_axis_position is None
                        else round(self.requested_axis_position, 12)
                    ),
                    "requested_local_slice": (
                        None
                        if self.requested_local_slice is None
                        else round(self.requested_local_slice, 12)
                    ),
                }
            )
        return rv

    def __repr__(self):
        return f"PipelinePlacement({self.candidate_id})"


class BitPlacementRequest:
    """A provisional raster site used only while choosing a stage budget.

    A raw bit-splittable leaf does not honor an arbitrary fractional slice:
    its VHDL generator balances the *final count* of selected splits into
    equal-width chunks.  Consequently a raster crossing cannot truthfully be
    called a physical placement until all requests for that leaf are known.
    PLAN_PIPELINE_PLACEMENTS materializes these requests into ordinal/count-
    aware :class:`PipelinePlacement` objects before returning to lowering.
    """

    kind = PipelinePlacement.BIT_INTERNAL

    def __init__(
        self,
        inst_path,
        func_name,
        axis_unit,
        axis_position,
        requested_local_slice,
        bit_width,
        leaf_axis_start,
        leaf_axis_end,
        registered_bits=None,
        hierarchy_depth=0,
        span_units=0.0,
        coherent_boundary=False,
        ancestor_funcs=None,
        fixed=False,
        source="planner",
    ):
        self.inst_path = inst_path
        self.func_name = func_name
        self.axis_unit = int(axis_unit)
        self.axis_position = float(axis_position)
        self.local_slice = None
        self.requested_local_slice = float(requested_local_slice)
        self.bit_width = None if bit_width is None else int(bit_width)
        self.leaf_axis_start = float(leaf_axis_start)
        self.leaf_axis_end = float(leaf_axis_end)
        self.registered_bits = registered_bits
        self.hierarchy_depth = int(hierarchy_depth)
        self.span_units = float(span_units)
        self.coherent_boundary = bool(coherent_boundary)
        self.ancestor_funcs = tuple(sorted(ancestor_funcs or ()))
        self.fixed = bool(fixed)
        self.source = source

    @property
    def is_physical(self):
        return False

    @property
    def candidate_id(self):
        return (
            f"bit_internal_request:{self.inst_path}"
            f"@{self.requested_local_slice:.15g}"
        )

    def copy_with(self, fixed=None, source=None):
        rv = copy.copy(self)
        if fixed is not None:
            rv.fixed = bool(fixed)
        if source is not None:
            rv.source = source
        return rv

    def to_dict(self):
        return {
            "candidate_id": self.candidate_id,
            "kind": self.kind,
            "placement_role": "planning_site",
            "physical": False,
            "instance_path": self.inst_path,
            "function": self.func_name,
            "requested_axis_unit": self.axis_unit,
            "requested_axis_position": round(self.axis_position, 12),
            "requested_local_slice": round(self.requested_local_slice, 12),
            "bit_width": self.bit_width,
            "registered_bits": self.registered_bits,
            "registered_bits_scope": "leaf_width_proxy",
            "hierarchy_depth": self.hierarchy_depth,
            "span_units": round(self.span_units, 6),
            "coherent_boundary": self.coherent_boundary,
            "ancestor_functions": list(self.ancestor_funcs),
            "fixed": self.fixed,
            "source": self.source,
        }

    def __repr__(self):
        return f"BitPlacementRequest({self.candidate_id})"


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
        # Candidate inventory. Operation outputs are concrete physical
        # placements. Bit-internal entries are explicitly provisional raster
        # requests: their physical equal-width boundaries depend on how many
        # requests ultimately target the same leaf.
        self.candidates = []
        self.candidates_by_unit = {}

    def add_candidate(self, placement):
        if not isinstance(placement, (PipelinePlacement, BitPlacementRequest)):
            raise TypeError(type(placement))
        self.candidates.append(placement)

    def _add_segment_candidates(self, seg, lo, hi, bits_cap_units):
        if hi <= lo or seg.kind in (Segment.ATOMIC, Segment.LOCKED):
            return
        depth = seg.inst_path.count(C_TO_LOGIC.SUBMODULE_MARKER) - (
            self.subtree_root_inst.count(C_TO_LOGIC.SUBMODULE_MARKER)
        )
        # Every sliceable operation has a deterministic output boundary.
        # For raw 1LL leaves this is the one useful side of the old two-edge
        # representation; the other side is normally the preceding
        # operation's output boundary (or an enclosing function's input).
        out_u = hi - 1
        self.add_candidate(
            PipelinePlacement(
                PipelinePlacement.INSTANCE_OUTPUT,
                seg.inst_path,
                seg.func_name,
                out_u,
                out_u + 0.5,
                hierarchy_depth=max(0, depth),
                span_units=max(0.0, seg.end - seg.start),
                coherent_boundary=False,
                ancestor_funcs=seg.ancestor_funcs,
            )
        )
        if seg.kind != Segment.SLICEABLE:
            return
        # Without a resolved leaf width there is no way to name or validate
        # the equal-width bit boundary RAW VHDL will emit. Keep the concrete
        # operation-output boundary above, but do not fabricate internal
        # physical candidates from an arbitrary fractional raster position.
        if seg.max_legal_units is None:
            return
        for u in range(lo, hi):
            if bits_cap_units is not None and u not in bits_cap_units:
                continue
            span = seg.end - seg.start
            if span <= 0.0:
                continue
            local_slice = ((u + 0.5) - seg.start) / span
            # It must describe logic on both sides.  Rounding at a segment's
            # raster edge can otherwise produce exactly 0/1, which is a
            # boundary register rather than a genuine bit-internal cut.
            local_slice = max(1.0e-12, min(1.0 - 1.0e-12, local_slice))
            self.add_candidate(
                BitPlacementRequest(
                    seg.inst_path,
                    seg.func_name,
                    u,
                    u + 0.5,
                    requested_local_slice=local_slice,
                    bit_width=seg.max_legal_units,
                    leaf_axis_start=seg.start,
                    leaf_axis_end=seg.end,
                    registered_bits=seg.max_legal_units,
                    hierarchy_depth=max(0, depth),
                    span_units=max(0.0, span),
                    coherent_boundary=False,
                    ancestor_funcs=seg.ancestor_funcs,
                )
            )

    def finalize(self, func_delay_scale):
        n = self.total_units
        self.legal = [False] * n
        covered = [False] * n
        locked_only = [True] * n
        self.blame = [None] * n
        # Zero while covered segments contribute their relative component
        # weights.  Starting at 1.0 would clamp every normal comb/full ratio
        # (<1) back to 1 and make the experiment a no-op.
        planner_scale = [0.0] * n
        feedback_scale = [1.0] * n
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
                # Reserve one of the width-derived legal positions for the
                # operation-output boundary added below.  It is a useful
                # physical boundary, but must not silently increase the
                # leaf's total useful cut capacity beyond the existing
                # width-1 model (except a 1-bit op, which has no genuine
                # interior position but still has a legal output boundary).
                cap = max(0, seg.max_legal_units - 2)
                span = hi - lo
                bits_cap_units = set()
                for k in range(1, cap + 1):
                    u = lo + int(round(k * span / float(cap + 1))) - 1
                    bits_cap_units.add(max(lo, min(hi - 1, u)))
            self._add_segment_candidates(seg, lo, hi, bits_cap_units)
            seg_scale = 1.0
            for f in seg.ancestor_funcs:
                if f in func_delay_scale:
                    seg_scale = max(seg_scale, func_delay_scale[f])
            for u in range(lo, hi):
                covered[u] = True
                if seg.kind != Segment.LOCKED:
                    locked_only[u] = False
                if seg.kind == Segment.SLICEABLE:
                    # Legal positions are finalized from concrete candidates
                    # below.  Keep only the atomic-floor attribution here.
                    pass
                elif seg.kind == Segment.SLICEABLE_1LL:
                    # The whole operation remains atomic; only its output
                    # boundary is exposed as a typed position.
                    if u != hi - 1 and self.blame[u] is None:
                        self.blame[u] = seg
                elif seg.kind == Segment.ATOMIC and self.blame[u] is None:
                    self.blame[u] = seg
                planner_scale[u] = max(planner_scale[u], seg.planner_scale)
                feedback_scale[u] = max(feedback_scale[u], seg_scale)
        # Deduplicate positions added both as hierarchical child boundaries
        # and leaf-segment boundaries, then make legality derive from what the
        # typed lowering can actually materialize.
        by_id = {}
        for candidate in self.candidates:
            if 0 <= candidate.axis_unit < n:
                old = by_id.get(candidate.candidate_id)
                if old is None or candidate.coherent_boundary:
                    by_id[candidate.candidate_id] = candidate
        self.candidates = sorted(
            by_id.values(), key=lambda p: (p.axis_unit, p.candidate_id)
        )
        # A candidate is only a real stage boundary if NOTHING uncuttable
        # straddles its position. Segments on the axis are not a serial
        # chain: parallel branches overlap (the divider's UNARY_OP_NOT reads
        # BIN_OP_MINUS's output and feeds q_out, so it runs alongside the MUX
        # that feeds remainder, not after it). Registering the NOT's output
        # therefore lands strictly INSIDE the parallel MUX's atomic span -
        # the NOT branch gets a register while the MUX path crosses the same
        # depth uncut, so no pipeline stage is actually created. Left
        # unchecked this silently inflates the cut count without deepening
        # the pipeline: the real divider planned 48 cuts and built 32 slices,
        # 16 of them wasted on NOT outputs. Compare exact positions, not
        # units - a preceding operation's output boundary rounds into the
        # same unit as the next segment's start and must stay legal.
        # (start, end, boundary_unit). A blocker never blocks a candidate
        # sitting at its OWN end boundary: that candidate is this operation's
        # output register (its own, or an enclosing function's whose last
        # child it is), not a cut through its middle. Keyed on the rounded
        # end unit rather than instance paths so it holds regardless of how
        # a segment's span rounds onto the raster - a 1LL segment [lo, hi)
        # places its own output boundary at hi - 0.5, i.e. inside itself.
        blockers = sorted(
            (
                seg.start,
                seg.end,
                min(n, int(math.ceil(seg.end))) - 1,
            )
            for seg in self.segments
            if seg.kind in (Segment.ATOMIC, Segment.SLICEABLE_1LL)
            and seg.end > seg.start
        )
        blocker_starts = [s for s, _, _ in blockers]
        max_end = []
        running = float("-inf")
        for _, e, _u in blockers:
            running = max(running, e)
            max_end.append(running)

        def _straddled(candidate):
            position = candidate.axis_position
            i = bisect.bisect_left(blocker_starts, position)
            for j in range(i - 1, -1, -1):
                if max_end[j] <= position:
                    break  # nothing starting this early reaches past it
                start, end, boundary_unit = blockers[j]
                # One raster unit of slack at the near edge. A candidate's
                # nominal position is its unit + 0.5, while the boundary it
                # stands for is the segment's exact .end - so an operation
                # output whose true edge is where this blocker BEGINS can
                # round to a hair inside it. Without the slack that deletes
                # a legitimate boundary (both branches start there, so a
                # register at that depth cuts every path): on the divider it
                # removed half of the BIN_OP_MINUS outputs and left the
                # planner nothing to use between whole iterations.
                if (
                    start + 1.0 < position < end
                    and candidate.axis_unit != boundary_unit
                ):
                    return True
            return False

        self.candidates = [c for c in self.candidates if not _straddled(c)]
        self.candidates_by_unit = {}
        for candidate in self.candidates:
            self.candidates_by_unit.setdefault(candidate.axis_unit, []).append(
                candidate
            )
            self.legal[candidate.axis_unit] = True
        planner_weight = [0.0] * n
        for u in range(n):
            if covered[u] and locked_only[u]:
                # Internally pipelined already - costs no stage budget
                planner_weight[u] = 0.0
            else:
                planner_weight[u] = planner_scale[u] if covered[u] else 1.0
        # Normalize planner-only relative geometry back to the old measured
        # frontier total.  This explicitly avoids the failed fixed-overhead
        # behavior: component timing can move cuts, but cannot by itself ask
        # for more stages.  Learned synthesis feedback is applied afterward
        # and therefore retains its intended ability to densify a hotspot.
        old_total = sum(1.0 for w in planner_weight if w > 0.0)
        planner_total = sum(planner_weight)
        planner_norm = old_total / planner_total if planner_total > 0.0 else 1.0
        self.weight = [
            planner_weight[u] * planner_norm * feedback_scale[u]
            for u in range(n)
        ]
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

    def output_register_bits(logic):
        bits = 0
        try:
            for output in logic.outputs:
                bits += VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM(
                    logic.wire_to_c_type[output], parser_state
                )
        except Exception:
            return None
        return bits

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

            # A child output is a concrete legal stage boundary in its own
            # right.  Record this before deciding whether the child is a raw
            # leaf or a hierarchy to recurse through: helper-function
            # boundaries (one whole divider step, for example) are exactly
            # what disappeared when the old fractional cut was recursively
            # pushed into all of the helper's descendants.  Flat user code is
            # covered too because each elaborated operator is itself a child.
            if (
                descend_ok
                and not child_timing_params.params_are_fixed
                and sub_logic.CAN_HAVE_ADDED_LATENCY(parser_state)
                and len(sub_logic.outputs) > 0
            ):
                axis_u = min(
                    landscape.total_units - 1,
                    max(0, int(math.ceil(e)) - 1),
                )
                depth = child_inst.count(C_TO_LOGIC.SUBMODULE_MARKER) - (
                    subtree_root_inst.count(C_TO_LOGIC.SUBMODULE_MARKER)
                )
                landscape.add_candidate(
                    PipelinePlacement(
                        PipelinePlacement.INSTANCE_OUTPUT,
                        child_inst,
                        sub_logic.func_name,
                        axis_u,
                        axis_u + 0.5,
                        registered_bits=output_register_bits(sub_logic),
                        hierarchy_depth=max(0, depth),
                        span_units=max(0.0, e - s),
                        coherent_boundary=len(sub_logic.submodule_instances) > 0,
                        ancestor_funcs=child_ancestors,
                    )
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
                        if split_kind
                        in (
                            RAW_VHDL.SPLIT_KIND_1LL,
                            RAW_VHDL.SPLIT_KIND_MUX_BITS,
                        )
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
            planner_delay = SYN.GET_PLANNER_DELAY(sub_logic)
            if (
                planner_delay is not None
                and planner_delay > 0
                and sub_logic.delay is not None
                and sub_logic.delay > 0
            ):
                seg.planner_scale = planner_delay / float(sub_logic.delay)
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
    # A coherent hierarchical operation output is an even stronger physical
    # boundary than the leaf-run heuristic above: it registers the helper as
    # a unit instead of projecting a diagonal fractional cut through all of
    # its descendants.  This is what makes repeated one-step helpers and
    # ordinary flat operation chains use the same typed mechanism.
    coherent_outputs = [
        p
        for p in landscape.candidates
        if p.kind == PipelinePlacement.INSTANCE_OUTPUT and p.coherent_boundary
    ]
    for p in coherent_outputs:
        units.add(p.axis_unit)
    if coherent_outputs:
        # Also retain direct sibling operations immediately before/after each
        # coherent helper region (setup/result muxes are a common shape).
        # Grouping by the helper's PARENT instance is important: an outer
        # wrapper is often shallower than both the repeated helpers and their
        # setup op.  Comparing everything with one global minimum hierarchy
        # depth would then hide precisely that setup boundary.  Do not admit
        # primitive boundaries *inside* a coherent helper; those would
        # reintroduce the diagonal/mid-helper choices this representation is
        # designed to avoid.
        outputs = [
            p
            for p in landscape.candidates
            if p.kind == PipelinePlacement.INSTANCE_OUTPUT
        ]
        marker = C_TO_LOGIC.SUBMODULE_MARKER

        def parent_inst(placement):
            return placement.inst_path.rsplit(marker, 1)[0]

        coherent_spans_by_parent = {}
        for p in coherent_outputs:
            coherent_spans_by_parent.setdefault(parent_inst(p), []).append(
                (p.axis_position - p.span_units, p.axis_position)
            )
        for p in outputs:
            coherent_spans = coherent_spans_by_parent.get(parent_inst(p))
            if coherent_spans is None:
                continue
            inside_helper = any(lo < p.axis_position <= hi for lo, hi in coherent_spans)
            if not inside_helper:
                units.add(p.axis_unit)
    # A completely flat function has no hierarchical helper boundary.  Its
    # shallowest operation outputs are the coherent boundaries available.
    else:
        outputs = [
            p
            for p in landscape.candidates
            if p.kind == PipelinePlacement.INSTANCE_OUTPUT
        ]
        if outputs:
            shallowest = min(p.hierarchy_depth for p in outputs)
            units.update(p.axis_unit for p in outputs if p.hierarchy_depth == shallowest)
    if n - 1 >= 0 and landscape.legal[n - 1]:
        units.add(n - 1)
    return sorted(units)


def _OP_OUTPUT_UNITS(landscape):
    """Units carrying a real operation-output boundary (an INSTANCE_OUTPUT
    candidate) as opposed to only a provisional bit-internal raster site.

    The distinction is physical, not cosmetic. A BitPlacementRequest is later
    snapped by MATERIALIZE_BIT_PLACEMENT_REQUESTS to an EQUAL-WIDTH bit
    boundary of its leaf, so a request landing one delay unit past an
    operation's edge does not become a register on that edge - it becomes a
    split through the MIDDLE of the next operation. See PLAN_CUTS pass 3.
    """
    return {
        unit
        for unit, candidates in landscape.candidates_by_unit.items()
        if any(
            getattr(c, "kind", None) == PipelinePlacement.INSTANCE_OUTPUT
            for c in candidates
        )
    }


def _GREEDY_CUTS(landscape, budget, required_units, op_output_units=None):
    """Pass 1 of PLAN_CUTS: the FEWEST cuts that keep every stage within
    ``budget``.

    Walk the delay axis and cut at the FURTHEST legal unit whose stage still
    fits the budget; overshoot only when no legal unit fits at all (a genuine
    atomic run - that stage sets the floor, exactly as before). This is the
    classic exchange-argument greedy and is optimal for the cut COUNT:
    starting a stage later can never make the remainder easier, so there is
    nothing to gain from cutting earlier than necessary and no lookahead is
    needed.
    """
    n = landscape.total_units
    legal = landscape.legal
    weight = landscape.weight
    cuts = []
    start = 0
    while start < n:
        acc = 0.0
        best = None
        best_op_output = None
        u = start
        while u < n:
            acc += weight[u]
            if u in required_units:
                # A fixed physical placement ends the stage regardless of
                # whether the budget has filled yet.
                best = u
                best_op_output = u
                break
            if legal[u]:
                if acc <= budget:
                    best = u  # fits - remember it and keep looking further
                    if op_output_units is not None and u in op_output_units:
                        best_op_output = u
                elif best is None:
                    best = u  # nothing fits: forced overshoot (the floor)
                    break
                else:
                    break
            elif acc > budget and best is not None:
                break
            u += 1
        chosen = best if best_op_output is None else best_op_output
        if chosen is None:
            break  # no legal position remains anywhere ahead
        cuts.append(chosen)
        start = chosen + 1
    return cuts


def PLAN_CUTS(landscape, budget_units, required_units=None):
    """Place cuts along the landscape, in three passes.

    Pass 1 (``_GREEDY_CUTS``) finds the fewest cuts K that keep every stage
    within the budget. Pass 2 then binary-searches the SMALLEST budget W that
    still needs only K cuts, and returns pass 1's plan at W - "use no more
    registers than the goal requires, then make the stages as tight as that
    number of registers allows, for free". Cut count is monotone
    non-increasing in W, so the predicate is monotone and the search is valid;
    ``hi`` only moves down when the predicate holds, so the returned plan
    always satisfies it.

    Pass 3 prefers an operation-output position when doing so preserves both
    the tightened budget and cut count.

    Pass 2 is not polish, it is what makes pass 1 safe to use. Pass 1 alone
    minimizes the cut COUNT but not the worst stage AT that count, and the
    difference is real hardware: on the radix-2 divider at a 7.4 ns budget the
    furthest fitting position sits ~0.23 ns PAST the iteration boundary (a
    legal bit-internal site 2 bits into a 34-bit subtractor), so pass 1 alone
    would keep the same 32 cuts but place them as ragged mid-operation
    register banks instead of on the clean MUX boundary. Pass 2 recovers the
    boundary by itself, with no notion of "boundary" in it.

    This replaced a walk that cut when the budget filled and then, via a
    ``PLAN_CUTS_BOUNDARY_SNAP_FRAC`` tolerance, allowed itself to accumulate
    up to 0.85 of an EXTRA budget in order to reach a ``_RUN_BOUNDARY_UNITS``
    position. That tolerance existed for a real reason - without any snap, a
    low cut count left a SLICEABLE_1LL segment (a MUX between two repeated
    loop iterations) with no cut near it and merged one iteration's tail, the
    MUX, and the next iteration's head into a single ~11 ns stage. But being
    a fraction of the budget, it scaled with the budget, and in the regime
    where the budget is SMALLER than one repeated unit it did the opposite of
    its job: on that divider a 4.7 ns budget (214 MHz) snapped forward to the
    7.119 ns iteration boundary - a 51% overrun - and reported 33 cuts where
    64 were needed. Every target from 167 to 250 MHz produced the identical
    33-cut plan. The rule here cannot do that: a stage is never allowed to
    exceed the budget when a legal position inside it would have fit, so the
    ~11 ns merge is forbidden outright rather than by tolerance, and the
    budget genuinely maps onto a cut count again.
    """
    n = landscape.total_units
    if n <= 0:
        return []
    required_units = set(required_units or ())
    for u in required_units:
        if u < 0 or u >= n or not landscape.legal[u]:
            raise ValueError(
                f"Required cut unit {u} is not a legal typed placement in "
                f"{landscape.subtree_root_inst}"
            )
    budget = max(budget_units, 0.5)

    cuts = _GREEDY_CUTS(landscape, budget, required_units)
    if len(cuts) > 0:
        # Pass 2: tighten the budget as far as it goes at no extra cost in
        # cuts. 50 bisections resolves W far finer than one delay unit.
        target_count = len(cuts)
        lo = 0.0
        hi = budget
        for _ in range(50):
            mid = 0.5 * (lo + hi)
            if mid <= lo or mid >= hi:
                break
            tightened = _GREEDY_CUTS(landscape, mid, required_units)
            if len(tightened) <= target_count:
                hi = mid
                cuts = tightened
            else:
                lo = mid
        # Pass 3: among positions that fit the TIGHTENED budget, prefer a
        # real operation-output boundary over a provisional bit-internal
        # raster site. Both can be equally good on the worst-stage metric
        # while being completely different hardware: on the divider at a
        # 7.4 ns goal, pass 2's furthest-fitting choice sat ONE delay unit
        # past each MUX boundary, and a bit-internal request there does not
        # become a register on the MUX edge - MATERIALIZE_BIT_PLACEMENT_
        # REQUESTS snaps it to the equal-width MIDDLE of the following
        # 34-bit subtractor instead. Guarded by the cut count so it can
        # never trade registers for tidiness: an op boundary is taken only
        # when preferring them costs no extra cuts, which is what keeps the
        # intermediate plans (the whole point of the first two passes) from
        # collapsing back onto operation boundaries.
        preferred = _GREEDY_CUTS(
            landscape,
            hi,
            required_units,
            op_output_units=_OP_OUTPUT_UNITS(landscape),
        )
        if 0 < len(preferred) <= target_count:
            cuts = preferred

    # Drop a trailing cut that leaves a nearly empty final stage
    if (
        len(cuts) > 0
        and cuts[-1] >= n - 1
        and cuts[-1] not in required_units
    ):
        cuts = cuts[:-1]
    return cuts


def CUTS_TO_SLICES(cuts, landscape):
    # Center each cut within its delay unit so SLICE_DOWN's floor() recovers
    # the intended offset without float boundary ambiguity
    return [(u + 0.5) / float(landscape.total_units) for u in cuts]


def _PLACEMENT_RANK_KEY(placement):
    """Deterministic tie-break among physical candidates at one axis point.

    PLAN_CUTS has already minimized predicted worst-stage delay by choosing
    the axis unit.  At that unit prefer a coherent/high-level operation
    boundary before consulting the *local* output width.  Local width is not
    the materialized register cost: a one-bit leaf boundary can force a huge
    bank of alignment registers in its parent, while one helper-output bank
    keeps all of those values coherent.  Until the graph-wide live-bit cost is
    available, treating local width as the primary score recreates exactly
    that pathology.  It remains a useful tie-break among equally coherent
    candidates; unknown widths sort last.
    """
    bits = placement.registered_bits
    if bits is None:
        bits = float("inf")
    return (
        0 if placement.coherent_boundary else 1,
        placement.hierarchy_depth,
        -placement.span_units,
        bits,
        0 if placement.kind == PipelinePlacement.INSTANCE_OUTPUT else 1,
        placement.candidate_id,
    )


def MATERIALIZE_BIT_PLACEMENT_REQUESTS(
    placements, landscape, exact_requested=False
):
    """Convert provisional bit raster sites to emitted equal-width boundaries.

    RAW VHDL chooses bit chunks from the final number of slices in a leaf, not
    from the fractional values stored in ``TimingParams``. Grouping first is
    therefore essential: for K selected sites on a W-bit leaf, the only
    truthful physical placements are ordinals 1..K of the K+1 equal-width
    chunks. The requested raster coordinates remain diagnostic metadata.
    """
    physical = []
    requests_by_inst = {}
    for placement in placements:
        if isinstance(placement, BitPlacementRequest):
            requests_by_inst.setdefault(placement.inst_path, []).append(placement)
        elif isinstance(placement, PipelinePlacement):
            physical.append(placement)
        else:
            raise TypeError(type(placement))

    for inst_path in sorted(requests_by_inst):
        requests = sorted(
            requests_by_inst[inst_path],
            key=lambda p: (p.axis_position, p.candidate_id),
        )
        unique = []
        seen_ids = set()
        for request in requests:
            if request.candidate_id not in seen_ids:
                unique.append(request)
                seen_ids.add(request.candidate_id)
        requests = unique
        count = len(requests)
        widths = {request.bit_width for request in requests}
        if None in widths or len(widths) != 1:
            raise ValueError(
                f"Cannot materialize bit placements for {inst_path}: "
                f"inconsistent/unresolved widths {sorted(str(w) for w in widths)}"
            )
        width = widths.pop()
        if count >= width:
            raise ValueError(
                f"Cannot materialize {count} internal bit placements in "
                f"{width}-bit leaf {inst_path}; at least one bit of logic is "
                "required in every emitted chunk"
            )
        starts = {request.leaf_axis_start for request in requests}
        ends = {request.leaf_axis_end for request in requests}
        if len(starts) != 1 or len(ends) != 1:
            raise ValueError(
                f"Cannot materialize bit placements for {inst_path}: "
                "requests disagree on the leaf's delay-axis span"
            )
        leaf_start = starts.pop()
        leaf_end = ends.pop()
        if exact_requested:
            # Honor the planner's requested physical coordinates.  Clamp in
            # sorted order so every chunk retains at least one bit even when
            # two nearby raster requests round to the same integer boundary.
            boundaries = []
            for index, request in enumerate(requests):
                remaining = count - index - 1
                boundary = int(round(request.requested_local_slice * width))
                minimum = 1 if not boundaries else boundaries[-1] + 1
                maximum = width - remaining - 1
                boundaries.append(max(minimum, min(maximum, boundary)))
            boundary_mode = "exact"
        else:
            boundaries = RAW_VHDL.GET_EQUAL_WIDTH_BIT_BOUNDARIES(width, count)
            boundary_mode = "equal_width"
        boundary_group = tuple(boundaries)
        for ordinal, (request, boundary) in enumerate(
            zip(requests, boundaries), start=1
        ):
            local_slice = boundary / float(width)
            axis_position = leaf_start + local_slice * (leaf_end - leaf_start)
            axis_unit = int(math.ceil(axis_position)) - 1
            if not 0 <= axis_unit < landscape.total_units:
                raise ValueError(
                    f"Physical bit boundary for {inst_path} fell outside "
                    f"landscape: unit {axis_unit} of {landscape.total_units}"
                )
            physical.append(
                PipelinePlacement(
                    PipelinePlacement.BIT_INTERNAL,
                    request.inst_path,
                    request.func_name,
                    axis_unit,
                    axis_position,
                    local_slice=local_slice,
                    registered_bits=(
                        width
                        if request.registered_bits is None
                        else request.registered_bits
                    ),
                    hierarchy_depth=request.hierarchy_depth,
                    span_units=request.span_units,
                    coherent_boundary=request.coherent_boundary,
                    ancestor_funcs=request.ancestor_funcs,
                    fixed=request.fixed,
                    source=request.source,
                    bit_width=width,
                    bit_split_ordinal=ordinal,
                    bit_split_count=count,
                    bit_boundary=boundary,
                    bit_boundary_mode=boundary_mode,
                    bit_boundaries=(
                        boundary_group if exact_requested else None
                    ),
                    leaf_axis_start=leaf_start,
                    leaf_axis_end=leaf_end,
                    requested_axis_unit=request.axis_unit,
                    requested_axis_position=request.axis_position,
                    requested_local_slice=request.requested_local_slice,
                )
            )
    return sorted(physical, key=lambda p: (p.axis_position, p.candidate_id))


def _LANDSCAPE_WITH_EQUAL_WIDTH_BIT_SITES(landscape, counts_by_inst):
    """Landscape view whose bit sites are the boundaries RAW VHDL will emit.

    The planner's raster bit sites are provisional fictions: a leaf with K
    selected cuts emits ordinals 1..K of K+1 EQUAL-WIDTH chunks, wherever the
    requests actually were. So a plan costed on raster positions can be a
    different pipeline once lowered - on the divider a 50-cut plan costed at
    5.20ns had 20 of its 31 bit cuts relocated (unit 142 -> 161, ~1.9ns) and
    realized 7.20ns, blowing the budget it was chosen to meet. Every
    intermediate depth between "one cut per loop iteration" and "two" died
    that way, which is why the fmax goal could only reach 32 or 64 cuts.

    Given how many cuts the previous round put in each leaf, this rebuilds
    that leaf's sites AT the equal-width boundaries for that count, so the
    next round plans against positions that survive lowering unchanged.
    Leaves the caller iterates to a fixed point; two or three rounds is
    plenty because the count per leaf is almost always 1 or 2.
    """
    view = copy.copy(landscape)
    kept = []
    for candidate in landscape.candidates:
        if not isinstance(candidate, BitPlacementRequest):
            kept.append(candidate)
    for inst_path, count in sorted(counts_by_inst.items()):
        template = next(
            (
                c
                for c in landscape.candidates
                if isinstance(c, BitPlacementRequest)
                and c.inst_path == inst_path
            ),
            None,
        )
        if template is None or count <= 0 or count >= template.bit_width:
            continue
        span = template.leaf_axis_end - template.leaf_axis_start
        if span <= 0.0:
            continue
        for boundary in RAW_VHDL.GET_EQUAL_WIDTH_BIT_BOUNDARIES(
            template.bit_width, count
        ):
            local_slice = boundary / float(template.bit_width)
            position = template.leaf_axis_start + local_slice * span
            unit = int(math.ceil(position)) - 1
            if not 0 <= unit < landscape.total_units:
                continue
            kept.append(
                BitPlacementRequest(
                    template.inst_path,
                    template.func_name,
                    unit,
                    position,
                    requested_local_slice=local_slice,
                    bit_width=template.bit_width,
                    leaf_axis_start=template.leaf_axis_start,
                    leaf_axis_end=template.leaf_axis_end,
                    registered_bits=template.registered_bits,
                    hierarchy_depth=template.hierarchy_depth,
                    span_units=template.span_units,
                    coherent_boundary=template.coherent_boundary,
                    ancestor_funcs=template.ancestor_funcs,
                )
            )
    view.candidates = sorted(
        {c.candidate_id: c for c in kept}.values(),
        key=lambda c: (c.axis_unit, c.candidate_id),
    )
    view.legal = [False] * landscape.total_units
    view.candidates_by_unit = {}
    for candidate in view.candidates:
        view.candidates_by_unit.setdefault(candidate.axis_unit, []).append(
            candidate
        )
        view.legal[candidate.axis_unit] = True
    return view


def _PLAN_RANK(cuts, landscape, budget_ns):
    """Sort key for choosing between two lowered plans. Lower is better.

    Meeting the goal is the whole point of a budget, so a plan that meets it
    is never beaten by one that is merely faster: among plans that meet it,
    the fewest cuts wins (registers are cost, and the extra speed was not
    asked for). Only when NOTHING meets the budget - the goal sits below the
    design's floor - does raw speed decide, and cut count breaks that tie.

    Ranking on worst stage first instead is what collapsed the divider's
    entire 32..64 cut range onto 64: a 48-cut plan meeting a 190 MHz goal at
    5.19ns kept losing to a 64-cut plan at 3.85ns.
    """
    worst = PREDICTED_STAGE_NS(cuts, landscape)
    meets = worst <= budget_ns + 1e-9
    if meets:
        return (0, len(cuts), worst)
    return (1, worst, len(cuts))


def _LANDSCAPE_WITHOUT_BIT_SITES(landscape):
    """Shallow view of ``landscape`` offering only real operation-output
    boundaries - no provisional bit-internal raster sites.

    Used to sanity-check a bit-splitting plan against the simpler plan that
    uses only physical operation boundaries. See PLAN_PIPELINE_PLACEMENTS.
    """
    view = copy.copy(landscape)
    view.candidates = [
        c
        for c in landscape.candidates
        if getattr(c, "kind", None) == PipelinePlacement.INSTANCE_OUTPUT
    ]
    view.legal = [False] * landscape.total_units
    view.candidates_by_unit = {}
    for candidate in view.candidates:
        view.candidates_by_unit.setdefault(candidate.axis_unit, []).append(
            candidate
        )
        view.legal[candidate.axis_unit] = True
    return view


def PLAN_PIPELINE_PLACEMENTS(landscape, budget_units, fixed_placements=None):
    """Plan concrete physical placements while retaining PLAN_CUTS's budget.

    ``fixed_placements`` is used only by the internal experiment hook.  Their
    axis units become required stage boundaries; the budget walk fills any
    remaining long intervals with normal typed candidates.  Multiple fixed
    placements at one unit are all retained (the axis has one logical cut,
    while the graph may need more than one physical register bank there).

    Returns ``(cuts, placements)``.  Keeping cuts explicit preserves the
    existing prediction/history machinery while callers lower placements.
    """
    fixed_placements = list(fixed_placements or ())
    fixed_by_unit = {}
    for placement in fixed_placements:
        candidates = {
            p.candidate_id: p
            for p in landscape.candidates_by_unit.get(placement.axis_unit, ())
        }
        if placement.candidate_id not in candidates:
            raise ValueError(
                f"Fixed pipeline placement is not legal in this landscape: "
                f"{placement.candidate_id}"
            )
        fixed_by_unit.setdefault(placement.axis_unit, []).append(placement)

    def _lower_at(view, budget, exact_requested=False):
        cuts = PLAN_CUTS(
            view,
            budget,
            required_units=set(fixed_by_unit),
        )
        placements = []
        used_ids = set()
        for unit in cuts:
            if unit in fixed_by_unit:
                selected = sorted(
                    fixed_by_unit[unit], key=lambda p: p.candidate_id
                )
            else:
                candidates = [
                    p
                    for p in view.candidates_by_unit.get(unit, ())
                    if p.candidate_id not in used_ids
                ]
                if not candidates:
                    raise RuntimeError(
                        f"PLAN_CUTS chose legal unit {unit} in "
                        f"{view.subtree_root_inst}, but no typed physical "
                        "candidate exists there"
                    )
                selected = [min(candidates, key=_PLACEMENT_RANK_KEY)]
            for placement in selected:
                if placement.candidate_id in used_ids:
                    continue
                used_ids.add(placement.candidate_id)
                placements.append(placement)
        placements = MATERIALIZE_BIT_PLACEMENT_REQUESTS(
            placements, view, exact_requested=exact_requested
        )
        # Bit boundaries can move from their provisional raster crossing to
        # the actual equal-width bit boundary. Return/report the physical
        # axis units, never the nominal request units PLAN_CUTS used to
        # choose the count.
        cuts = sorted(set(placement.axis_unit for placement in placements))
        return cuts, placements

    def _lower(view):
        return _lower_at(view, budget_units)

    if os.environ.get("PIPELINEC_INTERNAL_EXACT_REQUESTED_BITS") == "1":
        return _lower_at(
            landscape, budget_units, exact_requested=True
        )

    cuts, placements = _lower(landscape)

    # Judge the plan on where its registers ACTUALLY land, not where they
    # were requested. MATERIALIZE_BIT_PLACEMENT_REQUESTS emits EQUAL-WIDTH
    # bit boundaries chosen from how many requests hit a leaf, so a lone
    # request anywhere in a 34-bit operation becomes a split at bit 17 - the
    # real divider asked for cuts at 3.9%, 11.8% and 51.3% of its subtractors
    # and got the midpoint for all three. The stage structure the planner
    # costed then does not exist, and the extra registers can buy nothing: at
    # a 190 MHz goal that produced 48 cuts whose realized worst stage was
    # 7.00ns - identical to the 32-cut boundary-only plan, for 16 more
    # register banks. So also lower the plan that uses only real operation
    # boundaries (whose positions cannot move) and keep whichever is better
    # once realized. Bit splitting is kept whenever it genuinely pays, and
    # dropped when it only looked like it would on the raster.
    #
    # "Better" is ranked by _PLAN_RANK: MEET THE BUDGET FIRST, then use the
    # fewest cuts. Ranking on worst stage first (an earlier version of this)
    # is wrong and silently destroys every intermediate pipeline depth: on
    # the divider a 190 MHz goal has a real 48-cut plan at 5.19ns (cut at
    # MINUS's output, the next MINUS's midpoint, then that MUX's output - 3
    # cuts per 2 iterations), which comfortably meets the goal, but the
    # boundary-only plan realizes 3.85ns with 64 cuts and won on "lower worst
    # stage" - 33% more registers to beat a target that was already met. That
    # collapsed the whole 32..64 range onto 64 and left the fmax goal unable
    # to ask for anything in between.
    budget_ns = budget_units * landscape.units_to_ns

    def _consider(candidate_cuts, candidate_placements):
        nonlocal cuts, placements
        if len(candidate_cuts) == 0:
            return False
        if _PLAN_RANK(candidate_cuts, landscape, budget_ns) < _PLAN_RANK(
            cuts, landscape, budget_ns
        ):
            cuts, placements = candidate_cuts, candidate_placements
            return True
        return False

    # Round 2+: re-plan against the equal-width boundaries this plan's own
    # per-leaf cut counts imply, so the positions survive lowering unchanged
    # instead of being relocated out from under the budget that chose them.
    # Iterated to a fixed point (the per-leaf count is almost always 1 or 2,
    # so this settles immediately); every round is ranked, so a round can
    # only ever replace the incumbent with a strictly better plan.
    seen_counts = []
    for _ in range(3):
        counts_by_inst = {}
        for placement in placements:
            if getattr(placement, "kind", None) == PipelinePlacement.BIT_INTERNAL:
                counts_by_inst[placement.inst_path] = (
                    counts_by_inst.get(placement.inst_path, 0) + 1
                )
        if not counts_by_inst or counts_by_inst in seen_counts:
            break
        seen_counts.append(dict(counts_by_inst))
        _consider(
            *_lower(
                _LANDSCAPE_WITH_EQUAL_WIDTH_BIT_SITES(landscape, counts_by_inst)
            )
        )

    # A restriction derived from one plan only explores that plan's own
    # family, which leaves the result depending on where the first raster
    # plan happened to land - two nearby goals could pick different families
    # and the LOOSER goal end up with MORE registers (92 MHz took 26 cuts
    # where 96 MHz's 23-cut plan met it too). The families that matter are
    # few and structural ("split every wide leaf once", "twice"), so probe
    # them directly and let the rank decide.
    bit_insts = {
        c.inst_path
        for c in landscape.candidates
        if isinstance(c, BitPlacementRequest)
    }
    if bit_insts:
        for uniform_count in (1, 2):
            _consider(
                *_lower(
                    _LANDSCAPE_WITH_EQUAL_WIDTH_BIT_SITES(
                        landscape,
                        {inst: uniform_count for inst in bit_insts},
                    )
                )
            )

    if any(
        getattr(p, "kind", None) == PipelinePlacement.BIT_INTERNAL
        for p in placements
    ):
        _consider(*_lower(_LANDSCAPE_WITHOUT_BIT_SITES(landscape)))

    # Finally, never keep a register the plan did not earn. PLAN_CUTS'
    # pass 2 makes the stages as tight as a given cut COUNT allows; this is
    # its mirror, on realized positions: re-plan at the worst stage actually
    # achieved and keep the result if it reaches the same speed with fewer
    # cuts. The budget the caller asked for can be unreachable (the goal sits
    # below the design's floor), and then a tighter budget only buys extra
    # register banks that shorten nothing - the reported bug's 33rd cut,
    # which measured the identical 169.57 MHz the 32-cut plan already had.
    for _ in range(4):
        realized = PREDICTED_STAGE_NS(cuts, landscape)
        if realized <= 0.0 or len(cuts) == 0:
            break
        # Epsilon: the relaxed budget is reconstructed by dividing a ns
        # value back into units, so the very stage weight it came from can
        # land a few ULPs above it and be rejected as not fitting.
        relaxed_cuts, relaxed_placements = _lower_at(
            landscape, (realized / landscape.units_to_ns) + 1e-6
        )
        if len(relaxed_cuts) == 0:
            break
        if _PLAN_RANK(relaxed_cuts, landscape, budget_ns) < _PLAN_RANK(
            cuts, landscape, budget_ns
        ):
            cuts, placements = relaxed_cuts, relaxed_placements
        else:
            break
    return cuts, placements


def BUILD_CHUNKED_MUX_REFINEMENT(placements, landscape, parser_state):
    """Replace selected packed-MUX output banks with bit-chunk banks.

    The replacement has the same local latency, but halves the load seen by
    each stage's select.  Also split the terminal packed MUX when it was the
    deliberately unregistered tail of the plan; this costs one additional
    slice and prevents the output-only tail from retaining the old full
    fanout.  Nothing here recognizes a design or function name beyond the
    generic raw-HDL MUX split kind.
    """
    placements = list(placements)
    segments = {segment.inst_path: segment for segment in landscape.segments}

    def is_chunkable_mux_output(placement):
        if not isinstance(placement, PipelinePlacement):
            return False
        if placement.kind != PipelinePlacement.INSTANCE_OUTPUT:
            return False
        logic = parser_state.LogicInstLookupTable.get(placement.inst_path)
        return (
            logic is not None
            and len(logic.submodule_instances) == 0
            and RAW_VHDL.GET_LEAF_SPLIT_KIND(logic)
            == RAW_VHDL.SPLIT_KIND_MUX_BITS
        )

    selected_mux_outputs = [p for p in placements if is_chunkable_mux_output(p)]
    mux_candidates = [
        p for p in landscape.candidates if is_chunkable_mux_output(p)
    ]
    if not selected_mux_outputs or not mux_candidates:
        return None
    targets = {p.inst_path: p for p in selected_mux_outputs}
    terminal = max(
        mux_candidates, key=lambda p: (p.axis_position, p.candidate_id)
    )
    targets.setdefault(terminal.inst_path, terminal)

    refined = [
        p
        for p in placements
        if not (
            is_chunkable_mux_output(p) and p.inst_path in targets
        )
    ]
    for inst_path, output in sorted(
        targets.items(), key=lambda item: item[1].axis_position
    ):
        logic = parser_state.LogicInstLookupTable[inst_path]
        width = RAW_VHDL.GET_LEAF_BIT_WIDTH(logic, parser_state)
        segment = segments.get(inst_path)
        if width is None or width < 2 or segment is None:
            return None
        boundary = int(round(width / 2.0))
        local_slice = boundary / float(width)
        axis_position = segment.start + local_slice * (
            segment.end - segment.start
        )
        refined.append(
            PipelinePlacement(
                PipelinePlacement.BIT_INTERNAL,
                inst_path,
                logic.func_name,
                int(math.ceil(axis_position)) - 1,
                axis_position,
                local_slice=local_slice,
                registered_bits=width,
                hierarchy_depth=output.hierarchy_depth,
                span_units=output.span_units,
                coherent_boundary=False,
                ancestor_funcs=output.ancestor_funcs,
                fixed=False,
                source="same_depth_mux_refinement",
                bit_width=width,
                bit_split_ordinal=1,
                bit_split_count=1,
                bit_boundary=boundary,
                bit_boundary_mode="exact",
                bit_boundaries=(boundary,),
                leaf_axis_start=segment.start,
                leaf_axis_end=segment.end,
            )
        )
    refined.sort(key=lambda p: (p.axis_position, p.candidate_id))
    old_ids = tuple(p.candidate_id for p in placements)
    new_ids = tuple(p.candidate_id for p in refined)
    if new_ids == old_ids:
        return None
    return sorted(set(p.axis_unit for p in refined)), refined


def PIPELINE_PLACEMENT_FINGERPRINT(placements_by_subtree, locks=None):
    """Return a deterministic identity for one realized physical schedule.

    Mini-sweep boundary banks are physical registers too.  They must be in
    the identity or a ``--continue``/in-process dedupe can mistake an
    output-only serial schedule for the historical both-I/O schedule.
    """
    fields = []
    for subtree_root, placements in sorted(placements_by_subtree.items()):
        fields.append(subtree_root)
        fields.extend(
            placement.candidate_id
            for placement in sorted(
                placements,
                key=lambda placement: (
                    placement.axis_position,
                    placement.candidate_id,
                ),
            )
        )
    if locks:
        fields.append("--mini-sweep-locks--")
        for inst_path, lock in sorted(locks.items()):
            fields.append(inst_path)
            fields.append(
                json.dumps(lock.to_dict(), sort_keys=True, separators=(",", ":"))
            )
    return hashlib.sha256("\n".join(fields).encode("utf-8")).hexdigest()


# Intentionally not a command-line/source interface.  The opt-in QoR harness
# uses this hook to pin known physical placements for controlled A/B builds.
INTERNAL_PLACEMENT_FILE_ENV = "PIPELINEC_INTERNAL_PLACEMENT_FILE"
INTERNAL_PLACEMENT_SCHEMA_VERSION = 1


def LOAD_INTERNAL_PLACEMENT_CONFIG(environ=None):
    environ = os.environ if environ is None else environ
    path = environ.get(INTERNAL_PLACEMENT_FILE_ENV)
    if not path:
        return None
    with open(path, "r") as f:
        config = json.load(f)
    if not isinstance(config, dict):
        raise ValueError(f"{INTERNAL_PLACEMENT_FILE_ENV} JSON must be an object")
    version = config.get("version")
    if version != INTERNAL_PLACEMENT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported internal placement schema version {version}; "
            f"expected {INTERNAL_PLACEMENT_SCHEMA_VERSION}"
        )
    mode = config.get("mode", "seed")
    if mode not in ("seed", "replace"):
        raise ValueError(f"Internal placement mode must be seed or replace: {mode}")
    selectors = config.get("selectors", [])
    exact = config.get("placements", [])
    exact_bit_groups = config.get("exact_bit_boundaries", [])
    if (
        not isinstance(selectors, list)
        or not isinstance(exact, list)
        or not isinstance(exact_bit_groups, list)
    ):
        raise ValueError("Internal placement selectors/placements must be lists")
    # Exact candidate IDs use the same resolver and therefore get identical
    # unmatched/ambiguous checking.
    for item in exact:
        if not isinstance(item, dict) or "candidate_id" not in item:
            raise ValueError(
                "Each internal placements[] entry requires candidate_id"
            )
        selectors.append(dict(item))
    for item in exact_bit_groups:
        if (
            not isinstance(item, dict)
            or "instance_path" not in item
            or "boundaries" not in item
            or not isinstance(item["boundaries"], list)
        ):
            raise ValueError(
                "Each internal exact_bit_boundaries[] entry requires an "
                "instance_path and a boundaries list"
            )
    if not selectors and not exact_bit_groups:
        raise ValueError(
            "Internal placement request must contain at least one selector "
            "or exact bit-boundary group"
        )
    config = dict(config)
    config["mode"] = mode
    config["selectors"] = selectors
    config["exact_bit_boundaries"] = exact_bit_groups
    config["source_path"] = os.path.abspath(path)
    return config


def RESOLVE_INTERNAL_PIPELINE_PLACEMENTS(config, plans, parser_state):
    """Resolve generic selectors against this iteration's candidate inventory.

    The resolver is intentionally strict: a typo that matches nothing or an
    unqualified selector that matches multiple positions is an error, never a
    silently-different forced benchmark.
    """
    inventory = []
    for plan in plans.values():
        main_func = parser_state.LogicInstLookupTable[plan.main_inst].func_name
        for subtree_root, landscape in plan.landscapes.items():
            if landscape is None:
                continue
            subtree_func = parser_state.LogicInstLookupTable[
                subtree_root
            ].func_name
            for placement in landscape.candidates:
                inventory.append(
                    (plan, subtree_root, main_func, subtree_func, placement)
                )
    inventory.sort(key=lambda x: (x[4].axis_position, x[4].candidate_id))
    resolved = {plan.main_inst: {} for plan in plans.values()}
    allowed_keys = {
        "candidate_id",
        "kind",
        "func_name",
        "ancestor_func",
        "instance_path",
        "instance_path_regex",
        "main_function",
        "subtree_function",
        "hierarchy_depth",
        "coherent_boundary",
        "axis_unit_min",
        "axis_unit_max",
        "all",
        "limit",
        "fixed",
    }
    for selector_i, selector in enumerate(config.get("selectors", ())):
        if not isinstance(selector, dict):
            raise ValueError(f"Internal placement selector {selector_i} is not an object")
        unknown = set(selector) - allowed_keys
        if unknown:
            raise ValueError(
                f"Unknown internal placement selector field(s): {sorted(unknown)}"
            )
        pattern = selector.get("instance_path_regex")
        regex = re.compile(pattern) if pattern is not None else None
        matches = []
        for item in inventory:
            _plan, _root, main_func, subtree_func, placement = item
            if (
                "candidate_id" in selector
                and placement.candidate_id != selector["candidate_id"]
            ):
                continue
            if "kind" in selector and placement.kind != selector["kind"]:
                continue
            if (
                "func_name" in selector
                and placement.func_name != selector["func_name"]
            ):
                continue
            if (
                "ancestor_func" in selector
                and selector["ancestor_func"] not in placement.ancestor_funcs
            ):
                continue
            if (
                "instance_path" in selector
                and placement.inst_path != selector["instance_path"]
            ):
                continue
            if regex is not None and regex.search(placement.inst_path) is None:
                continue
            if (
                "main_function" in selector
                and main_func != selector["main_function"]
            ):
                continue
            if (
                "subtree_function" in selector
                and subtree_func != selector["subtree_function"]
            ):
                continue
            if (
                "hierarchy_depth" in selector
                and placement.hierarchy_depth != selector["hierarchy_depth"]
            ):
                continue
            if (
                "coherent_boundary" in selector
                and placement.coherent_boundary
                != bool(selector["coherent_boundary"])
            ):
                continue
            if (
                "axis_unit_min" in selector
                and placement.axis_unit < selector["axis_unit_min"]
            ):
                continue
            if (
                "axis_unit_max" in selector
                and placement.axis_unit > selector["axis_unit_max"]
            ):
                continue
            matches.append(item)
        if not matches:
            raise ValueError(
                f"Internal placement selector {selector_i} matched no legal "
                f"candidate: {selector}"
            )
        all_matches = bool(selector.get("all", False))
        limit = selector.get("limit")
        if limit is not None:
            if not isinstance(limit, int) or limit <= 0:
                raise ValueError("Internal placement selector limit must be > 0")
            matches = matches[:limit]
        elif not all_matches and len(matches) != 1:
            raise ValueError(
                f"Internal placement selector {selector_i} is ambiguous: "
                f"matched {len(matches)} candidates; use all=true, limit, or "
                "an exact candidate_id"
            )
        for plan, subtree_root, _main_func, _subtree_func, placement in matches:
            selected = placement.copy_with(
                fixed=selector.get("fixed", True), source="internal_forced"
            )
            bucket = resolved[plan.main_inst].setdefault(subtree_root, {})
            bucket[selected.candidate_id] = selected

    # Exact physical bit groups deliberately bypass the provisional raster
    # resolver.  They remain an internal experiment interface: the caller
    # must name a single elaborated raw-HDL leaf, while this resolver obtains
    # its legal width and delay-axis span from the normal candidate inventory.
    for group_i, spec in enumerate(config.get("exact_bit_boundaries", ())):
        unknown = set(spec) - {"instance_path", "boundaries", "fixed"}
        if unknown:
            raise ValueError(
                f"Unknown exact bit-boundary field(s): {sorted(unknown)}"
            )
        inst_path = spec["instance_path"]
        boundaries = tuple(int(boundary) for boundary in spec["boundaries"])
        raster_templates = []
        output_templates = []
        seen_raster_locations = set()
        seen_output_locations = set()
        for plan, subtree_root, _main_func, _subtree_func, placement in inventory:
            if placement.inst_path != inst_path:
                continue
            location = (plan.main_inst, subtree_root)
            if isinstance(placement, BitPlacementRequest):
                if location in seen_raster_locations:
                    continue
                seen_raster_locations.add(location)
                raster_templates.append((plan, subtree_root, placement))
            elif (
                isinstance(placement, PipelinePlacement)
                and placement.kind == PipelinePlacement.INSTANCE_OUTPUT
            ):
                logic = parser_state.LogicInstLookupTable.get(inst_path)
                if (
                    logic is None
                    or RAW_VHDL.GET_LEAF_SPLIT_KIND(logic)
                    != RAW_VHDL.SPLIT_KIND_MUX_BITS
                    or location in seen_output_locations
                ):
                    continue
                seen_output_locations.add(location)
                output_templates.append((plan, subtree_root, placement))
        templates = raster_templates or output_templates
        if len(templates) != 1:
            raise ValueError(
                f"Internal exact bit-boundary group {group_i} for {inst_path} "
                f"matched {len(templates)} bit-splittable leaves; expected one"
            )
        plan, subtree_root, template = templates[0]
        if isinstance(template, BitPlacementRequest):
            width = template.bit_width
            leaf_axis_start = template.leaf_axis_start
            leaf_axis_end = template.leaf_axis_end
        else:
            width = RAW_VHDL.GET_LEAF_BIT_WIDTH(
                parser_state.LogicInstLookupTable[inst_path], parser_state
            )
            matching_segments = [
                segment
                for segment in plan.landscapes[subtree_root].segments
                if segment.inst_path == inst_path
            ]
            if len(matching_segments) != 1:
                raise ValueError(
                    f"Internal exact bit-boundary group {group_i} for "
                    f"{inst_path} matched {len(matching_segments)} segments; "
                    "expected one"
                )
            leaf_axis_start = matching_segments[0].start
            leaf_axis_end = matching_segments[0].end
        if (
            width is None
            or not boundaries
            or boundaries != tuple(sorted(set(boundaries)))
            or any(boundary <= 0 or boundary >= width for boundary in boundaries)
        ):
            raise ValueError(
                f"Invalid exact bit boundaries {boundaries} for {width}-bit "
                f"leaf {inst_path}"
            )
        count = len(boundaries)
        bucket = resolved[plan.main_inst].setdefault(subtree_root, {})
        for ordinal, boundary in enumerate(boundaries, start=1):
            local_slice = boundary / float(width)
            axis_position = leaf_axis_start + local_slice * (
                leaf_axis_end - leaf_axis_start
            )
            selected = PipelinePlacement(
                PipelinePlacement.BIT_INTERNAL,
                inst_path,
                template.func_name,
                int(math.ceil(axis_position)) - 1,
                axis_position,
                local_slice=local_slice,
                registered_bits=(
                    width
                    if template.registered_bits is None
                    else template.registered_bits
                ),
                hierarchy_depth=template.hierarchy_depth,
                span_units=template.span_units,
                coherent_boundary=template.coherent_boundary,
                ancestor_funcs=template.ancestor_funcs,
                fixed=spec.get("fixed", True),
                source="internal_exact",
                bit_width=width,
                bit_split_ordinal=ordinal,
                bit_split_count=count,
                bit_boundary=boundary,
                bit_boundary_mode="exact",
                bit_boundaries=boundaries,
                leaf_axis_start=leaf_axis_start,
                leaf_axis_end=leaf_axis_end,
                requested_axis_unit=None,
                requested_axis_position=None,
                requested_local_slice=None,
            )
            bucket[selected.candidate_id] = selected

    for plan in plans.values():
        by_root = resolved[plan.main_inst]
        plan.fixed_placements = {
            root: sorted(items.values(), key=lambda p: (p.axis_unit, p.candidate_id))
            for root, items in by_root.items()
        }
        if plan.fixed_placements:
            plan.placement_mode = config["mode"]
    return resolved


def SUMMARIZE_SUBTREE_PIPELINE(
    main_inst, subtrees, TimingParamsLookupTable, parser_state
):
    """Describe how many slices the sweep built into a
    main's cut subtrees, and where.

    A main's own GET_TOTAL_LATENCY only counts registers on its *monolithic*
    (non-decoupled) input-to-output path: a flow-controlled/AUTOPIPELINE
    submodule reports latency 0 to its container by design
    (GET_SUBMODULE_LATENCY), so its stages are invisible there. Reporting only
    the main latency (0 for a pure stream) or only the deepest single instance
    (one block_step, not the whole chacha pipeline) both understate the depth.

    So walk the subtrees and add up every decoupled region's own
    latency alongside the monolithic part:
      monolithic  = slices inserted directly into the cut subtree roots
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
    autopipelined: total slices and the decoupled regions
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
            f"[sweep]   {main_func}: {total_stages} slice(s) total "
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


def APPLY_PIPELINE_PLACEMENTS(
    placements,
    parser_state,
    TimingParamsLookupTable,
    lock_targets=False,
):
    """Lower typed placements without recursively projecting global slices.

    This is deliberately an internal compiler API: the planned sweep and the
    opt-in QoR benchmark both use it, but it is not a source pragma or command
    line interface.  The setters invalidate each modified TimingParams hash
    and latency cache; the normal ancestor invalidation pass refreshes the
    enclosing entity hashes after the full batch is applied.
    """
    target_insts = set()
    seen = set()
    bit_groups = {}
    for placement in placements:
        if not isinstance(placement, PipelinePlacement):
            if isinstance(placement, BitPlacementRequest):
                raise ValueError(
                    f"Cannot lower provisional bit planning site "
                    f"{placement.candidate_id}; materialize its ordinal/count "
                    "against the complete selected leaf group first"
                )
            raise TypeError(type(placement))
        if placement.candidate_id in seen:
            continue
        seen.add(placement.candidate_id)
        if placement.inst_path not in TimingParamsLookupTable:
            raise KeyError(
                f"Pipeline placement instance does not exist: "
                f"{placement.inst_path}"
            )
        timing_params = TimingParamsLookupTable[placement.inst_path]
        logic = parser_state.LogicInstLookupTable[placement.inst_path]
        if timing_params.params_are_fixed:
            raise ValueError(
                f"Cannot add pipeline placement to locked instance "
                f"{placement.inst_path}"
            )
        if not logic.CAN_HAVE_ADDED_LATENCY(parser_state):
            raise ValueError(
                f"Pipeline placement targets non-sliceable function "
                f"{logic.func_name}: {placement.candidate_id}"
            )
        if placement.kind == PipelinePlacement.INSTANCE_INPUT:
            if len(logic.inputs) == 0:
                raise ValueError(
                    f"Input-boundary placement targets function with no "
                    f"inputs: {placement.candidate_id}"
                )
            timing_params.SET_HAS_IN_REGS(True)
        elif placement.kind == PipelinePlacement.INSTANCE_OUTPUT:
            if len(logic.outputs) == 0:
                raise ValueError(
                    f"Output-boundary placement targets function with no "
                    f"outputs: {placement.candidate_id}"
                )
            timing_params.SET_HAS_OUT_REGS(True)
        elif placement.kind == PipelinePlacement.BIT_INTERNAL:
            if len(logic.submodule_instances) != 0:
                raise ValueError(
                    f"Bit-internal placement must target a raw HDL leaf: "
                    f"{placement.candidate_id}"
                )
            if RAW_VHDL.GET_LEAF_SPLIT_KIND(logic) not in (
                RAW_VHDL.SPLIT_KIND_BITS,
                RAW_VHDL.SPLIT_KIND_MUX_BITS,
            ):
                raise ValueError(
                    f"Bit-internal placement targets non-bit-splittable leaf "
                    f"{logic.func_name}: {placement.candidate_id}"
                )
            bit_groups.setdefault(placement.inst_path, []).append(placement)
        else:  # guarded by PipelinePlacement.__init__, defensive for mutation
            raise ValueError(placement.kind)
        target_insts.add(placement.inst_path)

    for inst_path, group in bit_groups.items():
        timing_params = TimingParamsLookupTable[inst_path]
        logic = parser_state.LogicInstLookupTable[inst_path]
        counts = {placement.bit_split_count for placement in group}
        widths = {placement.bit_width for placement in group}
        modes = {placement.bit_boundary_mode for placement in group}
        if len(counts) != 1 or len(widths) != 1 or len(modes) != 1:
            raise ValueError(
                f"Physical bit placements for {inst_path} disagree on "
                f"split count/width/mode: counts={counts}, widths={widths}, "
                f"modes={modes}"
            )
        count = counts.pop()
        width = widths.pop()
        mode = modes.pop()
        ordinals = {placement.bit_split_ordinal for placement in group}
        if len(group) != count or ordinals != set(range(1, count + 1)):
            raise ValueError(
                f"Physical bit placement group for {inst_path} is incomplete: "
                f"ordinals={sorted(ordinals)}, expected 1..{count}"
            )
        actual_width = RAW_VHDL.GET_LEAF_BIT_WIDTH(logic, parser_state)
        if actual_width != width:
            raise ValueError(
                f"Physical bit placement width {width} disagrees with raw "
                f"VHDL leaf width {actual_width} for {inst_path}"
            )
        if mode == "exact":
            groups = {placement.bit_boundaries for placement in group}
            if len(groups) != 1:
                raise ValueError(
                    f"Exact physical bit placements for {inst_path} disagree "
                    f"on their boundary group: {groups}"
                )
            boundaries = list(groups.pop())
        else:
            boundaries = RAW_VHDL.GET_EQUAL_WIDTH_BIT_BOUNDARIES(width, count)
        expected_slices = [boundary / float(width) for boundary in boundaries]
        by_ordinal = {
            placement.bit_split_ordinal: placement for placement in group
        }
        for ordinal, (boundary, local_slice) in enumerate(
            zip(boundaries, expected_slices), start=1
        ):
            placement = by_ordinal[ordinal]
            if (
                placement.bit_boundary != boundary
                or not math.isclose(
                    placement.local_slice,
                    local_slice,
                    rel_tol=0.0,
                    abs_tol=1e-15,
                )
            ):
                raise ValueError(
                    f"Physical bit placement {placement.candidate_id} does "
                    f"not match RAW VHDL's {mode} allocation"
                )
        existing_boundaries = getattr(
            timing_params, "_exact_bit_boundaries", None
        )
        if timing_params._slices not in ([], expected_slices) or (
            existing_boundaries is not None
            and list(existing_boundaries) != boundaries
        ):
            raise ValueError(
                f"Physical bit placement group for {inst_path} conflicts "
                f"with existing slices {timing_params._slices}; expected "
                f"{expected_slices}"
            )
        if mode == "exact":
            timing_params.SET_EXACT_BIT_BOUNDARIES(boundaries, width)
        else:
            timing_params.SET_SLICES(expected_slices)

    if lock_targets:
        # Lock after the whole batch so multiple internal cuts may legally
        # target the same leaf.
        for inst in target_insts:
            TimingParamsLookupTable[inst].params_are_fixed = True
    return TimingParamsLookupTable


def PIPELINE_PLACEMENT_REALIZATION(
    placement, parser_state, TimingParamsLookupTable
):
    """Machine-readable realization/status record for placement_trace.json."""
    if isinstance(placement, BitPlacementRequest):
        rv = placement.to_dict()
        rv.update(
            {
                "realized": False,
                "realization": "provisional_planning_site",
            }
        )
        return rv
    if not isinstance(placement, PipelinePlacement):
        raise TypeError(type(placement))
    timing_params = TimingParamsLookupTable.get(placement.inst_path)
    rv = placement.to_dict()
    if timing_params is None:
        rv.update({"realized": False, "realization": "missing_instance"})
        return rv
    if placement.kind == PipelinePlacement.INSTANCE_INPUT:
        realized = timing_params._has_input_regs
        rv.update(
            {
                "realized": realized,
                "boundary_register": "input" if realized else None,
                "stage_assignment": {
                    "scope": "instance_local",
                    "starts_stage": 1 if realized else None,
                },
            }
        )
    elif placement.kind == PipelinePlacement.INSTANCE_OUTPUT:
        realized = timing_params._has_output_regs
        local_boundary = None
        if realized:
            local_boundary = timing_params.GET_TOTAL_LATENCY(
                parser_state, TimingParamsLookupTable
            )
        rv.update(
            {
                "realized": realized,
                "boundary_register": "output" if realized else None,
                "stage_assignment": {
                    "scope": "instance_local",
                    "ends_stage": local_boundary,
                },
            }
        )
    else:
        if placement.bit_boundary_mode == "exact":
            expected_boundaries = list(placement.bit_boundaries)
        else:
            expected_boundaries = RAW_VHDL.GET_EQUAL_WIDTH_BIT_BOUNDARIES(
                placement.bit_width, placement.bit_split_count
            )
        expected_slices = [
            boundary / float(placement.bit_width)
            for boundary in expected_boundaries
        ]
        exact_metadata = getattr(timing_params, "_exact_bit_boundaries", None)
        realized = timing_params._slices == expected_slices and (
            placement.bit_boundary_mode != "exact"
            or exact_metadata == expected_boundaries
        )
        ends_stage = placement.bit_split_ordinal if realized else None
        rv.update(
            {
                "realized": realized,
                "realization": (
                    f"{placement.bit_boundary_mode}_bit_boundary"
                    if realized
                    else "emitted_slice_group_mismatch"
                ),
                "emitted_slices": list(timing_params._slices),
                "expected_slices": expected_slices,
                "boundary_register": "leaf_internal" if realized else None,
                "stage_assignment": {
                    "scope": "leaf_local",
                    "ends_stage": ends_stage,
                },
            }
        )
    return rv


def CHECK_PIPELINE_PLACEMENTS_REALIZED(
    placements, parser_state, TimingParamsLookupTable
):
    missing = []
    for placement in placements:
        record = PIPELINE_PLACEMENT_REALIZATION(
            placement, parser_state, TimingParamsLookupTable
        )
        if not record["realized"]:
            missing.append(placement.candidate_id)
    if missing:
        raise RuntimeError(
            f"{len(missing)} planned pipeline placement(s) did not materialize: "
            + ", ".join(missing[:5])
        )
    return len(placements)


def WRITE_PIPELINE_PLACEMENT_TRACE(
    plans, parser_state, TimingParamsLookupTable, internal_config=None
):
    """Write the typed planner's candidate/selection/final-realization trace."""
    out_dir = os.path.join(SYN.SYN_OUTPUT_DIRECTORY, SYN.TOP_LEVEL_MODULE)
    os.makedirs(out_dir, exist_ok=True)
    trace_path = os.path.join(out_dir, "placement_trace.json")
    trace = {
        "schema_version": 5,
        "planner": "typed_physical_placement",
        "internal_forced_mode": (
            None if internal_config is None else internal_config.get("mode")
        ),
        "mains": {},
    }
    for plan in plans.values():
        main_func = parser_state.LogicInstLookupTable[plan.main_inst].func_name
        _ff_text, final_estimated_ffs = SYN.GET_REGISTERS_ESTIMATE_TEXT_AND_FFS(
            parser_state.LogicInstLookupTable[plan.main_inst],
            plan.main_inst,
            parser_state,
            TimingParamsLookupTable,
            {},
        )
        candidates = []
        planning_sites = []
        seen_candidates = set()
        seen_planning_sites = set()
        for subtree_root in plan.subtrees:
            landscape = plan.landscapes.get(subtree_root)
            if landscape is None:
                continue
            for placement in landscape.candidates:
                record = placement.to_dict()
                record["subtree"] = subtree_root
                if isinstance(placement, BitPlacementRequest):
                    if placement.candidate_id in seen_planning_sites:
                        continue
                    seen_planning_sites.add(placement.candidate_id)
                    planning_sites.append(record)
                else:
                    if placement.candidate_id in seen_candidates:
                        continue
                    seen_candidates.add(placement.candidate_id)
                    candidates.append(record)
        candidates.sort(key=lambda p: (p["axis_position"], p["candidate_id"]))
        planning_sites.sort(
            key=lambda p: (
                p["requested_axis_position"],
                p["candidate_id"],
            )
        )

        final_selected = []
        selected_ids = set()
        for subtree_root, placements in plan.placements.items():
            for placement in placements:
                if placement.candidate_id in selected_ids:
                    continue
                selected_ids.add(placement.candidate_id)
                record = PIPELINE_PLACEMENT_REALIZATION(
                    placement, parser_state, TimingParamsLookupTable
                )
                record["subtree"] = subtree_root
                final_selected.append(record)
        missing = [p["candidate_id"] for p in final_selected if not p["realized"]]
        if missing:
            raise RuntimeError(
                f"Final placement trace disagrees with emitted TimingParams for "
                f"{main_func}: {missing[:5]}"
            )
        final_selected.sort(
            key=lambda p: (p["axis_position"], p["candidate_id"])
        )
        # A mini-sweep fixes a helper's *interior*.  Its edge banks are a
        # separate full-design choice and are retained here with the topology
        # evidence that selected them.
        locked_instances = []
        for inst_path, lock in sorted(plan.locked.items()):
            timing_params = TimingParamsLookupTable[inst_path]
            logic = parser_state.LogicInstLookupTable[inst_path]
            realized = (
                timing_params.params_are_fixed
                and timing_params._slices == list(lock.slices)
                and timing_params._has_input_regs == lock.has_input_regs
                and timing_params._has_output_regs == lock.has_output_regs
            )
            if not realized:
                raise RuntimeError(
                    f"Locked pipeline decision did not materialize for {inst_path}"
                )
            locked_instances.append(
                {
                    "instance_path": inst_path,
                    "function": logic.func_name,
                    "slices": list(lock.slices),
                    "input_registers": lock.has_input_regs,
                    "output_registers": lock.has_output_regs,
                    "boundary_strategy": lock.boundary_strategy,
                    "total_latency": timing_params.GET_TOTAL_LATENCY(
                        parser_state, TimingParamsLookupTable
                    ),
                    "realized": realized,
                    "lowering": "coarse_minisweep_lock",
                }
            )
        trace["mains"][main_func] = {
            "main_instance": plan.main_inst,
            "target_mhz": plan.target_mhz,
            "mode": plan.placement_mode,
            "candidate_count": len(candidates),
            "planning_site_count": len(planning_sites),
            "final_estimated_total_ffs": final_estimated_ffs,
            "candidates": candidates,
            "planning_sites": planning_sites,
            "iterations": plan.placement_iterations,
            "same_depth_refinement": {
                "chunked_mux_attempted": (
                    plan.chunked_mux_refinement_attempted
                ),
                "final_active_kind": plan.active_placement_refinement,
                "attempted_physical_fingerprints": sorted(
                    plan.attempted_placement_fingerprints
                ),
            },
            "final_selected": final_selected,
            "locked_instances": locked_instances,
            "mini_sweep_boundary_diagnostics": plan.mini_sweep_boundary_diagnostics,
        }
    with open(trace_path, "w") as f:
        json.dump(trace, f, indent=1, sort_keys=True)
    print(f"[sweep] Placement trace: {trace_path}", flush=True)
    return trace_path


class MiniSweepLock:
    """A proven helper interior plus independently selectable edge banks.

    ``slices`` is the result of the isolated throughput measurement and is
    immutable for the lifetime of this lock.  Input/output banks are a
    full-design scheduling decision: putting both on every serial instance
    creates an avoidable empty output-to-input cycle.
    """

    def __init__(
        self,
        slices,
        has_input_regs=False,
        has_output_regs=False,
        boundary_strategy="topology_output",
    ):
        self.slices = list(slices)
        self.has_input_regs = bool(has_input_regs)
        self.has_output_regs = bool(has_output_regs)
        self.boundary_strategy = boundary_strategy

    def to_dict(self):
        return {
            "slices": list(self.slices),
            "input_registers": self.has_input_regs,
            "output_registers": self.has_output_regs,
            "boundary_strategy": self.boundary_strategy,
        }


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
        self.placements = {}  # subtree root inst -> [PipelinePlacement]
        self.fixed_placements = {}  # subtree root inst -> retained experiment seeds
        self.placement_mode = "automatic"  # automatic / seed / replace
        self.placement_iterations = []  # machine-readable trace snapshots
        self.func_delay_scale = {}  # func name -> learned weight multiplier
        self.global_scale = 1.0  # budget divisor when attribution fails
        # inst -> MiniSweepLock.  An isolated mini-sweep proves the interior
        # slices of a repeated helper, but does not prove that every instance
        # needs both external register banks.  Keep those decisions separate
        # so adjacent helpers can share one real boundary register.
        self.locked = {}
        self.mini_sweep_boundary_diagnostics = {}
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
        # A failed physical schedule may have a cheaper same-depth neighbor.
        # Keep this separate from the delay-scale feedback so the neighbor is
        # synthesized before the next denser landscape plan.
        self.pending_placement_refinement = None
        self.active_placement_refinement = None
        self.chunked_mux_refinement_attempted = False
        self.attempted_placement_fingerprints = set()
        self.current_placement_fingerprint = None
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


def _IO_REGISTER_BITS(logic, direction, parser_state):
    """Return the bank width used by the existing VHDL I/O-register path."""
    ports = logic.inputs if direction == "input" else logic.outputs
    bits = 0
    try:
        for port in ports:
            bits += VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM(
                logic.wire_to_c_type[port], parser_state
            )
    except Exception:
        return None
    return bits


def _PARENT_INST_AND_LOCAL(inst_path):
    marker = C_TO_LOGIC.SUBMODULE_MARKER
    if marker not in inst_path:
        return None, None
    return inst_path.rsplit(marker, 1)


def _TRACE_TRANSPARENT_DRIVER(logic, wire):
    """Follow only collapsed parent-scope aliases back to their source."""
    seen = set()
    while wire in logic.wire_driven_by and wire not in seen:
        seen.add(wire)
        wire = logic.wire_driven_by[wire]
    return wire


def _LOCKED_SOURCE_INSTANCE(parent_logic, parent_inst, wire, parser_state):
    """Return the immediate child instance driving ``wire``, if any.

    At this point aliases have been collapsed or followed.  Deliberately do
    not walk through a submodule/operator: a register is shared only when two
    locked helpers are connected by parent-scope wire plumbing with no logic
    in between.
    """
    marker = C_TO_LOGIC.SUBMODULE_MARKER
    if marker not in wire:
        return None
    local_inst, port_expr = wire.split(marker, 1)
    if local_inst not in parent_logic.submodule_instances:
        return None
    source_logic = parser_state.FuncLogicLookupTable[
        parent_logic.submodule_instances[local_inst]
    ]
    if not any(
        port_expr == port
        or port_expr.startswith(port + ".")
        or port_expr.startswith(port + "[")
        for port in source_logic.outputs
    ):
        return None
    return parent_inst + marker + local_inst


def FIND_DIRECT_LOCKED_BOUNDARY_EDGES(plan, hotspot_func, parser_state):
    """Find direct producer->consumer edges among one mini-swept helper set.

    This intentionally uses elaborated connectivity rather than source order
    or a function-name convention.  A serial chain, fanout, and fanin remain
    distinguishable, while an intervening operation prevents false boundary
    coalescing.
    """
    targets = {
        inst
        for inst in plan.locked
        if parser_state.LogicInstLookupTable[inst].func_name == hotspot_func
    }
    edges = set()
    for consumer in sorted(targets):
        parent_inst, local_consumer = _PARENT_INST_AND_LOCAL(consumer)
        if parent_inst is None:
            continue
        parent_logic = parser_state.LogicInstLookupTable.get(parent_inst)
        if parent_logic is None:
            continue
        consumer_logic = parser_state.LogicInstLookupTable[consumer]
        for input_port in consumer_logic.inputs:
            try:
                driver = C_TO_LOGIC.GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE(
                    parent_logic, local_consumer, input_port
                )
            except KeyError:
                continue
            driver = _TRACE_TRANSPARENT_DRIVER(parent_logic, driver)
            producer = _LOCKED_SOURCE_INSTANCE(
                parent_logic, parent_inst, driver, parser_state
            )
            if producer in targets and producer != consumer:
                edges.add((producer, consumer))
    return sorted(edges)


def _MIN_COST_BIPARTITE_BOUNDARY_COVER(
    edges, output_cost, input_cost, prefer_output
):
    """Exact weighted vertex cover for direct helper connections.

    Each graph edge can be covered by a producer output bank or consumer
    input bank.  This is a bipartite minimum-cut problem; using the exact
    solution avoids an order-dependent greedy policy on branching dataflow.
    """
    forced_outputs = {
        producer
        for producer, consumer in edges
        if producer in output_cost and consumer not in input_cost
    }
    forced_inputs = {
        consumer
        for producer, consumer in edges
        if producer not in output_cost and consumer in input_cost
    }
    remaining_edges = [
        (producer, consumer)
        for producer, consumer in edges
        if producer not in forced_outputs and consumer not in forced_inputs
    ]
    left = sorted(
        {producer for producer, _consumer in remaining_edges if producer in output_cost}
    )
    right = sorted(
        {consumer for _producer, consumer in remaining_edges if consumer in input_cost}
    )
    usable_edges = [
        (producer, consumer)
        for producer, consumer in remaining_edges
        if producer in output_cost and consumer in input_cost
    ]
    uncovered = [
        (producer, consumer)
        for producer, consumer in remaining_edges
        if producer not in output_cost and consumer not in input_cost
    ]
    # A selected bank has a strictly positive integer capacity.  The scale
    # makes width the primary objective, number of banks second, and the
    # requested output/input orientation the deterministic final tie-break.
    scale = 4 * (len(left) + len(right) + 1)

    def capacity(bits, side):
        bits = max(1, int(bits if bits is not None else 1_000_000))
        side_penalty = 0 if (side == "output") == prefer_output else 1
        return bits * scale + 1 + side_penalty

    source = "__source__"
    sink = "__sink__"
    graph = {}

    def add_edge(u, v, cap):
        graph.setdefault(u, {})
        graph.setdefault(v, {})
        graph[u][v] = graph[u].get(v, 0) + cap
        graph[v].setdefault(u, 0)

    for producer in left:
        add_edge(source, ("out", producer), capacity(output_cost[producer], "output"))
    inf = sum(
        capacity(output_cost[p], "output") for p in left
    ) + sum(capacity(input_cost[c], "input") for c in right) + 1
    for producer, consumer in usable_edges:
        add_edge(("out", producer), ("in", consumer), inf)
    for consumer in right:
        add_edge(("in", consumer), sink, capacity(input_cost[consumer], "input"))

    # Edmonds-Karp is adequate here: mini-sweep groups are deliberately
    # bounded repeated helpers, and the implementation stays dependency-free.
    while True:
        parent = {source: None}
        queue = [source]
        for u in queue:
            for v, cap in sorted(graph.get(u, {}).items(), key=lambda item: str(item[0])):
                if cap > 0 and v not in parent:
                    parent[v] = u
                    queue.append(v)
                    if v == sink:
                        break
            if sink in parent:
                break
        if sink not in parent:
            break
        flow = None
        v = sink
        while parent[v] is not None:
            u = parent[v]
            flow = graph[u][v] if flow is None else min(flow, graph[u][v])
            v = u
        v = sink
        while parent[v] is not None:
            u = parent[v]
            graph[u][v] -= flow
            graph[v][u] = graph[v].get(u, 0) + flow
            v = u

    reachable = {source}
    queue = [source]
    for u in queue:
        for v, cap in graph.get(u, {}).items():
            if cap > 0 and v not in reachable:
                reachable.add(v)
                queue.append(v)
    selected_outputs = sorted(
        forced_outputs | {
            producer for producer in left if ("out", producer) not in reachable
        }
    )
    selected_inputs = sorted(
        forced_inputs | {
            consumer for consumer in right if ("in", consumer) in reachable
        }
    )
    return selected_outputs, selected_inputs, uncovered


def SET_MINISWEEP_BOUNDARY_STRATEGY(plan, hotspot_func, strategy, parser_state):
    """Choose boundary banks for one repeated mini-sweep helper group.

    The compact policies cover only direct helper-to-helper edges.  This
    leaves top-level endpoints unregistered by default and lets timing
    feedback request the progressively broader one-sided/both-sided fallback
    policies only when necessary.
    """
    valid = {
        "topology_output",
        "topology_input",
        "all_output",
        "all_input",
        "both",
    }
    if strategy not in valid:
        raise ValueError(f"Unknown mini-sweep boundary strategy: {strategy}")
    target_insts = sorted(
        inst
        for inst in plan.locked
        if parser_state.LogicInstLookupTable[inst].func_name == hotspot_func
    )
    if not target_insts:
        return False
    allow_io = hotspot_func not in parser_state.func_marked_no_add_io_regs
    can_input = {
        inst: allow_io
        and len(parser_state.LogicInstLookupTable[inst].inputs) > 0
        for inst in target_insts
    }
    can_output = {
        inst: allow_io
        and len(parser_state.LogicInstLookupTable[inst].outputs) > 0
        for inst in target_insts
    }
    for inst in target_insts:
        lock = plan.locked[inst]
        lock.has_input_regs = False
        lock.has_output_regs = False
        lock.boundary_strategy = strategy

    edges = FIND_DIRECT_LOCKED_BOUNDARY_EDGES(plan, hotspot_func, parser_state)
    selected_outputs = []
    selected_inputs = []
    uncovered = []
    if strategy == "both":
        selected_outputs = [inst for inst in target_insts if can_output[inst]]
        selected_inputs = [inst for inst in target_insts if can_input[inst]]
    elif strategy == "all_output":
        selected_outputs = [inst for inst in target_insts if can_output[inst]]
    elif strategy == "all_input":
        selected_inputs = [inst for inst in target_insts if can_input[inst]]
    else:
        output_cost = {
            inst: _IO_REGISTER_BITS(
                parser_state.LogicInstLookupTable[inst], "output", parser_state
            )
            for inst in target_insts
            if can_output[inst]
        }
        input_cost = {
            inst: _IO_REGISTER_BITS(
                parser_state.LogicInstLookupTable[inst], "input", parser_state
            )
            for inst in target_insts
            if can_input[inst]
        }
        selected_outputs, selected_inputs, uncovered = _MIN_COST_BIPARTITE_BOUNDARY_COVER(
            edges,
            output_cost,
            input_cost,
            prefer_output=(strategy == "topology_output"),
        )
    for inst in selected_outputs:
        plan.locked[inst].has_output_regs = True
    for inst in selected_inputs:
        plan.locked[inst].has_input_regs = True
    diagnostics = {
        "strategy": strategy,
        "direct_edges": [
            {"producer": producer, "consumer": consumer}
            for producer, consumer in edges
        ],
        "selected_outputs": selected_outputs,
        "selected_inputs": selected_inputs,
        "uncovered_edges": [
            {"producer": producer, "consumer": consumer}
            for producer, consumer in uncovered
        ],
    }
    plan.mini_sweep_boundary_diagnostics[hotspot_func] = diagnostics
    return True


def TRY_NEXT_MINISWEEP_BOUNDARY_STRATEGY(plan, hotspot_func, parser_state):
    """Advance one bounded full-design boundary-policy A/B candidate."""
    target_locks = [
        plan.locked[inst]
        for inst in sorted(plan.locked)
        if parser_state.LogicInstLookupTable[inst].func_name == hotspot_func
    ]
    if not target_locks:
        return None
    current = target_locks[0].boundary_strategy
    order = [
        "topology_output",
        "topology_input",
        "all_output",
        "all_input",
        "both",
    ]
    try:
        next_index = order.index(current) + 1
    except ValueError:
        next_index = len(order)
    if next_index >= len(order):
        return None
    next_strategy = order[next_index]
    SET_MINISWEEP_BOUNDARY_STRATEGY(
        plan, hotspot_func, next_strategy, parser_state
    )
    return next_strategy


def HOTSPOT_IS_LOCKED(hotspot_func, plan, parser_state):
    if hotspot_func not in parser_state.FuncToInstances:
        return False
    insts = parser_state.FuncToInstances[hotspot_func]
    return len(insts) > 0 and all(inst in plan.locked for inst in insts)


def RUN_HOTSPOT_MINISWEEP(hotspot_func, plan, parser_state):
    """Isolated coarse sweep of one hotspot func.

    A nonzero result locks the *interior* slices on every instance.  Boundary
    registers are selected separately from the real parent dataflow: direct
    serial helpers share one bank instead of every instance receiving the old
    unconditional input-plus-output pair.
    """
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
    # The lock adds IO register banks around every instance.  If the helper
    # already meets its isolated goal with zero internal cuts, those banks
    # would add latency without subdividing the blamed combinational path.
    # Leave it to normal boundary planning instead.  This is also important
    # for repeated helpers such as Divider's step function, which may already
    # be fast enough in isolation and must not acquire two gratuitous clocks
    # per instance merely because a different path was blamed at top level.
    if len(working_slices) == 0:
        print(
            f"[sweep] Hotspot {hotspot_func} meets timing in isolation without "
            "internal cuts; not locking IO-only latency.",
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
    # Replace any conflicting (nested/containing) older locks
    for func_inst in sorted(parser_state.FuncToInstances[hotspot_func]):
        for locked_inst in list(plan.locked.keys()):
            if _INSTS_CONFLICT(func_inst, locked_inst):
                del plan.locked[locked_inst]
        plan.locked[func_inst] = MiniSweepLock(
            working_slices,
            boundary_strategy="topology_output",
        )
    SET_MINISWEEP_BOUNDARY_STRATEGY(
        plan, hotspot_func, "topology_output", parser_state
    )
    boundary = plan.mini_sweep_boundary_diagnostics[hotspot_func]
    print(
        f"[sweep] Locked {hotspot_func} at cuts={len(working_slices)} "
        f"({len(boundary['selected_inputs'])} input + "
        f"{len(boundary['selected_outputs'])} output boundary bank(s), "
        f"{len(boundary['direct_edges'])} direct edge(s)) on "
        f"{len(parser_state.FuncToInstances[hotspot_func])} instance(s)",
        flush=True,
    )
    return True


def APPLY_LOCKS(plan, parser_state, TimingParamsLookupTable):
    boundary_placements = []
    for locked_inst in sorted(plan.locked.keys()):
        lock = plan.locked[locked_inst]
        locked_logic = parser_state.LogicInstLookupTable[locked_inst]
        TimingParamsLookupTable = (
            SYN.ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(
                locked_inst,
                locked_logic,
                lock.slices,
                parser_state,
                TimingParamsLookupTable,
                write_files=False,
            )
        )
        if type(TimingParamsLookupTable) is int:
            raise Exception(f"Bad locked slices for {locked_inst}: {lock.slices}")
        if lock.has_input_regs:
            boundary_placements.append(
                PipelinePlacement(
                    PipelinePlacement.INSTANCE_INPUT,
                    locked_inst,
                    locked_logic.func_name,
                    0,
                    0.0,
                    registered_bits=_IO_REGISTER_BITS(
                        locked_logic, "input", parser_state
                    ),
                    source="minisweep_boundary_" + lock.boundary_strategy,
                )
            )
        if lock.has_output_regs:
            boundary_placements.append(
                PipelinePlacement(
                    PipelinePlacement.INSTANCE_OUTPUT,
                    locked_inst,
                    locked_logic.func_name,
                    0,
                    0.0,
                    registered_bits=_IO_REGISTER_BITS(
                        locked_logic, "output", parser_state
                    ),
                    source="minisweep_boundary_" + lock.boundary_strategy,
                )
            )
    # The helper interiors have now been lowered but are not frozen until the
    # independently selected I/O banks are present.  This reuses ordinary
    # typed placement lowering rather than growing a second VHDL path.
    TimingParamsLookupTable = APPLY_PIPELINE_PLACEMENTS(
        boundary_placements, parser_state, TimingParamsLookupTable
    )
    for locked_inst in sorted(plan.locked.keys()):
        timing_params = TimingParamsLookupTable[locked_inst]
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
    met_snapshot_plan_placements = None
    met_snapshot_plan_locks = None
    met_snapshot_plan_boundary_diagnostics = None
    best_plan_cuts = None
    best_plan_placements = None
    best_plan_locks = None
    best_plan_boundary_diagnostics = None
    internal_placement_config = LOAD_INTERNAL_PLACEMENT_CONFIG()
    if internal_placement_config is not None:
        print(
            f"[sweep] INTERNAL TEST placement hook: "
            f"{internal_placement_config['mode']} mode from "
            f"{internal_placement_config['source_path']}",
            flush=True,
        )

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
                    plan.placements[subtree_root] = []
                    continue
                plan.landscapes[subtree_root] = BUILD_SLICE_LANDSCAPE(
                    subtree_root, parser_state, tpl, plan.func_delay_scale
                )
        if internal_placement_config is not None:
            RESOLVE_INTERNAL_PIPELINE_PLACEMENTS(
                internal_placement_config, plans, parser_state
            )
        for plan in plans.values():
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
            pending_refinement = plan.pending_placement_refinement
            plan.pending_placement_refinement = None
            plan.active_placement_refinement = None
            if pending_refinement is not None:
                # The refinement was derived from the just-measured physical
                # schedule.  Try it byte-for-byte before the scale feedback
                # below is allowed to select a denser landscape plan.
                for subtree_root in plan.subtrees:
                    cuts, placements = pending_refinement["subtrees"].get(
                        subtree_root, ([], [])
                    )
                    plan.cuts[subtree_root] = list(cuts)
                    plan.placements[subtree_root] = list(placements)
                    total_cuts += len(cuts)
                plan.active_placement_refinement = pending_refinement["kind"]
                plan.chunked_mux_refinement_attempted = True
            planning_attempts = (
                range(8) if pending_refinement is None else ()
            )
            for attempt in planning_attempts:
                total_cuts = 0
                for subtree_root in plan.subtrees:
                    landscape = plan.landscapes.get(subtree_root)
                    if landscape is None:
                        continue
                    budget = (
                        plan.target_period_ns / landscape.units_to_ns
                    ) / plan.global_scale
                    fixed = plan.fixed_placements.get(subtree_root, ())
                    if plan.placement_mode == "replace":
                        placements = MATERIALIZE_BIT_PLACEMENT_REQUESTS(
                            list(fixed), landscape
                        )
                        cuts = sorted(set(p.axis_unit for p in placements))
                    else:
                        cuts, placements = PLAN_PIPELINE_PLACEMENTS(
                            landscape, budget, fixed_placements=fixed
                        )
                    plan.cuts[subtree_root] = cuts
                    plan.placements[subtree_root] = placements
                    total_cuts += len(plan.cuts[subtree_root])
                if not plan_unresolved or total_cuts != plan.prev_total_cuts:
                    break
                if plan.trim_pending:
                    plan.global_scale /= 1.1  # probing down - even fewer
                else:
                    plan.global_scale *= 1.1  # failing - force more cuts
            plan.prev_total_cuts = total_cuts
            plan.current_placement_fingerprint = PIPELINE_PLACEMENT_FINGERPRINT(
                plan.placements, plan.locked
            )
            plan.attempted_placement_fingerprints.add(
                plan.current_placement_fingerprint
            )
            # Apply the cuts
            for subtree_root in plan.subtrees:
                landscape = plan.landscapes.get(subtree_root)
                cuts = plan.cuts.get(subtree_root, [])
                placements = plan.placements.get(subtree_root, [])
                if landscape is None or len(placements) == 0:
                    continue
                tpl = APPLY_PIPELINE_PLACEMENTS(
                    placements,
                    parser_state,
                    tpl,
                )
                CHECK_PIPELINE_PLACEMENTS_REALIZED(
                    placements, parser_state, tpl
                )
            plan.placement_iterations.append(
                {
                    "iteration": iteration,
                    "mode": plan.placement_mode,
                    "refinement": plan.active_placement_refinement,
                    "placement_fingerprint": plan.current_placement_fingerprint,
                    "mini_sweep_locks": {
                        inst: lock.to_dict() for inst, lock in sorted(plan.locked.items())
                    },
                    "subtrees": {
                        subtree_root: {
                            "cuts": list(plan.cuts.get(subtree_root, ())),
                            "placements": [
                                p.to_dict()
                                for p in plan.placements.get(subtree_root, ())
                            ],
                        }
                        for subtree_root in plan.subtrees
                    },
                }
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
                # Nothing measures a --no_sweep plan, so report what the plan
                # itself predicts. Taken from the REALIZED cuts (post
                # MATERIALIZE_BIT_PLACEMENT_REQUESTS, which can relocate a
                # bit-internal cut to the leaf's equal-width bit boundary),
                # not from the planner's raster request. Without this, a plan
                # that cannot reach the goal looks identical to one that can:
                # every target from 167 to 250 MHz used to print the same
                # "cuts=33" line while predicting a 7.1 ns stage.
                predicted_ns = 0.0
                for subtree_root in plan.subtrees:
                    landscape = plan.landscapes.get(subtree_root)
                    if landscape is None:
                        continue
                    predicted_ns = max(
                        predicted_ns,
                        PREDICTED_STAGE_NS(
                            plan.cuts.get(subtree_root, []), landscape
                        ),
                    )
                predicted_str = ""
                if predicted_ns > 0.0:
                    predicted_mhz = 1000.0 / predicted_ns
                    predicted_str = (
                        f", predicted worst stage {predicted_ns:.2f}ns "
                        f"(~{predicted_mhz:.1f} MHz vs "
                        f"{plan.target_mhz:.1f} MHz goal)"
                    )
                print(
                    f"[sweep] {main_func_name}: --no_sweep guess, "
                    f"{total_stages} slice(s) built "
                    f"({total_stages + 1} pipeline stages), "
                    f"cuts={sum(len(c) for c in plan.cuts.values())}"
                    f"{predicted_str} (UNVERIFIED)",
                    flush=True,
                )
                if predicted_ns > 0.0 and 1000.0 / predicted_ns < plan.target_mhz:
                    print(
                        f"[sweep] WARNING: {main_func_name}'s --no_sweep plan "
                        f"is predicted at ~{1000.0 / predicted_ns:.1f} MHz, "
                        f"below its {plan.target_mhz:.1f} MHz goal - the "
                        "delay model cannot place enough registers to reach "
                        "the goal (see the floor report above).",
                        flush=True,
                    )
            WRITE_PIPELINE_PLACEMENT_TRACE(
                plans,
                parser_state,
                tpl,
                internal_config=internal_placement_config,
            )
            multimain_timing_params.sweep_timing_failures = []
            return multimain_timing_params

        # What's about to be synthesized, printed BEFORE the long wait below
        # (previously this only appeared after synthesis finished, alongside
        # the achieved MHz - leaving "how many slices/stages did it even try"
        # unknown for the whole duration of a long syn run).
        for plan in plans.values():
            main_logic = parser_state.LogicInstLookupTable[plan.main_inst]
            main_func_name = main_logic.func_name
            if SYN.LOGIC_IS_ZERO_DELAY(main_logic, parser_state, allow_none_delay=True):
                continue
            _mono, _regions, total_stages = SUMMARIZE_SUBTREE_PIPELINE(
                plan.main_inst, plan.subtrees, tpl, parser_state
            )
            print(
                f"[sweep] {main_func_name}: about to synthesize, "
                f"cuts={sum(len(c) for c in plan.cuts.values())}, "
                f"{total_stages} slice(s) "
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
                            # Its interior is fixed, but the full design has
                            # not necessarily proved the cheapest side for
                            # each boundary bank.  Try compact output/input
                            # covers and single-sided endpoint variants before
                            # giving up or restoring the historical both-I/O
                            # shape.
                            next_boundary_strategy = (
                                TRY_NEXT_MINISWEEP_BOUNDARY_STRATEGY(
                                    plan, hotspot_func, parser_state
                                )
                            )
                            if next_boundary_strategy is not None:
                                print(
                                    f"[sweep] Locked {hotspot_func} remains on "
                                    f"the critical path; trying "
                                    f"{next_boundary_strategy} boundary policy.",
                                    flush=True,
                                )
                                plan.same_mhz_count = 0
                                plan.last_mhz = None
                                action = (
                                    f"refine(minisweep boundary "
                                    f"{next_boundary_strategy})"
                                )
                                made_change = True
                            elif plan.same_mhz_count >= 1:
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
                            # A repeated, attributed helper is worth an early
                            # isolated probe. RUN_HOTSPOT_MINISWEEP measures
                            # that helper before making a lock, so an estimate
                            # elsewhere in the hierarchy is not a reason to
                            # keep globally densifying past a compact repeated
                            # solution. If the probe cannot find a nonzero
                            # internal cut, ordinary feedback densification
                            # continues below.
                            if (
                                plan.hotspot_streak[hotspot_func]
                                >= MINISWEEP_HOTSPOT_STREAK
                                and plan.minisweeps_used < MAX_MINISWEEPS
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
                    if (
                        not met
                        and plan.placement_mode == "automatic"
                        and plan.active_placement_refinement is None
                        and not plan.chunked_mux_refinement_attempted
                    ):
                        # Before spending another full synthesis on more
                        # stages, try the bounded physical neighbor which
                        # replaces selected packed-MUX output banks with a
                        # midpoint bit boundary.  The terminal MUX is included
                        # so a formerly unregistered tail does not retain the
                        # same high-fanout select path.  Delay-scale feedback
                        # computed above is retained for use only if this
                        # neighbor also fails.
                        refined_subtrees = {}
                        changed = False
                        for subtree_root in plan.subtrees:
                            landscape = plan.landscapes.get(subtree_root)
                            current = list(
                                plan.placements.get(subtree_root, ())
                            )
                            refinement = None
                            if landscape is not None:
                                refinement = BUILD_CHUNKED_MUX_REFINEMENT(
                                    current, landscape, parser_state
                                )
                            if refinement is None:
                                refined_subtrees[subtree_root] = (
                                    list(plan.cuts.get(subtree_root, ())),
                                    current,
                                )
                            else:
                                refined_subtrees[subtree_root] = refinement
                                changed = True
                        if changed:
                            candidate_fingerprint = (
                                PIPELINE_PLACEMENT_FINGERPRINT(
                                    {
                                        subtree_root: placements
                                        for subtree_root, (
                                            _cuts,
                                            placements,
                                        ) in refined_subtrees.items()
                                    },
                                    plan.locked,
                                )
                            )
                            if (
                                candidate_fingerprint
                                not in plan.attempted_placement_fingerprints
                            ):
                                plan.pending_placement_refinement = {
                                    "kind": "chunked_mux",
                                    "fingerprint": candidate_fingerprint,
                                    "subtrees": refined_subtrees,
                                }
                                plan.stopped_reason = None
                                action = (
                                    "refine(chunked MUX boundaries)"
                                )
                                made_change = True
                    if not met and plan.placement_mode == "replace":
                        # Controlled frozen-placement A/B: synthesize exactly
                        # the supplied hardware once and report its result.
                        # Any densify scale computed by the generic failure
                        # branch above is deliberately ignored.
                        plan.stopped_reason = "internal_forced_placement_result"
                        action = "stop(internal forced placement result)"
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
            best_plan_placements = {
                mi: copy.deepcopy(p.placements) for mi, p in plans.items()
            }
            best_plan_locks = {
                mi: copy.deepcopy(p.locked) for mi, p in plans.items()
            }
            best_plan_boundary_diagnostics = {
                mi: copy.deepcopy(p.mini_sweep_boundary_diagnostics)
                for mi, p in plans.items()
            }

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
                    met_snapshot_plan_placements = {
                        mi: copy.deepcopy(p.placements) for mi, p in plans.items()
                    }
                    met_snapshot_plan_locks = {
                        mi: copy.deepcopy(p.locked) for mi, p in plans.items()
                    }
                    met_snapshot_plan_boundary_diagnostics = {
                        mi: copy.deepcopy(p.mini_sweep_boundary_diagnostics)
                        for mi, p in plans.items()
                    }
                trim_candidates = []
                for p in plans.values():
                    if (
                        p.stopped_reason is not None
                        or p.placement_mode == "replace"
                    ):
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
                if mi in met_snapshot_plan_placements:
                    p.placements = met_snapshot_plan_placements[mi]
                if mi in met_snapshot_plan_locks:
                    p.locked = met_snapshot_plan_locks[mi]
                if mi in met_snapshot_plan_boundary_diagnostics:
                    p.mini_sweep_boundary_diagnostics = (
                        met_snapshot_plan_boundary_diagnostics[mi]
                    )
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
                if mi in best_plan_placements:
                    p.placements = best_plan_placements[mi]
                if mi in best_plan_locks:
                    p.locked = best_plan_locks[mi]
                if mi in best_plan_boundary_diagnostics:
                    p.mini_sweep_boundary_diagnostics = (
                        best_plan_boundary_diagnostics[mi]
                    )
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
            f"[sweep] {main_func_name}: {outcome}, {total_stages} slice(s) built "
            f"({total_stages + 1} pipeline stages), "
            f"cuts={sum(len(c) for c in plan.cuts.values())}, "
            f"locked={len(plan.locked)} inst(s), iterations={iteration}",
            flush=True,
        )
    WRITE_PIPELINE_PLACEMENT_TRACE(
        plans,
        parser_state,
        multimain_timing_params.TimingParamsLookupTable,
        internal_config=internal_placement_config,
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
