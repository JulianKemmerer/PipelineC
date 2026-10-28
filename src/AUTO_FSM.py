"""AUTO_FSM: implement a pure combinational function as a resource-shared FSM.

Where AUTO_PIPELINE cuts a function into stages for throughput, AUTO_FSM shares
units across clock cycles for area. The default search also considers the
combinational rewrites shared with AUTO_COMB_AREA_OPT, comparing complete scheduled
hardware including muxes, registers and control. Twelve identical adders can
become one adder used in twelve states; unsharing remains an area/timing choice.

If you have not done this kind of thing before, the two classic HLS steps are:

  * SCHEDULING - assign each operation of the dataflow graph to a time step
    (here: an FSM state), respecting data dependencies and a per-state delay
    budget (whatever chain of operations runs combinationally within one state
    must fit in one clock period).
  * BINDING - decide which physical hardware runs each operation. Two
    operations of the same kind placed in different states can share one
    "functional unit" (FU); the price is multiplexers selecting that unit's
    operands per state. Sharing is the entire point: it is what turns N copies
    of an adder into one.

Some vocabulary used throughout, in this codebase's terms:

  entity / Logic   one function definition; `parser_state.FuncLogicLookupTable`
                   maps entity name -> Logic. Every CALL SITE is a separate
                   hardware instance (`Logic.submodule_instances`), so nothing
                   is shared anywhere in the compiler by default -- AUTO_FSM
                   creates sharing by generating code with exactly ONE call
                   site per functional unit.
  delay unit (du)  tenths of a nanosecond. `Logic.delay` is an int in these
                   units (SYN.DELAY_UNIT_MULT == 10.0).
  glue             an operation with zero delay: struct field reads, constant
                   shifts, rewiring. Free, so it is never scheduled or shared;
                   it is just re-rendered inline wherever its value is used.
  node             one operation of the DAG, identified by its local instance
                   name in the Logic graph (op name + source coordinates, which
                   makes it a pure function of the source and therefore stable
                   across the driver's repeated re-elaborations).

Where the pieces live:

  pypeline.AUTO_FSM            the user-facing tag object (src/pypeline.py).
                              Holds .latency and the installed schedule.
  PY_TO_LOGIC._elab_call      probes for the tag at a call site and asks
                              BUILD_AUTO_FSM_FUNC (below) what to instantiate.
  AUTO (src/AUTO.py)          the machinery shared with AUTO_COMB_OPT: building
                              the DAG from the elaborated Logic graph (BUILD_DAG),
                              type resolution, the delay and area models,
                              source emission helpers.
  THIS MODULE                 schedules + binds the DAG, and GENERATES ORDINARY
                              PYPELINE PYTHON SOURCE implementing the FSM.
                              DO_SCHEDULE_PASSES (below) drives the
                              schedule-and-confirm loop: measure delays ->
                              schedule -> re-elaborate -> synthesize -> if an
                              FSM is blamed for a timing failure, tighten its
                              budget and reschedule -- until a tightening stops
                              raising fmax. Called from
                              AUTO_PIPELINE.DO_PIPELINED_BUILD. Every re-parse
                              inside a build goes through REPARSE (below), which
                              schedules call sites new to the build.

Generating Python source (rather than a new backend IR) is what keeps this
feature small: the generated FSM is elaborated by the same path as hand-written
pypeline, and because it holds non-volatile Reg state, SYN and SWEEP already
treat it correctly -- unsliceable, zero added latency, measured as one atomic
block whose delay becomes an fmax floor.

See docs/AUTO_FSM_DESIGN.md for the full design, docs/AUTO_DESIGN.md for the
shared machinery, docs/SYN_DESIGN.md for the delay model, and
docs/SWEEP_DESIGN.md for the sweep this rides on.
"""

import copy
import collections
import re
import hashlib
import json
import math
import multiprocessing
import multiprocessing.connection
import os
import pickle
import zlib

import LOGIC
import AUTO
import SYN
from pypeline import _AUTO_FSM_SCHEDULE_VERSION

# Schedule dict format version, bumped if the shape changes incompatibly OR the
# generated hardware changes for an unchanged schedule -- the entity name is a
# hash of the schedule, so codegen-only changes would otherwise reuse delays
# measured against different logic.
# 3: v3 constant-LUT control path (`ctl` field, see _Codegen).
# 4: glue operands materialize their port type (_render_operand at_port_type).
# 5: operand muxes select distinct values per port, rather than blindly
#    allocating one row per operation sharing the functional unit.
# 6: area-aware cross-FU register binding and optional combinational output.
# 7: structural mux factoring, rolling consume/produce storage, and compact
#    field-granular transaction input registers change generated hardware even
#    though the underlying operation schedule is unchanged.
# 8: schedules carry the input type for whole-transaction storage accounting,
#    including alternate combinational source graphs.
# 9: constant-aware typed graph cleanup and constant-specialized units.
# 10: unit implementations, launch/completion states and pinned recipes.
# 11: typed adapters, balanced selections and recurring fused functional units.
# 12: source and target context validation for carried schedules.
# 13: measured control tables, parallel select arrival and local timing repair.
# 14: inline control with width-keyed timing proxies and repair stall checks.
# 15: sparse pinned recipes with explicit restoration of implicit zero placements.
SCHEDULE_VERSION = _AUTO_FSM_SCHEDULE_VERSION

# How the generated FSM's CONTROL path is rendered. This selects codegen shape
# AND the matching area model -- the two must agree, so it is part of the
# schedule (hence hashed into the entity name), not a codegen-time afterthought.
# Without that, a codegen-only change would silently reuse measured delays
# cached against genuinely different hardware.
#   "v3"     constant lookup tables: per-FU select LUTs, per-register write
#            enable LUTs, next-state LUT. One comparator survives per FSM.
#   "v2"     the shipped comparator chains (`if st == k: ... elif ...`), kept
#            for A/B measurement and debugging.
#   "onehot" direct one-hot decode: the state bits themselves are the enables.
#   "auto"   build/rank v3 and onehot schedules independently and keep the
#            smaller area estimate that satisfies timing and max_latency.
CTL_CHOICES = ("auto", "v3", "v2", "onehot")
DEFAULT_CTL = "auto"

# Maximum schedule+synthesize passes before giving up on meeting timing by
# adding states (mirrors AUTO_PIPELINE.AUTO_PIPELINE_MAX_LATENCY_PASSES). Six rather than
# four because a pass may now also be spent absorbing freshly MEASURED operand
# mux delays (see the mux section below): the first build of a given mux shape
# schedules against the model, and the pass after it knows the real number.
MAX_SCHEDULE_PASSES = 6

# Fraction of the target clock period a state's operation chain may fill by the
# delay model's own reckoning. Below 1.0 because the model does not account for
# the operand multiplexers and writeback enables the FSM itself adds around
# every functional unit. Overridable per build with --auto_fsm_budget_scale.
DEFAULT_BUDGET_SCALE = 0.9

# Multiplied into budget_scale for an AUTO_FSM blamed for a timing failure that
# reported no achieved MHz; with one, the measured miss sets the step instead
# (see TIGHTENED_BUDGET_SCALE).
BUDGET_TIGHTEN_FACTOR = 0.75

# Minimum relative fmax gain a tightened (rescheduled) build must show over the
# build before it. A tightening whose build did not move fmax changed the FSM's
# states but not the critical path -- that path runs somewhere the state count
# cannot reach (the FSM's own control, e.g. the input-capture enable fanning out
# to every input register bit, or elsewhere in the MAIN) -- so the driver stops
# instead of shrinking further. Found on sky130: 102.25 MHz at 2, 3 and 6
# states, with the budget then shrunk below one adder until the schedule
# decomposed into gates. 1% absorbs run-to-run tool noise while still counting
# any real improvement.
TIGHTEN_MIN_FMAX_GAIN = 0.01

# How many times the driver may tighten a budget (TIGHTENED_BUDGET_SCALE)
# looking for one that actually changes the schedule, before concluding more
# states cannot help.
MAX_TIGHTEN_STEPS = 8


# Cap on generated entity/function name length, for VHDL identifier safety.
_MAX_NAME_LEN = 96

AREA_PER_STATE_DECODE = 1.0  # ctl "v2" only: per-state next-state/enable decode

# ── Control path, ctl "v3" ────────────────────────────────────────────────
# v3 decodes state with constant lookup tables instead of a comparator per
# state per unit. A table's leaves are constants, so synthesis folds it to
# roughly one 2-input gate per OUTPUT BIT -- hence the same 0.16 the other
# per-bit gate terms use, charged per bit of table output rather than per state.
AREA_PER_CTL_LUT_BIT = 0.16
# What is left per state once the tables are priced: clock-enable fanout and
# the routing of `st` to every table. Much smaller than v2's per-state decode
# because the decode itself is no longer per-state.
AREA_PER_STATE_CTL = 0.2
# ── Area sweep ────────────────────────────────────────────────────────────
# How many "open one more entity" moves the search may accept before stopping.
# Each move costs one full reschedule per remaining candidate entity, so this
# bounds the search at O(MAX_SWEEP_MOVES * n_entities) schedules -- all pure
# computation, no synthesis.
MAX_SWEEP_MOVES = 24

# A move must beat the BEST-SO-FAR by at least this fraction of its estimated
# area to become the new best. Without it the search chases model noise,
# churning the schedule (and therefore the generated entity name) for no real
# gain.
#
# SET FROM MEASURED MODEL ERROR, not from taste. The estimate is only a ranking
# of abstract units, and how far it can be trusted was unknown until the div
# design in auto_fsm_min_area_verify_test was built both ways: sharing a divider
# whole came to 979 yosys cells, opening it up across 36 states came to 1680 --
# 72% WORSE -- and the model rated that same move a 3% improvement. So the
# model's error between schedules of very different shape is tens of percent,
# and a threshold of 0.01 was licensing the search to act on differences an
# order of magnitude smaller than its own accuracy.
#
# The cost of setting this high is a missed opportunity (the anchor is kept);
# the cost of setting it low is shipping a design 70% bigger than the one the
# user would have got by not running the search at all. Those are not
# symmetric, which is why this sits well above the largest mis-ranking seen
# rather than just above it.
SWEEP_MIN_IMPROVEMENT = 0.25

# Extra confidence required when an OPEN move makes the scheduled shape much
# larger than the written-grain anchor.  A per-leaf area sum cannot see
# cross-instance sharing performed by flattened/no-hierarchy synthesis: it
# prices every repeated leaf inside an atomic composite, then appears to remove
# all those copies when the composite is opened and the leaves bind to one FU
# each.  Real synthesis may already have shared much of the anchor, while the
# opened FSM still pays for many more state-control decisions, live values and
# mux inputs.  That is a systematic shape-dependent error, not noise that can
# be fixed by retuning a measured mux or FF price.
#
# Require eight additional percentage points of modelled win per doubling of
# scheduled operations or states relative to the anchor.  This applies only to
# candidates that OPEN an entity; UNSHARE keeps the same DAG and its unit/mux/
# register trade is represented directly by the measured model.  The value is
# pinned by auto_fsm_min_area_verify_test.py: its 5-op/3-state anchor grows to
# 254 ops/60 states, the raw per-leaf sum predicts a 59.6% win, and whole-design
# yosys instead measures a 54.6% regression.  A 50.8x shape increase therefore
# needs a 70.3% win before it is trusted.
SWEEP_SHAPE_RISK_PER_DOUBLING = 0.08
SWEEP_MAX_REQUIRED_IMPROVEMENT = 0.95

# How many consecutive non-improving moves the search will walk through before
# giving up.
#
# This is what makes the search find CONVERGENCE wins. Opening one operation
# usually costs area on its own -- one shared unit becomes its unshared guts.
# The payoff comes when a SECOND operation is opened and the two turn out to be
# built from the same smaller pieces, which then share. A search that stopped
# at the first non-improving move could never reach that, because the win is
# only visible from the far side of the move that pays for it. So the search
# keeps walking down the granularity axis for a few moves, remembering the best
# point it has seen, and stops once several moves in a row have failed to beat
# it -- the point where multiplexer and register cost has taken over from unit
# cost for good.
MAX_SWEEP_UPHILL = 4

# Refuse to even score a candidate whose flattened DAG is bigger than this.
# Decomposing to gate granularity is exponential in the worst case, and a DAG
# this size cannot possibly schedule into a sane number of states anyway -- the
# cap keeps a runaway candidate from making the search itself the bottleneck.
# Deliberately a size cap, never a wall-clock one: the schedule must stay a
# pure function of the source (see _schedule_entity_name).
MAX_SWEEP_DAG_NODES = 20000

# Advisory threshold (never a cap -- see _warn_large_schedule): folds onto one
# shared unit past which BUILD_SCHEDULE prints a one-time notice before
# calling SCHEDULE_DAG. AUTO_FSM's own scheduling cost is superlinear in
# folds-per-unit (SCHEDULE_DAG retries placements state by state, each
# attempt walking the FU-edge graph reachable from it; ALLOCATE_REGISTERS and the
# operand-mux plan both scale with live cross-state values), and a single
# schedule at a few hundred folds can run for a long time with nothing
# printed -- exactly what happened when register_soft_mult()'s default
# switched to a 30-level carry-save multiplier (folds 247 adds onto one unit
# at uint16 x uint16) and qor_multiplier_auto_fsm_test hung silently for
# hours. Calibrated off every default-flag schedule in the repo: divider 32,
# sqrt 16, the multiplier's shipping uint8 default 36 -- all comfortably
# under this; the uint16 runaway is 247, well past it.
SWEEP_LARGE_SCHEDULE_FOLDS = 64


class AutoFsmInternalError(AUTO.AutoError):
    """An AUTO_FSM invariant broke -- a compiler bug, not a property of the
    design. A subclass so the area search, which treats AutoError as "this
    candidate is not schedulable, try the next one", can let it through
    instead of quietly discarding the evidence."""


# ─────────────────────────────────────────────
# Tag discovery
# ─────────────────────────────────────────────


def DESIGN_HAS_AUTO_FSM(parser_state) -> bool:
    """True if any elaborated function instantiates an AUTO_FSM call site."""
    for logic in parser_state.FuncLogicLookupTable.values():
        if logic.sub_inst_to_auto_fsm_key:
            return True
    return False


def COLLECT_AUTO_FSM_KEYS(parser_state):
    """Set of AUTO_FSM canonical keys instantiated anywhere in the design."""
    keys = set()
    for logic in parser_state.FuncLogicLookupTable.values():
        keys.update(logic.sub_inst_to_auto_fsm_key.values())
    return keys


def GET_TAGS(parser_state) -> dict:
    """canonical_key -> live pypeline.AUTO_FSM tag object, recorded by
    BUILD_AUTO_FSM_FUNC as call sites elaborate."""
    return getattr(parser_state, "pypeline_auto_fsm_tags", {})


# ─────────────────────────────────────────────
# Type resolution: ctype string -> live pypeline type object
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# Operand multiplexers: the price of sharing
# ─────────────────────────────────────────────


def _mux_sel_type(n):
    """Live type of an n-way mux's select input."""
    from operators.auto_fsm_mux import mux_sel_t

    return mux_sel_t(n)


# ─────────────────────────────────────────────
# Decoding elaborated operations back into Python expressions
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# DAG construction
# ─────────────────────────────────────────────


def _snapshot_subtree_delays(parser_state, entity, out=None):
    """Record delay for every entity in a subtree.

    Later schedule passes build the design with the FSM in place, so the pure
    function and its operations are no longer instantiated and carry no measured
    delay. The schedule therefore carries this snapshot forward, which is what
    lets a tightened reschedule work from the same numbers as the first one.
    """
    if out is None:
        out = {}
    if entity in out:
        return out
    logic = parser_state.FuncLogicLookupTable.get(entity)
    if logic is None:
        return out
    # None (never measured) is kept distinct from 0 (measured as free): a later
    # pass sees None for everything inside the pure function, because the FSM
    # replaced it and nothing instantiates it any more.
    out[entity] = logic.delay
    for sub_entity in logic.submodule_instances.values():
        _snapshot_subtree_delays(parser_state, sub_entity, out)
    return out


def _schedule_delays(parser_state, func_entity, snapshot):
    """entity -> delay (du) for everything a schedule of `func_entity` may use.

    What this pass measured, falling back to the previous pass's snapshot. The
    fallback is what makes rescheduling possible at all -- on every pass after
    the first, the FSM has replaced the pure function, so none of its
    operations are instantiated and none of them get measured, yet the
    scheduler still needs their delays to decide how many fit in a (now
    smaller) state.

    Anything in neither is RESOLVED (_resolve_delay_du: path delay cache,
    submodule sum, width heuristic), never defaulted to 0. A 0 here is final --
    _resolve_delay_du trusts a known value -- and a zero-delay operation is
    glue: never scheduled, re-rendered inline at every use. That default once
    turned a combinational candidate's never-instantiated soft-operator gates
    (1269 nodes) into a "0 ops, 1 state" schedule that won the area search,
    then hung codegen re-rendering a carry chain as one exponential inline
    expression. The resolved value is stored, so the carried snapshot is
    complete and later passes schedule from identical numbers.
    """
    live = _snapshot_subtree_delays(parser_state, func_entity)
    delays = {k: v for k, v in snapshot.items() if v is not None}
    for k, v in live.items():
        if v is not None:
            delays[k] = v
    for k in sorted(live):
        if k not in delays:
            delays[k] = AUTO._resolve_delay_du(parser_state, k, delays)
    return delays


def _measured_entities(parser_state, entities, previous_measured):
    """Those of `entities` whose scheduling delay is a synthesis measurement.

    A live delay is this parse's own; anything else came from the carried
    snapshot (measured only if the schedule that carried it said so) or was
    resolved from cache, submodules or width (an estimate). `entities` covers
    generated units too (constant wrappers, selections), which live outside
    the function's own subtree.
    """
    previous_measured = set(previous_measured)
    result = []
    for entity in sorted(set(entities)):
        logic = parser_state.FuncLogicLookupTable.get(entity)
        if logic is not None and logic.delay is not None:
            if not logic.delay_is_estimated:
                result.append(entity)
        elif entity in previous_measured:
            result.append(entity)
    return result


# Shifts (SL/SR) are deliberately absent even though operators/soft_shift.py
# ships barrel shifters: the built-in takes its amount at the operand's own
# width, while the barrel takes exactly log2(width) amount bits, so the two
# disagree for any shift amount at or above the operand width -- an
# out-of-range shift zeroes on the built-in and wraps on the barrel. Arity and
# return type match, so _open_target's checks would NOT catch the difference.
# Wiring these up needs an adapter that saturates the amount first.


def _openable(parser_state, entity, logic):
    """Can the area sweep choose to open this operation up?

    Either it has Python source of its own (_is_decomposable), or it is a
    built-in operator for which the soft-operator library provided an
    equivalent -- which is what lets descent continue PAST the built-in
    operators v1 bottomed out at, all the way down to bitwise leaves.
    """
    return AUTO._open_target(parser_state, entity, logic)[0] is not None


# ─────────────────────────────────────────────
# Scheduling and binding
# ─────────────────────────────────────────────


def _scheduled_ids(dag):
    """Node ids that consume a functional unit (delay > 0). Zero-delay glue is
    excluded: it is inlined at each use, never scheduled, never shared."""
    return {nid for nid, n in dag["nodes"].items() if n["delay_du"] > 0}


def _scheduled_deps(dag, ref, sched, out, _seen=None):
    """Collect the scheduled nodes a value depends on, seeing through glue.

    The visited set is not optional bookkeeping: glue is a DAG, not a tree, and
    one free value feeding several others is the normal case (a soft adder's
    carry chain is nothing but that). Without it this walk re-explores every
    shared path once per route into it, which is exponential -- fine for the
    handful of operations v1 ever descended into, fatal the moment the area
    sweep opens an operator into a few hundred gates.
    """
    if ref[0] != "node":
        return out
    nid = ref[1]
    if nid in sched:
        out.add(nid)
        return out
    _seen = set() if _seen is None else _seen
    if nid in _seen:
        return out
    _seen.add(nid)
    node = dag["nodes"].get(nid)
    if node is None:
        return out
    for operand in node["operands"]:
        _scheduled_deps(dag, operand, sched, out, _seen)
    return out


def _OUTPUT_SHIFT_PACKS(nodes, output_ref, n_states):
    """Find unrolled shift/concat accumulations used only by the final result.

    Python loops are gone by the time AUTO_FSM sees the Logic graph, but a very
    common loop-carried value leaves an unmistakable dataflow shape::

        x1 = concat(x0[W-2:0], bit1)
        x2 = concat(x1[W-2:0], bit2)
        ...

    The ordinary live-range analysis sees every ``bitN`` in the final expanded
    expression and allocates one separately-enabled register for each.  A
    handwritten FSM uses one W-bit shift register instead.  Recover that form
    conservatively when:

      * the chain is at least four steps and has a constant/glue-only seed;
      * each appended expression depends on exactly one scheduled one-bit
        result, produced in strictly increasing states before the final state;
      * no scheduled operation consumes the chain (it is output assembly only).

    The returned description is derived data, not stored in the schedule, so
    old schedule serialization stays simple and area/codegen always agree.
    """
    sched = {nid for nid, n in nodes.items() if n["delay_du"] > 0}
    dag = {"nodes": nodes}

    def glue_walk(ref, visit, seen=None):
        if ref[0] != "node":
            return
        nid = ref[1]
        seen = set() if seen is None else seen
        if nid in seen:
            return
        seen.add(nid)
        node = nodes.get(nid)
        if node is None or node["delay_du"] > 0:
            return
        visit(nid, node)
        for operand in node.get("operands", ()):
            glue_walk(operand, visit, seen)

    # A packed chain may not feed a scheduled operation: replacing it with the
    # progressively updated register would then change what an intermediate
    # state observes.  Final-output glue is the only allowed consumer.
    consumed_by_schedule = set()
    consumed_walk_seen = set()
    for node in nodes.values():
        if node["delay_du"] <= 0:
            continue
        for operand in node.get("operands", ()):
            glue_walk(
                operand,
                lambda nid, _node: consumed_by_schedule.add(nid),
                consumed_walk_seen,
            )

    seed_memo = {}

    def is_seed(ref):
        if ref[0] in ("const", "lit"):
            return True
        if ref[0] != "node":
            return False  # in/inlined/unknown: transaction-dependent seed
        nid = ref[1]
        if nid in seed_memo:
            return seed_memo[nid]
        node = nodes.get(nid)
        if node is None or node["delay_du"] > 0:
            return False
        seed_memo[nid] = all(is_seed(operand) for operand in node.get("operands", ()))
        return seed_memo[nid]

    def match_chain(root_ref):
        if root_ref[0] != "node":
            return None
        root_id = root_ref[1]
        root = nodes.get(root_id)
        if root is None:
            return None
        width = AUTO._ctype_width(root.get("out_type"))
        if width < 2 or AUTO._scalar_ctype_to_type(root.get("out_type")) is None:
            return None

        steps_outer_first = []
        cur = root_ref
        seed_casts = ()
        while cur[0] == "node":
            nid = cur[1]
            node = nodes.get(nid)
            if (
                node is None
                or node["delay_du"] > 0
                or node["op"].get("kind") != "bitmanip"
                or node["op"].get("builtin") != "concat"
                or len(node.get("operands", ())) != 2
                or AUTO._ctype_width(node.get("out_type")) != width
                or AUTO._ctype_width(node.get("port_types", (None, None))[0]) != width - 1
                or AUTO._ctype_width(node.get("port_types", (None, None))[1]) != 1
            ):
                break
            left = node["operands"][0]
            constant_seed = left[0] in ("const", "lit")
            if left[0] != "node" and not constant_seed:
                break
            slice_node = nodes.get(left[1]) if not constant_seed else None
            if not constant_seed and (
                slice_node is None
                or slice_node["delay_du"] > 0
                or slice_node["op"].get("kind") != "bitmanip"
                or slice_node["op"].get("builtin") != "__slice__"
                or slice_node["op"].get("consts") != [width - 2, 0]
                or len(slice_node.get("operands", ())) != 1
            ):
                break
            right = node["operands"][1]
            deps = _scheduled_deps(dag, right, sched, set())
            if len(deps) != 1:
                break
            (dep,) = tuple(deps)
            # Keep the first implementation deliberately narrow: every append
            # is one scheduled result directly.  Factored/glue append values
            # are legal too, but can need a state-selected write-data mux whose
            # area belongs in the model before enabling that broader case.
            if right[0] != "node" or right[1] != dep:
                break
            dep_state = nodes[dep].get("state")
            if dep_state is None or dep_state >= n_states:
                break
            steps_outer_first.append(
                {
                    "state": dep_state,
                    "ref": right,
                    "casts": tuple(node["casts"][1]),
                    "dep": dep,
                }
            )
            if constant_seed:
                # Constant propagation can fold the first seed's low-bit
                # slice. Its top bit is discarded by the first shift anyway.
                cur = left
                seed_casts = tuple(node["casts"][0])
                break
            cur = slice_node["operands"][0]
            seed_casts = tuple(slice_node["casts"][0])

        steps = list(reversed(steps_outer_first))
        states = [step["state"] for step in steps]
        if (
            len(steps) < 4
            or states != sorted(states)
            or len(states) != len(set(states))
            or len({nodes[step["dep"]].get("fu") for step in steps}) != 1
            or len(
                {(nodes[step["dep"]].get("out_type"), step["casts"]) for step in steps}
            )
            != 1
            or not is_seed(cur)
            or root_id in consumed_by_schedule
        ):
            return None
        return {
            "root": root_id,
            "ctype": root["out_type"],
            "width": width,
            "seed_ref": cur,
            "seed_casts": seed_casts,
            "steps": tuple(steps),
        }

    packs = []
    claimed = set()

    def search(ref, seen=None):
        if ref[0] != "node":
            return
        nid = ref[1]
        seen = set() if seen is None else seen
        if nid in seen:
            return
        seen.add(nid)
        pack = match_chain(ref)
        if pack is not None and not ({s["dep"] for s in pack["steps"]} & claimed):
            packs.append(pack)
            claimed.update(s["dep"] for s in pack["steps"])
            return
        node = nodes.get(nid)
        if node is None or node["delay_du"] > 0:
            return
        for operand in node.get("operands", ()):
            search(operand, seen)

    search(output_ref)

    def one_bit_slice_of(ref, source_nid):
        """Return the selected bit when ``ref`` is a direct scalar slice of
        ``source_nid``.  Keeping this direct is intentional: looking through
        arbitrary glue/casts would make it much harder to prove that replacing
        the whole expression by a bit of a rolling register is exact."""
        if ref[0] != "node":
            return None
        node = nodes.get(ref[1])
        if (
            node is None
            or node["delay_du"] > 0
            or node["op"].get("kind") != "bitmanip"
            or node["op"].get("builtin") != "__slice__"
            or len(node.get("operands", ())) != 1
            or tuple(node["operands"][0]) != ("node", source_nid)
            or AUTO._ctype_width(node.get("out_type")) != 1
        ):
            return None
        consts = node["op"].get("consts")
        if not isinstance(consts, (tuple, list)) or len(consts) != 2:
            return None
        hi, lo = consts
        return hi if hi == lo and isinstance(hi, int) else None

    def later_source_uses(ref, source_nid, state, found, seen=None):
        """Collect replaceable source-bit reads in one later-state value.

        Return false if the source is reachable by any route other than a
        direct one-bit slice.  Scheduled nodes are leaves here: a consumer's
        operand cannot inline another scheduled operation.
        """
        if ref[0] != "node":
            return True
        nid = ref[1]
        if nid == source_nid:
            return False
        node = nodes.get(nid)
        if node is None:
            return True
        bit = one_bit_slice_of(ref, source_nid)
        if bit is not None:
            found.append((nid, state, bit))
            return True
        if node["delay_du"] > 0:
            return True
        seen = set() if seen is None else seen
        if nid in seen:
            return True
        seen.add(nid)
        return all(
            later_source_uses(operand, source_nid, state, found, seen)
            for operand in node.get("operands", ())
        )

    def source_fusion_for(pack):
        """Recognize a consume/produce rolling-buffer recurrence.

        A handwritten bit-serial FSM commonly keeps the unconsumed input bits
        and already-produced output bits in ONE shift register.  Unrolled code
        instead leaves two width-W values in the graph: a source read at
        descending bit indices and an output assembled by W shifts.  Fuse them
        only for the exact full-width, consecutive-state form.  After state
        ``first`` captures the source, state ``first + d`` may read only the
        two positions that a left shift has moved to W-1/W-2::

            original[W-d]   -> rolling[W-1]  (the preceding step's bit)
            original[W-1-d] -> rolling[W-2]  (this step's new bit)

        Every other later use rejects the candidate.  The final output is the
        rolling register's low W-1 bits plus the last produced bit, so it needs
        one one-bit lifetime rather than a second W-bit bank.
        """
        width = pack["width"]
        steps = pack["steps"]
        states = [step["state"] for step in steps]
        if (
            len(steps) != width
            or not states
            or states != list(range(states[0], states[0] + width))
            or n_states != states[-1] + 1
        ):
            return None
        first = states[0]
        step_deps = {step["dep"] for step in steps}
        candidates = []
        for source_nid, source in sorted(nodes.items()):
            if (
                source["delay_du"] <= 0
                or source.get("state") != first
                or source.get("out_type") != pack["ctype"]
                or source_nid in step_deps
            ):
                continue

            uses = []
            valid = True
            for consumer in nodes.values():
                if consumer["delay_du"] <= 0 or consumer.get("state", 0) <= first:
                    continue
                for operand in consumer.get("operands", ()):
                    if source_nid not in _scheduled_deps(dag, operand, sched, set()):
                        continue
                    if not later_source_uses(
                        operand,
                        source_nid,
                        consumer.get("launch_state", consumer["state"]),
                        uses,
                    ):
                        valid = False
                        break
                if not valid:
                    break
            # A direct final-output use cannot be hidden by the rolling
            # rewrite.  (The recovered output chain itself depends only on its
            # appended bit results, not on this source.)
            if valid and source_nid in _scheduled_deps(dag, output_ref, sched, set()):
                valid = False
            replacements = {}
            if valid:
                for slice_nid, state, source_bit in uses:
                    delta = state - first
                    if source_bit == width - delta:
                        rolling_bit = width - 1
                    elif source_bit == width - 1 - delta:
                        rolling_bit = width - 2
                    else:
                        valid = False
                        break
                    key = (slice_nid, state)
                    old = replacements.get(key)
                    if old is not None and old != rolling_bit:
                        valid = False
                        break
                    replacements[key] = rolling_bit
            # Requiring at least one width's worth of distinct reads prevents
            # an incidental short-lived source from paying for a wide init
            # mux.  The divider-shaped recurrence has roughly 2W such reads;
            # serializers/CRC-like recurrences ordinarily have W or more.
            if valid and len(replacements) >= width:
                candidates.append(
                    {
                        "source_dep": source_nid,
                        "source_state": first,
                        "replacements": replacements,
                    }
                )
        # Ambiguity is a reason to stay conservative, not to choose whichever
        # node id happens to sort first.
        return candidates[0] if len(candidates) == 1 else None

    for pack in packs:
        fusion = source_fusion_for(pack)
        if fusion is not None:
            pack["source_fusion"] = fusion
    return tuple(sorted(packs, key=lambda pack: pack["root"]))


def _INPUT_STORAGE_PLAN(nodes, output_ref, n_states):
    """Plan field-granular transaction input storage when it is provably safe.

    The historical code keeps ``Reg[in_t]`` for the complete transaction even
    when a top-level field is consumed only in state 1.  Handwritten FSMs tend
    to load such a field straight into a work register and retain only the
    operands needed by later states.  Recover that form for scalar top-level
    struct fields and array elements represented by direct ``ref`` glue nodes.

    A field used only in the source state of a consume/produce rolling pack,
    and feeding that pack's source operation, may preload the pack on accept.
    Every other referenced field gets its own ordinary input register.  If any
    whole-input, nested-field or non-scalar use exists, return ``None`` and the
    code generator keeps the original whole-value input register.
    """
    sched = {nid for nid, node in nodes.items() if node["delay_du"] > 0}
    direct_input_consumers = set()
    qualified = {}
    for nid, node in nodes.items():
        operands = node.get("operands", ())
        has_direct_input = any(ref[0] == "in" for ref in operands)
        if not has_direct_input:
            continue
        direct_input_consumers.add(nid)
        toks = node.get("op", {}).get("toks")
        if (
            node["delay_du"] <= 0
            and node.get("op", {}).get("kind") == "ref"
            and isinstance(toks, (tuple, list))
            and len(toks) == 1
            and len(operands) == 1
            and operands[0][0] == "in"
            and AUTO._scalar_ctype_to_type(node.get("out_type")) is not None
        ):
            qualified[nid] = (str(toks[0]), node["out_type"])
    if set(qualified) != direct_input_consumers or output_ref[0] == "in":
        return None

    fields = {}
    for nid, (field, ctype) in qualified.items():
        entry = fields.setdefault(
            field, {"field": field, "ctype": ctype, "refs": set(), "states": set()}
        )
        if entry["ctype"] != ctype:
            return None
        entry["refs"].add(nid)

    visited_by_state = {}

    def mark_glue(ref, state):
        # This is a DAG walk, not a path walk. Copying a path-local seen set
        # revisits reconvergent carry-save glue exponentially. A node's field
        # uses are identical for every consumer in the same schedule state.
        seen = visited_by_state.setdefault(state, set())
        pending = [ref]
        while pending:
            ref = pending.pop()
            if ref[0] != "node" or ref[1] in seen:
                continue
            nid = ref[1]
            seen.add(nid)
            node = nodes.get(nid)
            if node is None or node["delay_du"] > 0:
                continue
            hit = qualified.get(nid)
            if hit is not None:
                fields[hit[0]]["states"].add(state)
            pending.extend(node.get("operands", ()))

    for consumer in nodes.values():
        if consumer["delay_du"] <= 0:
            continue
        for operand in consumer.get("operands", ()):
            mark_glue(operand, consumer.get("launch_state", consumer["state"]))
    mark_glue(output_ref, n_states)

    def contains_any(refs, wanted, seen=None):
        seen = set() if seen is None else seen
        pending = list(refs)
        while pending:
            ref = pending.pop()
            if ref[0] != "node":
                continue
            nid = ref[1]
            if nid in wanted:
                return True
            node = nodes.get(nid)
            if node is None or node["delay_du"] > 0:
                continue
            if nid in seen:
                continue
            seen.add(nid)
            pending.extend(node.get("operands", ()))
        return False

    packs = _OUTPUT_SHIFT_PACKS(nodes, output_ref, n_states)
    preload_by_pack = {}
    claimed_fields = set()
    for pack in packs:
        fusion = pack.get("source_fusion")
        if fusion is None:
            continue
        source = nodes[fusion["source_dep"]]
        candidates = []
        for field, entry in sorted(fields.items()):
            if (
                field not in claimed_fields
                and entry["ctype"] == pack["ctype"]
                and entry["states"] == {fusion["source_state"]}
                and contains_any(source.get("operands", ()), entry["refs"])
            ):
                candidates.append(field)
        if len(candidates) == 1:
            field = candidates[0]
            preload_by_pack[pack["root"]] = field
            claimed_fields.add(field)

    stored_fields = tuple(
        {
            "field": field,
            "ctype": entry["ctype"],
            "refs": tuple(sorted(entry["refs"])),
        }
        for field, entry in sorted(fields.items())
        if field not in claimed_fields
    )
    return {
        "stored_fields": stored_fields,
        "preload_by_pack": preload_by_pack,
        "preloaded_fields": tuple(sorted(claimed_fields)),
        "field_refs": {
            field: tuple(sorted(entry["refs"]))
            for field, entry in sorted(fields.items())
        },
    }


def _CROSS_STATE_NODES(nodes, output_ref, n_states):
    """Scheduled results that must survive into a later state, and so need a
    register. Everything else stays a combinational local.

    Uses is computed through glue: a field read in state 5 of a value produced
    in state 2 is still a state-2-to-state-5 use, because the glue itself is
    re-rendered in state 5 rather than stored.

    Shared by the code generator (which declares these registers) and the area
    model (which prices them) -- one definition, so the model can never drift
    from what actually gets built.
    """
    return {
        nid: t
        for nid, (t, _lo, _hi) in _LIVE_RANGES(nodes, output_ref, n_states).items()
    }


def _LIVE_RANGES(nodes, output_ref, n_states):
    """nid -> (c type, first state the value must already be in a register,
    last state that reads it) for every value that crosses a state boundary.

    The range STARTS the state after the one that computes the value: writeback
    happens at the end of a state, so the value only has to be held from the
    next one. That off-by-one is what lets a value written in state 5 reuse the
    register another value was read out of in state 5 -- reads see the snapshot
    committed at the last clock edge, writes land after it.
    """
    dag = {"nodes": nodes}
    sched = {nid for nid, n in nodes.items() if n["delay_du"] > 0}
    used_in_states = {nid: set() for nid in sched}
    for consumer in nodes.values():
        if consumer["delay_du"] <= 0:
            continue  # glue is recomputed where used, never stored
        for operand in consumer["operands"]:
            for dep in _scheduled_deps(dag, operand, sched, set()):
                used_in_states[dep].add(consumer.get("launch_state", consumer["state"]))
    # The final result is assembled in the last state.  Results captured into
    # a recovered rolling output register are consumed in their own producer
    # states instead, so they do not each need a separate long-lived register.
    output_packs = _OUTPUT_SHIFT_PACKS(nodes, output_ref, n_states)
    packed_deps = {step["dep"] for pack in output_packs for step in pack["steps"]}
    # A source fused into a rolling consume/produce register is captured in
    # its producer state; all of its proven later slice reads come from that
    # register instead.  Conversely each produced output bit now survives for
    # exactly one cycle: step N is shifted in during step N+1, and the final
    # bit is joined to the vector in the result state.  The interval allocator
    # consequently binds all W bits to one physical one-bit register.
    for pack in output_packs:
        fusion = pack.get("source_fusion")
        if fusion is None:
            continue
        source_nid = fusion["source_dep"]
        born = nodes[source_nid]["state"]
        used_in_states[source_nid] = {
            state for state in used_in_states[source_nid] if state <= born
        }
        for step in pack["steps"]:
            used_in_states[step["dep"]].add(step["state"] + 1)
    for dep in _scheduled_deps(dag, output_ref, sched, set()):
        if dep not in packed_deps:
            used_in_states[dep].add(n_states)
    out = {}
    for nid in sched:
        born = nodes[nid]["state"]
        later = [s for s in used_in_states[nid] if s > born]
        if later:
            out[nid] = (nodes[nid]["out_type"], born + 1, max(later))
    return out


def ALLOCATE_REGISTERS(nodes, output_ref, n_states, cross_fu_types=()):
    """Bind cross-state values to registers, letting values whose live ranges
    do not overlap SHARE one.

    This is the classic HLS register-binding step, and on a resource-shared FSM
    it is worth more than it looks: with everything folded onto a few units,
    registers are routinely the largest single part of the design -- bigger
    than the shared units they exist to feed. v1 gave every value its own
    register, so a 20-state schedule holding twenty short-lived intermediates
    paid for twenty registers to hold at most a couple of live values at a
    time.

    Left-edge algorithm: take values in order of when they come alive and put
    each into the lowest-numbered register that is free by then. Optimal for
    interval graphs, and deterministic given the tie-break on node id -- which
    it has to be, since the generated source names come out of this.

    Values always need the same c type. By default they must also come from the
    same functional unit, which makes sharing free: the register has one data
    source and merely gains more write-enable states. Types named by
    `cross_fu_types` may additionally share across producing units; those
    registers require a writeback mux, selected by the current state. The
    schedule builder enables that only when real/modelled FF savings exceed the
    mux area AND its measured/modelled delay fits the clock budget.

      * Same unit  -> the register's data input is that unit's output local in
        every state that writes it. The register gains extra write states, i.e.
        a wider enable term. No data path is added at all.
      * Different units -> the register's input becomes a multiplexer between
        two units' outputs, sitting directly in front of a flip-flop, on what
        is usually already the critical path.

    That second case is not a theoretical worry: the old unconstrained
    experiment dropped the donut FSM from 42.4 MHz to 37.5 MHz. That is why
    this allocator never decides to cross units on its own; BUILD_SCHEDULE
    supplies only the types whose FF/mux area comparison wins and whose
    producer paths remain within budget after charging the writeback mux.

    Returns (nid -> register index, register index -> c type).
    """
    ranges = _LIVE_RANGES(nodes, output_ref, n_states)
    order = sorted(ranges, key=lambda nid: (ranges[nid][1], ranges[nid][2], nid))
    cross_fu_types = set(cross_fu_types)
    # per register: (c type, producing units, first state free)
    free_at = []
    # c type -> its registers' indices, ascending: only these can hold a value
    # of that type, so the search below never scans the others.
    regs_of_type = {}
    # (c type, producing unit) -> its registers' indices, ascending. A type
    # outside cross_fu_types only ever reuses a register its own unit fills,
    # and every such register has that one source.
    regs_of_source = {}
    assignment = {}
    reg_types = {}
    for nid in order:
        ctype, lo, hi = ranges[nid]
        fu = nodes[nid].get("fu")
        if ctype in cross_fu_types:
            candidates = []
            for idx in regs_of_type.get(ctype, ()):
                _reg_type, reg_fus, busy_until = free_at[idx]
                same_source = fu in reg_fus
                if busy_until < lo:
                    # Preserve a single-source register whenever possible;
                    # after that, prefer the register with the fewest existing
                    # sources. Merely taking the first free interval can
                    # introduce a mux even though a later free register
                    # already has this FU as its source, losing area for no
                    # live-range benefit.
                    candidates.append((0 if same_source else 1, len(reg_fus), idx))
            chosen = min(candidates)[2] if candidates else None
        else:
            chosen = next(
                (
                    idx
                    for idx in regs_of_source.get((ctype, fu), ())
                    if free_at[idx][2] < lo
                ),
                None,
            )
        if chosen is None:
            chosen = len(free_at)
            free_at.append((ctype, frozenset((fu,)), hi))
            regs_of_type.setdefault(ctype, []).append(chosen)
            regs_of_source.setdefault((ctype, fu), []).append(chosen)
            reg_types[chosen] = ctype
        else:
            reg_fus = free_at[chosen][1] | frozenset((fu,))
            free_at[chosen] = (ctype, reg_fus, hi)
        assignment[nid] = chosen
    return assignment, reg_types


def _register_sources(nodes, reg_of):
    sources = {}
    for nid, idx in reg_of.items():
        fu = nodes[nid].get("fu")
        if fu is not None:
            sources.setdefault(idx, set()).add(_result_source(nodes[nid]))
    return sources


def _result_source(node):
    casts = tuple(node.get("result_casts", ()))
    return (node["fu"], casts, node["out_type"]) if casts else node["fu"]


def _stable_op_key(op):
    """Hashable, deterministic identity for a decoded operation description."""
    return json.dumps(op, sort_keys=True, default=str, separators=(",", ":"))


def _rolling_replacements(schedule, output_packs=None):
    """(glue node, use state) -> structural rolling-register bit identity.
    `output_packs` is the schedule's _OUTPUT_SHIFT_PACKS when the caller has
    already computed it."""
    if output_packs is None:
        output_packs = _OUTPUT_SHIFT_PACKS(
            schedule["nodes"], schedule["output"], schedule["n_states"]
        )
    out = {}
    for pack in output_packs:
        fusion = pack.get("source_fusion")
        if fusion is None:
            continue
        for key, bit in fusion["replacements"].items():
            out[key] = (pack["root"], bit, pack["ctype"])
    return out


class _GlueValueKey:
    """Exact structural DAG key with cached hashing and iterative equality.

    A nested tuple expands a shared child again on every hash/comparison, even
    when the traversal that constructed it was memoized. Keep child keys as
    objects so hashing is constant-time per edge; equality visits each pair
    only once and still checks actual structure when hashes collide.
    """
    __slots__ = ("parts", "_hash")

    def __init__(self, parts):
        self.parts = parts
        self._hash = hash(parts)

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        if not isinstance(other, _GlueValueKey):
            return NotImplemented
        pending = [(self, other)]
        seen = set()
        while pending:
            left, right = pending.pop()
            if left is right:
                continue
            pair = (id(left), id(right))
            if pair in seen:
                continue
            seen.add(pair)
            if isinstance(left, _GlueValueKey) and isinstance(right, _GlueValueKey):
                if left._hash != right._hash:
                    return False
                pending.append((left.parts, right.parts))
            elif isinstance(left, tuple) and isinstance(right, tuple):
                if len(left) != len(right):
                    return False
                pending.extend(zip(left, right))
            elif isinstance(left, _GlueValueKey) or isinstance(right, _GlueValueKey):
                return False
            elif left != right:
                return False
        return True


def _value_equiv_key(nodes, ref, cur_state, reg_of, replacements=None, _seen=None, _memo=None):
    """Structural identity of the expression `_Codegen._render_ref` emits.

    Node ids alone are deliberately not an identity here.  Thirty-two
    different subtract nodes bound to one FU all render as that FU's one output
    local in their respective states; likewise, two separately elaborated glue
    trees made from the same slices/constants render the same value.  This key
    is the shared source of truth for operand-mux row coalescing in both the
    area model and code generator.
    """
    kind = ref[0]
    if kind == "in":
        return ("in", ref[1])
    if kind == "const":
        return ("const", ref[1])
    if kind != "node":
        return ("unknown", tuple(ref))
    nid = ref[1]
    replacement = (replacements or {}).get((nid, cur_state))
    if replacement is not None:
        root, bit, ctype = replacement
        return ("rolling_bit", root, bit, ctype)
    node = nodes.get(nid)
    if node is None:
        return ("missing", nid)
    if node["delay_du"] > 0:
        if node.get("state") == cur_state:
            return ("fu_output", node.get("fu"), node.get("out_type"))
        return ("register", reg_of.get(nid), node.get("out_type"))

    _memo = {} if _memo is None else _memo
    memo_key = (nid, cur_state)
    if memo_key in _memo:
        return _memo[memo_key]
    _seen = set() if _seen is None else _seen
    if nid in _seen:
        return ("glue_cycle", nid)
    _seen.add(nid)
    operands = []
    assemble = node["op"].get("kind") == "assemble"
    for i, operand in enumerate(node.get("operands", ())):
        casts = tuple(node.get("casts", ())[i])
        # Inline glue materializes its port type unless it is struct assembly;
        # include that implicit cast in the equivalence key just as codegen does.
        port_type = None if assemble else node.get("port_types", ())[i]
        operands.append(
            (
                # Keep the replacement map on every recursive descent: the
                # source slice is normally nested inside concat/MUX glue.
                _value_equiv_key(
                    nodes,
                    operand,
                    cur_state,
                    reg_of,
                    replacements,
                    _seen,
                    _memo,
                ),
                casts,
                port_type,
            )
        )
    _seen.remove(nid)
    result = _GlueValueKey((
        "glue",
        _stable_op_key(node["op"]),
        node.get("out_type"),
        tuple(operands),
    ))
    _memo[memo_key] = result
    return result


def _operand_equiv_key(nodes, node, port_i, reg_of, replacements=None, memo=None):
    return (
        _value_equiv_key(
            nodes,
            node["operands"][port_i],
            node["state"],
            reg_of,
            replacements,
            _memo=memo,
        ),
        tuple(node["casts"][port_i]),
        node["port_types"][port_i],
    )


def _operand_factor_plan(
    nodes,
    alternatives,
    reg_of,
    n_users,
    target_type,
    replacements=None,
    _memo=None,
    _plans=None,
):
    """Factor a state-selected value through common zero-delay structure.

    ``alternatives`` contains ``(user_index, ref, casts, state)`` tuples.  The
    old emitter rendered every complete expression and put one mux at the FU
    port.  That loses a particularly important HLS simplification::

        mux(sel, concat(common, a), concat(common, b))
          -> concat(common, mux(sel, a, b))

    Elaborated loops produce this shape constantly: accumulators, shift
    registers, CRCs, serializers and iterative arithmetic all keep most of an
    operand fixed while changing one small leaf.  Factoring the mux through
    glue makes the generated hardware reflect that common structure directly,
    rather than hoping whole-design synthesis rediscovers it across many
    separately elaborated instances.

    The transform is deliberately limited to zero-delay nodes.  Scheduled
    operations remain FU/register leaves, so this cannot duplicate, move or
    combine actual computation across state boundaries.  Mixed root shapes are
    first partitioned and factored independently; this is what turns an
    initial-value-versus-recurrence mux into a small outer mux around a factored
    repeated body.
    """
    alternatives = tuple(alternatives)
    _memo = {} if _memo is None else _memo
    _plans = {} if _plans is None else _plans
    plan_key = (
        target_type,
        n_users,
        tuple(
            (user, tuple(ref), tuple(casts), state)
            for user, ref, casts, state in alternatives
        ),
    )
    if plan_key in _plans:
        return _plans[plan_key]

    def remember(plan):
        _plans[plan_key] = plan
        return plan
    if not alternatives:
        raise AUTO.AutoError("AUTO_FSM: cannot factor an empty operand choice set")

    def exact_key(alt):
        _user_i, ref, casts, state = alt
        return (
            _value_equiv_key(nodes, ref, state, reg_of, replacements, _memo=_memo),
            tuple(casts),
            target_type,
        )

    exact = {}
    for alt in alternatives:
        exact.setdefault(exact_key(alt), []).append(alt)
    if len(exact) == 1:
        return remember({
            "kind": "leaf",
            "target_type": target_type,
            "alternative": alternatives[0],
        })

    # A glue root can be shared only when re-emitting it means the same
    # operation at the same types.  Include entity as well as decoded op:
    # ordinary calls all decode as {"kind": "call"}, but calls to two
    # different functions are of course not interchangeable.
    def root_key(alt):
        _user_i, ref, casts, state = alt
        if ref[0] == "node" and (ref[1], state) in (replacements or {}):
            return ("value", exact_key(alt))
        if ref[0] == "node":
            node = nodes.get(ref[1])
            if (
                node is not None
                and node["delay_du"] <= 0
                and node["op"].get("kind") != "assemble"
                and all(t is not None for t in node.get("port_types", ()))
            ):
                return (
                    "glue",
                    node.get("entity"),
                    _stable_op_key(node["op"]),
                    node.get("out_type"),
                    tuple(node.get("port_types", ())),
                    tuple(casts),
                )
        # Exact values form one group; unrelated terminals become separate
        # choices of the surrounding mux.
        return ("value", exact_key(alt))

    groups = {}
    for alt in alternatives:
        groups.setdefault(root_key(alt), []).append(alt)
    if len(groups) > 1:
        choices = []
        mapping = [0] * n_users
        for row, group in enumerate(groups.values()):
            choices.append(
                _operand_factor_plan(
                    nodes,
                    group,
                    reg_of,
                    n_users,
                    target_type,
                    replacements,
                    _memo,
                    _plans,
                )
            )
            for user_i, _ref, _casts, _state in group:
                mapping[user_i] = row
        return remember({
            "kind": "mux",
            "target_type": target_type,
            "mapping": tuple(mapping),
            "choices": tuple(choices),
        })

    # Multiple non-identical alternatives with one root group must be the same
    # zero-delay operation shape (distinct terminal values were split above).
    first = alternatives[0]
    first_node = nodes[first[1][1]]
    children = []
    for port_i, child_type in enumerate(first_node["port_types"]):
        child_alts = []
        for user_i, ref, _outer_casts, state in alternatives:
            node = nodes[ref[1]]
            child_alts.append(
                (
                    user_i,
                    node["operands"][port_i],
                    tuple(node["casts"][port_i]),
                    state,
                )
            )
        children.append(
            _operand_factor_plan(
                nodes,
                child_alts,
                reg_of,
                n_users,
                child_type,
                replacements,
                _memo,
                _plans,
            )
        )
    return remember({
        "kind": "glue",
        "target_type": target_type,
        "node_id": first[1][1],
        "casts": tuple(first[2]),
        "children": tuple(children),
    })


def _factor_plan_muxes(plan, seen=None):
    """Yield each physical mux once, preserving reconvergent plan sharing."""
    seen = set() if seen is None else seen
    if id(plan) in seen:
        return
    seen.add(id(plan))
    if plan["kind"] == "mux":
        yield (
            plan["target_type"],
            len(plan["choices"]),
            plan["mapping"],
        )
        for child in plan["choices"]:
            yield from _factor_plan_muxes(child, seen)
    elif plan["kind"] == "glue":
        for child in plan["children"]:
            yield from _factor_plan_muxes(child, seen)


def _fu_nodes_in_emit_order(schedule, fu, users=None):
    nodes = schedule["nodes"]
    if users is not None:
        fu_nids = users.get(fu, ())
    else:
        fu_nids = (nid for nid in schedule["node_order"] if nodes[nid].get("fu") == fu)
    return sorted(
        (
            (
                nid,
                dict(
                    nodes[nid],
                    state=nodes[nid].get("launch_state", nodes[nid]["state"]),
                ),
            )
            for nid in fu_nids
        ),
        key=lambda pair: (pair[1]["state"], pair[0]),
    )


def _operand_mux_plan(schedule, fu, reg_of, replacements=None, users=None):
    """Per-port distinct operand rows and state-to-row mappings for one FU.

    Returns `(fu_nodes, ports)`, where each port is a dict containing the
    representative node ids and one class index per FU user.  Class numbering
    is first-use order, which is deterministic and keeps generated tables easy
    to audit. A caller planning every FU of one schedule passes what is the
    same for all of them, so it is computed once: `replacements` (the
    schedule's _rolling_replacements) and `users` (FU -> its node ids in
    node_order, which _fu_nodes_in_emit_order would otherwise rescan the
    whole schedule for).
    """
    fu_nodes = _fu_nodes_in_emit_order(schedule, fu, users)
    if not fu_nodes:
        return fu_nodes, []
    if replacements is None:
        replacements = _rolling_replacements(schedule)
    # Shared only within this immutable plan computation; never carried across
    # schedule mutations or rebindings. All ports/users see the same register
    # map and rolling replacements.
    value_memo = {}
    factor_memo = {}
    seen_muxes = set()
    n_ports = len(fu_nodes[0][1]["operands"])
    ports = []
    for port_i in range(n_ports):
        class_of = {}
        representatives = []
        mapping = []
        for nid, node in fu_nodes:
            key = _operand_equiv_key(
                schedule["nodes"], node, port_i, reg_of, replacements, value_memo
            )
            idx = class_of.get(key)
            if idx is None:
                idx = len(representatives)
                class_of[key] = idx
                representatives.append(nid)
            mapping.append(idx)
        alternatives = [
            (
                user_i,
                node["operands"][port_i],
                tuple(node["casts"][port_i]),
                node["state"],
            )
            for user_i, (_nid, node) in enumerate(fu_nodes)
        ]
        target_type = fu_nodes[0][1]["port_types"][port_i]
        implementation = schedule.get("implementations", {}).get(
            schedule["fus"][fu], {}
        )
        factor_plan = _operand_factor_plan(
            schedule["nodes"],
            alternatives,
            reg_of,
            len(fu_nodes),
            target_type,
            replacements,
            value_memo,
            factor_memo,
        )
        ports.append(
            {
                # Retained for diagnostics/tests and for compatibility with
                # schedules inspected by downstream code.  Hardware emission
                # and costing use the factored plan below.
                "representatives": representatives,
                "mapping": tuple(mapping),
                "n_choices": len(representatives),
                "factor_plan": factor_plan,
                "muxes": (
                    ((target_type, len(representatives), tuple(mapping)),)
                    if implementation.get("registered_selection")
                    else tuple(_factor_plan_muxes(factor_plan, seen_muxes))
                ),
            }
        )
    return fu_nodes, ports


def _selector_shapes(schedule, fu, fu_nodes, ports):
    implementation = schedule.get("implementations", {}).get(schedule["fus"][fu], {})
    if implementation.get("registered_selection"):
        return {(tuple(range(len(fu_nodes))), implementation["selection_rows"])}
    return {
        (mapping, n) for port in ports for _ctype, n, mapping in port["muxes"] if n >= 2
    }


def _critical_path(dag, sched, preds, implementations=None, budget_du=None):
    """Longest remaining delay from each node to any output, used as the list
    scheduler's priority: whatever is on the longest chain goes first, so the
    chain does not become the thing that forces extra states at the end."""
    succs = {nid: [] for nid in sched}
    for nid in sched:
        for p in preds[nid]:
            succs[p].append(nid)
    memo = {}

    def walk(nid, stack):
        if nid in memo:
            return memo[nid]
        if nid in stack:
            raise AUTO.AutoError(f"AUTO_FSM: dependency cycle at {nid!r}")
        stack.add(nid)
        best = 0
        for s in succs[nid]:
            best = max(best, walk(s, stack))
        stack.discard(nid)
        node = dag["nodes"][nid]
        implementation = (implementations or {}).get(node["entity"], {})
        latency = implementation.get("latency", 0)
        if latency and budget_du is None:
            raise AutoFsmInternalError(
                "AUTO_FSM: a pipelined critical path needs a clock budget"
            )
        memo[nid] = best + node["delay_du"] + latency * (budget_du or 0)
        return memo[nid]

    for nid in sched:
        walk(nid, set())
    return memo


def _fu_id(entity, copy_index):
    """Identity of one physical shared unit. Normally one per entity; a second
    copy only appears when a hard max_latency cap cannot be met by sharing
    everything (see SCHEDULE_DAG). The schedule keeps fu_id -> entity as an
    explicit map rather than assuming they are the same string, which is also
    the indirection used by compatible unsigned width adapters."""
    return entity if copy_index == 0 else f"{entity}#{copy_index}"


# ──────────────────────────────────────────────────────────────────────
# Functional units and pinned pipeline implementations
# ──────────────────────────────────────────────────────────────────────


def _prepare_unit_candidates(tag, parser_state, elaborator):
    """Retain the elaboration context for candidates discovered by scheduling."""
    parser_state.pypeline_auto_fsm_elaborators[tag.canonical_key] = elaborator


def _unit_function(parser_state, key, node, selection_rows=None):
    """Materialize a pure callable without changing an operation's dispatch."""
    import pypeline

    node = dict(node, out_type=node.get("physical_out_type", node["out_type"]))
    entity = node["entity"]
    cache_key = entity if selection_rows is None else (entity, selection_rows)
    cached = parser_state.pypeline_auto_fsm_unit_functions.get(cache_key)
    if cached is not None:
        return cached
    elaborator = parser_state.pypeline_auto_fsm_elaborators.get(key)
    if elaborator is None:
        return None
    if selection_rows is not None:
        base = _unit_function(parser_state, key, node)
        if base is None:
            return None
        types = AUTO._TypeResolver()
        types.seed_callable(base["function"])
        emitter = AUTO._Emitter()
        emitter.inj_named(pypeline.hw_func, "hw_func")
        select_type = pypeline.make_uint_t(max(1, (selection_rows - 1).bit_length()))
        arguments = [f"selected: {emitter.inj(select_type, 't')}"]
        for i, ctype in enumerate(node["port_types"]):
            array_type = pypeline.make_array_t(types.resolve(ctype), selection_rows)
            arguments.append(f"rows{i}: {emitter.inj(array_type, 't')}")
        identity = AUTO.frozen(
            (base["entity"], selection_rows, node["port_types"], node["out_type"])
        )
        name = (
            "auto_fsm_selected_unit_"
            + hashlib.sha256(identity.encode()).hexdigest()[:20]
        )
        emitter.line("@hw_func")
        emitter.line(
            f"def {name}({', '.join(arguments)}) -> {emitter.inj(types.resolve(node['out_type']), 't')}:"
        )
        for i, ctype in enumerate(node["port_types"]):
            mux = emitter.inj(
                AUTO._mux_callable(types.resolve(ctype), selection_rows), "mux"
            )
            emitter.line(
                f"    a{i}: {emitter.inj(types.resolve(ctype), 't')} = {mux}(selected, rows{i})"
            )
        call = emitter.inj(base["function"], "unit")
        emitter.line(
            f"    return {call}({', '.join(f'a{i}' for i in range(len(node['port_types'])))})"
        )
        fn = AUTO._exec_generated(name, emitter.src(), emitter.globals)
        logic = elaborator._elaborate_live_func(name, fn)
        AUTO._RESOLVE_BUILTIN_SUBMODULES(parser_state, logic.func_name)
        result = {"function": fn, "entity": logic.func_name}
        parser_state.pypeline_auto_fsm_unit_functions[cache_key] = result
        return result
    if node["kind"] == "call":
        fn = AUTO._entity_callables(parser_state).get(entity)
        if fn is not None:
            result = {"function": fn, "entity": entity}
            parser_state.pypeline_auto_fsm_unit_functions[entity] = result
            return result
        return None
    if node["kind"] != "binop" or node["op"].get("op") not in (
        "+",
        "-",
        "*",
        "==",
        "!=",
        "<",
        "<=",
        ">",
        ">=",
    ):
        return None
    if entity not in parser_state.pypeline_builtin_op_info:
        return None
    from operators.comb_opt import _primitive_math

    types = AUTO._TypeResolver()
    emitter = AUTO._Emitter()
    emitter.inj_named(pypeline.hw_func, "hw_func")
    arguments = [
        f"a{i}: {emitter.inj(types.resolve(t), 't')}"
        for i, t in enumerate(node["port_types"])
    ]
    identity = AUTO.frozen((entity, node["op"], node["port_types"], node["out_type"]))
    name = "auto_fsm_unit_" + hashlib.sha256(identity.encode()).hexdigest()[:20]
    emitter.line("@hw_func")
    emitter.line(
        f"def {name}({', '.join(arguments)}) -> {emitter.inj(types.resolve(node['out_type']), 't')}:"
    )
    expression = AUTO._render_op(
        node["op"],
        [f"a{i}" for i in range(len(arguments))],
        emitter,
        parser_state,
        entity,
    )
    emitter.line(f"    return {expression}")
    fn = _primitive_math(AUTO._exec_generated(name, emitter.src(), emitter.globals))
    opname, ports = parser_state.pypeline_builtin_op_info[entity]
    pypeline.register_operator(
        opname, *(types.resolve(t) for t in ports), pypeline.INFERRED, scope=fn
    )
    logic = elaborator._elaborate_live_func(name, fn)
    AUTO._RESOLVE_BUILTIN_SUBMODULES(parser_state, logic.func_name)
    result = {"function": fn, "entity": logic.func_name}
    parser_state.pypeline_auto_fsm_unit_functions[entity] = result
    return result


def _unit_isolated_tree(parser_state, entity, delays):
    """Own mutable instance/parameter tables; share read-only type metadata."""
    isolated = copy.copy(parser_state)
    isolated.FuncLogicLookupTable = dict(parser_state.FuncLogicLookupTable)
    isolated.LogicInstLookupTable = {}
    isolated.FuncToInstances = {}
    root = "auto_fsm_characterize_" + hashlib.sha256(entity.encode()).hexdigest()[:20]
    isolated.main_mhz = {root: None}
    isolated.main_syn_mhz = {}
    isolated.main_clk_group = {}
    owned = {}
    postorder = []
    representative = {}

    def visit(inst, name):
        if name not in owned:
            logic = copy.copy(parser_state.FuncLogicLookupTable[name])
            logic.delay = AUTO._resolve_delay_du(parser_state, name, delays)
            owned[name] = logic
        logic = owned[name]
        isolated.FuncLogicLookupTable[name] = logic
        isolated.LogicInstLookupTable[inst] = logic
        isolated.FuncToInstances.setdefault(name, set()).add(inst)
        representative.setdefault(name, inst)
        for local, child in sorted(logic.submodule_instances.items()):
            visit(inst + LOGIC.SUBMODULE_MARKER + local, child)
        if name not in postorder:
            postorder.append(name)

    visit(root, entity)
    import AUTO_PIPELINE

    for name in postorder:
        original = parser_state.FuncLogicLookupTable[name]
        logic = owned[name]
        if logic.submodule_instances and (
            original.delay is None or original.delay_is_estimated
        ):
            # A new mux/unit wrapper has no measured through-delay. Its delay
            # is its actual critical path, including repeated serial uses of
            # an entity and excluding parallel branches' summed delays.
            logic.delay = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_PIPELINE_MAP(
                representative[name], logic, isolated, write_files=False
            ).zero_clk_max_delay
    return isolated, root


def _unit_timing_recipe(root, table):
    """Concrete choices relative to the region; omitted descendants are unsliced."""
    return [
        {
            "path": inst[len(root) :],
            "slices": list(params._slices),
            "input_regs": params._has_input_regs,
            "output_regs": params._has_output_regs,
            "bit_boundaries": params._exact_bit_boundaries,
        }
        for inst, params in sorted(table.items())
        if inst == root
        or (
            inst.startswith(root + LOGIC.SUBMODULE_MARKER)
            and (
                params._slices
                or params._has_input_regs
                or params._has_output_regs
                or params._exact_bit_boundaries is not None
            )
        )
    ]


def _unit_recipe_digest(recipe):
    return hashlib.sha256(AUTO.frozen(recipe).encode()).hexdigest()


def _unit_candidate_nodes(parser_state, schedule):
    """Bound operations plus pure helper boundaries lost through descent."""
    candidates = {n["entity"]: n for n in schedule["nodes"].values() if n.get("fu")}
    for entity in sorted(AUTO._subtree_entities(parser_state, schedule["func_entity"])):
        if entity == schedule["func_entity"] or entity in candidates:
            continue
        logic = parser_state.FuncLogicLookupTable[entity]
        if AUTO._entity_callables(parser_state).get(entity) is None:
            continue
        delay = AUTO._resolve_delay_du(
            parser_state, entity, schedule["entity_delays_snapshot"]
        )
        if delay <= 0 or len(logic.outputs) != 1:
            continue
        ports = [port for port in logic.inputs if port != LOGIC.CLOCK_ENABLE_NAME]
        candidates[entity] = {
            "kind": "call",
            "op": {"kind": "call"},
            "entity": entity,
            "delay_du": delay,
            "operands": [["in", port] for port in ports],
            "casts": [[] for _port in ports],
            "port_types": [logic.wire_to_c_type[port] for port in ports],
            "out_type": logic.wire_to_c_type[logic.outputs[0]],
        }
    counts = {}

    def uses(entity):
        if entity not in counts:
            total = collections.Counter({entity: 1})
            for child in parser_state.FuncLogicLookupTable[
                entity
            ].submodule_instances.values():
                total.update(uses(child))
            counts[entity] = total
        return counts[entity]

    occurrences = uses(schedule["func_entity"])
    bound = collections.Counter(
        node["entity"] for node in schedule["nodes"].values() if node.get("fu")
    )
    return [
        dict(
            candidates[entity], unit_occurrences=max(occurrences[entity], bound[entity])
        )
        for entity in sorted(candidates)
    ]


def _unit_profiles(
    parser_state,
    key,
    node,
    delays,
    selection_rows=None,
    through_latency=None,
    until=None,
):
    """Pipelined profiles L=1.., characterized only as deep as a caller asks.

    Depths are planned in order, and the cache resumes where an earlier call
    stopped. Without a limit the walk runs to K*: the first count whose
    predicted worst stage stops improving, or the legal end. `through_latency`
    stops once that count is planned; `until(profiles)` stops once it is true.
    """
    import AUTO_PIPELINE
    import SWEEP

    node = dict(node, out_type=node.get("physical_out_type", node["out_type"]))
    unit = _unit_function(parser_state, key, node, selection_rows)
    if unit is None:
        return []
    subtree = sorted(AUTO._subtree_entities(parser_state, unit["entity"]))
    geometry = []
    if any(
        kind in ("state", "feedback", "global", "temporal", "unresolved")
        for _path, _name, kind, _detail in AUTO.FIND_EFFECTS(
            parser_state, unit["entity"]
        )
    ):
        return []
    for entity in subtree:
        logic = parser_state.FuncLogicLookupTable[entity]
        geometry.append(
            (
                entity,
                logic.submodule_instances,
                logic.wire_driven_by,
                logic.wire_to_c_type,
                AUTO._resolve_delay_du(parser_state, entity, delays),
            )
        )
    context = _unit_recipe_digest((_target_context(parser_state), geometry))
    state = parser_state.pypeline_auto_fsm_unit_profiles.setdefault(
        context, {"profiles": [], "count": 1, "previous_ns": None, "done": False}
    )

    def satisfied():
        if state["done"]:
            return True
        if through_latency is not None:
            return state["count"] > through_latency
        if until is not None:
            return until(state["profiles"])
        return False

    if satisfied():
        return state["profiles"]
    # Advanced as a new object, never in place, so a forked characterization
    # returns it as a changed cache entry (_map_forked).
    state = dict(state, profiles=list(state["profiles"]))
    parser_state.pypeline_auto_fsm_unit_profiles[context] = state
    isolated, root = _unit_isolated_tree(parser_state, unit["entity"], delays)
    # This unique root makes the existing instance-keyed zero-clock caches
    # independent of every real MAIN and every other unit characterization.
    zero = {
        inst: AUTO_PIPELINE.TimingParams(inst, logic)
        for inst, logic in isolated.LogicInstLookupTable.items()
    }
    landscape = SWEEP.BUILD_SLICE_LANDSCAPE(root, isolated, zero, {})
    if landscape is None:
        state["done"] = True
        return state["profiles"]
    if state["previous_ns"] is None:
        state["previous_ns"] = SWEEP.PREDICTED_STAGE_NS([], landscape)
    # The existing estimator keys by entity and realized placement hash. Reuse
    # unchanged child estimates across depths of this same isolated hierarchy.
    register_estimates = {}
    while not satisfied():
        count = state["count"]
        try:
            cuts, placements, _budget = AUTO_PIPELINE.COUNT_TARGETED_PLACEMENTS(
                landscape, count
            )
        except AUTO_PIPELINE.AutoPipelineLatencyInfeasible:
            state["done"] = True
            break
        table = AUTO_PIPELINE.COPY_TIMING_PARAMS_LOOKUP(zero)
        table = SWEEP.APPLY_PIPELINE_PLACEMENTS(placements, isolated, table)
        SWEEP.CHECK_PIPELINE_PLACEMENTS_REALIZED(placements, isolated, table)
        AUTO_PIPELINE._INVALIDATE_REGION_CACHES(root, table)
        realized = table[root].GET_TOTAL_LATENCY(isolated, table)
        predicted = SWEEP.PREDICTED_STAGE_NS(cuts, landscape)
        if realized == count:
            boundaries = [-1] + list(cuts) + [landscape.total_units - 1]
            stages = [
                sum(landscape.weight[a + 1 : b + 1]) * landscape.units_to_ns
                + landscape.stage_overhead_ns
                for a, b in zip(boundaries, boundaries[1:])
            ]
            recipe = _unit_timing_recipe(root, table)
            _text, bits = SYN.GET_REGISTERS_ESTIMATE_TEXT_AND_FFS(
                isolated.FuncLogicLookupTable[unit["entity"]],
                root,
                isolated,
                table,
                register_estimates,
            )
            state["profiles"].append(
                {
                    "base_entity": node["entity"],
                    "unit_entity": unit["entity"],
                    "kind": "pipelined",
                    "latency": count,
                    "ii": 1,
                    "registered_selection": selection_rows is not None,
                    "selection_rows": selection_rows,
                    "input_stage_du": int(round(stages[0] * SYN.DELAY_UNIT_MULT)),
                    "output_stage_du": int(round(stages[-1] * SYN.DELAY_UNIT_MULT)),
                    "worst_stage_du": int(round(predicted * SYN.DELAY_UNIT_MULT)),
                    "register_bits": bits,
                    "timing": recipe,
                    "register_bits_source": "lowered pipeline storage estimate",
                    "placement_digest": _unit_recipe_digest(recipe),
                    "context": context,
                    "evidence": "AUTO_PIPELINE count-targeted placement estimate",
                }
            )
        state["count"] = count + 1
        if predicted >= state["previous_ns"]:
            state["done"] = True
        state["previous_ns"] = predicted
    return state["profiles"]


def _pinned_unit_name(implementation):
    """The AUTO_PIPELINE tag name of a pinned placement: the selected
    placement is part of this internal region's identity."""
    identity = _unit_recipe_digest(
        (
            implementation["unit_entity"],
            implementation["latency"],
            implementation["ii"],
            implementation["registered_selection"],
            implementation["placement_digest"],
        )
    )
    return "auto_fsm_pinned_" + identity[:20]


def _make_unit_tag(parser_state, key, node, implementation):
    """The selected placement is part of this internal region's identity."""
    import pypeline

    unit = _unit_function(parser_state, key, node, implementation.get("selection_rows"))
    if unit is None or unit["entity"] != implementation["unit_entity"]:
        raise AUTO.AutoError("AUTO_FSM: selected functional unit is unavailable")
    tag = pypeline.AUTO_PIPELINE(
        unit["function"],
        latency=implementation["latency"],
        name=_pinned_unit_name(implementation),
    )
    tag._auto_fsm_implementation = json.loads(AUTO.frozen(implementation))
    return tag


def RESTORE_UNIT_PLACEMENT(root, implementation, parser_state, table):
    """Reapply the already-lowered recipe; surrounding sweeps cannot move it."""
    # Sparse recipes describe a fully fixed hierarchy: restore their implicit
    # zero placements too, including registers added by an enclosing sweep.
    for inst, params in table.items():
        if inst == root or inst.startswith(root + LOGIC.SUBMODULE_MARKER):
            params.SET_SLICES([])
            params._has_input_regs = False
            params._has_output_regs = False
            params._exact_bit_boundaries = None
            params.INVALIDATE_CACHE()
            params.params_are_fixed = True
    for row in implementation["timing"]:
        inst = root + row["path"]
        if inst not in table:
            raise AutoFsmInternalError(
                "AUTO_FSM: pinned pipeline hierarchy changed: " + inst
            )
        params = table[inst]
        params.SET_SLICES(list(row["slices"]))
        params._has_input_regs = row["input_regs"]
        params._has_output_regs = row["output_regs"]
        params._exact_bit_boundaries = (
            list(row["bit_boundaries"]) if row["bit_boundaries"] is not None else None
        )
        params.INVALIDATE_CACHE()
        params.params_are_fixed = True
    CHECK_UNIT_PLACEMENT(root, implementation, parser_state, table)
    return table


def CHECK_UNIT_PLACEMENT(root, implementation, parser_state, table):
    """A different realized placement is an invariant failure, never a replan."""
    if (
        _unit_recipe_digest(_unit_timing_recipe(root, table))
        != implementation["placement_digest"]
    ):
        raise AutoFsmInternalError(
            "AUTO_FSM: pinned pipeline placement changed at " + root
        )
    if table[root].GET_TOTAL_LATENCY(parser_state, table) != implementation["latency"]:
        raise AutoFsmInternalError("AUTO_FSM: pinned unit latency changed at " + root)


def SCHEDULE_DAG(
    dag,
    budget_du,
    mux_du_of=None,
    max_states=None,
    copies=None,
    implementations=None,
    select_du_of=None,
    no_chain_edges=(),
    no_chain_entity_pairs=(),
):
    """List-schedule the DAG into states, binding same-entity operations to one
    shared functional unit each.

    The greedy rule, per state: walk the ready operations in longest-remaining-
    chain order and place one if
      (a) some copy of its unit is not already busy this state -- one operation
          per unit per state is exactly what makes the unit shareable rather
          than duplicated;
      (b) the chain of operations it would join still fits the delay budget,
          counting the operand multiplexer that sharing puts in front of it;
      (c) placing it keeps the units' emission order acyclic. Generated source
          declares units in a fixed order, so if unit A feeds unit B in one
          state, B can never feed A in another.
    If nothing at all fits an empty state, the cheapest ready operation is
    forced in alone and the schedule is flagged as at its floor -- one
    indivisible operation that no amount of extra states can speed up.

    `mux_du_of(nid)` returns the mux delay to charge one operation, derived
    from its unit's fold count and port widths -- v1 charged a flat constant
    here, which both over-priced lightly shared units and badly under-priced
    heavily shared ones, i.e. exactly the regime the area sweep explores.

    `copies[entity]` allows more than one physical unit for an entity. Replication,
    pipelined units and graph/adapter choices all participate in meeting a hard
    max_latency cap; every choice is checked by a complete schedule.
    """
    nodes = dag["nodes"]
    implementations = implementations or {}
    sched = _scheduled_ids(dag)
    copies = copies or {}
    mux_du_of = mux_du_of or (lambda nid: AUTO.MUX_PENALTY_DU)
    select_du_of = select_du_of or (lambda nid: 0)
    no_chain_edges = set(tuple(edge) for edge in no_chain_edges)
    no_chain_entity_pairs = set(tuple(pair) for pair in no_chain_entity_pairs)
    # What each scheduled operation must wait for: the scheduled operations
    # feeding its OPERANDS, seen through any zero-delay glue in between.
    preds = {}
    for nid in sched:
        deps = set()
        for operand in nodes[nid]["operands"]:
            _scheduled_deps(dag, operand, sched, deps)
        preds[nid] = deps - {nid}
    prio = _critical_path(dag, sched, preds, implementations, budget_du)

    state_of = {}  # Completion state, including a pipelined unit's latency.
    launch_of = {}
    next_launch = {}
    uses_of = {}  # A selected unit's concrete row count bounds its binding.
    fu_of = {}
    end_du_of = {}
    fu_edges = {}  # fu -> set of fus it feeds (within some state)
    at_floor = False
    worst_state_du = 0
    state = 0

    # entity -> its units' ids, lowest copy first; built once, not per attempt.
    fu_ids = {}

    def free_fu(entity, fus_used):
        """Lowest-numbered copy of `entity` not yet busy this state. Lowest
        first (rather than round-robin) deliberately: it keeps the extra copies
        lightly loaded, so their operand muxes stay small and any copy that
        ends up unused disappears entirely."""
        ids = fu_ids.get(entity)
        if ids is None:
            ids = [_fu_id(entity, i) for i in range(max(1, copies.get(entity, 1)))]
            fu_ids[entity] = ids
        rows = implementations.get(entity, {}).get("selection_rows")
        for fu in ids:
            if (
                fu not in fus_used
                and state >= next_launch.get(fu, 1)
                and (rows is None or uses_of.get(fu, 0) < rows)
            ):
                return fu
        return None

    # Ready operations are tracked INCREMENTALLY, through a priority heap fed
    # by a per-node count of not-yet-placed predecessors. The obvious
    # alternative -- rescanning every unplaced operation after every placement
    # -- is quadratic per state, which was invisible when a DAG held a few
    # dozen operations and is fatal now the area search routinely evaluates
    # candidates holding thousands.
    import heapq

    succs = {nid: [] for nid in sched}
    n_unsat = {}
    for nid in sched:
        n_unsat[nid] = len(preds[nid])
        for p in preds[nid]:
            succs[p].append(nid)
    heap = [(-prio[nid], nid) for nid in sorted(sched) if n_unsat[nid] == 0]
    heapq.heapify(heap)
    n_placed = 0
    n_total = len(sched)

    while n_placed < n_total:
        state += 1
        fus_used = set()
        chain_end = {}
        state_worst = 0
        deferred = []
        waiting_for_future = False
        # entity -> whether a copy is still in a pipelined launch interval,
        # for every entity with no copy free this state. Units only get busier
        # within a state, so neither answer changes before the next one.
        exhausted = {}
        while heap:
            item = heapq.heappop(heap)
            nid = item[1]
            if any(state_of[p] > state for p in preds[nid]):
                waiting_for_future = True
                deferred.append(item)
                continue
            entity = nodes[nid]["entity"]
            fu = None if entity in exhausted else free_fu(entity, fus_used)
            if fu is None:
                if entity not in exhausted:
                    exhausted[entity] = any(
                        next_launch.get(candidate, 1) > state
                        for candidate in fu_ids[entity]
                    )
                waiting_for_future = waiting_for_future or exhausted[entity]
                deferred.append(item)
                continue
            same_state_preds = [p for p in preds[nid] if state_of[p] == state]
            if any(
                (p, nid) in no_chain_edges
                or (nodes[p]["entity"], nodes[nid]["entity"]) in no_chain_entity_pairs
                for p in same_state_preds
            ):
                waiting_for_future = True
                deferred.append(item)
                continue
            start = max((end_du_of[p] for p in same_state_preds), default=0)
            implementation = implementations.get(nodes[nid]["entity"], {})
            latency = implementation.get("latency", 0)
            input_delay = implementation.get("input_stage_du", nodes[nid]["delay_du"])
            launch_end = max(start, select_du_of(nid)) + mux_du_of(nid) + input_delay
            end = max(launch_end, implementation.get("worst_stage_du", 0))
            if end > budget_du and (fus_used or chain_end or same_state_preds):
                # A pipeline may complete late in an otherwise empty state.
                # Wait for its result register next cycle instead of calling
                # this a unit floor: the input stage itself can still fit.
                waiting_for_future = waiting_for_future or bool(same_state_preds)
                deferred.append(item)
                continue
            # A pipelined producer's output crosses its own registers. Its
            # Feedback local permits declaration before the physical call.
            new_edges = {
                (fu_of[p], fu)
                for p in same_state_preds
                if not implementations.get(nodes[p]["entity"], {}).get("latency", 0)
            }
            if not _edges_stay_acyclic(fu_edges, new_edges):
                deferred.append(item)
                continue
            if end > budget_du:
                # Nothing fits an empty state: force this one in alone.
                at_floor = True
            for a, b in new_edges:
                fu_edges.setdefault(a, set()).add(b)
            launch_of[nid] = state
            state_of[nid] = state + latency
            next_launch[fu] = state + implementation.get("ii", 1)
            uses_of[fu] = uses_of.get(fu, 0) + 1
            fu_of[nid] = fu
            chain_end[nid] = end
            end_du_of[nid] = (
                implementation["output_stage_du"] if latency else launch_end
            )
            fus_used.add(fu)
            state_worst = max(state_worst, end)
            n_placed += 1
            # Anything this unblocks may still land in THIS state -- that is
            # what lets a chain of cheap operations share one state.
            for s in succs[nid]:
                n_unsat[s] -= 1
                if n_unsat[s] == 0:
                    heapq.heappush(heap, (-prio[s], s))
        # Everything blocked this state is retried in the next one. Nothing
        # deferred can become placeable later WITHIN this state: units only get
        # busier, chains only get longer, and unit-ordering edges only
        # accumulate.
        for item in deferred:
            heapq.heappush(heap, item)
        if not fus_used and not waiting_for_future:
            # No progress at all: only possible if every ready node was blocked
            # by the acyclicity rule, which an empty state cannot reproduce.
            raise AUTO.AutoError(
                "AUTO_FSM: scheduling stalled with operations left to place "
                "(internal error)"
            )
        worst_state_du = max(worst_state_du, state_worst)
        # Deliberately no early exit once past max_states: scheduling to
        # completion is what tells the caller how many states this REALLY
        # needs, which is the one thing a user staring at an infeasible
        # latency cap actually wants told.

    n_states = max(state_of.values(), default=1)
    used_fus = sorted(set(fu_of.values()))
    return {
        "n_states": n_states,
        "state_of": state_of,
        "launch_of": launch_of,
        "fu_of": fu_of,
        "end_du_of": end_du_of,
        "at_floor": at_floor,
        "worst_state_du": worst_state_du,
        "fu_order": _topological_fu_order(used_fus, fu_edges),
        "fus": {fu: _fu_entity(fu) for fu in used_fus},
        "latency_infeasible": max_states is not None and n_states > max_states,
    }


def _fu_entity(fu_id):
    """The entity a unit id names (see _fu_id)."""
    return fu_id.rsplit("#", 1)[0] if "#" in fu_id else fu_id


def _edges_stay_acyclic(fu_edges, new_edges):
    """Would adding `new_edges` to the (acyclic) `fu_edges` keep it acyclic?

    SCHEDULE_DAG asks this for every placement attempt, so it neither copies
    the graph nor walks all of it: since `fu_edges` has no cycle, any cycle
    the union has runs through a new edge, and so through that edge's target.
    A depth-first search of the union from the new targets alone therefore
    finds a cycle exactly when one exists. An edge `fu_edges` already has
    adds nothing, so only the others are searched from."""
    added = {}
    for a, b in new_edges:
        if a == b:
            # A unit feeding itself within one state would need two copies of
            # it live at once -- exactly what sharing forbids.
            return False
        if b not in fu_edges.get(a, ()):
            added.setdefault(a, set()).add(b)
    color = {}

    def visit(n):
        state = color.get(n)
        if state == 1:
            return False
        if state == 2:
            return True
        color[n] = 1
        for m in fu_edges.get(n, ()):
            if not visit(m):
                return False
        for m in added.get(n, ()):
            if not visit(m):
                return False
        color[n] = 2
        return True

    return all(visit(b) for targets in added.values() for b in targets)


def _topological_fu_order(fus, fu_edges):
    """Order units so a unit always appears after everything that feeds it."""
    order = []
    visited = set()

    def visit(fu):
        if fu in visited:
            return
        visited.add(fu)
        for producer in sorted(fus):
            if fu in fu_edges.get(producer, ()):
                visit(producer)
        order.append(fu)

    for fu in sorted(fus):
        visit(fu)
    return order


# ─────────────────────────────────────────────
# Schedule assembly
# ─────────────────────────────────────────────


def _state_reg_ctype(n_states: int) -> str:
    """C type of the FSM state register: holds 0 (idle) .. n_states."""
    return f"uint{max(1, int(n_states).bit_length())}_t"


def _schedule_entity_name(func_entity: str, schedule_core: dict) -> str:
    """Name (and therefore FuncLogicLookupTable key / VHDL entity) of a
    generated FSM.

    The physical schedule and concrete placement recipes are hashed in. Model-only
    changes keep the name when they emit identical hardware; a changed operation,
    binding, state or placement changes the entity and its synthesis identity.
    """
    h = hashlib.sha256(
        json.dumps(
            _schedule_hardware(schedule_core), sort_keys=True, default=str
        ).encode()
    ).hexdigest()[:8]
    base = f"auto_fsm_{func_entity}"
    budget = _MAX_NAME_LEN - 9  # "_" + 8 hex chars
    if len(base) > budget:
        base = base[:budget].rstrip("_")
    return f"{base}_{h}"


def SCHEDULE_CACHE_USABLE(schedule):
    """Malformed carried data is a cache miss, never a build failure."""
    try:
        return _schedule_cache_usable(schedule)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def _schedule_cache_usable(schedule):
    """Ignore stale or malformed carried data before any datapath is emitted."""
    if not isinstance(schedule, dict) or schedule.get("version") != SCHEDULE_VERSION:
        return False
    if not all(
        key in schedule
        for key in (
            "nodes",
            "node_order",
            "fus",
            "fu_order",
            "output",
            "output_casts",
            "out_type",
            "in_type",
            "source_identity",
            "target_context",
            "entity",
            "n_states",
            "latency",
        )
    ):
        return False
    if not isinstance(schedule["nodes"], dict) or not isinstance(schedule["fus"], dict):
        return False
    if (
        not isinstance(schedule["node_order"], list)
        or not isinstance(schedule["fu_order"], list)
        or set(schedule["node_order"]) != set(schedule["nodes"])
        or set(schedule["fu_order"]) != set(schedule["fus"])
    ):
        return False
    if type(schedule["n_states"]) is not int or schedule["n_states"] < 1:
        return False
    if (
        type(schedule["latency"]) is not int
        or schedule["latency"] < schedule["n_states"]
    ):
        return False
    if schedule["entity"] != _schedule_entity_name(schedule["func_entity"], schedule):
        return False

    implementations = schedule.get("implementations", {})
    if not isinstance(implementations, dict):
        return False
    for implementation in implementations.values():
        if not isinstance(implementation, dict) or not all(
            key in implementation
            for key in (
                "base_entity",
                "unit_entity",
                "latency",
                "ii",
                "registered_selection",
                "input_stage_du",
                "output_stage_du",
                "worst_stage_du",
                "register_bits",
                "timing",
                "placement_digest",
                "context",
            )
        ):
            return False
        if any(
            type(implementation[key]) is not int or implementation[key] < 0
            for key in (
                "latency",
                "ii",
                "input_stage_du",
                "output_stage_du",
                "worst_stage_du",
                "register_bits",
            )
        ):
            return False
        try:
            if (
                _unit_recipe_digest(implementation["timing"])
                != implementation["placement_digest"]
            ):
                return False
        except (TypeError, ValueError):
            return False
    return all(
        isinstance(node, dict)
        and all(
            key in node
            for key in (
                "kind",
                "op",
                "entity",
                "delay_du",
                "operands",
                "casts",
                "port_types",
                "out_type",
            )
        )
        and isinstance(node["op"], dict)
        and len(node["operands"]) == len(node["casts"]) == len(node["port_types"])
        and (not node.get("fu") or node["fu"] in schedule["fus"])
        for node in schedule["nodes"].values()
    )


def _source_identity(parser_state, entity):
    return AUTO.fingerprint(
        [
            (
                name,
                logic.inputs,
                logic.outputs,
                logic.submodule_instances,
                logic.wire_to_c_type,
                logic.wire_driven_by,
            )
            for name in sorted(AUTO._subtree_entities(parser_state, entity))
            for logic in [parser_state.FuncLogicLookupTable[name]]
        ]
    )


def _target_context(parser_state):
    import DEVICE_MODELS
    import SYN

    return [
        AUTO.GRAPH_VERSION,
        AUTO.TIMING_VERSION,
        parser_state.part,
        getattr(SYN.SYN_TOOL, "__name__", None),
        getattr(DEVICE_MODELS, "SELECTED_LIBRARY", None),
    ]


_LARGE_SCHEDULE_WARNED_ATTR = "_auto_fsm_large_schedule_warned"


def _warn_large_schedule(parser_state, key, busiest_entity, predicted_folds):
    """One-time (per key, per parser_state -- see _DELAY_MEMO_ATTR for the
    same pattern) notice that a schedule's busiest shared unit is about to
    fold a lot of operations, printed BEFORE calling SCHEDULE_DAG so it lands
    even when a single schedule (e.g. under --auto_fsm_no_area_sweep, or the
    sweep's own anchor) is what runs long -- see SWEEP_LARGE_SCHEDULE_FOLDS.

    Advisory only: never raises, never changes the schedule. Names only the
    knobs that actually shrink predicted_folds on the FIRST schedule built --
    NOT --auto_fsm_unshare/--auto_fsm_open: those route through FORCE_SCHEDULE,
    which resolves its pattern against an already-scheduled anchor
    (_resolve_entity_pattern reads schedule["fus"]) and so unconditionally
    pays for one full, uncapped BUILD_SCHEDULE before the forced one -- no
    help when THAT is what is slow (confirmed: killed after 10+ minutes on
    the design that motivated this constant). Recommending it here would
    point at a knob that cannot possibly land in time.
    """
    warned = getattr(parser_state, _LARGE_SCHEDULE_WARNED_ATTR, None)
    if warned is None:
        warned = set()
        setattr(parser_state, _LARGE_SCHEDULE_WARNED_ATTR, warned)
    if key in warned:
        return
    warned.add(key)
    print(
        f"AUTO_FSM {key}: {busiest_entity!r} folds {predicted_folds} "
        f"operations onto one shared unit (> {SWEEP_LARGE_SCHEDULE_FOLDS}) -- "
        f"this binding needs at least {predicted_folds} states. This is a "
        f"latency/search-size advisory, not a timing failure. To constrain "
        f"the state count before scheduling, use a "
        f"max_latency= cap on the AUTO_FSM/make_stream_auto_fsm call (forces "
        f"replication up front), a lower @MAIN clock goal (widens the "
        f"per-state budget, so fewer -- or no -- operations need descending "
        f"in the first place), or a shallower/narrower source for whatever "
        f"is being shared (e.g. a soft-multiplier's max_width, or its "
        f"operand widths). --auto_fsm_unshare/--auto_fsm_open do NOT help here "
        f"-- they still schedule this exact shape once, unmodified, before "
        f"applying anything you asked for.",
        flush=True,
    )


def BUILD_SCHEDULE(
    parser_state,
    key,
    tag,
    budget_scale,
    prev_schedule=None,
    opened=(),
    max_nodes=None,
    unshared=(),
    ctl=DEFAULT_CTL,
    func_entity_override=None,
    build_memo=None,
    pipelined=(),
    merged=(),
    fused=(),
    _graph_memo=None,
):
    """Schedule + bind one AUTO_FSM'd function into a plain (picklable,
    comparable) schedule dict.

    Pure function of (the function's Logic graphs, its operations' delays,
    budget_scale, `opened`, `unshared`) -- deliberately independent of the
    surrounding design, which is what makes the driver's loop converge
    trivially: only an explicit budget tightening, or the area sweep choosing
    different grain/binding, can change the answer.

    `ctl` selects the control-path rendering (see CTL_CHOICES). It is part of
    the schedule because codegen shape and area model must agree, and because
    the entity name must change with it -- otherwise measured delays cached
    against one control path would be reused against another.

    `unshared` is a sequence of (entity, n_units) pairs: how many physical
    copies of an operation to build instead of the default one. Sharing is not
    free -- it buys one unit at the price of a multiplexer on every input port
    and, when it forces extra states, a register for every value that now has
    to cross one. For a CHEAP operation (a one-bit OR costs less than the
    two-bit multiplexer selecting its operands) sharing is a straight loss, and
    v1 had no way to decline it.

    `build_memo`, when given, is a dict shared by every call for ONE
    (parser_state, key, tag, prev_schedule) -- HARVEST_AUTO_FSM_SCHEDULES
    keeps one per call site when it searches more than one encoding. The memo
    keys on select arrival, corrected timing evidence and implementation choices,
    so encodings share packing only under the same model. A refusal (AutoError) is remembered and raised
    again the same way.

    `_graph_memo`, an _AreaSearchMemo, is private to one fixed-parser area
    search. Binding and depth variants reuse its cleaned graph when source
    boundary choices and delays agree, and its SCHEDULE_DAG plan when they also
    agree on unit counts and implementations; each result is decoded
    independently.
    """
    # `auto` is a driver-level request because each encoding needs its own full
    # area sweep. Keep the low-level builder useful to direct callers/tests by
    # giving it the historical binary-table rendering when asked in isolation;
    # HARVEST_AUTO_FSM_SCHEDULES expands auto into both candidates below.
    if ctl == "auto":
        ctl = "v3"
    args = (
        parser_state, key, tag, budget_scale, prev_schedule, opened, max_nodes,
        unshared, ctl, func_entity_override, pipelined, merged, fused, _graph_memo,
    )
    if build_memo is None:
        return _BUILD_SCHEDULE(*args)
    memo_key = (
        func_entity_override,
        budget_scale,
        tuple(sorted(set(opened))),
        max_nodes,
        tuple(tuple(pair) for pair in unshared),
        _select_delay(
            _control_snapshot(
                parser_state, (prev_schedule or {}).get("control_delays_snapshot")
            ),
            ctl,
        ),
        AUTO.frozen(
            {
                field: (prev_schedule or {}).get(field)
                for field in (
                    "corrected_entity_delays",
                    "select_arrivals",
                    "no_chain_edges",
                    "no_chain_entity_pairs",
                    "control_delays_snapshot",
                    "unit_measurements",
                )
            }
        ),
        AUTO.frozen(pipelined),
        tuple(tuple(pair) for pair in merged),
        tuple(fused),
    )
    hit = build_memo.get(memo_key)
    if hit is None:
        try:
            schedule = _BUILD_SCHEDULE(*args)
        except AutoFsmInternalError:
            raise
        except AUTO.AutoError as e:
            # A copy: the raised exception's traceback holds every frame
            # under it, including the refused DAG (up to MAX_SWEEP_DAG_NODES
            # operations) and the search's candidate schedules.
            build_memo[memo_key] = copy.copy(e)
            raise
        # Kept compressed, and taken before callers add their scoring fields.
        # A search visits hundreds of points, and a live schedule of a
        # thousand-operation function is ~10 MB of Python objects against
        # ~80 KB here (WireGuard's Poly1305 epilogue).
        build_memo[memo_key] = zlib.compress(
            pickle.dumps(schedule, pickle.HIGHEST_PROTOCOL), 1
        )
        return schedule
    if isinstance(hit, AUTO.AutoError):
        raise copy.copy(hit)
    return _restamp_ctl(pickle.loads(zlib.decompress(hit)), ctl)


# Fields BUILD_SCHEDULE adds after hashing the schedule core into the entity
# name: the name itself and the diagnostic-only descent reports.
_SCHEDULE_UNHASHED_KEYS = ("entity", "descend_truncated", "descend_blocked")


def _restamp_ctl(schedule, ctl):
    """A memoized schedule (see BUILD_SCHEDULE's `build_memo`), set in place
    to control encoding `ctl`, with the entity name rehashed to match."""
    schedule["ctl"] = ctl
    core = {k: v for k, v in schedule.items() if k not in _SCHEDULE_UNHASHED_KEYS}
    schedule["entity"] = _schedule_entity_name(schedule["func_entity"], core)
    return schedule


# ──────────────────────────────────────────────────────────────────────
# Typed selection, width adapters and recurring groups
# ──────────────────────────────────────────────────────────────────────


def _transform_identity(value):
    return hashlib.sha256(AUTO.frozen(value).encode()).hexdigest()


def _selection_chains(dag, parser_state, entity):
    """Distinct equalities on one unsigned index, with a BDD exclusivity proof."""
    dag.setdefault("constants", {}).update(
        {
            ref[1]: AUTO._literal(parser_state, entity, ref)
            for node in dag["nodes"].values()
            for ref in node["operands"]
            if ref[0] == "const"
        }
    )
    proof_dag = dict(dag, nodes=dict(dag["nodes"]))
    users = {nid: [] for nid in dag["nodes"]}
    for nid, node in dag["nodes"].items():
        for ref in node["operands"]:
            if ref[0] == "node":
                users[ref[1]].append(nid)
    if dag["output"][0] == "node":
        users[dag["output"][1]].append("$output")
    for nid, node in dag["nodes"].items():
        shape = parser_state.pypeline_auto_fsm_specialization_shapes.get(node["entity"])
        if shape is None or shape["base"] not in parser_state.pypeline_builtin_op_info:
            continue
        if shape["op"].get("op") != "==":
            continue
        variable = iter(zip(node["operands"], node["casts"]))
        operands, casts = [], []
        for value, ctype in zip(shape["values"], shape["port_types"]):
            ref, chain = (
                next(variable) if value is None else (["lit", value, ctype], [])
            )
            operands.append(ref)
            casts.append(chain)
        proof_dag["nodes"][nid] = dict(
            node,
            kind="binop",
            op=shape["op"],
            entity=shape["base"],
            operands=operands,
            casts=casts,
            port_types=shape["port_types"],
        )
    result = []
    covered = set()
    for root in reversed(AUTO.order(dag)):
        if root in covered:
            continue
        first = dag["nodes"][root]
        if first["kind"] != "mux":
            continue
        current = ["node", root]
        cases = []
        chain = []
        index = None
        seen = 0
        proof = AUTO.BDD()
        default_casts = []
        while current[0] == "node":
            mux = dag["nodes"][current[1]]
            if mux["kind"] != "mux" or mux["out_type"] != first["out_type"]:
                break
            condition = mux["operands"][0]
            if condition[0] != "node" or mux["casts"][0]:
                break
            eq = proof_dag["nodes"][condition[1]]
            if (
                eq["kind"] != "binop"
                or eq["op"].get("op") != "=="
                or eq["entity"] not in parser_state.pypeline_builtin_op_info
            ):
                break
            values = [
                AUTO._constant_operand(eq, i, parser_state, entity) for i in range(2)
            ]
            if sum(value is not None for value in values) != 1:
                break
            literal = 0 if values[0] is not None else 1
            other = 1 - literal
            port_type = eq["port_types"][other]
            if (
                not AUTO._unsigned(port_type)
                or AUTO.width(port_type) > 64
                or any(not AUTO._unsigned(t) for t in eq["casts"][other])
            ):
                break
            candidate = (eq["operands"][other], eq["casts"][other], port_type)
            if index is not None and candidate != index:
                break
            try:
                predicate = proof.expression(proof_dag, condition)
                if proof.apply("and", seen, predicate) != 0:
                    break
                seen = proof.apply("or", seen, predicate)
            except AUTO.BudgetExceeded:
                break
            index = candidate
            chain.append(current[1])
            cases.append(
                (
                    values[literal],
                    mux["operands"][1],
                    mux["casts"][1] + [mux["port_types"][1]],
                )
            )
            current = mux["operands"][2]
            default_casts = mux["casts"][2] + [mux["port_types"][2]]
            # An intervening assignment to a different type changes the
            # priority chain's value; retain it rather than moving that cast.
            if any(t != first["out_type"] for t in default_casts):
                break
        if len(cases) >= 2:
            shape = (
                index[2],
                first["out_type"],
                [value for value, _ref, _casts in cases],
            )
            result.append(
                (
                    root,
                    _transform_identity(shape),
                    shape,
                    index,
                    cases,
                    current,
                    default_casts,
                )
            )
            # Only surviving selectors need characterization. Nested chain
            # suffixes disappear with this replacement unless used elsewhere.
            covered.update(nid for nid in chain[1:] if len(users[nid]) == 1)
    return result


def _selection_function(shape, types):
    import pypeline
    from operators.comb_opt import _primitive_math

    index_type, out_type, constants = shape
    em = AUTO._Emitter()
    em.inj_named(pypeline.hw_func, "hw_func")
    em.inj_named(pypeline.bit_assign, "bit_assign")
    it = em.inj(types.resolve(index_type), "t")
    ot = em.inj(types.resolve(out_type), "t")
    st = em.inj(pypeline.make_uint_t(len(constants).bit_length()), "t")
    bt = em.inj(pypeline.uint1_t, "t")
    array = em.inj(
        pypeline.make_array_t(types.resolve(out_type), len(constants) + 1), "t"
    )
    mux = em.inj(AUTO._mux_callable(types.resolve(out_type), len(constants) + 1), "mux")
    name = "auto_fsm_selection_" + _transform_identity(shape)[:20]
    args = [f"index: {it}"] + [f"a{i}: {ot}" for i in range(len(constants) + 1)]
    em.line("@hw_func")
    em.line(f"def {name}({', '.join(args)}) -> {ot}:")
    for i, constant in enumerate(constants):
        em.line(f"    eq{i}: {bt} = index == {constant}")
    em.line(f"    selected: {st} = 0")
    for bit in range(len(constants).bit_length()):
        terms = [f"eq{i}" for i in range(len(constants)) if ((i + 1) >> bit) & 1]
        # Balanced source ORs avoid introducing a priority or serial OR chain.
        while len(terms) > 1:
            terms = [
                f"({terms[i]} | {terms[i+1]})" if i + 1 < len(terms) else terms[i]
                for i in range(0, len(terms), 2)
            ]
        if terms:
            em.line(f"    selected = bit_assign(selected, {terms[0]}, {bit})")
    em.line(f"    rows: {array}")
    for i in range(len(constants) + 1):
        em.line(f"    rows[{i}] = a{i}")
    em.line(f"    return {mux}(selected, rows)")
    return _primitive_math(AUTO._exec_generated(name, em.src(), em.globals))


def _pair_matches(dag, parser_state):
    """Recurring multiply/add/subtract and arithmetic/mux pairs, without escapes."""
    users = {nid: [] for nid in dag["nodes"]}
    for nid, node in dag["nodes"].items():
        for ref in node["operands"]:
            if ref[0] == "node":
                users[ref[1]].append(nid)
    if dag["output"][0] == "node":
        users[dag["output"][1]].append("$output")
    groups = {}
    for cid in AUTO.order(dag):
        consumer = dag["nodes"][cid]
        for port, ref in enumerate(consumer["operands"]):
            if ref[0] != "node" or users[ref[1]] != [cid]:
                continue
            producer = dag["nodes"][ref[1]]
            if (
                producer["kind"] == "binop"
                and producer["entity"] not in parser_state.pypeline_builtin_op_info
                or consumer["kind"] == "binop"
                and consumer["entity"] not in parser_state.pypeline_builtin_op_info
            ):
                continue
            op = producer["op"].get("op")
            multiply = op == "*"
            arithmetic = op in ("+", "-", "*")
            if producer["kind"] == "call":
                # Calls retain their original dispatch. Primitive semantics,
                # when needed for recognizing multiplication, are attached
                # by the same proof used for width adapters below.
                multiply = producer.get("primitive_op") == "*"
                arithmetic = producer.get("primitive_op") in ("+", "-", "*")
            if not (
                (multiply and consumer["op"].get("op") in ("+", "-"))
                or (arithmetic and consumer["kind"] == "mux" and port in (1, 2))
            ):
                continue
            signature = [
                (n["kind"], n["entity"], n["op"], n["port_types"], n["out_type"])
                for n in (producer, consumer)
            ]
            key = _transform_identity((signature, port, consumer["casts"][port]))
            groups.setdefault(key, []).append((ref[1], cid, port))
    return {key: matches for key, matches in groups.items() if len(matches) >= 2}


class _PairEmitter(AUTO._GraphCodegen):
    def __init__(self, dag, parser_state, types):
        self.nodes = dag["nodes"]
        self.parser_state = parser_state
        self.types = types
        self.em = AUTO._Emitter()
        self.em.type_resolver = types
        self._tmp_n = 0
        self.locals = {}

    def _render_ref(self, ref):
        return self.locals[ref[1]] if ref[0] == "node" else ref[1]


def _pair_function(key, producer, consumer, port, parser_state, types):
    import pypeline
    from operators.comb_opt import _primitive_math

    p, c = copy.deepcopy(producer), copy.deepcopy(consumer)
    inputs = list(p["port_types"]) + [
        t for i, t in enumerate(c["port_types"]) if i != port
    ]
    p["operands"] = [["in", f"a{i}"] for i in range(len(p["operands"]))]
    p["casts"] = [[] for _t in p["port_types"]]
    next_input = len(p["operands"])
    for i in range(len(c["operands"])):
        if i == port:
            c["operands"][i] = ["node", "producer"]
        else:
            c["operands"][i] = ["in", f"a{next_input}"]
            c["casts"][i] = []
            next_input += 1
    graph = {"nodes": {"producer": p, "consumer": c}, "output": ["node", "consumer"]}
    emitter = _PairEmitter(graph, parser_state, types)
    em = emitter.em
    em.inj_named(pypeline.hw_func, "hw_func")
    name = "auto_fsm_fused_" + key[:20]
    args = [f"a{i}: {em.inj(types.resolve(t), 't')}" for i, t in enumerate(inputs)]
    em.line("@hw_func")
    em.line(
        f"def {name}({', '.join(args)}) -> {em.inj(types.resolve(c['out_type']), 't')}:"
    )
    for nid in AUTO.order(graph):
        node = graph["nodes"][nid]
        expression = emitter._render_glue(nid, node)
        em.line(
            f"    {nid}: {em.inj(types.resolve(node['out_type']), 't')} = {expression}"
        )
        emitter.locals[nid] = nid
    em.line("    return consumer")
    fn = _primitive_math(AUTO._exec_generated(name, em.src(), em.globals))
    for node in (p, c):
        primitive = parser_state.pypeline_builtin_op_info.get(node["entity"])
        if primitive is not None:
            opname, ports = primitive
            pypeline.register_operator(
                opname, *(types.resolve(t) for t in ports), pypeline.INFERRED, scope=fn
            )
    return fn


def _prepare_transform_candidates(tag, parser_state, elaborator):
    """Prepare deterministic, measured candidates in every parse, including replay."""
    root = elaborator._elaborate_live_func(tag.func.__name__, tag.func).func_name
    if root is None or any(
        kind in ("state", "feedback", "global")
        for _path, _entity, kind, _detail in AUTO.FIND_EFFECTS(parser_state, root)
    ):
        return
    types = AUTO._TypeResolver()
    types.seed_callable(tag.func)
    for fn in AUTO._entity_callables(parser_state).values():
        types.seed_callable(fn)
    for entity in sorted(AUTO._subtree_entities(parser_state, root)):
        logic = parser_state.FuncLogicLookupTable[entity]
        if (
            not logic.submodule_instances
            or entity != root
            and AUTO._entity_callables(parser_state).get(entity) is None
        ):
            continue
        try:
            # Structural proofs must not populate the timing resolver's memo
            # with estimates before synthesis supplies the real leaf delays.
            dag = AUTO._resolve_inlined(
                AUTO.BUILD_DAG(
                    parser_state,
                    entity,
                    dict.fromkeys(parser_state.FuncLogicLookupTable, 1),
                    float("inf"),
                )
            )
            # Preparation and scheduling prove the same cleaned graph. Before
            # frontend trimming, repeated reads of one struct field otherwise
            # have different node ids and hide an exclusive equality chain.
            dag, _cleanup = AUTO.cleanup(dag, parser_state, entity)
        except AUTO.UnregenerableOpError:
            continue
        _annotate_primitives(dag, parser_state)
        for _nid, key, shape, _index, _cases, _default, _casts in _selection_chains(
            dag, parser_state, entity
        ):
            if key not in parser_state.pypeline_auto_fsm_selections:
                fn = _selection_function(shape, types)
                selected = elaborator._elaborate_live_func(fn.__name__, fn).func_name
                AUTO._RESOLVE_BUILTIN_SUBMODULES(parser_state, selected)
                parser_state.pypeline_auto_fsm_selections[key] = selected
                parser_state.pypeline_auto_fsm_measure_callables.append(fn)
        for key, matches in _pair_matches(dag, parser_state).items():
            if key in parser_state.pypeline_auto_fsm_fusions:
                continue
            pid, cid, port = matches[0]
            fn = _pair_function(
                key, dag["nodes"][pid], dag["nodes"][cid], port, parser_state, types
            )
            fused = elaborator._elaborate_live_func(fn.__name__, fn).func_name
            AUTO._RESOLVE_BUILTIN_SUBMODULES(parser_state, fused)
            original_calls = {
                node["entity"]
                for node in (dag["nodes"][pid], dag["nodes"][cid])
                if node["kind"] == "call"
            }
            if not original_calls <= set(
                parser_state.FuncLogicLookupTable[fused].submodule_instances.values()
            ):
                continue
            parser_state.pypeline_auto_fsm_fusions[key] = fused
            parser_state.pypeline_auto_fsm_measure_callables.append(fn)


def _balance_selections(dag, parser_state, entity, delays):
    """Replace proved chains with the exact prepared compact selection table."""
    count = 0
    for nid, key, _shape, index, cases, default, default_casts in _selection_chains(
        dag, parser_state, entity
    ):
        selected = parser_state.pypeline_auto_fsm_selections.get(key)
        if selected is None:
            continue
        old = dag["nodes"][nid]
        old.update(
            kind="call",
            op={"kind": "call"},
            entity=selected,
            operands=[index[0], default] + [ref for _v, ref, _c in cases],
            casts=[list(index[1]), default_casts] + [casts for _v, _r, casts in cases],
            port_types=[index[2]] + [old["out_type"]] * (len(cases) + 1),
            delay_du=AUTO._resolve_delay_du(parser_state, selected, delays),
            balanced_selection=True,
        )
        count += 1
    return AUTO.prune(dag), count


def _fuse_pairs(dag, keys, parser_state, delays):
    """Fuse only closed recurring pairs; outside uses retain their original nodes."""
    count = 0
    for key in keys:
        entity = parser_state.pypeline_auto_fsm_fusions.get(key)
        if entity is None:
            continue
        for pid, cid, port in _pair_matches(dag, parser_state).get(key, ()):
            producer, consumer = dag["nodes"][pid], dag["nodes"][cid]
            external = [i for i in range(len(consumer["operands"])) if i != port]
            consumer.update(
                kind="call",
                op={"kind": "call"},
                entity=entity,
                operands=producer["operands"]
                + [consumer["operands"][i] for i in external],
                casts=producer["casts"] + [consumer["casts"][i] for i in external],
                port_types=producer["port_types"]
                + [consumer["port_types"][i] for i in external],
                delay_du=AUTO._resolve_delay_du(parser_state, entity, delays),
                fused_pattern=key,
            )
            count += 1
        dag = AUTO.prune(dag)
    return dag, count


def _annotate_primitives(dag, parser_state):
    for node in dag["nodes"].values():
        form = _primitive_form(node, parser_state)
        if form is not None:
            node["primitive_op"] = form["op"]
        else:
            shape = parser_state.pypeline_auto_fsm_specialization_shapes.get(
                node["entity"]
            )
            if (
                shape is not None
                and shape["base"] in parser_state.pypeline_builtin_op_info
            ):
                node["primitive_op"] = shape["op"].get("op")


def _primitive_form(node, parser_state):
    """Prove a builtin operation, or a pure wrapper containing just that operation.

    This recognizes a square by its graph, never its name. Multi-operation
    reducers and custom arithmetic implementations have no such proof.
    """
    entity = node["entity"]
    cached = parser_state.pypeline_auto_fsm_primitive_forms
    if entity not in cached:
        logic = parser_state.FuncLogicLookupTable.get(entity)
        if entity in parser_state.pypeline_builtin_op_info and node["kind"] == "binop":
            cached[entity] = dict(
                op=node["op"].get("op"),
                ports=list(node["port_types"]),
                inputs=[(i, []) for i in range(len(node["port_types"]))],
                result_casts=[node["out_type"]],
            )
        elif logic is not None and node["kind"] == "call":
            # Open source wrappers, retaining their elaborated builtin leaves.
            opened = [
                name
                for name in AUTO._subtree_entities(parser_state, entity)
                if AUTO._entity_callables(parser_state).get(name) is not None
            ]
            try:
                dag = AUTO._resolve_inlined(
                    AUTO.BUILD_DAG(
                        parser_state,
                        entity,
                        dict.fromkeys(parser_state.FuncLogicLookupTable, 1),
                        float("inf"),
                        opened=opened,
                    )
                )
                operations = [
                    (nid, n) for nid, n in dag["nodes"].items() if n["kind"] != "copy"
                ]
                ports = [
                    port for port in logic.inputs if port != LOGIC.CLOCK_ENABLE_NAME
                ]
                if len(operations) != 1:
                    raise ValueError("not a single primitive")
                nid, primitive = operations[0]
                if (
                    primitive["kind"] != "binop"
                    or primitive["entity"] not in parser_state.pypeline_builtin_op_info
                ):
                    raise ValueError("not a builtin primitive")

                def source(ref, casts):
                    if ref[0] == "node" and dag["nodes"][ref[1]]["kind"] == "copy":
                        copy_node = dag["nodes"][ref[1]]
                        return source(
                            copy_node["operands"][0],
                            copy_node["casts"][0]
                            + [copy_node["port_types"][0], copy_node["out_type"]]
                            + casts,
                        )
                    return ref, casts

                mappings = []
                for i, ref in enumerate(primitive["operands"]):
                    ref, casts = source(ref, primitive["casts"][i])
                    if ref[0] != "in" or ref[1] not in ports:
                        raise ValueError("primitive operands are not public inputs")
                    mappings.append((ports.index(ref[1]), casts))
                output, casts = source(dag["output"], dag["output_casts"])
                if output != ["node", nid]:
                    raise ValueError("result is not the primitive output")
                cached[entity] = dict(
                    op=primitive["op"].get("op"),
                    ports=primitive["port_types"],
                    inputs=mappings,
                    result_casts=[primitive["out_type"]] + casts + [node["out_type"]],
                )
            except (AUTO.AutoError, ValueError):
                cached[entity] = None
        else:
            cached[entity] = None
    form = cached[entity]
    if form is None or form["op"] not in (
        "+",
        "-",
        "*",
        "==",
        "!=",
        "<",
        "<=",
        ">",
        ">=",
    ):
        return None
    if any(
        not AUTO._unsigned(t)
        for t in node["port_types"]
        + form["ports"]
        + form["result_casts"]
        + [t for _i, casts in form["inputs"] for t in casts]
    ):
        return None
    return form


def _merge_choices(dag, parser_state):
    representatives = {}
    for node in dag["nodes"].values():
        if node["delay_du"] > 0 and (
            node["entity"] not in representatives or not node.get("binding_from")
        ):
            representatives[node["entity"]] = dict(
                node, out_type=node.get("physical_out_type", node["out_type"])
            )
    forms = {
        entity: _primitive_form(node, parser_state)
        for entity, node in representatives.items()
    }
    result = []
    for narrow, left in sorted(representatives.items()):
        a = forms[narrow]
        if a is None:
            continue
        for wide, right in sorted(representatives.items()):
            b = forms[wide]
            if (
                narrow == wide
                or b is None
                or a["op"] != b["op"]
                or len(right["port_types"]) != 2
            ):
                continue
            # The target must expose both primitive inputs independently.
            if sorted(i for i, _casts in b["inputs"]) != [0, 1]:
                continue
            if any(
                AUTO.width(t) < AUTO.width(right["port_types"][i])
                for i, casts in b["inputs"]
                for t in casts
            ):
                continue
            if any(
                AUTO.width(t) < AUTO.width(right["out_type"]) for t in b["result_casts"]
            ):
                continue
            if any(
                AUTO.width(t) > AUTO.width(right["port_types"][b["inputs"][i][0]])
                for i, t in enumerate(a["ports"])
            ):
                continue
            if min(AUTO.width(t) for t in a["result_casts"]) > AUTO.width(
                right["out_type"]
            ):
                continue
            if len(left["port_types"]) == 2 and not any(
                AUTO.width(t) < AUTO.width(right["port_types"][b["inputs"][i][0]])
                for i, t in enumerate(a["ports"])
            ):
                continue
            result.append((narrow, wide))
    return result


def _local_merge_choices(dag, parser_state):
    """Merge steps into each unit's next wider compatible unit only.

    A later merge moves everything already bound to the narrower unit, so any
    chain of merges stays reachable one step at a time, as UNSHARE adds one
    copy at a time. Every legal pair made a search over sixteen subtract
    widths (an integer square root) evaluate about 110 merges per step.
    """
    sizes = {}
    for node in dag["nodes"].values():
        if node["entity"] not in sizes or not node.get("binding_from"):
            sizes[node["entity"]] = sum(
                AUTO.width(t) for t in node["port_types"]
            ) + AUTO.width(node.get("physical_out_type", node["out_type"]))
    nearest = {}
    for narrow, wide in _merge_choices(dag, parser_state):
        if narrow not in nearest or (sizes[wide], wide) < (
            sizes[nearest[narrow]],
            nearest[narrow],
        ):
            nearest[narrow] = wide
    return sorted(nearest.items())


def _merge_widths(dag, choices, parser_state, delays):
    """Bind compatible unsigned operations through explicit input/result adapters."""
    count = 0
    for narrow, wide in choices:
        if (narrow, wide) not in _merge_choices(dag, parser_state):
            continue
        target = next(
            (
                n
                for n in dag["nodes"].values()
                if n["entity"] == wide and not n.get("binding_from")
            ),
            next(n for n in dag["nodes"].values() if n["entity"] == wide),
        )
        target_form = _primitive_form(target, parser_state)
        for node in dag["nodes"].values():
            if node["entity"] != narrow:
                continue
            form = _primitive_form(node, parser_state)
            refs = [None, None]
            casts = [None, None]
            for i, (source, internal_casts) in enumerate(form["inputs"]):
                target_port = target_form["inputs"][i][0]
                refs[target_port] = node["operands"][source]
                casts[target_port] = (
                    node["casts"][source]
                    + [node["port_types"][source]]
                    + internal_casts
                    + [form["ports"][i]]
                )
            result_casts = list(form["result_casts"]) + node.get("result_casts", [])
            node.update(
                entity=wide,
                kind=target["kind"],
                op=copy.deepcopy(target["op"]),
                operands=refs,
                casts=casts,
                port_types=list(target["port_types"]),
                physical_out_type=target.get("physical_out_type", target["out_type"]),
                result_casts=result_casts,
                binding_from=narrow,
                delay_du=AUTO._resolve_delay_du(parser_state, wide, delays),
            )
            count += 1
    return dag, count


class _AreaSearchMemo:
    """Caches private to one fixed-parser area search (BUILD_SCHEDULE's
    `_graph_memo`). Every entry is compressed, and decoded afresh for each
    candidate that reuses it."""

    def __init__(self):
        # graph identity -> (cleaned graph, cleanup stats)
        self.graphs = {}
        # (graph identity, select delay, implementations, unit counts) ->
        # (SCHEDULE_DAG plan, the operand-mux snapshot entries it priced)
        self.plans = {}


# (function, items, caches) for the workers _map_forked forks, which inherit it.
_FORKED_MAP = None
# In a forked worker: per cache, a shallow copy of it as the parent had it or as
# this worker last reported it.
_FORKED_SENT = None
# True in a forked worker, where a nested _map_forked runs serially.
_IN_FORKED_WORKER = False


def _map_forked(fn, items, caches=()):
    """[fn(item) for item in items], in forked worker processes when -j allows
    more than one and the platform can fork. Workers inherit the caller's state
    as it is at the call, and nothing is pickled to start them. Results come
    back in item order, and an exception in a worker is raised here. The dicts
    in `caches` hold pure results keyed by their inputs, and a value is
    replaced, never changed in place, when it advances (a resumable
    characterization, say). What a worker adds or replaces is merged back in
    item order, so later calls reuse it as they would after running here."""
    n_workers = min(SYN.GET_NUM_PROCESSES(), len(items))
    if (
        n_workers < 2
        or _IN_FORKED_WORKER
        or "fork" not in multiprocessing.get_all_start_methods()
    ):
        return [fn(item) for item in items]
    global _FORKED_MAP
    _FORKED_MAP = (fn, items, caches)
    context = multiprocessing.get_context("fork")
    tasks = context.SimpleQueue()
    workers = {}
    try:
        for _ in range(n_workers):
            reader, writer = context.Pipe(duplex=False)
            process = context.Process(target=_forked_worker, args=(tasks, writer))
            process.daemon = True
            process.start()
            writer.close()
            workers[reader] = process
        for index in range(len(items)):
            tasks.put(index)
        for _ in range(n_workers):
            tasks.put(None)
        packed = {}
        while len(packed) < len(items):
            if not workers:
                raise AutoFsmInternalError(
                    "AUTO_FSM: forked search workers stopped before returning "
                    f"{len(items) - len(packed)} of {len(items)} results"
                )
            for reader in multiprocessing.connection.wait(list(workers)):
                try:
                    index, failed, payload = reader.recv()
                except EOFError:
                    process = workers.pop(reader)
                    process.join()
                    if process.exitcode != 0:
                        raise AutoFsmInternalError(
                            f"AUTO_FSM: a forked search worker exited with code "
                            f"{process.exitcode} (killed for memory? -j sets "
                            f"how many run at once)"
                        )
                    continue
                if failed:
                    raise pickle.loads(payload)
                packed[index] = payload
    finally:
        _FORKED_MAP = None
        for reader, process in workers.items():
            if process.is_alive():
                process.terminate()
            process.join()
            reader.close()
    results = []
    for index in range(len(items)):
        result, changed = pickle.loads(zlib.decompress(packed[index]))
        for cache, entries in zip(caches, changed):
            cache.update(entries)
        results.append(result)
    return results


def _forked_worker(tasks, writer):
    """A _map_forked worker: runs item indices from `tasks` until None and
    sends (index, failed, payload) for each. A failure's payload is the
    pickled exception; its traceback is printed here."""
    global _IN_FORKED_WORKER
    _IN_FORKED_WORKER = True
    while True:
        index = tasks.get()
        if index is None:
            break
        try:
            writer.send((index, False, _forked_call(index)))
        except Exception as error:
            import traceback

            traceback.print_exc()
            try:
                payload = pickle.dumps(error, pickle.HIGHEST_PROTOCOL)
            except Exception:
                payload = pickle.dumps(
                    AutoFsmInternalError(f"{type(error).__name__}: {error}")
                )
            writer.send((index, True, payload))
            break
    writer.close()


def _forked_call(index):
    """One _map_forked item in a worker: its result, and the cache entries
    added or replaced since this worker last reported."""
    global _FORKED_SENT
    fn, items, caches = _FORKED_MAP
    if _FORKED_SENT is None:
        _FORKED_SENT = [dict(cache) for cache in caches]
    result = fn(items[index])
    changed = []
    absent = object()
    for cache, sent in zip(caches, _FORKED_SENT):
        new = [(k, v) for k, v in cache.items() if sent.get(k, absent) is not v]
        sent.update(new)
        changed.append(new)
    return zlib.compress(pickle.dumps((result, changed), pickle.HIGHEST_PROTOCOL), 1)


def _clean_schedule_graph(
    parser_state, func_entity, delays, budget_du, opened, preserved, merged, fused, memo
):
    """Reuse typed graphs across bindings within one fixed-parser area search.
    Returns the graph, its cleanup stats and its identity in `memo`.

    Fused pairs and width merges rebind an already-cleaned graph, so the graph
    before them is kept as well: those moves skip descent and cleanup.
    """
    identity = AUTO.fingerprint(
        (func_entity, delays, budget_du, opened, sorted(preserved), merged, fused)
    )
    memo = memo.graphs if memo is not None else None
    if memo is not None and identity in memo:
        return pickle.loads(zlib.decompress(memo[identity])) + (identity,)
    cleaned = AUTO.fingerprint(
        ("cleaned", func_entity, delays, budget_du, opened, sorted(preserved))
    )
    if memo is not None and cleaned in memo:
        dag, stats = pickle.loads(zlib.decompress(memo[cleaned]))
    else:
        dag = AUTO._resolve_inlined(
            AUTO.BUILD_DAG(
                parser_state,
                func_entity,
                delays,
                budget_du,
                opened,
                preserved=preserved,
            )
        )
        dag, stats = AUTO.cleanup(dag, parser_state, func_entity)
        stats["specialized"] = dag.get(
            "specialized_nodes", 0
        ) + AUTO.specialize_constants(dag, parser_state, func_entity, delays)
        dag, stats["balanced_selections"] = _balance_selections(
            dag, parser_state, func_entity, delays
        )
        _annotate_primitives(dag, parser_state)
        if memo is not None:
            memo[cleaned] = zlib.compress(
                pickle.dumps((dag, stats), pickle.HIGHEST_PROTOCOL), 1
            )
    dag, stats["fused_pairs"] = _fuse_pairs(dag, fused, parser_state, delays)
    dag, stats["width_adapters"] = _merge_widths(dag, merged, parser_state, delays)
    if memo is not None:
        memo[identity] = zlib.compress(
            pickle.dumps((dag, stats), pickle.HIGHEST_PROTOCOL), 1
        )
    return dag, stats, identity


def _BUILD_SCHEDULE(
    parser_state,
    key,
    tag,
    budget_scale,
    prev_schedule,
    opened,
    max_nodes,
    unshared,
    ctl,
    func_entity_override,
    pipelined,
    merged,
    fused,
    graph_memo,
):
    """BUILD_SCHEDULE without the memo; `ctl` is already resolved from auto."""
    import pypeline

    func_entity = func_entity_override or AUTO._entity_key_for_callable(
        parser_state, tag.func
    )
    if func_entity is None:
        raise AUTO.AutoError(
            f"AUTO_FSM: the function tagged by {key!r} was never elaborated, so "
            f"there is nothing to schedule (internal error)."
        )
    budget_du = _budget_du(parser_state, budget_scale)
    snapshot = (prev_schedule or {}).get("entity_delays_snapshot", {})
    delays = _schedule_delays(parser_state, func_entity, snapshot)
    delays.update((prev_schedule or {}).get("corrected_entity_delays", {}))

    # A measured correction must not force a characterized word-level unit
    # apart before trying its feasible pipeline. This also runs without the
    # area search. Explicit OPEN choices still request decomposition.
    pipeline_choices = dict(pipelined)
    measurements = (prev_schedule or {}).get("unit_measurements", {})

    def fits(profile):
        return _with_measurements(profile, measurements)["worst_stage_du"] <= budget_du

    for entity, corrected in sorted(
        (prev_schedule or {}).get("corrected_entity_delays", {}).items()
    ):
        if (
            entity in pipeline_choices
            or entity in opened
            or corrected + AUTO.MUX_PENALTY_DU <= budget_du
        ):
            continue
        node = next(
            (
                node
                for node in (prev_schedule or {}).get("nodes", {}).values()
                if node["entity"] == entity and node.get("fu")
            ),
            None,
        )
        if node is None:
            continue
        feasible = next(
            (
                profile
                for profile in _unit_profiles(
                    parser_state,
                    key,
                    node,
                    delays,
                    until=lambda rows: any(fits(row) for row in rows),
                )
                if fits(profile)
            ),
            None,
        )
        if feasible is not None:
            pipeline_choices[entity] = feasible["latency"]
    pipelined = tuple(sorted(pipeline_choices.items()))

    AUTO._seed_struct_widths(parser_state)
    # The whole subtree must be pure, not just the levels BUILD_DAG opens: an
    # impure child kept as one shared unit would be time-multiplexed across
    # states (its state stepped / its global wires sampled per use).
    for path, ent, kind, detail in AUTO.FIND_EFFECTS(parser_state, func_entity):
        if kind not in ("state", "feedback", "global"):
            continue
        what = {
            "state": "holds Reg state",
            "feedback": "holds Feedback state",
            "global": "reads or writes global wires",
        }[kind]
        where = (
            "it"
            if not path
            else f"its callee {ent!r} (instance {LOGIC.SUBMODULE_MARKER.join(path)})"
        )
        raise AUTO.AutoError(
            f"AUTO_FSM: {func_entity!r} is not a pure function of its argument: "
            f"{where} {what} ({', '.join(detail)}). Only a pure combinational "
            f"function can be turned into an FSM -- move the state or global "
            f"wire use out into the calling function and pass values as "
            f"arguments/return values."
        )
    opened = tuple(sorted(set(opened)))
    dag, cleanup_stats, graph_identity = _clean_schedule_graph(
        parser_state,
        func_entity,
        delays,
        budget_du,
        opened,
        [entity for entity, _latency in pipelined],
        merged,
        fused,
        graph_memo,
    )
    if max_nodes is not None and len(dag["nodes"]) > max_nodes:
        # Checked BEFORE scheduling: this is the area search asking "what if I
        # opened that up", and scheduling something this size to find out it
        # was never going to be worth it is the expensive way to learn it.
        raise AUTO.AutoError(
            f"AUTO_FSM: opening {sorted(opened)!r} flattens {key} into "
            f"{len(dag['nodes'])} operations, past the {max_nodes} the area "
            f"search will consider"
        )

    implementations = {}
    by_entity = {node["entity"]: node for node in dag["nodes"].values()}
    for entity, choice in pipelined:
        if entity not in by_entity:
            continue
        latency, selection_rows = (
            choice if isinstance(choice, (tuple, list)) else (choice, None)
        )
        profiles = _unit_profiles(
            parser_state, key, by_entity[entity], delays, selection_rows, latency
        )
        selected = next(
            (profile for profile in profiles if profile["latency"] == latency), None
        )
        if selected is None:
            raise AUTO.AutoError(
                f"AUTO_FSM: no pipeline placement for {entity} at latency {latency}"
            )
        implementations[entity] = _with_measurements(
            selected, (prev_schedule or {}).get("unit_measurements", {})
        )

    # Operand-mux delays. Scheduling conservatively charges the unit's fold
    # count, which is known before states/registers exist. Codegen may later
    # coalesce equal per-port values to a narrower mux (or a wire); it never
    # emits anything wider than the delay the scheduler reserved here.
    types = AUTO._TypeResolver()
    for t in (tag.in_type, tag.out_type):
        types.seed(t)
    mux_snapshot = dict((prev_schedule or {}).get("mux_delays_snapshot", {}))

    control_snapshot = _control_snapshot(
        parser_state, (prev_schedule or {}).get("control_delays_snapshot")
    )
    select_proxy = _select_delay(control_snapshot, ctl)
    select_arrivals = (prev_schedule or {}).get("select_arrivals", {})
    no_chain_edges = (prev_schedule or {}).get("no_chain_edges", ())
    no_chain_entity_pairs = (prev_schedule or {}).get("no_chain_entity_pairs", ())
    sched_ids = _scheduled_ids(dag)
    folds = {}
    for nid in sched_ids:
        e = dag["nodes"][nid]["entity"]
        folds[e] = folds.get(e, 0) + 1
    max_latency = getattr(tag, "max_latency", None)
    register_output = getattr(tag, "register_output", True)
    output_cycles = 1 if register_output else 0
    max_states = (max_latency - output_cycles) if max_latency else None
    copies = _replication_for_latency(folds, max_states, implementations)
    for entity, implementation in implementations.items():
        rows = implementation.get("selection_rows")
        if rows is not None:
            copies[entity] = max(copies.get(entity, 1), math.ceil(folds[entity] / rows))
    # The area search's unsharing choices, floored by whatever the latency cap
    # already forces and capped at one unit per operation (past which extra
    # units could never be used).
    for entity, n in unshared:
        if entity in folds:
            copies[entity] = min(folds[entity], max(copies.get(entity, 1), int(n)))

    busiest_entity, predicted_folds = max(
        (
            (e, _fold_count_per_unit(folds[e], copies.get(e, 1)))
            for e in folds
        ),
        key=lambda pair: pair[1],
        default=(None, 0),
    )
    if predicted_folds > SWEEP_LARGE_SCHEDULE_FOLDS:
        _warn_large_schedule(parser_state, key, busiest_entity, predicted_folds)

    # (entity, fold count) -> (mux delay, the snapshot entries it recorded)
    mux_du_cache = {}
    # The (entity, fold count) pairs priced since `scheduled` last cleared it.
    mux_priced = set()

    def mux_du_of(nid):
        node = dag["nodes"][nid]
        e = node["entity"]
        if implementations.get(e, {}).get("registered_selection"):
            # The selected AUTO_PIPELINE region already contains the muxes.
            return 0
        n = _fold_count_per_unit(folds.get(e, 1), copies.get(e, 1))
        mux_priced.add((e, n))
        cached = mux_du_cache.get((e, n))
        if cached is None:
            du_max, entries = 0, []
            for ctype in node["port_types"]:
                du = AUTO._mux_delay_du(parser_state, types, ctype, n, mux_snapshot)
                mux_snapshot.setdefault(f"{ctype}#{n}", du)
                entries.append((f"{ctype}#{n}", mux_snapshot[f"{ctype}#{n}"]))
                du_max = max(du_max, du)
            cached = mux_du_cache[(e, n)] = (du_max, entries)
        return cached[0]

    def select_du_of(nid):
        entity = dag["nodes"][nid]["entity"]
        if _fold_count_per_unit(folds[entity], copies.get(entity, 1)) < 2:
            return 0
        return select_arrivals.get(entity, select_proxy)

    # What a plan depends on besides `copies`, within one area search.
    plan_context = (
        (graph_identity, select_proxy, AUTO.frozen(implementations))
        if graph_memo is not None
        else None
    )

    def scheduled():
        """SCHEDULE_DAG at the current `copies`. Within an area search, the
        candidates on one graph share plans: one unit per operation, say, is
        the same plan for every binding of it. A reused plan records the
        operand-mux snapshot entries its scheduling priced, as scheduling
        it again would."""
        plan_key = None
        if plan_context is not None:
            plan_key = plan_context + (tuple(sorted(copies.items())),)
            hit = graph_memo.plans.get(plan_key)
            if hit is not None:
                plan, entries = pickle.loads(zlib.decompress(hit))
                for snapshot_key, du in entries:
                    mux_snapshot.setdefault(snapshot_key, du)
                return plan
        mux_priced.clear()
        plan = SCHEDULE_DAG(
            dag,
            budget_du,
            mux_du_of,
            max_states,
            copies,
            implementations,
            select_du_of,
            no_chain_edges,
            no_chain_entity_pairs,
        )
        if plan_key is not None:
            entries = sorted(
                {entry for pair in mux_priced for entry in mux_du_cache[pair][1]}
            )
            graph_memo.plans[plan_key] = zlib.compress(
                pickle.dumps((plan, entries), pickle.HIGHEST_PROTOCOL), 1
            )
        return plan

    plan = scheduled()
    if plan["latency_infeasible"]:
        # A cap that sharing alone cannot meet: give units back until it is.
        plan = _replicate_to_cap(folds, copies, scheduled)
    # Recorded after the latency-driven bumps above, so the schedule always
    # states the binding it actually has.
    unshared = tuple(sorted((e, n) for e, n in copies.items() if n > 1))

    nodes = {}
    for nid, node in dag["nodes"].items():
        nodes[nid] = dict(node)
        nodes[nid]["state"] = plan["state_of"].get(nid)
        nodes[nid]["launch_state"] = plan["launch_of"].get(nid)
        nodes[nid]["unit_latency"] = implementations.get(node["entity"], {}).get(
            "latency", 0
        )
        nodes[nid]["fu"] = plan["fu_of"].get(nid)
        nodes[nid]["end_du"] = plan["end_du_of"].get(nid)
    n_states = plan["n_states"]

    # Cross-FU register reuse is an AREA decision with an explicit timing
    # guard. A same-width sky130 FF costs 48.84 um2/bit while a 2:1 mux bank
    # costs 29.304 um2/bit, so replacing a register with one more mux input is
    # profitable there; the abstract FPGA-oriented model has the opposite
    # ratio and keeps the old same-FU-only allocation. If any resulting
    # writeback mux would exceed the state budget, disable cross-FU reuse for
    # that type and allocate again. This conservative per-type fallback keeps
    # the allocation pure and deterministic while never spending clock budget
    # the model says is unavailable.
    range_types = sorted(
        {t for t, _lo, _hi in _LIVE_RANGES(nodes, dag["output"], n_states).values()}
    )
    cross_fu_types = set()
    ff_area = AUTO._ff_area_um2(parser_state)
    for ctype in range_types:
        if AUTO._ctype_width(ctype) * ff_area > AUTO._mux_bank_area_um2(parser_state, ctype):
            cross_fu_types.add(ctype)

    writeback_mux_du = {}
    while True:
        reg_of, reg_types = ALLOCATE_REGISTERS(
            nodes, dag["output"], n_states, cross_fu_types
        )
        sources = _register_sources(nodes, reg_of)
        bad_types = set()
        writeback_mux_du = {}
        for idx, srcs in sorted(sources.items()):
            if len(srcs) < 2:
                continue
            ctype = reg_types[idx]
            du = AUTO._mux_delay_du(parser_state, types, ctype, len(srcs), mux_snapshot)
            mux_snapshot.setdefault(f"{ctype}#{len(srcs)}", du)
            writeback_mux_du[idx] = du
            for nid, reg_idx in reg_of.items():
                if reg_idx != idx:
                    continue
                end_du = nodes[nid].get("end_du") or 0
                if end_du + du > budget_du:
                    bad_types.add(ctype)
                    break
        if not (bad_types & cross_fu_types):
            break
        cross_fu_types -= bad_types

    worst_state_du = plan["worst_state_du"]
    for nid, idx in reg_of.items():
        worst_state_du = max(
            worst_state_du,
            (nodes[nid].get("end_du") or 0) + writeback_mux_du.get(idx, 0),
        )
    schedule_core = {
        "version": SCHEDULE_VERSION,
        "source_identity": parser_state.pypeline_auto_fsm_source_identities.get(key)
        or _source_identity(parser_state, func_entity),
        "target_context": _target_context(parser_state),
        "key": key,
        "ctl": ctl,
        "register_output": register_output,
        "func_entity": func_entity,
        "n_states": n_states,
        "latency": n_states + output_cycles,
        "max_latency": max_latency,
        "latency_infeasible": plan["latency_infeasible"],
        "budget_scale": budget_scale,
        "budget_du": budget_du,
        "worst_state_du": worst_state_du,
        "at_floor": plan["at_floor"],
        "nodes": nodes,
        "node_order": sorted(nodes),
        "fus": plan["fus"],
        "fu_order": plan["fu_order"],
        "output": dag["output"],
        "output_casts": dag["output_casts"],
        "in_type": pypeline._ctype_str(tag.in_type),
        "out_type": dag["out_type"],
        "entity_delays_snapshot": delays,
        "measured_entities": _measured_entities(
            parser_state,
            set(delays) | {node["entity"] for node in dag["nodes"].values()},
            (prev_schedule or {}).get("measured_entities", ()),
        ),
        "mux_delays_snapshot": mux_snapshot,
        "control_delays_snapshot": control_snapshot,
        "corrected_entity_delays": dict(
            (prev_schedule or {}).get("corrected_entity_delays", {})
        ),
        "select_arrivals": dict(select_arrivals),
        "no_chain_edges": list(no_chain_edges),
        "no_chain_entity_pairs": list(no_chain_entity_pairs),
        "unit_measurements": dict((prev_schedule or {}).get("unit_measurements", {})),
        "cross_fu_register_types": sorted(cross_fu_types),
        "opened": list(opened),
        "unshared": [list(pair) for pair in unshared],
        "cleanup": cleanup_stats,
        "constant_wrapper_count": len(
            set(parser_state.pypeline_auto_fsm_specializations.values())
        ),
        "implementations": implementations,
        "pipelined": [list(pair) for pair in pipelined if pair[0] in implementations],
        "merged": [list(pair) for pair in merged],
        "fused": list(fused),
    }
    _check_nonempty_schedule(parser_state, key, func_entity, nodes)
    # Everything added below is listed in _SCHEDULE_UNHASHED_KEYS.
    schedule = dict(schedule_core)
    schedule["entity"] = _schedule_entity_name(func_entity, schedule_core)
    # NOT part of schedule_core: it must never affect _schedule_entity_name's
    # hash (see that function's docstring) -- it is diagnostic-only, read by
    # DESCRIBE_SCHEDULE, and must not perturb entity names / cache keys.
    schedule["descend_truncated"] = dag.get("descend_truncated", [])
    schedule["descend_blocked"] = dag.get("descend_blocked", [])
    return schedule


def _check_nonempty_schedule(parser_state, key, func_entity, nodes):
    """Refuse a schedule that placed NO operation while real logic was
    treated as free.

    Zero scheduled operations is legitimate for a function that is genuinely
    all wiring, or whose gates really measured below one delay unit (delays
    are truncated to 0.1 ns). What is never legitimate is an operation priced
    at 0 that its own delay resolution says costs time: that is an unmeasured
    delay having been defaulted rather than resolved (see _schedule_delays),
    and building it renders every such gate inline as glue -- the "0 ops -> 0
    shared unit(s)" schedule that once hung codegen for half an hour.
    """
    if any(node.get("fu") for node in nodes.values()):
        return
    for nid in sorted(nodes):
        node = nodes[nid]
        if node["kind"] == "inlined" or node["delay_du"] > 0:
            continue
        logic = parser_state.FuncLogicLookupTable.get(node["entity"])
        if logic is None or AUTO._leaf_area(node["entity"], logic) <= 0.0:
            continue
        resolved = AUTO._resolve_delay_du(parser_state, node["entity"], {})
        if resolved > 0:
            raise AutoFsmInternalError(
                f"AUTO_FSM {key}: scheduling {func_entity!r} placed 0 operations, "
                f"but operation {nid!r} ({node['entity']}) was priced at 0 ns "
                f"while its delay resolves to {resolved / 10.0:.2f} ns -- an "
                f"unmeasured delay was treated as free wiring (internal error)"
            )


def _fold_count_per_unit(folds, n_copies):
    """Operations per physical unit, rounded up -- what its operand mux has to
    select between."""
    n_copies = max(1, n_copies)
    return max(1, -(-folds // n_copies))


def _replication_for_latency(folds, max_states, implementations=None):
    """Minimum copies from available launch states, result latency and II."""
    if max_states is None:
        return {}
    copies = {}
    for entity, count in folds.items():
        implementation = (implementations or {}).get(entity, {})
        available = max_states - implementation.get("latency", 0)
        if available <= 0:
            copies[entity] = count
            continue
        launches = 1 + (available - 1) // implementation.get("ii", 1)
        copies[entity] = -(-count // launches)
    return copies


def _replicate_to_cap(folds, copies, scheduled):
    """The SCHEDULE_DAG plan with the most sharing found that meets a
    max_latency cap, setting `copies` (in place) to its binding.
    `scheduled()` returns the plan at the current `copies`.

    Searches one knob: a limit k on operations per unit, every entity getting
    max(its current copies, ceil(folds / k)) units. Uniform rather than
    per-entity, because what keeps a capped schedule long is usually many
    kinds of operation queueing at once, and because each unit's operand mux
    shrinks with its fold count -- giving units one at a time to the most
    loaded entity (the step this replaced, eight times at most) never reached
    a 64- or 32-cycle cap on the WireGuard Poly1305 kernels, both of which
    k = 2 meets. k = 1 is one unit per operation: the dependency chain alone
    sets the state count, so a cap that k = 1 misses cannot be met at all, and
    its plan (the shortest possible) is what the infeasibility report shows.
    Fewer units means more states, so the largest k meeting the cap is found
    by bisection (a handful of reschedules; still no synthesis).
    """
    base = dict(copies)
    # Different k often give every entity the same unit count; SCHEDULE_DAG
    # is a pure function of the counts, so such a k reuses the plan.
    plans = {}

    def trial(k):
        copies.clear()
        copies.update(base)
        for entity, n_ops in folds.items():
            need = min(n_ops, -(-n_ops // k))
            if need > copies.get(entity, 1):
                copies[entity] = need
        counts = tuple(sorted(copies.items()))
        if counts not in plans:
            plans[counts] = scheduled()
        return plans[counts]

    best = trial(1)
    best_copies = dict(copies)
    if not best["latency_infeasible"]:
        lo, hi = 2, max(folds.values(), default=1)
        while lo <= hi:
            k = (lo + hi) // 2
            plan = trial(k)
            if plan["latency_infeasible"]:
                hi = k - 1
            else:
                best, best_copies = plan, dict(copies)
                lo = k + 1
    copies.clear()
    copies.update(best_copies)
    return best


# ─────────────────────────────────────────────
# Area model and the minimum-area search
# ─────────────────────────────────────────────


def _describe_area_model(parser_state, schedule):
    """One line for DESCRIBE_SCHEDULE: which unit a schedule's est_area is in,
    and -- under DEVICE_MODELS -- how many of its leaves were real
    measurements versus abstract fallbacks. Recomputes the final schedule's
    area once more with a fresh memo/tally purely to observe that split; the
    cost itself is already known (schedule["est_area"]) and discarded here.
    """
    if AUTO._area_unit_scale(parser_state) == 1.0:
        return "abstract"
    tally = {}
    ESTIMATE_SCHEDULE_AREA(parser_state, schedule, memo={}, tally=tally)
    measured = tally.get("measured", 0)
    estimated = tally.get("estimated", 0)
    return f"sky130 um2 ({measured} leaf/leaves measured, {estimated} estimated)"


def ESTIMATE_SCHEDULE_AREA(parser_state, schedule, memo=None, tally=None):
    """Estimated area of the FSM a schedule describes, in the model's current
    output unit -- abstract units for any tool with no area measurement
    (unchanged from before this function could measure anything), or real
    sky130 um2 under DEVICE_MODELS (_area_unit_scale). Under sky130 this is a
    MIX of measured and estimated terms, not a wholesale swap: the unit and
    operand-multiplexer terms use a real cached measurement wherever one
    exists and the abstract estimate (scaled into um2) as a per-leaf
    fallback; the flip-flop term is always real (no cache needed, see
    _ff_area_um2); the control-path terms stay abstract, scaled into um2,
    because they price a decode LUT or comparator chain that has no
    synthesizable entity of its own to measure in isolation. `tally`, when
    given, is filled in by the unit/mux terms for _describe_area_model to
    report how much of this number came from measurement.

    Five terms, which are exactly the things sharing trades between:

      units      one copy of each bound entity, however many operations use it.
                 This is the term sharing SHRINKS, and the reason AUTO_FSM
                 exists.
      glue       every UNSCHEDULED operation, counted once per use. Zero-delay
                 operations are re-rendered wherever their value is needed
                 rather than shared, so they are replicated hardware -- free
                 when they really are wiring (a field read, a constant shift),
                 and emphatically not free otherwise. Counting them is what
                 stops decomposition from looking free: open an adder into
                 gates and its gates land here, unshared, until the scheduler
                 has delays saying they are worth scheduling.
      muxes      one operand multiplexer per unit input port, sized by fold
                 count. This is the term sharing GROWS, and the reason sharing
                 more finely eventually stops paying.
      registers  every value that has to survive from the state that computes
                 it to a later state that reads it, plus the input/output/state
                 registers. Finer sharing means more states means more values
                 in flight, so this grows too.
      control    decoding the state into unit selects, register write enables
                 and the next state. Priced by `ctl`, because the two control
                 paths differ by more than a constant: v2's cost is per STATE
                 (a comparator chain that lengthens as sharing adds states),
                 while v3's is per TABLE OUTPUT BIT and grows only
                 logarithmically. That is what makes sharing cheaper under v3,
                 and therefore what lets the search share further before the
                 mux and register terms overtake it.

    Ranking only, even under sky130 -- a per-leaf sum still misses whatever
    cross-instance sharing real synthesis finds across a whole design (see
    the note on the AREA_* constants and docs/AUTO_FSM_DESIGN.md section 3.8),
    and the anchor guarantee (SWEEP_MIN_AREA_SCHEDULE) is what actually
    bounds the risk of that, not the unit this returns.
    """
    memo = {} if memo is None else memo
    AUTO._seed_struct_widths(parser_state)
    scale = AUTO._area_unit_scale(parser_state)
    nodes = schedule["nodes"]
    fus = schedule["fus"]

    area_terms = []
    for fu, entity in sorted(fus.items()):
        area_terms.append(AUTO.ESTIMATE_ENTITY_AREA(parser_state, entity, memo, tally))
    for nid in schedule["node_order"]:
        node = nodes[nid]
        if not node.get("fu"):
            area_terms.append(
                AUTO.ESTIMATE_ENTITY_AREA(parser_state, node["entity"], memo, tally)
            )

    users = {}
    for nid in schedule["node_order"]:
        node = nodes[nid]
        fu = node.get("fu")
        if fu:
            users.setdefault(fu, []).append(nid)

    reg_of, reg_types = ALLOCATE_REGISTERS(
        nodes,
        schedule["output"],
        schedule["n_states"],
        schedule.get("cross_fu_register_types", ()),
    )
    output_packs = _OUTPUT_SHIFT_PACKS(nodes, schedule["output"], schedule["n_states"])
    input_storage = _INPUT_STORAGE_PLAN(nodes, schedule["output"], schedule["n_states"])
    fused_output_packs = [
        pack for pack in output_packs if pack.get("source_fusion") is not None
    ]
    # A consume/produce fusion saves a second W-bit register bank, but its one
    # physical rolling register has two write-data shapes: capture the source
    # in the first state, then shift in produced bits.  Price that real wide
    # mux explicitly so the optimization cannot win merely by hiding cost from
    # the estimator.
    for pack in fused_output_packs:
        area_terms.append(AUTO._mux_bank_area_um2(parser_state, pack["ctype"], tally))
        if (
            input_storage is not None
            and pack["root"] in input_storage["preload_by_pack"]
        ):
            # Accept-time field preload is the third source of the rolling
            # register (shift, transformed source, raw input field).
            area_terms.append(
                AUTO._mux_bank_area_um2(parser_state, pack["ctype"], tally)
            )
    mux_plans = {}
    replacements = _rolling_replacements(schedule, output_packs)
    for fu in sorted(users):
        fu_nodes, ports = _operand_mux_plan(schedule, fu, reg_of, replacements, users)
        mux_plans[fu] = (fu_nodes, ports)
        if not fu_nodes:
            continue
        for port in ports:
            for ctype, n, _mapping in port["muxes"]:
                if n < 2:
                    continue
                area_terms.append(
                    (n - 1) * AUTO._mux_bank_area_um2(parser_state, ctype, tally)
                )
    # Input storage is now field/lifetime aware and therefore can change a
    # ranking (a first-state field may preload a rolling work register).
    area_terms.append(
        _reg_bits_from_types(schedule, reg_types) * AUTO._ff_area_um2(parser_state)
    )

    n_states = schedule["n_states"]
    statew = max(1, int(n_states).bit_length())
    ctl = schedule.get("ctl", "v3")
    if ctl == "v2":
        area_terms.append(n_states * AREA_PER_STATE_DECODE * scale)
        area_terms.append(len(fused_output_packs) * AREA_PER_STATE_DECODE * scale)
    elif ctl == "onehot":
        # State bits ARE the decode. Operand/writeback selectors only need OR
        # trees when several hot states select the same output bit; next-state
        # advance and the output pulse are wires. This is intentionally priced
        # separately from v3's lookup tables so auto encoding has a meaningful
        # area comparison rather than inheriting v3's control estimate.
        for fu in sorted(users):
            _fu_nodes, ports = mux_plans[fu]
            selector_shapes = _selector_shapes(schedule, fu, _fu_nodes, ports)
            for mapping, n in sorted(selector_shapes):
                for bit in range(max(1, (n - 1).bit_length())):
                    terms = sum(1 for row in mapping if (row >> bit) & 1)
                    area_terms.append(
                        max(0, terms - 1) * AUTO.AREA_PER_BIT_BITWISE * scale
                    )
        writes_by_reg = {}
        for nid, idx in reg_of.items():
            writes_by_reg.setdefault(idx, set()).add(nodes[nid]["state"])
        for states in writes_by_reg.values():
            area_terms.append(
                max(0, len(states) - 1) * AUTO.AREA_PER_BIT_BITWISE * scale
            )
        for pack in output_packs:
            area_terms.append(
                max(0, len(pack["steps"]) - 1) * AUTO.AREA_PER_BIT_BITWISE * scale
            )
        for idx, srcs in sorted(_register_sources(nodes, reg_of).items()):
            if len(srcs) < 2:
                continue
            nids = sorted(
                (nid for nid, reg_idx in reg_of.items() if reg_idx == idx),
                key=lambda nid: (nodes[nid]["state"], nid),
            )
            source_rows = {}
            rows = []
            for nid in nids:
                src = _result_source(nodes[nid])
                if src not in source_rows:
                    source_rows[src] = len(source_rows)
                rows.append(source_rows[src])
            for bit in range(max(1, (len(srcs) - 1).bit_length())):
                terms = sum(1 for row in rows if (row >> bit) & 1)
                area_terms.append(max(0, terms - 1) * AUTO.AREA_PER_BIT_BITWISE * scale)
        # idle-and-valid plus idle-and-not-valid in the one-hot transition.
        area_terms.append(2 * AUTO.AREA_PER_BIT_BITWISE * scale)
        if input_storage is not None:
            area_terms.append(
                len(input_storage["preload_by_pack"])
                * AUTO.AREA_PER_BIT_BITWISE
                * scale
            )
    else:
        # One select table per DISTINCT state-to-choice mapping. Ports whose
        # operands coalesce the same way share a selector; constant ports need
        # none at all.
        for fu in sorted(users):
            _fu_nodes, ports = mux_plans[fu]
            selector_shapes = _selector_shapes(schedule, fu, _fu_nodes, ports)
            for _mapping, n in sorted(selector_shapes):
                area_terms.append(
                    max(1, (n - 1).bit_length()) * AREA_PER_CTL_LUT_BIT * scale
                )
        # ...one one-bit write-enable table per register, plus the next-state
        # table and the output-write pulse.
        area_terms.append(
            (len(reg_types) + len(output_packs) + len(fused_output_packs))
            * AREA_PER_CTL_LUT_BIT
            * scale
        )
        for srcs in _register_sources(nodes, reg_of).values():
            if len(srcs) > 1:
                area_terms.append(
                    max(1, (len(srcs) - 1).bit_length()) * AREA_PER_CTL_LUT_BIT * scale
                )
        area_terms.append((statew + 1) * AREA_PER_CTL_LUT_BIT * scale)
        area_terms.append(n_states * AREA_PER_STATE_CTL * scale)
        if input_storage is not None:
            area_terms.append(
                len(input_storage["preload_by_pack"]) * AREA_PER_CTL_LUT_BIT * scale
            )
    # A cross-FU shared register needs a real source mux regardless of control
    # encoding. Same-FU reuse has one unchanged data wire and costs zero here.
    for idx, srcs in sorted(_register_sources(nodes, reg_of).items()):
        if len(srcs) > 1:
            area_terms.append(
                (len(srcs) - 1)
                * AUTO._mux_bank_area_um2(parser_state, reg_types[idx], tally)
            )
    return math.fsum(area_terms)


def _openable_entities(parser_state, schedule, opened):
    """Which of a schedule's bound units the sweep could still open up."""
    out = set()
    for entity in schedule["fus"].values():
        if entity in opened:
            continue
        logic = parser_state.FuncLogicLookupTable.get(entity)
        if _openable(parser_state, entity, logic):
            out.add(entity)
    return out


def _resolve_entity_pattern(schedule, pattern):
    """Which of a schedule's bound entities a user-supplied substring names.

    Used only by the force flags (--auto_fsm_open / --auto_fsm_unshare), which
    exist so a test can build the schedule the search REJECTED and compare real
    cell counts against it. Entity names are long and generated
    (BIN_OP_DIV_uint32_t_uint32_t), so matching is by substring -- but an
    ambiguous or absent match is an error, never a guess: a flag that silently
    forced nothing would look exactly like a search that declined to move.
    """
    matches = sorted({e for e in schedule["fus"].values() if pattern in e})
    if not matches:
        raise AUTO.AutoError(
            f"AUTO_FSM: no functional unit matching {pattern!r}. This schedule "
            f"binds: " + ", ".join(sorted(set(schedule["fus"].values())))
        )
    if len(matches) > 1:
        raise AUTO.AutoError(
            f"AUTO_FSM: {pattern!r} matches more than one functional unit: "
            + ", ".join(matches)
        )
    return matches[0]


def FORCE_SCHEDULE(
    parser_state,
    key,
    tag,
    budget_scale,
    prev_schedule=None,
    ctl=DEFAULT_CTL,
    open_patterns=(),
    unshare_patterns=(),
    build_memo=None,
):
    """Build one explicitly-chosen point of the search space instead of
    searching: open these entities, give those entities that many units.

    This is the measurement counterpart to the area search. The search ranks
    candidates with an internal model and never sees a real utilization number
    (see the AREA_* constants for why it cannot), so the only way to check that
    its answer is really the smallest is to BUILD the alternatives it passed
    over and count their cells -- which is what
    src/tests/pypeline_tests/inst/auto_fsm_min_area_verify_test.py does. The
    resulting schedule is a normal schedule in every respect: its entity name
    hashes its hardware, so a forced variant can never reuse measured delays
    belonging to different hardware. `forced` is a report flag, not hardware.
    """
    anchor = BUILD_SCHEDULE(
        parser_state, key, tag, budget_scale, prev_schedule, ctl=ctl,
        build_memo=build_memo,
    )
    opened = sorted({_resolve_entity_pattern(anchor, p) for p in open_patterns})
    unshared = {}
    for pattern, n_units in unshare_patterns:
        unshared[_resolve_entity_pattern(anchor, pattern)] = int(n_units)
    schedule = BUILD_SCHEDULE(
        parser_state,
        key,
        tag,
        budget_scale,
        prev_schedule,
        tuple(opened),
        None,
        tuple(sorted(unshared.items())),
        ctl=ctl,
        build_memo=build_memo,
    )
    schedule["forced"] = True
    return schedule


def _scheduled_op_count(schedule):
    return sum(1 for node in schedule["nodes"].values() if node.get("fu"))


def _state_excess(schedule):
    """How far a schedule's worst state runs past its delay budget (0 when it
    fits). The area search ranks by this before area: a schedule that fits
    the clock always beats one that does not, and between two that do not,
    the one closer to fitting is the one to keep walking from."""
    return max(0, schedule["worst_state_du"] - schedule["budget_du"])


def _sweep_required_improvement(anchor, candidate):
    """Minimum raw model win needed to make `candidate` the incumbent.

    SWEEP_MIN_IMPROVEMENT handles ordinary ranking noise. OPEN candidates
    additionally pay a confidence margin based on how far their generated
    control/data-selection shape moved from the written-grain anchor; see
    SWEEP_SHAPE_RISK_PER_DOUBLING above.
    """
    if not candidate.get("opened"):
        return SWEEP_MIN_IMPROVEMENT
    growth = max(
        1.0,
        _scheduled_op_count(candidate) / float(max(1, _scheduled_op_count(anchor))),
        candidate["n_states"] / float(max(1, anchor["n_states"])),
    )
    return min(
        SWEEP_MAX_REQUIRED_IMPROVEMENT,
        SWEEP_MIN_IMPROVEMENT + SWEEP_SHAPE_RISK_PER_DOUBLING * math.log(growth, 2.0),
    )


def _pareto_frontier(cheapest_by_states):
    """[[states, estimated area]] pairs no point with fewer states beats on
    area: the latency/area trade the area search saw."""
    points, best = [], None
    for states, cost in sorted(cheapest_by_states.items()):
        if best is None or cost < best:
            points.append([states, round(cost, 1)])
            best = cost
    return points


def _SWEEP_MIN_AREA_SCHEDULE(
    parser_state,
    key,
    tag,
    budget_scale,
    prev_schedule=None,
    ctl=DEFAULT_CTL,
    debug=False,
    func_entity_override=None,
    build_memo=None,
    graph_memo=None,
):
    """Search for the SMALLEST schedule that still meets the clock goal and the
    latency cap, by opening operations up one entity at a time.

    Shape of the search, and why:

      * The ANCHOR is the plain v1 schedule: everything shared, nothing opened
        beyond what the delay budget forces. It is candidate zero and the
        incumbent, so the answer is never worse than v1's by this model -- which
        is what makes it safe to run by default on every build.
      * Two kinds of MOVE, which are the two directions off that anchor:
          OPEN one entity     - finer grain, fewer distinct units, but more
                                operations to schedule and therefore more
                                states, registers and multiplexers.
          UNSHARE one entity  - one more copy of a unit, so its multiplexers
                                get narrower and its operations stop queueing
                                for it. v1 could not do this at all: it shared
                                everything unconditionally, which for anything
                                cheaper than its own multiplexer (a one-bit OR,
                                say) is a straight loss.
        Sharing costs area in one direction and saves it in the other; the
        anchor sits somewhere in the middle and the search walks both ways.
      * Proposals are local, but every proposal is judged by rescheduling the
        WHOLE function: opening or unsharing entity A changes how B and C pack
        into states, how many values cross state boundaries, and how wide
        everyone's multiplexers get. Judging a move by A's own numbers alone
        would miss all of that.
      * The search walks through up to MAX_SWEEP_UPHILL non-improving moves
        before stopping, and returns the best point it saw. The stopping point
        is not a special rule about multiplexers -- it FALLS OUT of the cost
        model: past some granularity, mux and register area grows faster than
        unit area shrinks, and no move improves on the best any more.

    Everything here is pure computation over already-measured delays. No
    synthesis runs, and no area number is ever read back from the user's tool
    (only timing is available uniformly across tools) -- see the AREA_*
    constants.
    """

    memo = {}
    if graph_memo is None:
        graph_memo = _AreaSearchMemo()
    anchor = BUILD_SCHEDULE(
        parser_state, key, tag, budget_scale, prev_schedule, ctl=ctl,
        func_entity_override=func_entity_override, build_memo=build_memo,
        _graph_memo=graph_memo,
    )
    anchor_cost = ESTIMATE_SCHEDULE_AREA(parser_state, anchor, memo)
    anchor_excess = _state_excess(anchor)
    # States -> the cheapest estimated area of a feasible candidate seen there.
    frontier = {} if anchor["latency_infeasible"] else {anchor["n_states"]: anchor_cost}
    best, best_cost = anchor, anchor_cost
    best_excess = (anchor["latency_infeasible"], anchor_excess)
    cur = anchor
    opened = []
    # Start from the units a max_latency cap already forced on the anchor
    # (_replicate_to_cap): every candidate then begins at a binding that meets
    # the cap instead of repeating that search, and the moves only add to it.
    unshared = {e: n for e, n in anchor["unshared"]} if anchor["max_latency"] else {}
    pipelined = dict(anchor.get("pipelined", ()))
    merged, fused = [], []
    max_states = (
        anchor["max_latency"] - int(anchor.get("register_output", True))
        if anchor["max_latency"] is not None
        else None
    )

    def feasible(profile):
        measured = _with_measurements(profile, anchor.get("unit_measurements"))
        return measured["worst_stage_du"] <= anchor["budget_du"] and (
            max_states is None or profile["latency"] < max_states
        )

    def pipeline_moves(schedule):
        """Local depth steps, as UNSHARE adds one copy: each selection form's
        shallowest feasible depth, one level either side of a chosen depth,
        and back to combinational. Depths are characterized only that far,
        one unit per _map_forked item."""
        delays = anchor["entity_delays_snapshot"]

        def unit_moves(node):
            moves = []
            entity = node["entity"]
            chosen = pipelined.get(entity)
            chosen_latency, chosen_rows = (
                chosen if isinstance(chosen, (tuple, list)) else (chosen, None)
            )
            rows = _fold_count_per_unit(
                node["unit_occurrences"], _units_of(schedule, entity)
            )
            for selection_rows in [None, rows] if rows > 1 else [None]:
                if chosen is None or chosen_rows != selection_rows:
                    profiles = _unit_profiles(
                        parser_state,
                        key,
                        node,
                        delays,
                        selection_rows,
                        until=lambda found: any(feasible(row) for row in found),
                    )
                    targets = [next((row for row in profiles if feasible(row)), None)]
                else:
                    profiles = _unit_profiles(
                        parser_state,
                        key,
                        node,
                        delays,
                        selection_rows,
                        chosen_latency + 1,
                    )
                    targets = [
                        row
                        for row in profiles
                        if row["latency"] in (chosen_latency - 1, chosen_latency + 1)
                    ]
                moves.extend(
                    (entity, row)
                    for row in targets
                    if row is not None and feasible(row)
                )
            if chosen is not None:
                moves.append((entity, None))
            return moves

        return [
            move
            for moves in _map_forked(
                unit_moves,
                _unit_candidate_nodes(parser_state, schedule),
                [
                    parser_state.pypeline_auto_fsm_unit_profiles,
                    SYN.CACHED_PATH_DELAY_READS,
                ],
            )
            for move in moves
        ]

    n_considered = 0
    uphill = 0
    visited = set()

    def trace(label, sched, verdict, cost):
        """One auditable line per candidate. Every 'the search declined to
        move' claim in the docs and tests is only as good as being able to see
        WHICH candidates were considered and why each lost.

        `cost` is evaluate()'s own estimate, passed in rather than recomputed
        -- this function used to call ESTIMATE_SCHEDULE_AREA a second time on
        every surviving candidate just to print what evaluate() already knew."""
        if not debug:
            return
        move = f"{label[0]} {label[1]}"
        if sched is None:
            print(f"AUTO_FSM {key}: sweep candidate {move}: {verdict}", flush=True)
            return
        print(
            f"AUTO_FSM {key}: sweep candidate {move}: est "
            f"{cost:.0f}, "
            f"{len(sched['fus'])} unit(s), {sched['n_states']} states, worst "
            f"state {sched['worst_state_du'] / 10.0:.2f} ns: {verdict}",
            flush=True,
        )

    def build(choices):
        """The schedule for one move's (opened, unshared, pipelined, merged,
        fused), or None with the reason it was rejected. Third element is the
        candidate's estimated cost, computed here (once) rather than by
        trace() or the caller -- ESTIMATE_SCHEDULE_AREA is not cheap (register
        allocation + operand-mux planning over the whole function), memo only
        covers its per-entity area lookups, and this function used to be
        called a second time per surviving candidate under
        --auto_fsm_sweep_debug just to print the same number."""
        trial_opened, trial_unshared, trial_pipelined, trial_merged, trial_fused = (
            choices
        )
        try:
            sched = BUILD_SCHEDULE(
                parser_state,
                key,
                tag,
                budget_scale,
                prev_schedule,
                tuple(sorted(trial_opened)),
                MAX_SWEEP_DAG_NODES,
                tuple(sorted(trial_unshared.items())),
                ctl=ctl,
                func_entity_override=func_entity_override,
                build_memo=build_memo,
                pipelined=tuple(sorted(trial_pipelined.items())),
                merged=tuple(sorted(trial_merged)),
                fused=tuple(sorted(trial_fused)),
                _graph_memo=graph_memo,
            )
        except AutoFsmInternalError:
            raise
        except AUTO.AutoError as error:
            return None, f"rejected: {error}", None
        if sched["latency_infeasible"] and not anchor["latency_infeasible"]:
            return None, "rejected: cannot meet the max_latency cap", None
        if sched["at_floor"] and not anchor["at_floor"]:
            # This made some state unschedulable at the clock goal. More area
            # for worse timing is never the trade being looked for here.
            return None, "rejected: a state stopped fitting the clock goal", None
        if _state_excess(sched) > anchor_excess:
            # Area is the objective; unused timing margin is available to buy
            # it. The hard boundary is the declared clock budget, not the
            # anchor's incidental (often much shorter) worst state. Real
            # synthesis still confirms the result and the driver's existing
            # tighten/reschedule loop recovers from model optimism.
            #
            # When the anchor ITSELF runs over budget (an operation plus the
            # operand mux its fold count implies does not fit a state), a
            # candidate no further over is kept: unsharing one of two
            # over-budget units leaves the other over budget, and rejecting
            # that intermediate would make the jointly feasible two-unit
            # binding unreachable one move at a time.
            return (
                None,
                f"rejected: worst state {sched['worst_state_du'] / 10.0:.2f} ns "
                f"exceeds its {sched['budget_du'] / 10.0:.2f} ns budget",
                None,
            )
        if SCHEDULES_EQUAL({key: cur}, {key: sched}):
            return None, "rejected: unchanged physical schedule", None
        return sched, "considered", ESTIMATE_SCHEDULE_AREA(parser_state, sched, memo)

    def evaluate(moves):
        """The considered candidates among `moves`, in move order, as
        (closeness to the budget, cost, label, schedule, opened, unshared,
        pipelined, merged, fused). A move is (trace label, candidate label,
        opened, unshared, pipelined, merged, fused). Each step's builds are
        independent, so _map_forked may run them in parallel; everything
        else happens here, in move order."""
        nonlocal n_considered
        todo, slots = [], []
        for move in moves:
            choices = move[2:]
            identity = AUTO.frozen(
                (
                    sorted(choices[0]),
                    sorted(choices[1].items()),
                    sorted(choices[2].items()),
                    sorted(choices[3]),
                    sorted(choices[4]),
                )
            )
            if identity in visited:
                slots.append(None)
                continue
            visited.add(identity)
            slots.append(len(todo))
            todo.append(choices)
        caches = [graph_memo.graphs, graph_memo.plans, memo, SYN.CACHED_PATH_DELAY_READS]
        if build_memo is not None:
            caches.append(build_memo)
        built = _map_forked(build, todo, caches)
        considered = []
        for move, slot in zip(moves, slots):
            n_considered += 1
            sched, why, cost = (
                (None, "rejected: already considered", None)
                if slot is None
                else built[slot]
            )
            trace(move[0], sched, why, cost)
            if sched is None:
                continue
            if not sched["latency_infeasible"]:
                frontier[sched["n_states"]] = min(
                    cost, frontier.get(sched["n_states"], cost)
                )
            considered.append(
                ((sched["latency_infeasible"], _state_excess(sched)), cost, move[1], sched)
                + tuple(move[2:])
            )
        return considered

    if debug:
        print(
            f"AUTO_FSM {key}: sweep anchor (share everything): est "
            f"{anchor_cost:.0f}, {len(anchor['fus'])} unit(s), "
            f"{anchor['n_states']} states, worst state "
            f"{anchor['worst_state_du'] / 10.0:.2f} ns",
            flush=True,
        )
    if len(anchor["nodes"]) > MAX_SWEEP_DAG_NODES:
        # Expansion and unsharing cannot score this anchor. A pipelined
        # helper can replace its opened body with one node, so coarsening
        # remains eligible and is checked against the normal per-trial cap.
        n_moves = MAX_SWEEP_MOVES if pipeline_moves(anchor) else 0
        if debug:
            print(
                f"AUTO_FSM {key}: expansion skipped: the anchor already has "
                f"{len(anchor['nodes'])} operations, past the "
                f"{MAX_SWEEP_DAG_NODES} the area search will consider",
                flush=True,
            )
    else:
        n_moves = MAX_SWEEP_MOVES
    for _move in range(n_moves):
        # (trace label, candidate label, opened, unshared, pipelined, merged,
        # fused) for every move off `cur`, in a fixed order.
        moves = []
        allow_expansion = len(cur["nodes"]) <= MAX_SWEEP_DAG_NODES
        for entity in sorted(
            _openable_entities(parser_state, cur, opened) if allow_expansion else ()
        ):
            trial_opened = sorted(opened + [entity])
            trial_pipelined = {
                e: latency for e, latency in pipelined.items() if e != entity
            }
            label = ("open", entity)
            moves.append(
                (label, label, trial_opened, unshared, trial_pipelined, merged, fused)
            )
        unit_moves = _unshareable_entities(cur, unshared) if allow_expansion else {}
        unshare_moves = [
            ("unshare", entity, n) for entity, n in sorted(unit_moves.items())
        ]
        unshare_moves += [
            ("unshare_all", entity, n)
            for entity, n in sorted(_fold_counts(cur).items())
            if entity in unit_moves and n > unit_moves[entity]
        ]
        for move, entity, n_units in unshare_moves:
            trial_unshared = dict(unshared)
            trial_unshared[entity] = n_units
            moves.append(
                (
                    (move, f"{entity} -> {n_units} units"),
                    (move, entity),
                    opened,
                    trial_unshared,
                    pipelined,
                    merged,
                    fused,
                )
            )
        for entity, implementation in pipeline_moves(cur):
            latency = implementation["latency"] if implementation is not None else None
            choice = (
                (latency, implementation["selection_rows"])
                if implementation is not None and implementation["registered_selection"]
                else latency
            )
            if pipelined.get(entity) == choice:
                continue
            trial_pipelined = dict(pipelined)
            if latency is None:
                trial_pipelined.pop(entity)
            else:
                trial_pipelined[entity] = choice
            trial_opened = [e for e in opened if e != entity]
            description = (
                f"{entity} combinational"
                if latency is None
                else f"{entity} L={latency}, selection={implementation['selection_rows']}"
            )
            label = ("pipeline", description)
            moves.append(
                (label, label, trial_opened, unshared, trial_pipelined, merged, fused)
            )
        trial_dag = {"nodes": cur["nodes"], "output": cur["output"]}
        rebinds = [
            ("merge", (narrow, wide))
            for narrow, wide in _local_merge_choices(trial_dag, parser_state)
            if [narrow, wide] not in merged
        ]
        rebinds += [
            ("fuse", pattern)
            for pattern in sorted(_pair_matches(trial_dag, parser_state))
            if pattern in parser_state.pypeline_auto_fsm_fusions
            and pattern not in fused
        ]
        for move, item in rebinds:
            trial_merged = merged + [list(item)] if move == "merge" else merged
            trial_fused = fused + [item] if move == "fuse" else fused
            label = (move, " -> ".join(item) if move == "merge" else item)
            moves.append(
                (label, label, opened, unshared, pipelined, trial_merged, trial_fused)
            )
        candidates = evaluate(moves)
        if not candidates:
            if debug:
                print(
                    f"AUTO_FSM {key}: sweep move {_move}: no candidate survived; "
                    f"stopping",
                    flush=True,
                )
            break
        candidates.sort(key=lambda c: (c[0], c[1], c[2]))
        excess, cost, label, sched, opened, unshared, pipelined, merged, fused = (
            candidates[0]
        )
        # Always take the cheapest available move, even uphill -- see
        # MAX_SWEEP_UPHILL. The incumbent BEST is what gets returned, so
        # walking uphill can only ever discover something, never lose anything.
        cur = sched
        min_win = _sweep_required_improvement(anchor, sched)
        # The ordinary best-to-best threshold suppresses local model noise.
        # The anchor-relative threshold is the structural confidence guard:
        # walking farther through an opened DAG must not make a known modelling
        # blind spot look progressively more authoritative.
        # Getting closer to the clock budget beats any area: only between
        # equally (in)feasible schedules does area decide.
        improved = excess < best_excess or (
            excess == best_excess
            and cost < best_cost * (1.0 - SWEEP_MIN_IMPROVEMENT)
            and cost < anchor_cost * (1.0 - min_win)
        )
        if debug:
            confidence = (
                ""
                if min_win == SWEEP_MIN_IMPROVEMENT
                else f", shape guard needs {min_win * 100.0:.1f}% vs anchor"
            )
            print(
                f"AUTO_FSM {key}: sweep move {_move}: took {label[0]} "
                f"{label[1]} at est {cost:.0f} vs best {best_cost:.0f} -- "
                + ("NEW BEST" if improved else f"uphill {uphill + 1}{confidence}"),
                flush=True,
            )
        if improved:
            best, best_cost, best_excess = sched, cost, excess
            uphill = 0
        else:
            uphill += 1
            if uphill > MAX_SWEEP_UPHILL:
                break

    best["est_area"] = round(best_cost, 3)
    best["est_area_anchor"] = round(anchor_cost, 3)
    best["area_frontier"] = _pareto_frontier(frontier)
    best["sweep_candidates"] = n_considered
    best["sweep_skipped_dag_nodes"] = (
        len(anchor["nodes"]) if len(anchor["nodes"]) > MAX_SWEEP_DAG_NODES else None
    )
    return best


def SWEEP_MIN_AREA_SCHEDULE(
    parser_state, key, tag, budget_scale, prev_schedule=None, ctl=DEFAULT_CTL, debug=False,
    build_memo=None, graph_memo=None,
):
    """Search original and combinationally rewritten graphs by total FSM area.

    Rewrites are choices, not a preprocessing commitment: a larger combinational
    graph can require fewer registers, muxes or states after scheduling.
    `graph_memo` (an _AreaSearchMemo) may be shared by every search of one
    (parser_state, key, tag, budget_scale, prev_schedule).
    """
    graph_memo = graph_memo if graph_memo is not None else _AreaSearchMemo()
    best = _SWEEP_MIN_AREA_SCHEDULE(
        parser_state, key, tag, budget_scale, prev_schedule, ctl=ctl, debug=debug,
        build_memo=build_memo, graph_memo=graph_memo,
    )
    entity = AUTO._entity_key_for_callable(parser_state, tag.func)
    choices = list(getattr(parser_state, "pypeline_comb_area_opt_candidates", {}).get(entity, []))
    choices += getattr(parser_state, "pypeline_comb_delay_opt_candidates", {}).get(entity, [])[:3]
    considered = 0
    for func, report in choices:
        candidate_entity = AUTO._entity_key_for_callable(parser_state, func)
        if candidate_entity is None or candidate_entity == entity:
            continue
        candidate_logic = parser_state.FuncLogicLookupTable[candidate_entity]
        # Bound this additional search by graph work, not a wall-clock timer.
        # The existing OPEN search remains available for deeper decomposition.
        if len(candidate_logic.submodule_instances) > max(128, 4 * len(best["nodes"])):
            continue
        considered += 1
        try:
            candidate = _SWEEP_MIN_AREA_SCHEDULE(
                parser_state, key, tag, budget_scale, prev_schedule, ctl=ctl, debug=debug,
                func_entity_override=candidate_entity, build_memo=build_memo,
                graph_memo=graph_memo,
            )
        except AutoFsmInternalError:
            raise
        except AUTO.AutoError:
            continue
        if (candidate["latency_infeasible"]
                or _state_excess(candidate) > _state_excess(best)
                or (candidate["at_floor"] and not best["at_floor"])):
            continue
        if (_state_excess(candidate) < _state_excess(best)
                or candidate["est_area"] < best["est_area"]):
            candidate["comb_opt_moves"] = report["moves"]
            best = candidate
    if considered:
        best["comb_opt_candidates"] = considered
    return best


def _units_of(schedule, entity):
    """How many physical copies of `entity` a schedule actually built."""
    return sum(1 for e in schedule["fus"].values() if e == entity) or 1


def _fold_counts(schedule):
    """entity -> how many operations are bound to its unit(s)."""
    counts = {}
    for node in schedule["nodes"].values():
        if node.get("fu"):
            counts[node["entity"]] = counts.get(node["entity"], 0) + 1
    return counts


def _unshareable_entities(schedule, unshared):
    """entity -> the copy count to try next, for every unit still carrying more
    than one operation. One extra copy at a time, so the search can stop the
    moment the multiplexer it removes stops being worth the unit it adds."""
    folds = _fold_counts(schedule)
    out = {}
    for entity, n_ops in folds.items():
        have = max(_units_of(schedule, entity), unshared.get(entity, 1))
        if n_ops > have:
            out[entity] = have + 1
    return out


def _budget_du(parser_state, budget_scale):
    """Per-state delay budget in delay units (tenths of a nanosecond).

    Derived from the clock goal of the MAIN(s) the FSM ends up inside; when it
    is instantiated under several clocks the tightest one wins, since one entity
    is built once and must satisfy every context it appears in.
    """
    period_du = _period_du(parser_state)
    if period_du is None:
        # No clock goal anywhere: nothing to schedule against, so keep the whole
        # function in one state.
        return 1 << 30
    return max(1, int(period_du * budget_scale))


def _period_du(parser_state):
    """The tightest MAIN clock period in (fractional) delay units, or None
    when no MAIN has a clock goal. See _budget_du."""
    import SYN

    mhz_values = [
        mhz for mhz in parser_state.main_mhz.values() if mhz is not None and mhz > 0
    ]
    if not mhz_values:
        return None
    return 1000.0 / max(mhz_values) * SYN.DELAY_UNIT_MULT


# Version of the persistent search cache's key and file format.
_SEARCH_CACHE_VERSION = 1
# sha256 of the compiler's and the Pypeline library's source files, computed
# once per process: a search result is reused only by the code that searched it.
_COMPILER_SOURCE_HASH = None


def _compiler_source_hash():
    """sha256 over the Python sources of src/ (tests excluded), src/pipelinec
    and include/pypeline/."""
    global _COMPILER_SOURCE_HASH
    if _COMPILER_SOURCE_HASH is None:
        src = os.path.dirname(os.path.abspath(__file__))
        digest = hashlib.sha256()
        for root in (src, os.path.join(src, "..", "include", "pypeline")):
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(
                    d for d in dirnames if d not in ("__pycache__", "tests")
                )
                for name in sorted(filenames):
                    if not (name.endswith(".py") or name == "pipelinec"):
                        continue
                    path = os.path.join(dirpath, name)
                    digest.update(os.path.relpath(path, src).encode() + b"\0")
                    with open(path, "rb") as f:
                        digest.update(hashlib.sha256(f.read()).digest())
        _COMPILER_SOURCE_HASH = digest.hexdigest()
    return _COMPILER_SOURCE_HASH


def _search_parser_inputs(parser_state):
    """What an area search can read from the parser state besides the FSM's own
    source: the design's sources, every delay an entity carries and its
    estimated flag, the measured control-path proxies, the clock goals and
    target, the delay, area and placement settings and, under DEVICE_MODELS,
    the leaf area cache. An entity without a delay is left out: a search materializes such
    entities (candidates' built-in leaves, unit functions) as it goes, so they
    depend on what searched earlier. What they resolve to from the cache/delay
    files is checked separately (SYN.CACHED_PATH_DELAY_READS)."""
    import DEVICE_MODELS
    import PY_TO_LOGIC
    import SWEEP

    delays = [
        (name, logic.delay, bool(logic.delay_is_estimated))
        for name, logic in sorted(parser_state.FuncLogicLookupTable.items())
        if logic.delay is not None
    ]
    area_files = []
    if SYN.SYN_TOOL is DEVICE_MODELS:
        area_dir = SYN.GET_AREA_CACHE_DIR(parser_state)
        for dirpath, dirnames, filenames in os.walk(area_dir or ""):
            dirnames.sort()
            for name in sorted(filenames):
                stat = os.stat(os.path.join(dirpath, name))
                area_files.append((name, stat.st_size, stat.st_mtime_ns))
    return AUTO.fingerprint(
        [
            sorted(PY_TO_LOGIC.DESIGN_SOURCE_HASHES().values()),
            _target_context(parser_state),
            sorted((main, mhz) for main, mhz in parser_state.main_mhz.items()),
            [
                SYN.USE_PRIMITIVE_DELAY_MODEL,
                SYN._mux_cache_key_is_width_collapsed(),
                AUTO.FORCE_ABSTRACT_AREA,
                SWEEP.PIPELINE_MIN_EFFORT,
            ],
            _control_snapshot(parser_state),
            delays,
            area_files,
        ]
    )


def _search_cache_paths(parser_state, digest):
    """Where a search result with this input digest lives: the output
    directory, then the --syn_cache store when there is one."""
    paths = []
    if SYN.SYN_OUTPUT_DIRECTORY is not None:
        paths.append(
            os.path.join(SYN.SYN_OUTPUT_DIRECTORY, "auto_fsm_searches", digest + ".pkl.z")
        )
    if SYN.SYNTHESIS_STORE_DIR is not None:
        paths.append(
            os.path.join(
                SYN.SYNTHESIS_STORE_DIR,
                "auto_fsm",
                f"v{_SEARCH_CACHE_VERSION}",
                getattr(SYN.SYN_TOOL, "__name__", "none"),
                SYN.PART_CACHE_DIR_NAME(parser_state.part or "none"),
                digest + ".pkl.z",
            )
        )
    return paths


def _read_cached_search(paths, digest, key):
    """The schedule an earlier search with these exact inputs selected, its
    recorded cache/delay reads, and the file it came from; (None, None, None)
    on a miss. A result is reused only while every cache/delay file the
    earlier build had read still reads the same. Anything unreadable, stale
    or malformed is a miss, never a failure."""
    for path in paths:
        try:
            with open(path, "rb") as f:
                version, cached_digest, cached_key, schedule, reads = pickle.loads(
                    zlib.decompress(f.read())
                )
            if (
                version != _SEARCH_CACHE_VERSION
                or cached_digest != digest
                or cached_key != key
                or not SCHEDULE_CACHE_USABLE(schedule)
                or any(
                    SYN.READ_CACHED_PATH_DELAY_FILE(file_path) != delay_ns
                    for file_path, delay_ns in reads.items()
                )
            ):
                continue
        except Exception:
            continue
        try:
            os.utime(path)  # --syn_cache_prune keeps what builds still reuse
        except OSError:
            pass
        return schedule, reads, path
    return None, None, None


def _write_cached_search(paths, digest, key, schedule, reads):
    """Keep a search result, with the cache/delay reads it rests on, at every
    path that lacks it; a failed write only costs the next build a search."""
    blob = zlib.compress(
        pickle.dumps(
            (_SEARCH_CACHE_VERSION, digest, key, schedule, reads),
            pickle.HIGHEST_PROTOCOL,
        ),
        1,
    )
    for path in paths:
        if os.path.exists(path):
            continue
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            temporary = f"{path}.{os.getpid()}.tmp"
            with open(temporary, "wb") as f:
                f.write(blob)
            os.replace(temporary, path)
        except OSError:
            pass


@SYN.PHASED("AUTO_FSM schedule search")
def HARVEST_AUTO_FSM_SCHEDULES(
    parser_state,
    budget_scales=None,
    prev_schedules=None,
    area_sweep=True,
    ctl=DEFAULT_CTL,
    sweep_debug=False,
    force_open=(),
    force_unshare=(),
    keys=None,
):
    """Schedule every AUTO_FSM call site in the design, or only those in
    `keys` when given.

    Returns canonical_key -> schedule dict, ready to hand to
    pypeline.SET_AUTO_FSM_SCHEDULE_CACHE before re-executing the design file.
    prev_schedules carries forward the delay snapshot, so a reschedule on a
    later pass (where the pure function is no longer instantiated and therefore
    no longer measured) works from the same numbers as the first one.

    A call site whose search inputs (_search_parser_inputs, its own source,
    carried schedule and request) match an earlier search reuses that search's
    result from the output directory or the --syn_cache store.
    """
    budget_scales = budget_scales or {}
    prev_schedules = prev_schedules or {}
    tags = GET_TAGS(parser_state)
    schedules = {}
    parser_inputs = None
    for key in sorted(COLLECT_AUTO_FSM_KEYS(parser_state)):
        if keys is not None and key not in keys:
            continue
        tag = tags.get(key)
        if tag is None:
            raise AUTO.AutoError(
                f"AUTO_FSM: no live tag object recorded for call site {key!r} "
                f"(internal error)"
            )
        budget_scale = budget_scales.get(key, DEFAULT_BUDGET_SCALE)
        prev = prev_schedules.get(key)
        if parser_inputs is None:
            parser_inputs = _search_parser_inputs(parser_state)
        func_entity = AUTO._entity_key_for_callable(parser_state, tag.func)
        digest = hashlib.sha256(
            json.dumps(
                [
                    _SEARCH_CACHE_VERSION,
                    SCHEDULE_VERSION,
                    _compiler_source_hash(),
                    parser_inputs,
                    key,
                    parser_state.pypeline_auto_fsm_source_identities.get(key)
                    or _source_identity(parser_state, func_entity),
                    budget_scale,
                    prev,
                    area_sweep,
                    ctl,
                    sorted(force_open),
                    sorted(force_unshare),
                ],
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        cache_paths = _search_cache_paths(parser_state, digest)
        cached, reads, cached_path = _read_cached_search(cache_paths, digest, key)
        if cached is not None:
            print(
                f"AUTO_FSM {key}: reusing the schedule an earlier search chose "
                f"from identical inputs ({cached_path})",
                flush=True,
            )
            _write_cached_search(cache_paths, digest, key, cached, reads)
            schedules[key] = cached
            continue
        modes = ("v3", "onehot") if ctl == "auto" else (ctl,)
        # Shared by the encodings below: under `auto` the onehot search
        # reuses every point the v3 search already scheduled under the same
        # select delay, and every cleaned graph.
        build_memo = {} if len(modes) > 1 else None
        graph_memo = _AreaSearchMemo()

        def build_mode(mode):
            if force_open or force_unshare:
                # An explicitly requested point of the search space overrides
                # the grain/binding search, but auto may still compare its
                # control encodings at that exact point.
                return FORCE_SCHEDULE(
                    parser_state,
                    key,
                    tag,
                    budget_scale,
                    prev,
                    ctl=mode,
                    open_patterns=force_open,
                    unshare_patterns=force_unshare,
                    build_memo=build_memo,
                )
            if area_sweep:
                return SWEEP_MIN_AREA_SCHEDULE(
                    parser_state,
                    key,
                    tag,
                    budget_scale,
                    prev,
                    ctl=mode,
                    debug=sweep_debug,
                    build_memo=build_memo,
                    graph_memo=graph_memo,
                )
            return BUILD_SCHEDULE(
                parser_state, key, tag, budget_scale, prev, ctl=mode,
                build_memo=build_memo,
            )

        variants = []
        for mode in modes:
            candidate = build_mode(mode)
            cost = candidate.get("est_area")
            if cost is None:
                cost = ESTIMATE_SCHEDULE_AREA(parser_state, candidate)
            feasible = (
                not candidate["latency_infeasible"]
                and candidate["worst_state_du"] <= candidate["budget_du"]
            )
            variants.append((not feasible, cost, mode, candidate))
        _bad, _cost, _mode, selected = min(variants, key=lambda v: v[:3])
        if ctl == "auto":
            selected["ctl_auto_candidates"] = {
                mode: round(cost, 3) for _bad, cost, mode, _candidate in variants
            }
        _write_cached_search(
            cache_paths, digest, key, selected, dict(SYN.CACHED_PATH_DELAY_READS)
        )
        schedules[key] = selected
    return schedules


def LATENCY_INFEASIBLE_MESSAGE(key, schedule) -> str:
    """What to print when a hard max_latency cap cannot be met. Names the FSM,
    the cap, and the latency it actually needs -- the number the user has to
    know to decide between raising the cap, relaxing the clock goal, or
    rewriting the function."""
    return (
        f"AUTO_FSM {key}: max_latency={schedule['max_latency']} cannot be met. "
        f"The shortest schedule meeting the {schedule['budget_du'] / 10.0:.2f} "
        f"ns/state delay budget needs {schedule['n_states']} states "
        f"(latency {schedule['latency']}) even with one unit per operation, so "
        f"no amount of unsharing meets the cap. Raise max_latency to at least "
        f"{schedule['latency']}, lower the clock goal, or shorten the "
        f"function's dependency chain."
    )


def BLAMED_AUTO_FSM_KEYS(parser_state, multimain_timing_params, schedules):
    """Which AUTO_FSM regions could plausibly be responsible for a timing failure.

    The sweep's failure records name the MAIN that missed its clock and, when it
    could attribute one, the function to blame. A generated FSM entity is
    stateful, so the sweep already treats it as an unsliceable atomic block
    whose delay is a floor -- exactly what it reports as blame when it cannot
    pipeline its way out.

    With no attribution available (notably the PYRTL software timing model,
    which reports no path detail), fall back to blaming every AUTO_FSM under the
    failing MAIN. Over-blaming costs one extra schedule pass at a tighter
    budget; under-blaming would silently give up.
    """
    return set(_BLAMED_MISS_RATIOS(parser_state, multimain_timing_params, schedules))


def _BLAMED_MISS_RATIOS(parser_state, multimain_timing_params, schedules):
    """blamed key -> achieved/goal MHz of the worst failure blaming it, or None
    when no failure blaming it reported an achieved number. The attribution
    behind BLAMED_AUTO_FSM_KEYS; the ratio is how far TIGHTENED_BUDGET_SCALE
    shrinks the key's per-state budget."""
    failures = getattr(multimain_timing_params, "sweep_timing_failures", None)
    if not failures:
        return {}
    # A failure names an FSM entity, or the AUTO_PIPELINE region of one of its
    # pinned units ("stop(AUTO_FSM owns pipeline placement auto_fsm_pinned_...)"),
    # which repair and tightening of the owning FSM can address.
    name_to_key = {sched["entity"]: key for key, sched in schedules.items()}
    for key, sched in schedules.items():
        for implementation in sched.get("implementations", {}).values():
            name_to_key[_pinned_unit_name(implementation)] = key
    ratios = {}
    for main_func_name, goal, achieved, why in failures:
        keys = {
            name_to_key[name] for name in name_to_key if name in (why or "")
        } or _AUTO_FSM_KEYS_UNDER_MAIN(parser_state, main_func_name)
        ratio = achieved / goal if achieved and goal else None
        for key in keys:
            if key not in schedules:
                continue
            prev = ratios.get(key)
            if prev is None or (ratio is not None and ratio < prev):
                ratios[key] = ratio
            else:
                ratios.setdefault(key, prev)
    return ratios


def TIGHTENED_BUDGET_SCALE(parser_state, budget_scale, miss_ratio, worst_state_du):
    """The next per-state budget scale for an FSM blamed for a timing miss.

    Scaled by the measured miss (achieved / goal MHz): a build that reached
    72.65 of 80 MHz had its real critical state about 1/0.908 longer than the
    model priced it, so the budget shrinks by that much -- not by a fixed
    step that can overshoot past whole operator widths (0.75 took the
    WireGuard Poly1305 epilogue from 11.2 to 8.4 ns, below its 34-bit
    multiplies and 260-bit adds). BUDGET_TIGHTEN_FACTOR stands in when the
    failure reported no achieved number.

    Always at least just below the schedule's current worst state, so the
    state that state's chain packed into must change -- a near miss (79.99 of
    80 MHz) would otherwise shrink the budget by a rounding error and move
    nothing.
    """
    factor = (
        miss_ratio if miss_ratio is not None and 0.0 < miss_ratio < 1.0
        else BUDGET_TIGHTEN_FACTOR
    )
    scale = budget_scale * factor
    period_du = _period_du(parser_state)
    if period_du and worst_state_du > 0:
        # _budget_du truncates, so any scale putting period_du * scale below
        # worst_state_du gives a budget of at most worst_state_du - 1.
        scale = min(scale, (worst_state_du - 0.5) / period_du)
    return scale


def _AUTO_FSM_KEYS_UNDER_MAIN(parser_state, main_func_name):
    """AUTO_FSM keys instantiated anywhere in one MAIN's instance hierarchy."""
    keys = set()
    for inst_name, logic in parser_state.LogicInstLookupTable.items():
        if not logic.sub_inst_to_auto_fsm_key:
            continue
        root = inst_name.split(LOGIC.SUBMODULE_MARKER)[0]
        if root == main_func_name:
            keys.update(logic.sub_inst_to_auto_fsm_key.values())
    return keys


# Schedule fields that describe HOW a schedule was reached or scored, not the
# hardware it builds. The budget fields change on every tightening step, and
# `entity` hashes them in -- comparing them made every tightened trial look
# "changed", so the driver's "shrinking no longer changes the schedule" stop
# could never fire and each step spent a synthesis on identical hardware.
_SCHEDULE_NON_HARDWARE_KEYS = frozenset(
    (
        "budget_scale",
        "budget_du",
        "worst_state_du",
        "at_floor",
        "entity",
        "est_area",
        "est_area_anchor",
        "area_frontier",
        "sweep_candidates",
        "ctl_auto_candidates",
        "comb_opt_candidates",
        "comb_opt_moves",
        "sweep_skipped_dag_nodes",
        "descend_truncated",
        "descend_blocked",
        "cleanup",
        "constant_wrapper_count",
        "entity_delays_snapshot",
        "measured_entities",
        "mux_delays_snapshot",
        "timing_evidence",
        "repair_history",
        "unit_measurements",
        "control_delays_snapshot",
        "corrected_entity_delays",
        "select_arrivals",
        "no_chain_edges",
        "no_chain_entity_pairs",
        "opened",
        "unshared",
        "merged",
        "fused",
        "pipelined",
        "forced",
    )
)


def _schedule_hardware(schedule):
    hardware = {
        k: v for k, v in schedule.items() if k not in _SCHEDULE_NON_HARDWARE_KEYS
    }
    if "nodes" in hardware:
        hardware["nodes"] = {
            nid: {key: value for key, value in node.items() if key != "end_du"}
            for nid, node in hardware["nodes"].items()
        }
    if "implementations" in hardware:
        fields = (
            "base_entity",
            "unit_entity",
            "latency",
            "ii",
            "registered_selection",
            "selection_rows",
            "timing",
            "placement_digest",
        )
        hardware["implementations"] = {
            entity: {
                key: value for key, value in implementation.items() if key in fields
            }
            for entity, implementation in hardware["implementations"].items()
        }
    return hardware


def SCHEDULES_EQUAL(a, b) -> bool:
    """Do two {key: schedule} maps build the same hardware?

    The driver loop's convergence test. Budget and scoring bookkeeping is
    ignored (see _SCHEDULE_NON_HARDWARE_KEYS): the tighten loop asks whether a
    smaller budget moved any operation, not whether the number changed."""
    if a is None or b is None:
        return a is b
    if set(a) != set(b):
        return False
    return all(
        _schedule_hardware(a[k]) == _schedule_hardware(b[k]) for k in sorted(a)
    )


def FAILED_MAIN_MHZ(multimain_timing_params):
    """main name -> achieved MHz for every MAIN that missed its goal on the
    last build (entries with no achieved number are left out)."""
    failures = getattr(multimain_timing_params, "sweep_timing_failures", None) or []
    return {
        main: achieved
        for main, _goal, achieved, _why in failures
        if achieved is not None
    }


def TIGHTENING_STALLED(prev_failed_mhz, failed_mhz):
    """[(main, prev_mhz, mhz)] when a tightened build helped NO failing MAIN,
    else [].

    Stalled means every MAIN that still fails had also failed before and did
    not gain more than TIGHTEN_MIN_FMAX_GAIN. Any MAIN without a previous
    number counts as progress unknown -- never stop on missing data."""
    if not failed_mhz or not prev_failed_mhz:
        return []
    stalled = []
    for main in sorted(failed_mhz):
        prev = prev_failed_mhz.get(main)
        if prev is None:
            return []
        mhz = failed_mhz[main]
        if mhz > prev * (1.0 + TIGHTEN_MIN_FMAX_GAIN):
            return []
        stalled.append((main, prev, mhz))
    return stalled


def _reg_bits_from_types(schedule, reg_types):
    """Total register bits given an allocation's reg_types: every register's
    own width, compacted transaction-input storage, the state register and
    optional output data/valid bank.
    Shared by ESTIMATE_SCHEDULE_AREA (which already has reg_types from its own
    ALLOCATE_REGISTERS call) and _register_bit_count (which needs the same
    total on its own, with no other area computation)."""
    reg_bits = sum(AUTO._ctype_width(t) for t in reg_types.values())
    reg_bits += sum(
        schedule.get("implementations", {}).get(entity, {}).get("register_bits", 0)
        for entity in schedule["fus"].values()
    )
    reg_bits += sum(
        pack["width"]
        for pack in _OUTPUT_SHIFT_PACKS(
            schedule["nodes"], schedule["output"], schedule["n_states"]
        )
    )
    input_storage = _INPUT_STORAGE_PLAN(
        schedule["nodes"], schedule["output"], schedule["n_states"]
    )
    if input_storage is None:
        reg_bits += AUTO._ctype_width(schedule["in_type"])
    else:
        reg_bits += sum(
            AUTO._ctype_width(field["ctype"]) for field in input_storage["stored_fields"]
        )
    if schedule.get("register_output", True):
        reg_bits += AUTO._ctype_width(schedule["out_type"]) + 1  # data + valid
    if schedule.get("ctl", "v3") == "onehot":
        # One flip-flop per state plus idle, where binary needs only log2.
        reg_bits += schedule["n_states"] + 1
    else:
        reg_bits += max(1, int(schedule["n_states"]).bit_length())
    return reg_bits


def _register_bit_count(schedule):
    """Total register bits ALLOCATE_REGISTERS commits a schedule to: every
    cross-state value (sharing where live ranges and functional unit both
    allow it) plus compacted input, state and optional output registers -- exactly what
    ESTIMATE_SCHEDULE_AREA prices, recomputed here (cheap: pure function of
    an already-built schedule, no rescheduling) so DESCRIBE_SCHEDULE can
    print it regardless of whether the area sweep ran. This is AUTO_FSM's OWN
    register count, distinct from SYN.GET_REGISTERS_ESTIMATE_TEXT_AND_FFS's
    whole-design FF estimate (which counts every declared pipeline-register
    bit before yosys's own FF optimization, and is already documented to
    overshoot real synthesized FF count by 5.7-5.9x on a state-heavy design)
    -- comparing THIS number against a real build's measured sequential cell
    count is what checks whether AUTO_FSM's allocator has a comparable gap.
    """
    _reg_of, reg_types = ALLOCATE_REGISTERS(
        schedule["nodes"],
        schedule["output"],
        schedule["n_states"],
        schedule.get("cross_fu_register_types", ()),
    )
    return _reg_bits_from_types(schedule, reg_types)


def _chain_floor(schedule):
    """States this graph needs with one unit per operation and no operand
    muxes: the dependency chain's floor at the schedule's budget."""
    folds = collections.Counter(
        node["entity"] for node in schedule["nodes"].values() if node["delay_du"] > 0
    )
    plan = SCHEDULE_DAG(
        {"nodes": schedule["nodes"], "output": schedule["output"]},
        schedule["budget_du"],
        lambda nid: 0,
        None,
        dict(folds),
        schedule.get("implementations", {}),
        None,
        schedule.get("no_chain_edges", ()),
        schedule.get("no_chain_entity_pairs", ()),
    )
    return plan["n_states"]


def DESCRIBE_SCHEDULE(parser_state, key, schedule) -> str:
    """One-line (or, once the area search ran, multi-line) build-log summary:
    what got folded onto what, and at what cost.

    This is the compiler-side resource statement -- deterministic and
    tool-independent, unlike utilization numbers, which only a real synthesis
    run produces (Vivado report_utilization; yosys cell counts under PYRTL)."""
    n_ops = len([n for n in schedule["nodes"].values() if n.get("fu")])
    n_fus = len(schedule["fus"])
    worst_ns = schedule["worst_state_du"] / 10.0
    budget_ns = schedule["budget_du"] / 10.0
    floor = " AT FLOOR" if schedule["at_floor"] else ""
    cap = schedule.get("max_latency")
    cap_txt = f"/{cap} max" if cap else ""
    line = (
        f"AUTO_FSM {key}: {n_ops} ops -> {n_fus} shared unit(s), "
        f"{schedule['n_states']} states, latency {schedule['latency']}{cap_txt} clks, "
        f"budget {budget_ns:.2f} ns/state (scale {schedule['budget_scale']:.3f}), "
        f"worst state {worst_ns:.2f} ns{floor}"
    )
    truncated = schedule.get("descend_truncated") or []
    if truncated:
        # Surfaces a fallback that used to be silent: descent gave up on
        # these entities purely because of _MAX_DESCEND_DEPTH, not because
        # nothing more could be shared -- worth knowing when AT FLOOR shows
        # up right after it (see the depth cap's own docstring).
        entities = sorted({e for _nid, e, _du in truncated})
        worst = max(du for _nid, _e, du in truncated)
        more = f", +{len(entities) - 3} more" if len(entities) > 3 else ""
        line += (
            f"\n  descend cap: gave up after {AUTO._MAX_DESCEND_DEPTH} levels for "
            f"{len(entities)} entity/ies (worst {worst / 10.0:.2f} ns vs "
            f"{budget_ns:.2f} ns/state budget), kept atomic: "
            f"{', '.join(entities[:3])}{more}"
        )
    blocked = schedule.get("descend_blocked") or []
    if blocked:
        # The other silent fallback: an operation too slow for one state
        # stayed atomic because it could not be opened at all. Usually this
        # is the whole story behind AT FLOOR, so name what stood in the way.
        worst_by_entity = {}
        for _nid, entity, du, why in blocked:
            if entity not in worst_by_entity or du > worst_by_entity[entity][0]:
                worst_by_entity[entity] = (du, why)
        ranked = sorted(worst_by_entity, key=lambda e: (-worst_by_entity[e][0], e))
        line += (
            f"\n  descent blocked: {len(ranked)} entity/ies slower than the "
            f"{budget_ns:.2f} ns/state budget kept atomic:"
        )
        for entity in ranked[:3]:
            du, why = worst_by_entity[entity]
            line += f"\n    {entity} ({du / 10.0:.2f} ns): {why}"
        if len(ranked) > 3:
            line += f"\n    +{len(ranked) - 3} more"
    line += f"\n  register bits: {_register_bit_count(schedule)}"
    line += f"\n  dependency floor: {_chain_floor(schedule)} states with one unit per operation"
    bound = {node["entity"] for node in schedule["nodes"].values() if node.get("fu")}
    measured = bound & set(schedule.get("measured_entities", ()))
    line += (
        f"\n  operation delays: {len(measured)} of {len(bound)} unit kind(s) measured, "
        f"{len(bound) - len(measured)} estimated"
    )
    if schedule.get("cleanup"):
        line += "\n  graph cleanup: " + ", ".join(
            f"{name} {count}" for name, count in sorted(schedule["cleanup"].items())
        )
    line += f"\n  constant characterization shapes: {schedule.get('constant_wrapper_count', 0)}"
    for entity, implementation in sorted(schedule.get("implementations", {}).items()):
        line += (
            f"\n  pipeline {entity}: L={implementation['latency']}, II={implementation['ii']}, "
            f"{implementation['register_bits']} register bits (estimated), "
            f"placement {implementation['placement_digest'][:16]}"
        )
        events = sorted(
            (node["launch_state"], node["state"])
            for node in schedule["nodes"].values()
            if node.get("fu") and node["entity"] == entity
        )
        line += f"\n    launch/completion states: {events}"
        recipe = implementation["timing"]
        line += (
            f"\n    pipeline boundaries: {sum(len(row['slices']) for row in recipe)} slice(s), "
            f"{sum(bool(row['input_regs']) for row in recipe)} input bank(s), "
            f"{sum(bool(row['output_regs']) for row in recipe)} output bank(s); "
            "concrete placement in the generated schedule JSON"
        )
        measured = schedule.get("unit_measurements", {}).get(
            implementation["placement_digest"]
        )
        stages = _with_measurements(implementation, schedule.get("unit_measurements"))
        line += (
            f"\n    stage timing: {stages['evidence']}, worst stage "
            f"{stages['worst_stage_du'] / 10.0:.2f} ns"
            + ("" if measured else " (predicted)")
        )
    controls = schedule.get("control_delays_snapshot", {})
    if controls:
        line += f"\n  control timing: {len(controls)} measured/proved decode shape(s); max(data, select) + mux"
    evidence = schedule.get("timing_evidence", ())
    if evidence:
        line += (
            f"\n  timing provenance: {sum(row['attributed'] for row in evidence)} attributed, "
            f"{sum(not row['attributed'] for row in evidence)} unattributed path(s)"
        )
    for decision in schedule.get("repair_history", ()):
        line += f"\n  timing repair: {decision}"
    if schedule.get("comb_opt_candidates"):
        line += f"\n  combinational candidates: {schedule['comb_opt_candidates']}; "
        line += (
            ", ".join(schedule.get("comb_opt_moves", [])) or "original graph retained"
        )
    ctl_candidates = schedule.get("ctl_auto_candidates")
    if ctl_candidates:
        scores = ", ".join(
            f"{mode} {cost:.0f}" for mode, cost in sorted(ctl_candidates.items())
        )
        line += f"\n  control encoding: {schedule['ctl']} selected ({scores})"
    else:
        line += f"\n  control encoding: {schedule.get('ctl', 'v3')}"
    est = schedule.get("est_area")
    if est is not None:
        anchor = schedule.get("est_area_anchor") or est
        # Negative = smaller than sharing everything at the written grain.
        pct = ((est - anchor) / anchor) * 100.0 if anchor else 0.0
        n_opened = len(schedule.get("opened") or ())
        n_unshared = len(schedule.get("unshared") or ())
        line += (
            f"\n  area search: {pct:+.1f}% area vs sharing everything "
            f"(estimated {est:.0f} against {anchor:.0f}), {n_opened} kind(s) "
            f"opened up, {n_unshared} kind(s) given extra unit(s), "
            f"{schedule.get('sweep_candidates', 0)} candidate schedule(s) tried"
        )
        frontier = schedule.get("area_frontier")
        if frontier and len(frontier) > 1:
            # A max_latency= cap at one of these state counts gets about that
            # area. Only what the area walk visited, so not exhaustive.
            line += "\n  area vs states (seen by the area search, not exhaustive): " + ", ".join(
                f"{states} states {cost:.0f}" for states, cost in frontier
            )
        if schedule.get("sweep_skipped_dag_nodes"):
            line += (
                f"\n  area search skipped: the share-everything schedule already "
                f"has {schedule['sweep_skipped_dag_nodes']} operations (> "
                f"{MAX_SWEEP_DAG_NODES}), so every candidate would exceed the cap"
            )
        line += f"\n  area model: {_describe_area_model(parser_state, schedule)}"
        for entity in schedule.get("opened") or ():
            line += f"\n    opened up: {entity}"
        built = collections.Counter(schedule["fus"].values())
        for entity, n_units in schedule.get("unshared") or ():
            # The scheduler fills the lowest-numbered copies first; unused
            # allowed copies are never built.
            allowed = f" ({n_units} allowed)" if n_units != built[entity] else ""
            line += f"\n    {built[entity]} units of: {entity}{allowed}"
        for narrow, wide in schedule.get("merged") or ():
            line += f"\n    merged onto a wider unit: {narrow} -> {wide}"
        for pattern in schedule.get("fused") or ():
            line += f"\n    fused pair: {pattern}"
    return line


def DESCRIBE_FUS(schedule):
    """Per-unit fold counts: 'this operation appears N times in the pure
    function and became 1 instance'. Sorted lines for the build log."""
    counts = {}
    for node in schedule["nodes"].values():
        fu = node.get("fu")
        if not fu:
            continue
        counts[fu] = counts.get(fu, 0) + 1
    fus = schedule["fus"]
    return [
        f"  {fus.get(fu, fu)} x{count} -> 1 unit"
        + ("" if fus.get(fu, fu) == fu else f" [{fu}]")
        for fu, count in sorted(counts.items())
    ]


def PARSE_UNSHARE_SPEC(spec):
    """argparse type= callable for --auto_fsm_unshare SUBSTR=N. Returns (pattern,
    n_units); raises ArgumentTypeError on a malformed spec so a bad flag fails at
    argument-parsing time rather than partway into a build."""
    import argparse

    pattern, _, n_units = spec.rpartition("=")
    if not pattern or not n_units.isdigit():
        raise argparse.ArgumentTypeError(
            f"--auto_fsm_unshare expects SUBSTR=N, got {spec!r}"
        )
    return (pattern, int(n_units))


# ──────────────────────────────────────────────────────────────────────
# Control timing, path attribution and local repair
# ──────────────────────────────────────────────────────────────────────


def _control_proxy(parser_state, key, ctl, state_width, select_width):
    """Small shape proxy for first-pass decode delay, never emitted in an FSM."""
    import pypeline

    identity = AUTO.frozen((ctl, state_width, select_width))
    cached = parser_state.pypeline_auto_fsm_control_proxies.get(identity)
    if cached is not None:
        return cached
    elaborator = parser_state.pypeline_auto_fsm_elaborators.get(key)
    if elaborator is None:
        return None
    emitter = AUTO._Emitter()
    state_type = pypeline.make_uint_t(state_width)
    select_type = pypeline.make_uint_t(select_width)
    name = (
        "auto_fsm_control_proxy_"
        + AUTO.fingerprint((ctl, state_width, select_width))[:20]
    )
    emitter.inj_named(pypeline.hw_func, "hw_func")
    emitter.inj_named(pypeline.bit_assign, "bit_assign")
    emitter.line("@hw_func")
    emitter.line(
        f"def {name}(state: {emitter.inj(state_type, 't')}) -> {emitter.inj(select_type, 't')}:"
    )
    emitter.line(f"    result: {emitter.inj(select_type, 't')} = 0")
    wiring = True
    for bit in range(select_width):
        if ctl == "onehot":
            positions = [i for i in range(state_width) if (i >> bit) & 1]
            operator = " | "
        else:
            # Overlapping parity windows exercise decode logic at this input
            # width. This is a shape proxy, not a truth-table or fanout claim.
            span = max(1, state_width - select_width + 1)
            positions = [(bit + offset) % state_width for offset in range(span)]
            operator = " ^ "
        wiring = wiring and len(positions) <= 1
        expression = operator.join(f"state[{i}:{i}]" for i in positions) or "0"
        emitter.line(f"    result = bit_assign(result, {expression}, {bit})")
    emitter.line("    return result")
    fn = AUTO._exec_generated(name, emitter.src(), emitter.globals)
    if wiring:
        fn = pypeline.wires(fn)
    logic = elaborator._elaborate_live_func(name, fn)
    AUTO._RESOLVE_BUILTIN_SUBMODULES(parser_state, logic.func_name)
    if wiring:
        logic.delay = 0
    else:
        parser_state.pypeline_auto_fsm_measure_callables.append(fn)
    result = dict(
        function=fn,
        entity=logic.func_name,
        ctl=ctl,
        wiring=wiring,
        state_width=state_width,
        select_width=select_width,
    )
    parser_state.pypeline_auto_fsm_control_proxies[identity] = result
    return result


def _prepare_control_proxies(parser_state, key, schedule, ctl):
    """One proxy per encoding/state width/select width, independent of rows."""
    reg_of, _types = ALLOCATE_REGISTERS(
        schedule["nodes"],
        schedule["output"],
        schedule["n_states"],
        schedule.get("cross_fu_register_types", ()),
    )
    state_width = (
        schedule["n_states"] + 1
        if ctl == "onehot"
        else max(1, schedule["n_states"].bit_length())
    )
    widths = set()
    for fu in schedule["fu_order"]:
        nodes, plans = _operand_mux_plan(schedule, fu, reg_of)
        widths.update(
            max(1, (choices - 1).bit_length())
            for _mapping, choices in _selector_shapes(schedule, fu, nodes, plans)
        )
    return [
        record
        for width in sorted(widths)
        for record in [_control_proxy(parser_state, key, ctl, state_width, width)]
        if record is not None
    ]


def _control_snapshot(parser_state, previous=None):
    """Measured shape proxies, retained across scheduled re-parses."""
    result = copy.deepcopy(previous or {})
    for record in parser_state.pypeline_auto_fsm_control_proxies.values():
        logic = parser_state.FuncLogicLookupTable[record["entity"]]
        if logic.delay is not None and (
            record["wiring"] or not logic.delay_is_estimated
        ):
            result[record["entity"]] = dict(
                ctl=record["ctl"],
                delay_du=logic.delay,
                state_width=record["state_width"],
                select_width=record["select_width"],
                source="wiring proof"
                if record["wiring"]
                else "measured decode shape proxy",
            )
    return result


def _select_delay(snapshot, ctl):
    """Measured shape proxy; in-context state-register paths refine each unit."""
    return max(
        (row["delay_du"] for row in snapshot.values() if row["ctl"] == ctl), default=0
    )


def _calibrate_controls(parser_state, budget_scales, ctl, previous, keys=None):
    """Measure distinct decode shapes before the first full area search, for
    every call site or only those in `keys`."""
    snapshots = {}
    modes = ("v3", "onehot") if ctl == "auto" else (ctl,)
    for key, tag in sorted(GET_TAGS(parser_state).items()):
        if keys is not None and key not in keys:
            continue
        old = (previous or {}).get(key)
        snapshot = _control_snapshot(
            parser_state, (old or {}).get("control_delays_snapshot")
        )
        missing = [
            mode
            for mode in modes
            if not any(row["ctl"] == mode for row in snapshot.values())
        ]
        roots = set()
        for mode in missing:
            provisional = BUILD_SCHEDULE(
                parser_state,
                key,
                tag,
                budget_scales.get(key, DEFAULT_BUDGET_SCALE),
                old,
                ctl=mode,
            )
            roots.update(
                record["entity"]
                for record in _prepare_control_proxies(
                    parser_state, key, provisional, mode
                )
                if not record["wiring"]
            )
        if roots:
            parser_state = _measure_entities(parser_state, roots)
        snapshots[key] = _control_snapshot(parser_state, snapshot)
    return parser_state, snapshots


def _estimate_could_decide(parser_state, entity, budget_du):
    """Whether measuring an estimated entity could change whether it fits a
    state. A derived estimate always could. A primitive width estimated from
    measured widths (SYN.PrimitiveDelayModel) carries an error bound; only one
    whose delay plus the flat mux allowance lies within that bound of the
    state budget gets a synthesis run."""
    logic = parser_state.FuncLogicLookupTable[entity]
    error = logic.delay_model_error
    if not logic.delay_is_estimated or error is None or logic.delay is None:
        return True
    return abs(logic.delay + AUTO.MUX_PENALTY_DU - budget_du) <= error


def _needs_measurement(parser_state, entity):
    """A pure, inspectable entity whose current delay is not a measurement."""
    import SYN

    logic = parser_state.FuncLogicLookupTable.get(entity)
    if logic is None or logic.vhdl_module_text is not None:
        return False
    if logic.delay is not None and not logic.delay_is_estimated:
        return False
    if entity in getattr(parser_state, "func_force_estimated", ()):
        return False
    return not SYN.LOGIC_IS_ZERO_DELAY(
        logic, parser_state, allow_none_delay=True
    ) and not SYN.FUNC_SUBTREE_HAS_STATE(entity, parser_state)


def _measure_entities(parser_state, entities):
    """Standalone measurements for entities the design's delay scope cannot reach.

    The delay scope walks instances under a MAIN. Generated candidates (decode
    proxies, constant wrappers) are never instantiated there, and neither is
    anything inside a pure function once its scheduled FSM replaces it. Each
    entity gets an isolated root instance instead, reaching the backend's
    ordinary per-function run with its output-directory and --syn_cache reuse.
    The design's own instance tables are untouched; the shared Logic objects
    receive the measurements.
    """
    import AUTO_PIPELINE
    import SYN
    import VHDL

    pending = sorted(entities)
    if not pending:
        return parser_state
    isolated = copy.copy(parser_state)
    isolated.LogicInstLookupTable = {}
    isolated.FuncToInstances = {}
    isolated.main_mhz = {}
    isolated.main_syn_mhz = {}
    isolated.main_clk_group = {}

    def visit(inst, name):
        logic = parser_state.FuncLogicLookupTable[name]
        isolated.LogicInstLookupTable[inst] = logic
        isolated.FuncToInstances.setdefault(name, set()).add(inst)
        for local, child in sorted(logic.submodule_instances.items()):
            visit(inst + LOGIC.SUBMODULE_MARKER + local, child)

    for entity in pending:
        root = "auto_fsm_measure_" + hashlib.sha256(entity.encode()).hexdigest()[:20]
        isolated.main_mhz[root] = None
        visit(root, entity)
        # Per-function runs only measure what has no delay yet.
        parser_state.FuncLogicLookupTable[entity].delay = None
    # Per-function runs read their submodules' entity files, which the design
    # wrote only for what it instantiates.
    timing = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(isolated)
    for name, insts in sorted(isolated.FuncToInstances.items()):
        logic = isolated.FuncLogicLookupTable[name]
        if (
            logic.is_vhdl_func
            or logic.is_vhdl_expr
            or logic.func_name == LOGIC.VHDL_FUNC_NAME
            or logic.is_clock_crossing
            or logic.is_fsm_clk_func
        ):
            continue
        out_dir = SYN.GET_OUTPUT_DIRECTORY(logic)
        os.makedirs(out_dir, exist_ok=True)
        VHDL.WRITE_LOGIC_ENTITY(sorted(insts)[0], logic, out_dir, isolated, timing)
    SYN.ADD_PATH_DELAY_TO_LOOKUP(isolated, root_func_names=set(pending))
    # Resolved delays derived from the old estimates are stale now.
    memo = getattr(parser_state, AUTO._DELAY_MEMO_ATTR, None)
    if memo is not None:
        memo.clear()
    return parser_state


def _measure_schedule_inputs(parser_state, budget_scales, previous, keys=None):
    """Measure every delay that decides the forced-descent grain, for every
    call site or only those in `keys`.

    A helper that is not a delay-scope frontier carries a delay derived from
    its submodules: standalone leaves, each with its own registers and routing,
    summed along the deepest chain. On Artix-7 a nine-leaf soft comparator
    prefix level derives 10.8 ns where its synthesis measures 2.3 ns, and
    forced descent then split it and everything above it into one-bit gates.
    So before scheduling, every operation the plain forced grain opens or keeps
    atomic over budget gets a measurement, and then every operation it binds.
    Descent decisions go first, outermost first: a helper measured whole needs
    none of its children measured. An entity with a measured part already too slow for a
    state is not measured: the whole cannot be faster, so the decision stands
    (this keeps a kernel's whole parallel body from being synthesized). A
    measurement can move a descent and expose new decisions, so this repeats
    until none rests on an estimate.
    """
    tried = set()
    while True:
        descents = set()
        # Bound entity -> the tightest state budget it is scheduled against.
        bound = {}
        for key, tag in sorted(GET_TAGS(parser_state).items()):
            if keys is not None and key not in keys:
                continue
            func_entity = AUTO._entity_key_for_callable(parser_state, tag.func)
            if func_entity is None:
                continue
            old = (previous or {}).get(key) or {}
            delays = _schedule_delays(
                parser_state, func_entity, old.get("entity_delays_snapshot", {})
            )
            measured = set(
                _measured_entities(
                    parser_state,
                    set(delays) | set(old.get("measured_entities", ())),
                    old.get("measured_entities", ()),
                )
            )
            budget_du = _budget_du(
                parser_state, budget_scales.get(key, DEFAULT_BUDGET_SCALE)
            )
            try:
                dag = AUTO.BUILD_DAG(parser_state, func_entity, delays, budget_du)
            except AUTO.AutoError:
                continue  # BUILD_SCHEDULE reports why.
            decided = {
                nid: node["entity"]
                for nid, node in dag["nodes"].items()
                if node["kind"] == "inlined"
            }
            decided.update((row[0], row[1]) for row in dag["descend_blocked"])
            pending_ids = {
                nid
                for nid, entity in decided.items()
                if entity not in measured
                and not any(
                    part in measured
                    and delays.get(part, 0) + AUTO.MUX_PENALTY_DU > budget_du
                    for part in AUTO._subtree_entities(parser_state, entity)
                    if part != entity
                )
            }
            # Outermost first: a descent inside a pending one may never happen.
            descents.update(
                decided[nid]
                for nid in pending_ids
                if not any(
                    nid.startswith(outer + LOGIC.SUBMODULE_MARKER)
                    for outer in pending_ids
                )
            )
            # Bound operations as scheduling sees them: cleanup adds units of
            # its own (balanced selections, constant-multiply factories).
            cleaned, _stats, _identity = _clean_schedule_graph(
                parser_state, func_entity, delays, budget_du, (), [], (), (), None
            )
            for node in cleaned["nodes"].values():
                if node["delay_du"] > 0 and node["entity"] not in measured:
                    bound[node["entity"]] = min(
                        budget_du, bound.get(node["entity"], budget_du)
                    )
        pending = {
            entity
            for entity in descents - tried
            if _needs_measurement(parser_state, entity)
        }
        if not pending:
            pending = {
                entity
                for entity, budget_du in bound.items()
                if entity not in tried
                and _needs_measurement(parser_state, entity)
                and _estimate_could_decide(parser_state, entity, budget_du)
            }
        if not pending:
            return parser_state
        tried |= pending
        print(
            f"AUTO_FSM: measuring {len(pending)} operation(s) before scheduling instead of "
            f"deciding on derived estimates",
            flush=True,
        )
        parser_state = _measure_entities(parser_state, pending)


def _timing_register(name, registers):
    lowered = (name or "").lower()
    rows = [
        row
        for reg, row in sorted(registers.items())
        if re.search(
            r"(?:^|[^a-z0-9])" + re.escape(reg.lower()) + r"(?:$|[^a-z0-9])", lowered
        )
    ]
    if not rows:
        return None
    roles = sorted({row["role"] for row in rows})
    return dict(
        role="/".join(roles),
        node_ids=sorted({nid for row in rows for nid in row["node_ids"]}),
        states=sorted({state for row in rows for state in row["states"]}),
    )


def _attribute_path(path, schedule, provenance, aliases=()):
    """Attribute ordered boundaries and endpoint writers; preserve the raw path."""
    nodes = schedule["nodes"]
    text = " ".join(
        str(path.get(field) or "") for field in ("start_reg_name", "end_reg_name")
    )
    text += " " + " ".join(
        [*path.get("start_reg_aliases", ()), *path.get("end_reg_aliases", ())]
    )
    resources = [
        element.get("resource", "") for element in path.get("path_elements") or []
    ]
    resources += path.get("netlist_resources") or []
    text += " " + " ".join(resources)
    owned = any(
        alias.lower() in text.lower()
        for alias in (schedule["entity"], *aliases)
        if alias
    )
    result = dict(
        path=copy.deepcopy(path),
        attributed=False,
        states=[],
        node_ids=[],
        fus=[],
        boundaries=[],
    )
    if not owned:
        result["reason"] = "no matching FSM hierarchy or generated source"
        return result
    registers = provenance.get("registers", {})
    end = _timing_register(
        " ".join([path.get("end_reg_name") or "", *path.get("end_reg_aliases", ())]),
        registers,
    )
    start = _timing_register(
        " ".join(
            [path.get("start_reg_name") or "", *path.get("start_reg_aliases", ())]
        ),
        registers,
    )
    result["start_role"] = start["role"] if start else None
    result["end_role"] = end["role"] if end else None
    writers = set(end.get("node_ids", ())) if end else set()
    states = set(end.get("states", ())) if end else set()
    lines = {row["line"]: row for row in provenance.get("lines", ())}
    for element in path.get("path_elements") or []:
        # Source coordinates refer to this FSM only when its source/hierarchy
        # precedes the coordinate. A nested helper's line 20 is not FSM line 20,
        # and the FSM instance's own label carries its call site in the caller.
        # Net names may come from a neighbouring module; cells place the arc.
        if (element.get("delay_type") or "").startswith("net"):
            continue
        resource = element.get("resource", "")
        lowered = resource.lower()
        ends = [
            lowered.rfind(alias.lower()) + len(alias)
            for alias in (schedule["entity"], *aliases)
            if alias and alias.lower() in lowered
        ]
        if not ends:
            continue
        matches = list(
            re.finditer(
                r"(?:_py_l|\.py[:_]l?)(\d+)(?:_|:|$)",
                resource[max(ends) :],
                re.IGNORECASE,
            )
        )
        if not matches:
            continue
        row = lines.get(int(matches[0].group(1)))
        if row is None:
            continue
        result["boundaries"].append(
            dict(
                kind=row["kind"],
                fu=row.get("fu"),
                node_ids=row["node_ids"],
                arrival_ns=element.get("arrival_ns"),
                increment_ns=element.get("increment_ns"),
                resource=resource,
            )
        )
        writers.update(row["node_ids"])
        states.update(row["states"])
    # A work register may have several writers. Keep every possible same-state
    # predecessor chain, rather than guessing which unreported mux input won.
    chain = set()

    def visit(nid, state):
        if nid in chain or nid not in nodes:
            return
        node = nodes[nid]
        if node.get("state") not in (None, state):
            return
        chain.add(nid)
        for ref in node["operands"]:
            if ref[0] == "node":
                visit(ref[1], state)

    for nid in sorted(writers):
        if nid in nodes:
            visit(nid, nodes[nid].get("state"))
    result.update(
        attributed=bool(end or result["boundaries"]),
        states=sorted(states),
        node_ids=sorted(chain),
        fus=sorted({nodes[nid]["fu"] for nid in chain if nodes[nid].get("fu")}),
    )
    if not result["attributed"]:
        result["reason"] = "FSM matched but no register or operation boundary matched"
    return result


def _fsm_instance_aliases(parser_state, key):
    """VHDL names of the instances that call this FSM. Netlist names carry the
    elaborated hierarchy, not the schedule's entity name."""
    import VHDL

    aliases = []
    for logic in parser_state.LogicInstLookupTable.values():
        aliases.extend(
            VHDL.WIRE_TO_VHDL_NAME(local, parser_state)
            for local, tagged_key in logic.sub_inst_to_auto_fsm_key.items()
            if tagged_key == key
        )
    return aliases


def _fsm_source_line(name, aliases):
    """The FSM source line a netlist name points into, once inside the FSM.

    Returns (owned, line). The first source coordinate after the FSM's own
    instance is a line of the generated FSM; the instance label itself carries
    its caller's line. A register of the FSM proper (st_r, v<n>_r) has none.
    """
    lowered = (name or "").lower()
    ends = [
        lowered.rfind(alias.lower()) + len(alias)
        for alias in aliases
        if alias and alias.lower() in lowered
    ]
    if not ends:
        return False, None
    match = re.search(
        r"(?:_py_l|\.py[:_]l?)(\d+)(?:_|:|$)", name[max(ends) :], re.IGNORECASE
    )
    return True, int(match.group(1)) if match else None


def _unit_measurements(observation, schedule, provenance, aliases):
    """Measured unit stages replace their placement's estimates.

    A path ending inside a unit measures it when it starts inside the same
    unit (an isolated stage) or at a register of the FSM proper (its launch:
    operand selection and first stage). A path from another unit's output also
    holds that unit's stage and the chained logic, so it is not either one.
    """
    unit_lines = {
        row["line"]: row["fu"]
        for row in provenance.get("lines", ())
        if row["kind"] == "unit" and row.get("fu")
    }
    aliases = [schedule["entity"], *aliases]
    result = copy.deepcopy(schedule.get("unit_measurements", {}))
    for path in (observation or {}).get("paths", ()):
        end = path.get("end_reg_name") or ""
        end_owned, end_line = _fsm_source_line(end, aliases)
        start_owned, start_line = _fsm_source_line(path.get("start_reg_name"), aliases)
        fu = unit_lines.get(end_line)
        if not (end_owned and start_owned) or fu is None:
            continue
        if start_line != end_line and start_line in unit_lines:
            continue
        implementation = schedule.get("implementations", {}).get(schedule["fus"][fu])
        delay = path.get("path_delay_ns")
        if implementation is None or not delay:
            continue
        digest = implementation["placement_digest"]
        measurement = result.setdefault(
            digest, dict(evidence="measured unit stages", paths=[])
        )
        stage_delay = math.ceil(float(delay) * 10.0)
        measurement["worst_stage_du"] = max(
            measurement.get("worst_stage_du", implementation["worst_stage_du"]),
            stage_delay,
        )
        stage = re.search(r"REG_STAGE(\d+)_", end, re.IGNORECASE)
        measurement["paths"].append(
            dict(
                stage=int(stage.group(1)) if stage else None,
                launch=start_line != end_line,
                delay_du=stage_delay,
                path=copy.deepcopy(path),
            )
        )
    return result


def SCHEDULED_FSM_DELAY_DU(key):
    """The worst state of a call site's installed schedule, in delay units:
    the modelled worst state, or a measured stage of one of its pinned units
    when that is longer. None without an installed schedule.

    SYN uses it as the generated FSM's delay instead of synthesizing the whole
    module: that run reports an input-to-output figure, not a state's
    register-to-register delay, and the sweep cannot pipeline an FSM."""
    import pypeline

    schedule = pypeline.AUTO_FSM_SCHEDULE_CACHE().get(key)
    if schedule is None:
        return None
    stages = [
        _with_measurements(implementation, schedule.get("unit_measurements"))[
            "worst_stage_du"
        ]
        for implementation in schedule.get("implementations", {}).values()
    ]
    return max([schedule["worst_state_du"]] + stages)


def _with_measurements(profile, measurements):
    """A built placement's measured stages replace its estimate."""
    measured = (measurements or {}).get(profile["placement_digest"])
    return dict(profile, **measured) if measured else profile


def _placement_node(schedule, entity):
    """The scheduled node a pinned unit of `entity` was bound for."""
    return next(
        node
        for _nid, node in sorted(schedule["nodes"].items())
        if node.get("fu") and node["entity"] == entity
    )


def _prepare_placement_measurement(parser_state, key, schedule, entity, implementation):
    """Write one pinned placement's isolated hierarchy for synthesis on its
    own. Returns (root, isolated parse, timing params)."""
    import AUTO_PIPELINE
    import VHDL

    node = _placement_node(schedule, entity)
    unit = _unit_function(parser_state, key, node, implementation.get("selection_rows"))
    if unit is None or unit["entity"] != implementation["unit_entity"]:
        raise AutoFsmInternalError(
            "AUTO_FSM: selected functional unit is unavailable: " + entity
        )
    delays = dict(
        schedule["entity_delays_snapshot"],
        **schedule.get("corrected_entity_delays", {}),
    )
    isolated, root = _unit_isolated_tree(parser_state, unit["entity"], delays)
    table = {
        inst: AUTO_PIPELINE.TimingParams(inst, logic)
        for inst, logic in isolated.LogicInstLookupTable.items()
    }
    RESTORE_UNIT_PLACEMENT(root, implementation, isolated, table)
    for inst, logic in sorted(isolated.LogicInstLookupTable.items()):
        if (
            logic.is_vhdl_func
            or logic.is_vhdl_expr
            or logic.func_name == LOGIC.VHDL_FUNC_NAME
            or logic.is_clock_crossing
            or logic.is_fsm_clk_func
        ):
            continue
        out_dir = SYN.GET_OUTPUT_DIRECTORY(logic)
        os.makedirs(out_dir, exist_ok=True)
        VHDL.WRITE_LOGIC_ENTITY(inst, logic, out_dir, isolated, table)
    return root, isolated, table


def _measured_placement(implementation, report):
    """A placement's measured worst stage and that path's endpoints, or None
    when the report has no path."""
    paths = [
        path for path in report.path_reports.values() if path.path_delay_ns is not None
    ]
    if not paths:
        return None
    worst = max(paths, key=lambda path: path.path_delay_ns)

    def depth_free(name):
        # The isolated root is named per depth (<unit>_5CLK_<hash>/...); the
        # path below it is what two depths share.
        return re.sub(r"^[^/]*_\d+CLK_[0-9a-f]+/", "", name or "")

    return dict(
        evidence="measured on its own",
        worst_stage_du=max(
            implementation["worst_stage_du"],
            math.ceil(worst.path_delay_ns * SYN.DELAY_UNIT_MULT),
        ),
        worst_path=[
            depth_free(worst.start_reg_name),
            depth_free(worst.end_reg_name),
            round(worst.path_delay_ns, 3),
        ],
        paths=[],
    )


@SYN.PHASED("AUTO_FSM pinned-unit measurement")
def _synthesize_placements(parser_state, jobs):
    """Measure pinned placements on their own: [(key, schedule, entity,
    implementation)] -> [measurement or None]. Hierarchies are written one
    at a time; the syntheses run in parallel (SYN.GET_NUM_PROCESSES)."""
    from multiprocessing.pool import ThreadPool

    import VHDL

    if not jobs:
        return []
    # The units first: a schedule a forked search built or an earlier build
    # stored never materialized them in this parser state, and a selected
    # unit's row array is a type of its own.
    for key, schedule, entity, implementation in jobs:
        _unit_function(
            parser_state,
            key,
            _placement_node(schedule, entity),
            implementation.get("selection_rows"),
        )
    # Grow-only: the units' own types join the chunk index, and isolated runs
    # read a package scoped to what they use.
    VHDL.WRITE_C_DEFINED_VHDL_STRUCTS_PACKAGE(parser_state)
    prepared = []
    for key, schedule, entity, implementation in jobs:
        print(
            f"AUTO_FSM {key}: measuring pinned unit {entity} "
            f"L={implementation['latency']} on its own",
            flush=True,
        )
        prepared.append(
            _prepare_placement_measurement(
                parser_state, key, schedule, entity, implementation
            )
        )
    pool = ThreadPool(processes=min(SYN.GET_NUM_PROCESSES(), len(prepared)))
    try:
        reports = pool.map(
            lambda job: SYN.SYN_TOOL.SYN_AND_REPORT_TIMING(
                job[0], job[1].LogicInstLookupTable[job[0]], job[1], job[2]
            ),
            prepared,
        )
    finally:
        pool.close()
        pool.join()
    return [
        _measured_placement(implementation, report)
        for (_key, _schedule, _entity, implementation), report in zip(jobs, reports)
    ]


def _measure_unit_placements(parser_state, schedules):
    """Synthesize each chosen pinned placement once, on its own.

    The landscape predicts stages from the cut positions it plans, and a
    hierarchy measured as a whole can realize its registers elsewhere (§3.2,
    "Measured stages"). One synthesis of the pinned unit, its operand
    selection included, measures its worst register-to-register stage before
    a whole-design build relies on it. Results land in each schedule's
    unit_measurements (diagnostic data, not hardware). Returns
    {key: {entity: implementation}} for chosen placements over their budget.
    """
    jobs = []
    for key, schedule in sorted(schedules.items()):
        measurements = schedule.setdefault("unit_measurements", {})
        for entity, implementation in sorted(
            schedule.get("implementations", {}).items()
        ):
            if implementation["placement_digest"] not in measurements:
                jobs.append((key, schedule, entity, implementation))
    for (key, schedule, _entity, implementation), measured in zip(
        jobs, _synthesize_placements(parser_state, jobs)
    ):
        if measured is not None:
            schedule["unit_measurements"][implementation["placement_digest"]] = measured
    over = {}
    for key, schedule in sorted(schedules.items()):
        measurements = schedule["unit_measurements"]
        for entity, implementation in sorted(
            schedule.get("implementations", {}).items()
        ):
            measured = measurements.get(implementation["placement_digest"])
            if measured and measured["worst_stage_du"] > schedule["budget_du"]:
                over.setdefault(key, {})[entity] = implementation
    return over


def _measure_deeper_placements(parser_state, schedules, over):
    """Before one reschedule, measure every deeper depth of a recipe whose
    chosen depth missed: each would otherwise take a round of measurement
    and a full area search of its own. The depths are the ones
    _unit_profiles predicts can still improve, below the latency cap."""
    jobs = []
    for key in sorted(over):
        schedule = schedules[key]
        measurements = schedule["unit_measurements"]
        max_states = (
            schedule["max_latency"] - int(schedule.get("register_output", True))
            if schedule.get("max_latency") is not None
            else None
        )
        for entity, implementation in sorted(over[key].items()):
            profiles = _unit_profiles(
                parser_state,
                key,
                _placement_node(schedule, entity),
                schedule["entity_delays_snapshot"],
                implementation.get("selection_rows"),
            )
            jobs.extend(
                (key, schedule, entity, profile)
                for profile in profiles
                if profile["latency"] > implementation["latency"]
                and (max_states is None or profile["latency"] < max_states)
                and profile["placement_digest"] not in measurements
            )
    for (key, schedule, _entity, profile), measured in zip(
        jobs, _synthesize_placements(parser_state, jobs)
    ):
        if measured is not None:
            schedule["unit_measurements"][profile["placement_digest"]] = measured
    for key in sorted(over):
        schedule = schedules[key]
        for entity, implementation in sorted(over[key].items()):
            print(_describe_depth_curve(parser_state, key, schedule, entity, implementation), flush=True)


def _describe_depth_curve(parser_state, key, schedule, entity, implementation):
    """One line per recipe: each measured depth's worst stage, and whether a
    deeper depth moved the worst path at all."""
    measurements = schedule["unit_measurements"]
    profiles = _unit_profiles(
        parser_state,
        key,
        _placement_node(schedule, entity),
        schedule["entity_delays_snapshot"],
        implementation.get("selection_rows"),
    )
    curve = [
        (profile["latency"], measurements[profile["placement_digest"]])
        for profile in profiles
        if profile["placement_digest"] in measurements
    ]
    parts = []
    previous = None
    for latency, measured in curve:
        path = measured.get("worst_path")
        same = previous is not None and path is not None and path == previous
        parts.append(
            f"L={latency} {measured['worst_stage_du'] / 10.0:.2f} ns"
            + (" (same path)" if same else "")
        )
        previous = path
    paths = {tuple(measured["worst_path"]) for _l, measured in curve if measured.get("worst_path")}
    verdict = (
        "; every depth kept the same worst path, so no depth of this recipe can fix it"
        if len(curve) > 1 and len(paths) == 1
        else ""
    )
    return (
        f"AUTO_FSM {key}: pinned unit {entity} measured on its own at "
        + ", ".join(parts)
        + f" against the {schedule['budget_du'] / 10.0:.2f} ns/state budget"
        + verdict
    )


def _confirm_unit_placements(parser_state, schedules, harvest):
    """Reschedule call sites until every chosen pinned placement is measured
    within its budget, or measuring finds no new miss.

    A measured placement is never chosen again, so each round either measures
    something new or ends; a miss that rescheduling cannot avoid is left to
    the whole-design build and its timing loop. A recipe whose chosen depth
    misses has its deeper depths measured too, before the one reschedule
    (_measure_deeper_placements).
    """
    known = set()
    while True:
        over = _measure_unit_placements(parser_state, schedules)
        new = {
            implementation["placement_digest"]
            for chosen in over.values()
            for implementation in chosen.values()
        } - known
        if not new:
            return schedules
        known |= new
        _measure_deeper_placements(parser_state, schedules, over)
        for key in sorted(over):
            budget_ns = schedules[key]["budget_du"] / 10.0
            print(
                f"AUTO_FSM {key}: a pinned unit placement measured over the "
                f"{budget_ns:.2f} ns/state budget on its own; rescheduling "
                f"before the whole-design build.",
                flush=True,
            )
        schedules = dict(schedules)
        schedules.update(harvest(parser_state, schedules, set(over)))


def _mapped_endpoint_aliases(observation):
    """Recover readable sky130 endpoints from the retained, authenticated netlist."""
    log_path = (observation or {}).get("log_path")
    if not log_path:
        return {}, "no retained netlist path"
    try:
        with open(os.path.splitext(log_path)[0] + "_timing.json") as source:
            timing = json.load(source)
        mapped = os.path.join(os.path.dirname(log_path), timing["mapped_json_path"])
        with open(mapped, "rb") as source:
            contents = source.read()
        if hashlib.sha256(contents).hexdigest() != timing["mapped_json_sha256"]:
            return {}, "retained mapped-netlist digest differs"
        result = {}
        for module in json.loads(contents)["modules"].values():
            aliases_of_bit = {}
            for name, net in module["netnames"].items():
                for bit in net["bits"]:
                    aliases_of_bit.setdefault(bit, set()).add(name)
            for name, cell in module["cells"].items():
                bits = cell["connections"].get("Q", []) + cell["connections"].get(
                    "QN", []
                )
                if bits:
                    result[name] = sorted(
                        {alias for bit in bits for alias in aliases_of_bit.get(bit, ())}
                    )
        return result, "retained mapped-netlist digest verified"
    except (OSError, KeyError, TypeError, ValueError):
        return {}, "retained mapped-netlist aliases unavailable"


def _collect_timing_evidence(parser_state, params, schedules):
    """Read the retained implementation, never an abandoned sweep candidate."""

    import SWEEP

    observation = SWEEP.RETAINED_OBSERVATION(parser_state, params)
    endpoint_aliases, alias_status = _mapped_endpoint_aliases(observation)
    result = {key: [] for key in schedules}
    failures = getattr(params, "sweep_timing_failures", ()) or ()
    for key, schedule in schedules.items():
        aliases = _fsm_instance_aliases(parser_state, key)
        provenance = parser_state.pypeline_auto_fsm_provenance.get(key, {})
        relevant = [
            (main, goal)
            for main, goal, _mhz, _why in failures
            if key in _AUTO_FSM_KEYS_UNDER_MAIN(parser_state, main)
        ]
        for path in (observation or {}).get("paths", ()):
            delay = path.get("path_delay_ns")
            if not delay or not any(
                goal and delay > 1000.0 / goal for _main, goal in relevant
            ):
                continue
            path = dict(
                path,
                start_reg_aliases=endpoint_aliases.get(path.get("start_reg_name"), []),
                end_reg_aliases=endpoint_aliases.get(path.get("end_reg_name"), []),
                endpoint_alias_status=alias_status,
            )
            row = _attribute_path(path, schedule, provenance, aliases)
            row["observation"] = {
                field: observation.get(field)
                for field in (
                    "input_signature",
                    "implementation_signature",
                    "log_path",
                    "iteration",
                )
            }
            result[key].append(row)
        if relevant and not result[key]:
            result[key].append(
                dict(
                    attributed=False,
                    reason="backend supplied no failing path for the retained implementation",
                    path={},
                )
            )
    return result


def _corrected_timing_model(schedule, evidence):
    """Apply observed/modelled ratios locally, including equivalent chains."""
    model = copy.deepcopy(schedule)
    delays = model.setdefault("corrected_entity_delays", {})
    selects = model.setdefault("select_arrivals", {})
    for row in evidence:
        if not row["attributed"]:
            continue
        ids = row["node_ids"]
        measured = (row["path"].get("path_delay_ns") or 0) * 10.0
        predicted = max(
            (schedule["nodes"][nid].get("end_du") or 0 for nid in ids), default=0
        )
        if row.get("start_role") == "control":
            # The first arithmetic/mux boundary isolates the select arrival.
            arrivals = [
                arc["arrival_ns"]
                for arc in row["boundaries"]
                if arc["kind"] in ("operand_mux", "unit")
                and arc["arrival_ns"] is not None
            ]
            if arrivals:
                for fu in row["fus"]:
                    entity = schedule["fus"][fu]
                    selects[entity] = max(
                        selects.get(entity, 0), math.ceil(min(arrivals) * 10.0)
                    )
        if predicted and measured > predicted:
            ratio = measured / predicted
            for nid in ids:
                node = schedule["nodes"][nid]
                if node.get("fu") and node["delay_du"]:
                    entity = node["entity"]
                    delays[entity] = max(
                        delays.get(entity, 0), math.ceil(node["delay_du"] * ratio)
                    )
    model["timing_evidence"] = list(
        {
            AUTO.frozen(row): row
            for row in list(schedule.get("timing_evidence", ())) + evidence
        }.values()
    )
    return model


def _separation_entity_pairs(schedule, evidence):
    """Cut the operation boundary where an ordered path first crosses budget.

    Every same-state edge follows the units' emission order. Synthesis names
    some merged cells after a neighbouring unit, so a transition against that
    order is a naming artifact, not a producer-to-consumer boundary.
    """
    order = {fu: index for index, fu in enumerate(schedule["fu_order"])}
    pairs = set()
    for row in evidence:
        previous_fu = None
        previous_pair = None
        for boundary in row.get("boundaries", ()):
            fu = boundary.get("fu")
            if boundary["kind"] != "unit" or fu is None:
                continue
            if previous_fu is not None and previous_fu != fu:
                if order.get(previous_fu, -1) >= order.get(fu, -1):
                    continue
                previous_pair = (schedule["fus"][previous_fu], schedule["fus"][fu])
            previous_fu = fu
            if (
                boundary.get("arrival_ns") is not None
                and boundary["arrival_ns"] * 10.0 > schedule["budget_du"]
            ):
                if previous_pair is not None:
                    pairs.add(previous_pair)
                break
    return pairs


def _timing_repair_candidates(parser_state, key, tag, schedule, evidence, build_memo):
    """Full reschedules of corrected timing, selection, edges, depth and copies."""

    attributed = [row for row in evidence if row["attributed"]]
    if not attributed:
        return []
    model = _corrected_timing_model(schedule, evidence)
    affected = sorted({schedule["fus"][fu] for row in attributed for fu in row["fus"]})
    common = dict(
        ctl=schedule["ctl"],
        opened=tuple(schedule.get("opened", ())),
        unshared=tuple(tuple(row) for row in schedule.get("unshared", ())),
        pipelined=tuple(
            (row[0], tuple(row[1]) if isinstance(row[1], list) else row[1])
            for row in schedule.get("pipelined", ())
        ),
        merged=tuple(tuple(row) for row in schedule.get("merged", ())),
        fused=tuple(schedule.get("fused", ())),
        func_entity_override=schedule["func_entity"],
        build_memo=build_memo,
    )
    variants = [("corrected attributed delays", model, common)]
    candidates = {
        node["entity"]: node for node in _unit_candidate_nodes(parser_state, schedule)
    }
    for entity in affected:
        node = candidates.get(entity)
        if node is None:
            continue
        uses = sum(
            n.get("fu") is not None and n["entity"] == entity
            for n in schedule["nodes"].values()
        )
        selected = schedule.get("implementations", {}).get(entity, {})
        for rows in (None, uses) if uses > 1 else (None,):
            delays = dict(
                model["entity_delays_snapshot"],
                **model.get("corrected_entity_delays", {}),
            )
            after = (
                selected.get("latency", 0)
                if selected.get("selection_rows") == rows
                else 0
            )
            profiles = _unit_profiles(
                parser_state,
                key,
                node,
                delays,
                rows,
                until=lambda found: any(row["latency"] > after for row in found),
            )
            next_profile = next(
                (profile for profile in profiles if profile["latency"] > after), None
            )
            if next_profile is not None:
                chosen = dict(common["pipelined"])
                chosen[entity] = (
                    (next_profile["latency"], rows)
                    if rows is not None
                    else next_profile["latency"]
                )
                variants.append(
                    (
                        f"pipeline {entity} L={next_profile['latency']} selection_rows={rows}",
                        model,
                        dict(common, pipelined=tuple(sorted(chosen.items()))),
                    )
                )
        copies = dict(common["unshared"])
        current = sum(bound == entity for bound in schedule["fus"].values())
        if current < uses:
            copies[entity] = current + 1
            variants.append(
                (
                    f"duplicate {entity}",
                    model,
                    dict(common, unshared=tuple(sorted(copies.items()))),
                )
            )
    edge_model = copy.deepcopy(model)
    pairs = {tuple(pair) for pair in model.get("no_chain_entity_pairs", ())}
    observed_pairs = _separation_entity_pairs(schedule, attributed)
    edge_model["no_chain_entity_pairs"] = sorted(pairs | observed_pairs)
    if observed_pairs - pairs:
        variants.append(
            ("separate the measured over-budget operation boundary", edge_model, common)
        )
    result = []
    for reason, previous, options in variants:
        try:
            trial = BUILD_SCHEDULE(
                parser_state, key, tag, schedule["budget_scale"], previous, **options
            )
        except AutoFsmInternalError:
            raise
        except AUTO.AutoError:
            continue
        if SCHEDULES_EQUAL({key: schedule}, {key: trial}):
            continue
        period = _period_du(parser_state)
        clock_budget = min(trial["budget_du"], period) if period else trial["budget_du"]
        feasible = (
            not trial["latency_infeasible"] and trial["worst_state_du"] <= clock_budget
        )
        trial["est_area"] = ESTIMATE_SCHEDULE_AREA(parser_state, trial)
        trial["repair_history"] = list(schedule.get("repair_history", ())) + [reason]
        trial["timing_evidence"] = model["timing_evidence"]
        result.append((not feasible, trial["est_area"], reason, trial))
    return sorted(result, key=lambda row: row[:3])


def CHECK_SCHEDULES_APPLIED(parser_state):
    """Every call site of a build's re-parse uses the schedule installed for it.

    A refused or missing schedule elaborates the combinational passthrough,
    which is a cache miss elsewhere. Inside a build every installed schedule
    comes from the build's own passes, and REPARSE schedules the call sites
    new to the build before checking, so the passthrough would be synthesized
    in place of the chosen FSM: an internal error naming why.
    """
    import pypeline

    installed = pypeline.AUTO_FSM_SCHEDULE_CACHE()
    if not installed:
        return
    problems = dict(parser_state.pypeline_auto_fsm_schedule_rejections)
    for key, tag in sorted(GET_TAGS(parser_state).items()):
        if key in problems:
            continue
        if key not in installed:
            problems[key] = "no schedule was installed for this call site"
        elif tag.schedule is None:
            problems[key] = (
                "the call site refused it (version, max_latency or register_output)"
            )
    if problems:
        raise AutoFsmInternalError(
            "AUTO_FSM: re-elaboration did not apply a schedule this build produced: "
            + "; ".join(f"{key}: {why}" for key, why in sorted(problems.items()))
        )


@SYN.PHASED("re-elaboration")
def REPARSE(src_file, part, tool=None, schedule_call_sites=None):
    """Re-execute the design inside a pipelined build: DO_SCHEDULE_PASSES' own
    re-parse, AUTO_PIPELINE's pin-and-confirm passes and its RAM plan re-parses.

    part and tool, when given, are the driver's resolved target and carry over
    to the new parser_state. A call site with no installed schedule is new to
    the build: its function changed with a value the design read during
    elaboration, such as an AUTO_PIPELINE .latency sizing it (WireGuard's
    Poly1305 kernels have capacity = body depth + 2). With DO_SCHEDULE_PASSES'
    schedule_call_sites, (parser_state, keys) -> (parser_state, schedules),
    those call sites (passthroughs in this parse) are measured and scheduled,
    installed beside the others, and the design is executed again. Each round
    installs every new key, and a construction depends only on values read
    before it (AUTO_PIPELINE latencies are fixed for the re-parse, an earlier
    AUTO_FSM's latency once its schedule is installed), so each round settles
    the next construction and the rounds end. A refused schedule is still an
    internal error (CHECK_SCHEDULES_APPLIED). Returns the parser_state.
    """
    import pypeline
    import PY_TO_LOGIC

    while True:
        parser_state = PY_TO_LOGIC.PARSE_FILE(src_file, resolved_part=part)
        if part is not None:
            parser_state.part = part
        if tool is not None:
            parser_state.syn_tool_name = tool
        if schedule_call_sites is None:
            break
        installed = pypeline.AUTO_FSM_SCHEDULE_CACHE()
        new = sorted(key for key in GET_TAGS(parser_state) if key not in installed)
        if not new:
            break
        print(
            "AUTO_FSM: re-elaboration created call site(s) with no schedule yet "
            "(their functions changed with a value read during elaboration, such "
            "as an AUTO_PIPELINE .latency); scheduling: " + ", ".join(new),
            flush=True,
        )
        parser_state, schedules = schedule_call_sites(parser_state, new)
        unscheduled = sorted(set(new) - set(schedules))
        if unscheduled:
            raise AutoFsmInternalError(
                "AUTO_FSM: scheduling produced no schedule for new call site(s): "
                + ", ".join(unscheduled)
            )
        pypeline.SET_AUTO_FSM_SCHEDULE_CACHE(dict(installed, **schedules))
    CHECK_SCHEDULES_APPLIED(parser_state)
    return parser_state


def DO_SCHEDULE_PASSES(parser_state, args, src_file):
    """AUTO_FSM schedule-and-confirm loop, wrapping the sweep + AUTO_PIPELINE flow.

    An AUTO_FSM call site elaborates to a combinational passthrough until a
    schedule exists for it, so the bootstrap parse handed in deliberately built a
    design with the raw combinational blob inline. That design is only useful
    for MEASURING -- ADD_PATH_DELAY_TO_LOOKUP populates the per-operation delays
    the scheduler needs -- so the sweep is skipped for it entirely (it would
    just fail timing on a blob nobody intends to build).

    Each pass then: schedule -> install -> re-execute the design (so call sites
    now elaborate to the real FSM, and any .latency-derived Python sizing sees
    real values) -> full sweep + AUTO_PIPELINE convergence. If timing fails and
    an AUTO_FSM is to blame, shrink its per-state budget so the next schedule
    uses more, smaller states, and go again -- the direct analogue of the sweep
    adding pipeline stages, and the reason an AUTO_FSM can be tuned by iteration
    rather than by hand.

    A re-elaboration inside a pass (the pass's own, AUTO_PIPELINE's
    pin-and-confirm passes, or the RAM plan search) can create call sites no
    pass scheduled: a function sized from an AUTO_PIPELINE .latency changes
    with it. REPARSE schedules them with schedule_new_call_sites, and after the
    sweep the loop follows the call sites the design now builds.

    The loop stops when timing is met, when no AUTO_FSM is blamed, when every
    blamed FSM is at its floor, when a tightened build did not raise any
    failing MAIN's fmax (TIGHTEN_MIN_FMAX_GAIN -- the critical path is not in
    the FSM's states), when shrinking the budget no longer changes the
    hardware, or at MAX_SCHEDULE_PASSES.
    """
    import AUTO_PIPELINE

    import sys

    import SWEEP
    import SYN
    import pypeline

    budget_scales = {}
    force_unshare = list(args.auto_fsm_unshare)
    force_open = list(args.auto_fsm_open)
    prev_schedules = None
    # Set only once a pass has been rebuilt after a tightening or a local
    # repair: what the build before it achieved and which step rebuilt it, so
    # the stall check below compares like with like.
    tightened_from = None
    pending_schedules = None
    attempted_repairs = set()
    # Call sites the next pass reschedules: the FSMs a tightening blamed. The
    # others keep their schedules; None (the first pass) schedules every one.
    reschedule_keys = None

    def harvest(state, previous, keys):
        return HARVEST_AUTO_FSM_SCHEDULES(
            state,
            budget_scales,
            previous,
            area_sweep=not args.auto_fsm_no_area_sweep,
            ctl=args.auto_fsm_ctl,
            sweep_debug=args.auto_fsm_sweep_debug,
            force_open=force_open,
            force_unshare=force_unshare,
            keys=keys,
        )

    def measure_and_harvest(state, previous, keys=None):
        """Measure what scheduling decisions rest on, then schedule every call
        site, or only those in keys."""
        if args.auto_fsm_budget_scale is not None:
            # Every call site the build schedules starts from the requested
            # scale, including one created by a re-elaboration during a pass
            for key in GET_TAGS(state) if keys is None else keys:
                budget_scales.setdefault(key, args.auto_fsm_budget_scale)
        state = _measure_schedule_inputs(state, budget_scales, previous, keys)
        state, control_snapshots = _calibrate_controls(
            state, budget_scales, args.auto_fsm_ctl, previous, keys
        )
        previous = {
            key: dict(
                (previous or {}).get(key, {}),
                control_delays_snapshot=snapshot,
            )
            for key, snapshot in control_snapshots.items()
        }
        return state, harvest(state, previous, keys)

    def confirm_and_report(state, schedules):
        schedules = _confirm_unit_placements(state, schedules, harvest)
        for key in sorted(schedules):
            print(DESCRIBE_SCHEDULE(state, key, schedules[key]), flush=True)
            for fu_line in DESCRIBE_FUS(schedules[key]):
                print(fu_line, flush=True)
        # A max_latency= cap is a hard constraint, so failing to meet it fails
        # the build. Silently returning a slower FSM would defeat the point of
        # asking for the cap in the first place.
        infeasible = [
            k for k in sorted(schedules) if schedules[k]["latency_infeasible"]
        ]
        if infeasible:
            for key in infeasible:
                print(LATENCY_INFEASIBLE_MESSAGE(key, schedules[key]), flush=True)
            sys.exit(-1)
        return schedules

    def schedule_new_call_sites(state, keys):
        """REPARSE's scheduler. The parse holds these call sites'
        passthroughs, so their operations are measured as on the bootstrap
        pass."""
        AUTO_PIPELINE.WRITE_0_ADDED_CLKS_INIT_FILES(state)
        state = SYN.ADD_PATH_DELAY_TO_LOOKUP(state)
        state, schedules = measure_and_harvest(state, None, keys)
        return state, confirm_and_report(state, schedules)

    for schedule_pass in range(1, MAX_SCHEDULE_PASSES + 1):
        print(
            f"================== AUTO_FSM Pass {schedule_pass}: Scheduling "
            f"Shared-Resource FSMs ================================",
            flush=True,
        )
        parser_state = SYN.ADD_PATH_DELAY_TO_LOOKUP(parser_state)
        if pending_schedules is not None:
            schedules, pending_schedules = pending_schedules, None
        else:
            parser_state, harvested = measure_and_harvest(
                parser_state, prev_schedules, reschedule_keys
            )
            schedules = dict(prev_schedules) if reschedule_keys is not None else {}
            schedules.update(harvested)
        schedules = confirm_and_report(parser_state, schedules)
        prev_schedules = schedules

        pypeline.SET_AUTO_FSM_SCHEDULE_CACHE(schedules)
        parser_state = REPARSE(
            src_file, parser_state.part, schedule_call_sites=schedule_new_call_sites
        )
        AUTO_PIPELINE.WRITE_0_ADDED_CLKS_INIT_FILES(parser_state)
        DUMP_GENERATED_SOURCE(parser_state, SYN.SYN_OUTPUT_DIRECTORY)
        parser_state, multimain_timing_params = AUTO_PIPELINE.DO_SWEEP_AND_AUTO_PIPELINE(
            parser_state, args, src_file, schedule_call_sites=schedule_new_call_sites
        )
        current = set(GET_TAGS(parser_state))
        if current != set(schedules):
            # Blame, repair and tightening follow the call sites built. The
            # stall rule judges a tightening of the same FSMs, not this pass.
            print(
                "AUTO_FSM: re-elaboration changed the design's call sites; now "
                "building: " + ", ".join(sorted(current)),
                flush=True,
            )
            installed = pypeline.AUTO_FSM_SCHEDULE_CACHE()
            schedules = {key: installed[key] for key in sorted(current)}
            prev_schedules = schedules
            tightened_from = None

        observation = SWEEP.RETAINED_OBSERVATION(parser_state, multimain_timing_params)
        for key, schedule in schedules.items():
            schedule["unit_measurements"] = _unit_measurements(
                observation,
                schedule,
                parser_state.pypeline_auto_fsm_provenance.get(key, {}),
                _fsm_instance_aliases(parser_state, key),
            )
        DUMP_GENERATED_SOURCE(
            parser_state, SYN.SYN_OUTPUT_DIRECTORY, schedules=schedules
        )

        failures = getattr(multimain_timing_params, "sweep_timing_failures", None)
        if not failures:
            break
        blamed = BLAMED_AUTO_FSM_KEYS(parser_state, multimain_timing_params, schedules)
        if not blamed:
            print(
                "AUTO_FSM: timing was missed but no AUTO_FSM region is implicated; "
                "adding states cannot help.",
                flush=True,
            )
            break
        failed_mhz = FAILED_MAIN_MHZ(multimain_timing_params)
        repair_stalled = False
        if tightened_from is not None:
            prev_failed_mhz, prev_states, step = tightened_from
            stalled = TIGHTENING_STALLED(prev_failed_mhz, failed_mhz)
            if stalled and step == "repair":
                # One failed local repair never shows that more states cannot
                # help: the corrected model was wrong, not the budget. Fall
                # back to global tightening; the stall rule judges that step.
                mains = ", ".join(
                    f"{main} {mhz:.2f} MHz (was {prev:.2f})"
                    for main, prev, mhz in stalled
                )
                print(
                    f"AUTO_FSM: the local timing repair did not raise fmax: "
                    f"{mains}; tightening the per-state budget instead.",
                    flush=True,
                )
                repair_stalled = True
            elif stalled:
                states = ", ".join(
                    f"{key} {prev_states[key]}->{schedules[key]['n_states']} states"
                    for key in sorted(prev_states)
                )
                mains = ", ".join(
                    f"{main} {mhz:.2f} MHz (was {prev:.2f})"
                    for main, prev, mhz in stalled
                )
                print(
                    f"AUTO_FSM: tightening changed the schedule ({states}) but "
                    f"fmax did not improve: {mains}. The critical path does not "
                    f"run through the FSM's per-state operations (it may be in "
                    f"the FSM's control, e.g. input-capture enable fanout, or "
                    f"elsewhere in the MAIN); more states cannot help.",
                    flush=True,
                )
                break
        evidence = _collect_timing_evidence(
            parser_state, multimain_timing_params, schedules
        )
        repaired = dict(schedules)
        period_du = _period_du(parser_state)
        for key in sorted(blamed):
            rows = evidence[key]
            unmatched = sum(not row["attributed"] for row in rows)
            schedules[key]["timing_evidence"] = (
                list(schedules[key].get("timing_evidence", ())) + rows
            )
            if unmatched:
                print(
                    f"AUTO_FSM {key}: retained {unmatched} unattributed timing path(s); "
                    "global tightening remains available.",
                    flush=True,
                )
            # Local repair corrects model error. A schedule whose modelled
            # worst state already exceeds the clock period was predicted to
            # miss: its budget is the problem, and tightening addresses it.
            if repair_stalled or (
                period_du is not None and schedules[key]["worst_state_du"] > period_du
            ):
                continue
            candidates = _timing_repair_candidates(
                parser_state, key, GET_TAGS(parser_state)[key], schedules[key], rows, {}
            )
            for infeasible, _area, reason, candidate in candidates:
                identity = _schedule_entity_name(candidate["func_entity"], candidate)
                if infeasible or (key, identity) in attempted_repairs:
                    continue
                attempted_repairs.add((key, identity))
                repaired[key] = candidate
                print(f"AUTO_FSM {key}: local timing repair: {reason}", flush=True)
                break
        DUMP_GENERATED_SOURCE(
            parser_state, SYN.SYN_OUTPUT_DIRECTORY, schedules=schedules
        )
        if (
            not SCHEDULES_EQUAL(repaired, schedules)
            and schedule_pass < MAX_SCHEDULE_PASSES
        ):
            pending_schedules = repaired
            tightened_from = (
                failed_mhz,
                {key: schedules[key]["n_states"] for key in blamed},
                "repair",
            )
            continue
        if all(schedules[key]["at_floor"] for key in blamed):
            print(
                "AUTO_FSM: every implicated FSM is already at its floor -- its "
                "slowest state is a single indivisible operation, so no number "
                "of extra states can make the clock: " + ", ".join(sorted(blamed)),
                flush=True,
            )
            break
        if schedule_pass == MAX_SCHEDULE_PASSES:
            print(
                f"AUTO_FSM: still missing timing after "
                f"{MAX_SCHEDULE_PASSES} schedule passes.",
                flush=True,
            )
            break
        # Tighten until the schedule ACTUALLY changes. One step of the tighten
        # factor does not always move an operation across a state boundary, and
        # rebuilding a byte-identical design to discover that would waste a
        # whole synthesis run -- so keep shrinking the budget (a cheap pure
        # computation) until the plan differs, then go build that.
        changed = False
        miss_ratios = _BLAMED_MISS_RATIOS(parser_state, multimain_timing_params, schedules)
        latest = schedules
        for _attempt in range(MAX_TIGHTEN_STEPS):
            for key in blamed:
                budget_scales[key] = TIGHTENED_BUDGET_SCALE(
                    parser_state,
                    budget_scales.get(key, DEFAULT_BUDGET_SCALE),
                    miss_ratios.get(key),
                    latest[key]["worst_state_du"],
                )
            if args.auto_fsm_sweep_debug:
                # Without this header, a tighten-loop sweep's own "sweep
                # candidate ..." trace lines (below) are indistinguishable
                # from the pass's primary sweep -- this was previously
                # invisible outright, since sweep_debug was never passed to
                # this HARVEST_AUTO_FSM_SCHEDULES call at all (see the one
                # right below).
                print(
                    f"AUTO_FSM: tighten attempt {_attempt + 1}/{MAX_TIGHTEN_STEPS} "
                    f"for {sorted(blamed)}",
                    flush=True,
                )
            # Only the blamed FSMs' budgets moved, so only they are
            # rescheduled; the others keep this pass's schedule, in the next
            # pass too. Rescheduling an FSM whose MAIN met timing can only
            # change hardware that already passed, at the cost of a full
            # area search and its pinned-unit rounds.
            parser_state = _measure_schedule_inputs(
                parser_state, budget_scales, schedules
            )
            trial = dict(schedules)
            trial.update(
                HARVEST_AUTO_FSM_SCHEDULES(
                    parser_state,
                    budget_scales,
                    schedules,
                    area_sweep=not args.auto_fsm_no_area_sweep,
                    ctl=args.auto_fsm_ctl,
                    sweep_debug=args.auto_fsm_sweep_debug,
                    force_open=force_open,
                    force_unshare=force_unshare,
                    keys=blamed,
                )
            )
            if not SCHEDULES_EQUAL(trial, schedules):
                changed = True
                break
            latest = trial
        if not changed:
            print(
                "AUTO_FSM: shrinking the per-state budget no longer changes the "
                "schedule; adding states cannot help further.",
                flush=True,
            )
            break
        tightened_from = (
            failed_mhz,
            {key: schedules[key]["n_states"] for key in blamed},
            "tighten",
        )
        reschedule_keys = set(blamed)
        for key in sorted(blamed):
            print(
                f"AUTO_FSM {key}: timing missed; tightened per-state budget to "
                f"{budget_scales[key]:.3f} of the clock period, rescheduling "
                f"into more states...",
                flush=True,
            )
    return parser_state, multimain_timing_params


# ─────────────────────────────────────────────
# Code generation
# ─────────────────────────────────────────────


def _passthrough_name(tag) -> str:
    h = hashlib.sha256(tag.canonical_key.encode()).hexdigest()[:8]
    base = f"auto_fsm_{tag.canonical_key}"
    budget = _MAX_NAME_LEN - 14  # "_" + 8 hex + "_comb"
    if len(base) > budget:
        base = base[:budget].rstrip("_")
    return f"{base}_{h}_comb"


def BUILD_PASSTHROUGH_FUNC(tag):
    """Bootstrap-pass hardware for an AUTO_FSM call site: a plain combinational
    wrapper, `o.data = func(s.data); o.valid = s.valid`.

    Its job is to put the real function -- and therefore every operation inside
    it -- into the design, so SYN.ADD_PATH_DELAY_TO_LOOKUP measures/estimates
    the per-operation delays the scheduler needs. The wrapper itself is forced
    estimated; the tagged operation roots and registered operand muxes are
    independent consumers in SYN.COLLECT_PATH_DELAY_REQUIREMENTS.
    """
    from pypeline import hw_func

    name = _passthrough_name(tag)
    em = AUTO._Emitter()
    in_t = em.inj(tag.in_stream_t, "t")
    out_t = em.inj(tag.out_stream_t, "t")
    fn = em.inj(tag.func, "f")
    em.line("@hw_func")
    em.line(f"def {name}(s: {in_t}) -> {out_t}:")
    em.line(f"    o: {out_t}")
    em.line(f"    o.data = {fn}(s.data)")
    em.line("    o.valid = s.valid")
    em.line("    return o")
    em.globals["hw_func"] = hw_func
    _seed_struct_globals(em, [tag.in_stream_t, tag.out_stream_t])
    return AUTO._exec_generated(name, em.src(), em.globals)


def _seed_struct_globals(em, types):
    """Put every struct type reachable from `types` into the generated module's
    globals under its own canonical name.

    PY_TO_LOGIC auto-registers struct shapes by scanning an elaborated
    function's __globals__ values, and does not follow struct field types
    transitively -- so a nested struct that never appears standalone in the
    generated source would otherwise be unknown to the elaborator. The same
    precaution pypeline.make_type_to_bytes takes.
    """
    import pypeline

    for t in types:
        try:
            collected = pypeline._collect_struct_types(t)
        except Exception:
            continue
        for name, st in collected.items():
            em.globals.setdefault(name, st)


class _FsmEmitter(AUTO._Emitter):
    """Keep every generated line attributable to operations and hardware roles."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.records = []

    def line(self, text="", kind=None):
        import re

        super().line(text)
        context = dict(self.owner.emission_context)
        stripped = text.strip()
        register = re.match(r"(\w+_r)\s*(?::|=)", stripped)
        if register is not None:
            context.update(self.owner.register_nodes.get(register.group(1), {}))
        if kind is None:
            if ": Reg[" in stripped or ": Feedback[" in stripped:
                kind = "register"
            elif register is not None and "=" in stripped:
                kind = "writeback"
            elif (
                "_lut" in stripped
                or "_slut" in stripped
                or "st1h" in stripped
                or stripped.startswith("st_r =")
            ):
                kind = "control_table"
            elif "_af_mux" in stripped:
                kind = "operand_mux"
            else:
                kind = "glue"
        self.records.append(
            dict(
                line=len(self.lines),
                kind=kind,
                node_ids=context.get("node_ids", []),
                fu=context.get("fu"),
                states=context.get("states", []),
            )
        )


class _Codegen(AUTO._GraphCodegen):
    """Renders one scheduled DAG as pypeline source.

    The generated function's shape (see docs/AUTO_FSM_DESIGN.md for a worked
    example):

        state + value registers
        -> snapshot every register into a local, so all reads see the value
           committed at the last clock edge (pypeline assignment is sequential,
           so a later write in the same body would otherwise be visible to an
           earlier-written read)
        -> drive registered outputs, or expose the final-state value directly
           when an enclosing wrapper already owns the output register
        -> accept a new input when idle
        -> for each shared unit, in a fixed order: multiplex its operands by
           state, then ONE call site -- the single call site is the whole point,
           one hardware instance reused every state
        -> per-state writebacks into value registers, and the next state.
    """

    def __init__(self, tag, schedule, parser_state):
        self.tag = tag
        self.schedule = schedule
        self.parser_state = parser_state
        self.func_entity = schedule.get("func_entity")
        self.nodes = schedule["nodes"]
        self.n_states = schedule["n_states"]
        self.register_output = schedule.get("register_output", True)
        # Control-path rendering, see CTL_CHOICES. Schedules built before this
        # field existed cannot reach here (SCHEDULE_VERSION gates them), so the
        # default is for hand-built test schedules only.
        self.ctl = schedule.get("ctl", "v3")
        self.emission_context = {}  # Current shared unit and its scheduled uses.
        self.register_nodes = {}  # Emitted register name -> write states and source nodes.
        self.em = _FsmEmitter(self)
        self.types = AUTO._TypeResolver()
        self.em.type_resolver = self.types
        self.local_of_node = {}  # node id -> local name holding its result
        self.reg_of_node = {}  # node id -> snapshot local of its register
        self.pack_of_node = {}  # output concat-chain root -> rolling reg local
        self.rolling_ref_of_node = {}  # (glue id, state) -> rolling bit expr
        self.input_ref_of_node = {}  # ref id/(ref id,state) -> compact input expr
        self.glue_local = {}  # (node id, state) -> one materialized shared glue value
        self.pipeline_output = {}  # FU id -> Feedback local for its registered output
        self.result_adapters = {}  # Physical output/cast chain -> one typed result local.
        self.input_value_name = "in_v"
        self.cur_state = None
        self._tmp_n = 0
        self.mux_shapes = []  # (type, fold count) of every operand mux emitted

        for t in (tag.in_type, tag.out_type, tag.in_stream_t, tag.out_stream_t):
            self.types.seed(t)
        for entity in schedule["fus"].values():
            f = AUTO._entity_callables(parser_state).get(entity)
            if f is not None:
                self.types.seed_callable(f)
        for node in self.nodes.values():
            f = AUTO._entity_callables(parser_state).get(node["entity"])
            if f is not None:
                self.types.seed_callable(f)
        # fus/nodes only cover entities that SURVIVED into the schedule -- an
        # entity fully consumed by descent (its whole body inlined into the
        # parent, see "kind": "inlined" in BUILD_DAG) contributes nothing
        # there, so a type living only inside it (a descended soft multiplier's
        # local partial-products array, say) would otherwise never be seeded.
        # BUILD_AUTO_FSM_FUNC already elaborates tag.func's whole subtree right
        # before constructing this _Codegen, so it is safe to walk here.
        func_entity = schedule.get("func_entity")
        if func_entity is not None:
            entity_callables = AUTO._entity_callables(parser_state)
            for entity in AUTO._subtree_entities(parser_state, func_entity):
                f = entity_callables.get(entity)
                if f is not None:
                    self.types.seed_callable(f)

    # ── value rendering ────────────────────────────────────────────────
    def _render_ref(self, ref):
        """Render a ValueRef as an expression valid in the current state."""
        kind = ref[0]
        if kind == "in":
            if self.input_value_name is None:
                raise AUTO.AutoError(
                    "AUTO_FSM: whole transaction input reached codegen after "
                    "field-granular input storage was selected"
                )
            return self.input_value_name
        if kind == "const":
            return self._render_const(ref[1])
        if kind == "lit":
            return self._cast_local(repr(ref[1]), ref[2])
        if kind != "node":
            raise AUTO.AutoError(f"AUTO_FSM: unsupported value reference {ref!r}")
        nid = ref[1]
        input_expr = self.input_ref_of_node.get(
            (nid, self.cur_state), self.input_ref_of_node.get(nid)
        )
        if input_expr is not None:
            return input_expr
        rolling_expr = self.rolling_ref_of_node.get((nid, self.cur_state))
        if rolling_expr is not None:
            return rolling_expr
        node = self.nodes.get(nid)
        if node is None:
            raise AUTO.AutoError(f"AUTO_FSM: reference to unknown operation {nid!r}")
        if nid in self.pack_of_node:
            return self.pack_of_node[nid]
        if node["delay_du"] > 0:
            # A shared unit's output local holds whichever operation that unit
            # is running THIS state. Only a same-state producer can be read
            # from it; anything computed earlier must come from its register.
            if node["state"] == self.cur_state and nid in self.local_of_node:
                return self.local_of_node[nid]
            if nid in self.reg_of_node:
                return self.reg_of_node[nid]
            raise AUTO.AutoError(
                f"AUTO_FSM: operation {nid!r} (state {node['state']}) is read in "
                f"state {self.cur_state} but was not given a register "
                f"(internal scheduling error)"
            )
        # Preserve shared glue as a DAG instead of expanding reconvergent
        # expressions every time a factored operand reads the same value.
        key = nid, self.cur_state
        if key not in self.glue_local:
            expression = self._render_glue(nid, node)
            self.glue_local[key] = self._cast_local(expression, node["out_type"])
        return self.glue_local[key]

    def _st_bit(self, state):
        """Source expression for "the FSM is in this state", one-hot only."""
        return f"st1h[{state}:{state}]"

    def _st_bits_or(self, states):
        """OR of the hot bits for a set of states, one-hot only."""
        return " | ".join(self._st_bit(k) for k in sorted(states))

    # ── register allocation ────────────────────────────────────────────
    def _adapt_unit_result(self, node, expression):
        casts = tuple(node.get("result_casts", ()))
        if not casts:
            return expression
        key = expression, casts, node["out_type"]
        if key not in self.result_adapters:
            result = expression
            for ctype in casts + (node["out_type"],):
                result = self._cast_local(result, ctype)
            self.result_adapters[key] = result
        return self.result_adapters[key]

    def _cross_state_nodes(self):
        return _CROSS_STATE_NODES(self.nodes, self.schedule["output"], self.n_states)

    # ── main ───────────────────────────────────────────────────────────
    def generate(self):
        from pypeline import Reg, hw_func, make_array_t

        em = self.em
        tag = self.tag
        schedule = self.schedule
        name = schedule["entity"]

        in_stream_t = em.inj(tag.in_stream_t, "t")
        out_stream_t = em.inj(tag.out_stream_t, "t")
        in_t = em.inj(tag.in_type, "t")
        out_t = em.inj(tag.out_type, "t")
        st_t = em.inj(self.types.resolve(_state_reg_ctype(self.n_states)), "t")
        u1_t = em.inj(self.types.resolve("uint1_t"), "t")
        onehot = self.ctl == "onehot"
        if onehot:
            # One bit per state, bit 0 = idle. Reg initialiser makes idle the
            # reset state, which binary encoding gets for free from zero.
            st1h_t = em.inj(self.types.resolve(f"uint{self.n_states + 1}_t"), "t")

        # Values crossing a state boundary, bound to registers -- SHARING one
        # register between values that are never live at the same time (see
        # ALLOCATE_REGISTERS; on a heavily shared FSM this is typically the
        # largest single area saving available).
        reg_of, reg_types = ALLOCATE_REGISTERS(
            self.nodes,
            schedule["output"],
            self.n_states,
            schedule.get("cross_fu_register_types", ()),
        )
        self.reg_of = reg_of
        for nid, idx in sorted(reg_of.items()):
            row = self.register_nodes.setdefault(
                f"v{idx}_r", dict(role="work", node_ids=[], states=[])
            )
            row["node_ids"].append(nid)
            row["states"] = sorted(set(row["states"] + [self.nodes[nid]["state"]]))
        for state_register in ("st_r", "st1h_r"):
            self.register_nodes[state_register] = dict(
                role="control", node_ids=[], states=list(range(self.n_states + 1))
            )
        terminal_nodes = set()
        _scheduled_deps(
            {"nodes": self.nodes},
            schedule["output"],
            _scheduled_ids({"nodes": self.nodes}),
            terminal_nodes,
        )
        self.register_nodes["out_data_r"] = dict(
            role="output", node_ids=sorted(terminal_nodes), states=[self.n_states]
        )
        self.register_nodes["out_valid_r"] = dict(
            role="control", node_ids=[], states=[self.n_states]
        )
        self.register_nodes["in_r"] = dict(role="input", node_ids=[], states=[0])
        cross = sorted(reg_of)
        reg_names = {nid: f"v{reg_of[nid]}" for nid in cross}
        output_packs = _OUTPUT_SHIFT_PACKS(
            self.nodes, schedule["output"], self.n_states
        )
        input_storage = _INPUT_STORAGE_PLAN(
            self.nodes, schedule["output"], self.n_states
        )
        pack_names = {
            pack["root"]: f"pack{idx}" for idx, pack in enumerate(output_packs)
        }
        input_field_names = {}
        if input_storage is not None:
            self.input_value_name = None
            for idx, field in enumerate(input_storage["stored_fields"]):
                local = f"in_f{idx}"
                input_field_names[field["field"]] = local
                self.register_nodes[local + "_r"] = dict(
                    role="input", node_ids=sorted(field["refs"]), states=[0]
                )
                for nid in field["refs"]:
                    self.input_ref_of_node[nid] = local
            pack_of_root = {pack["root"]: pack for pack in output_packs}
            for root, field in input_storage["preload_by_pack"].items():
                pack = pack_of_root[root]
                state = pack["source_fusion"]["source_state"]
                for nid in input_storage["field_refs"][field]:
                    self.input_ref_of_node[(nid, state)] = pack_names[root]
        for pack in output_packs:
            fusion = pack.get("source_fusion")
            if fusion is None:
                continue
            pack_name = pack_names[pack["root"]]
            for key, bit in fusion["replacements"].items():
                self.rolling_ref_of_node[key] = f"{pack_name}[{bit}:{bit}]"

        em.line("@hw_func")
        em.line(f"def {name}(s: {in_stream_t}) -> {out_stream_t}:")
        if onehot:
            em.line(f"    st1h_r: Reg[{st1h_t}] = 1")
        else:
            em.line(f"    st_r: Reg[{st_t}]")
        if input_storage is None:
            em.line(f"    in_r: Reg[{in_t}]")
        else:
            for field in input_storage["stored_fields"]:
                local = input_field_names[field["field"]]
                t = em.inj(self.types.resolve(field["ctype"]), "t")
                em.line(f"    {local}_r: Reg[{t}]")
        for idx in sorted(reg_types):
            t = em.inj(self.types.resolve(reg_types[idx]), "t")
            em.line(f"    v{idx}_r: Reg[{t}]")
        for pack in output_packs:
            t = em.inj(self.types.resolve(pack["ctype"]), "t")
            em.line(f"    {pack_names[pack['root']]}_r: Reg[{t}]")
        if self.register_output:
            em.line(f"    out_data_r: Reg[{out_t}]")
            em.line(f"    out_valid_r: Reg[{u1_t}]")
        em.line(
            "    # Snapshot committed state before any write below "
            "(pypeline assignment is sequential)"
        )
        if onehot:
            em.line(f"    st1h: {st1h_t} = st1h_r")
        else:
            em.line(f"    st: {st_t} = st_r")
        if input_storage is None:
            em.line(f"    in_v: {in_t} = in_r")
        else:
            for field in input_storage["stored_fields"]:
                local = input_field_names[field["field"]]
                t = em.inj(self.types.resolve(field["ctype"]), "t")
                em.line(f"    {local}: {t} = {local}_r")
        for idx in sorted(reg_types):
            t = em.inj(self.types.resolve(reg_types[idx]), "t")
            em.line(f"    v{idx}: {t} = v{idx}_r")
        for pack in output_packs:
            pack_name = pack_names[pack["root"]]
            t = em.inj(self.types.resolve(pack["ctype"]), "t")
            em.line(f"    {pack_name}: {t} = {pack_name}_r")
            if pack.get("source_fusion") is None:
                self.pack_of_node[pack["root"]] = pack_name
        for nid in cross:
            self.reg_of_node[nid] = reg_names[nid]
        em.line(f"    o: {out_stream_t}")
        if self.register_output:
            em.line("    o.data = out_data_r")
            em.line("    o.valid = out_valid_r")
        if onehot:
            # Assemble the next one-hot state directly: shift the hot bit along
            # and wrap the last state back to idle. No override contract is
            # needed (unlike v3's table) because accepting an input is just one
            # more term in bit 1's expression.
            n = self.n_states
            em.line("    # Next state: shift the hot bit along, wrap to idle")
            em.line(f"    ns1h: {st1h_t} = 0")
            em.line(f"    ns1h[1:1] = {self._st_bit(0)} & s.valid")
            for k in range(1, n):
                em.line(f"    ns1h[{k + 1}:{k + 1}] = {self._st_bit(k)}")
            # `^ 1` rather than `~`: on a one-bit value `~` would invert the
            # whole promoted width, and only the low bit is wanted here.
            em.line(
                f"    ns1h[0:0] = {self._st_bit(n)} | "
                f"({self._st_bit(0)} & (s.valid ^ 1))"
            )
            em.line("    st1h_r = ns1h")
        elif self.ctl == "v2" and self.register_output:
            em.line("    out_valid_r = 0")
        else:
            # Next state from a constant LUT rather than a comparator per state.
            # ns[0] = 0 holds idle, ns[k] = k + 1 advances, ns[n_states] = 0
            # wraps -- one table covers all three, where `st + 1` would need an
            # idle guard, a wrap guard and a promotion cast.
            ns = [0] * (self.n_states + 1)
            for k in range(1, self.n_states):
                ns[k] = k + 1
            ns_lut_t = em.inj(
                self.types.resolve(_state_reg_ctype(self.n_states))[self.n_states + 1],
                "t",
            )
            em.line(
                "    # Next state from a constant LUT: idle holds 0, "
                "last state wraps to 0."
            )
            em.line(
                "    # Written BEFORE the accept below, so accept's "
                "st_r = 1 overrides it."
            )
            em.line(f"    ns_lut: {ns_lut_t} = {ns!r}")
            em.line("    st_r = ns_lut[st]")

        # Constant/glue-only seeds for recovered rolling output registers.
        # Rendered outside the accept branch because rendering a cast or slice
        # can need a typed local declaration.
        pack_seeds = {}
        self.cur_state = 0
        for pack in output_packs:
            if pack.get("source_fusion") is not None:
                continue
            expr = self._render_ref(pack["seed_ref"])
            for ctype in pack["seed_casts"]:
                expr = self._cast_local(expr, ctype)
            pack_seeds[pack["root"]] = expr
        em.line("    # Accept a new input only while idle (II == latency)")
        if onehot:
            em.line(f"    if {self._st_bit(0)} & s.valid:")
            if input_storage is None:
                em.line("        in_r = s.data")
            else:
                for field in input_storage["stored_fields"]:
                    local = input_field_names[field["field"]]
                    em.line(
                        f"        {local}_r = s.data{AUTO._path_suffix([field['field']])}"
                    )
                for root, field in input_storage["preload_by_pack"].items():
                    em.line(
                        f"        {pack_names[root]}_r = s.data{AUTO._path_suffix([field])}"
                    )
            for pack in output_packs:
                if pack.get("source_fusion") is not None:
                    continue
                pack_name = pack_names[pack["root"]]
                em.line(f"        {pack_name}_r = {pack_seeds[pack['root']]}")
        else:
            em.line("    if (st == 0) & s.valid:")
            if input_storage is None:
                em.line("        in_r = s.data")
            else:
                for field in input_storage["stored_fields"]:
                    local = input_field_names[field["field"]]
                    em.line(
                        f"        {local}_r = s.data{AUTO._path_suffix([field['field']])}"
                    )
                for root, field in input_storage["preload_by_pack"].items():
                    em.line(
                        f"        {pack_names[root]}_r = s.data{AUTO._path_suffix([field])}"
                    )
            for pack in output_packs:
                if pack.get("source_fusion") is not None:
                    continue
                pack_name = pack_names[pack["root"]]
                em.line(f"        {pack_name}_r = {pack_seeds[pack['root']]}")
            em.line("        st_r = 1")

        # ── shared functional units ──
        for index, fu in enumerate(schedule["fu_order"]):
            entity = schedule["fus"][fu]
            implementation = schedule.get("implementations", {}).get(entity)
            if implementation is None:
                continue
            from pypeline import Feedback

            em.inj_named(Feedback, "Feedback")
            feedback_name = f"pipeline{index}_o"
            node_ids = [
                nid for nid in schedule["node_order"] if self.nodes[nid].get("fu") == fu
            ]
            first = self.nodes[node_ids[0]]
            result_type = em.inj(
                self.types.resolve(first.get("physical_out_type", first["out_type"])),
                "t",
            )
            em.line(f"    {feedback_name}: Feedback[{result_type}]")
            self.pipeline_output[fu] = feedback_name
            for nid in node_ids:
                self.local_of_node[nid] = self._adapt_unit_result(
                    self.nodes[nid], feedback_name
                )
        for fu in schedule["fu_order"]:
            # Ascending state, node id breaking ties: the fold index a unit's
            # operand mux selects with is then just "how many earlier states
            # used this unit", which reads far better in generated source than
            # an arbitrary permutation would -- and is equally deterministic.
            fu_nodes = sorted(
                (
                    (nid, self.nodes[nid])
                    for nid in schedule["node_order"]
                    if self.nodes[nid].get("fu") == fu
                ),
                key=lambda pair: (pair[1]["state"], pair[0]),
            )
            if not fu_nodes:
                continue
            self._emit_fu(fu, fu_nodes)
        self.emission_context = {}

        # One write-data expression per recovered rolling register.  A plain
        # output pack always shifts in the current shared-FU result.  A fused
        # consume/produce pack captures its full source in the first state,
        # then shifts in the PREVIOUS state's one-bit result; its wide 2:1
        # write-data mux is explicit here and in ESTIMATE_SCHEDULE_AREA.
        pack_write_srcs = {}
        for pack in output_packs:
            pack_name = pack_names[pack["root"]]
            first_step = pack["steps"][0]
            fusion = pack.get("source_fusion")
            self.cur_state = (
                first_step["state"] if fusion is None else first_step["state"] + 1
            )
            bit_expr = self._render_ref(first_step["ref"])
            for ctype in first_step["casts"]:
                bit_expr = self._cast_local(bit_expr, ctype)
            root_node = self.nodes[pack["root"]]
            shifted = f"({pack_name})[{pack['width'] - 2}:0]"
            shift_expr = AUTO._render_op(
                root_node["op"],
                [shifted, bit_expr],
                em,
                self.parser_state,
                root_node["entity"],
            )
            src = f"{pack_name}_wsrc"
            pack_t_obj = self.types.resolve(pack["ctype"])
            t = em.inj(pack_t_obj, "t")
            if fusion is None:
                em.line(f"    {src}: {t} = {shift_expr}")
                pack_write_srcs[pack["root"]] = src
                continue

            # In the common case the one-cycle output-bit live ranges all bind
            # to one register.  Assert that invariant instead of silently
            # selecting the wrong bit if unrelated same-type lifetimes ever
            # perturb allocation; declining/further generalizing the fusion is
            # safer than generating a latent functional bug.
            bit_regs = {reg_of[step["dep"]] for step in pack["steps"]}
            if len(bit_regs) != 1:
                raise AUTO.AutoError(
                    "AUTO_FSM: rolling output bits did not bind to one register "
                    f"for pack {pack['root']!r} (got {sorted(bit_regs)})"
                )
            source_expr = self.local_of_node[fusion["source_dep"]]
            choices_t = em.inj(make_array_t(pack_t_obj, 2), "t")
            choices = f"{pack_name}_wchoices"
            em.line(f"    {choices}: {choices_t}")
            em.line(f"    {choices}[0] = {shift_expr}")
            em.line(f"    {choices}[1] = {source_expr}")
            sel = f"{pack_name}_wsel"
            first_state = fusion["source_state"]
            if onehot:
                em.line(f"    {sel}: {u1_t} = {self._st_bit(first_state)}")
            elif self.ctl == "v2":
                em.line(f"    {sel}: {u1_t} = st == {first_state}")
            else:
                sel_lut_t = em.inj(
                    self.types.resolve("uint1_t")[self.n_states + 1], "t"
                )
                sel_lut = [0] * (self.n_states + 1)
                sel_lut[first_state] = 1
                em.line(f"    {pack_name}_wslut: {sel_lut_t} = {sel_lut!r}")
                em.line(f"    {sel}: {u1_t} = {pack_name}_wslut[st]")
            mux_fn = AUTO._mux_callable(pack_t_obj, 2)
            if mux_fn is not None:
                em.line(
                    f"    {src}: {t} = " f"{em.inj(mux_fn, 'mux')}({sel}, {choices})"
                )
                self._note_mux_entity(pack_t_obj, 2)
            else:
                em.line(f"    {src}: {t} = {shift_expr}")
                em.line(f"    if {sel}:")
                em.line(f"        {src} = {source_expr}")
            pack_write_srcs[pack["root"]] = src

        # A fused pack has shifted bits 0..W-2 into place by the final state;
        # the last produced bit has a one-cycle scalar lifetime and forms bit
        # zero directly.  Materialize that exact final value before rendering
        # the surrounding output assembly.
        self.cur_state = self.n_states
        for pack in output_packs:
            fusion = pack.get("source_fusion")
            if fusion is None:
                continue
            pack_name = pack_names[pack["root"]]
            last_step = pack["steps"][-1]
            bit_expr = self._render_ref(last_step["ref"])
            for ctype in last_step["casts"]:
                bit_expr = self._cast_local(bit_expr, ctype)
            root_node = self.nodes[pack["root"]]
            expr = AUTO._render_op(
                root_node["op"],
                [f"({pack_name})[{pack['width'] - 2}:0]", bit_expr],
                em,
                self.parser_state,
                root_node["entity"],
            )
            final_name = f"{pack_name}_final"
            t = em.inj(self.types.resolve(pack["ctype"]), "t")
            em.line(f"    {final_name}: {t} = {expr}")
            self.pack_of_node[pack["root"]] = final_name

        # ── the final result ──
        # Rendered here, at this indentation, BEFORE the state branches below:
        # assembling a struct or replaying a narrowing cast needs typed locals,
        # and a local first declared inside one branch would have no type on
        # the other paths. Computing it unconditionally costs nothing -- it is
        # combinational either way, and only the register's enable is gated.
        if self.register_output:
            em.line("    # Final result (registered in the last state below)")
        else:
            em.line("    # Final result (visible directly in the last state)")
        self.cur_state = self.n_states
        out_expr = self._render_ref(schedule["output"])
        for ctype in schedule["output_casts"]:
            out_expr = self._cast_local(out_expr, ctype)

        # ── writebacks and next state ──
        if self.ctl == "v2":
            em.line("    # Writebacks and next state")
            for state in range(1, self.n_states + 1):
                kw = "if" if state == 1 else "elif"
                em.line(f"    {kw} st == {state}:")
                for pack in output_packs:
                    if state in {step["state"] for step in pack["steps"]}:
                        pack_name = pack_names[pack["root"]]
                        em.line(
                            f"        {pack_name}_r = "
                            f"{pack_write_srcs[pack['root']]}"
                        )
                for nid in cross:
                    if self.nodes[nid]["state"] == state:
                        em.line(
                            f"        {reg_names[nid]}_r = {self.local_of_node[nid]}"
                        )
                if state == self.n_states:
                    if self.register_output:
                        em.line(f"        out_data_r = {out_expr}")
                        em.line("        out_valid_r = 1")
                    em.line("        st_r = 0")
                else:
                    em.line(f"        st_r = {state + 1}")
            if not self.register_output:
                em.line(f"    o.data = {out_expr}")
                em.line(f"    o.valid = st == {self.n_states}")
        else:
            # One write-enable bit per register, read from a constant table.
            # `if <uint1>:` is pure clock-enable gating -- PY_TO_LOGIC only
            # inserts a comparator when the condition is not already one bit
            # wide -- so this costs a table and no compare, where v2 paid an
            # equality comparator per state plus a priority chain.
            if onehot:
                em.line(
                    "    # Writebacks: write enable is an OR of the states' " "hot bits"
                )
            else:
                em.line(
                    "    # Writebacks: constant write-enable LUT per register, "
                    "no state compares"
                )
                we_lut_t = em.inj(self.types.resolve("uint1_t")[self.n_states + 1], "t")
            by_reg = {}
            for nid in cross:
                by_reg.setdefault(reg_of[nid], []).append(nid)
            for idx in sorted(by_reg):
                nids = sorted(
                    by_reg[idx], key=lambda nid: (self.nodes[nid]["state"], nid)
                )
                src_index = {}
                srcs = []
                src_rows = []
                for nid in nids:
                    src = self.local_of_node[nid]
                    if src not in src_index:
                        src_index[src] = len(srcs)
                        srcs.append(src)
                    src_rows.append(src_index[src])
                write_src = srcs[0]
                if len(srcs) > 1:
                    reg_t = self.types.resolve(reg_types[idx])
                    t = em.inj(reg_t, "t")
                    sel_t_obj = _mux_sel_type(len(srcs))
                    sel_t = em.inj(sel_t_obj, "t")
                    sel_name = f"v{idx}_wsel"
                    if onehot:
                        em.line(f"    {sel_name}: {sel_t} = 0")
                        selw = max(1, (len(srcs) - 1).bit_length())
                        for bit in range(selw):
                            states = [
                                self.nodes[nid]["state"]
                                for nid, row in zip(nids, src_rows)
                                if (row >> bit) & 1
                            ]
                            if states:
                                em.line(
                                    f"    {sel_name}[{bit}:{bit}] = "
                                    f"{self._st_bits_or(states)}"
                                )
                    else:
                        lut = [0] * (self.n_states + 1)
                        for nid, row in zip(nids, src_rows):
                            lut[self.nodes[nid]["state"]] = row
                        lut_t = em.inj(sel_t_obj[self.n_states + 1], "t")
                        em.line(f"    v{idx}_wslut: {lut_t} = {lut!r}")
                        em.line(f"    {sel_name}: {sel_t} = v{idx}_wslut[st]")
                    mux_fn = AUTO._mux_callable(reg_t, len(srcs))
                    if mux_fn is not None:
                        choices_t = em.inj(make_array_t(reg_t, len(srcs)), "t")
                        em.line(f"    v{idx}_wchoices: {choices_t}")
                        for row, src in enumerate(srcs):
                            em.line(f"    v{idx}_wchoices[{row}] = {src}")
                        write_src = f"v{idx}_wsrc"
                        em.line(
                            f"    {write_src}: {t} = "
                            f"{em.inj(mux_fn, 'mux')}({sel_name}, v{idx}_wchoices)"
                        )
                        self._note_mux_entity(reg_t, len(srcs))
                    else:
                        write_src = f"v{idx}_wsrc"
                        em.line(f"    {write_src}: {t} = {srcs[0]}")
                        for row, src in enumerate(srcs[1:], start=1):
                            kw = "if" if row == 1 else "elif"
                            em.line(f"    {kw} {sel_name} == {row}:")
                            em.line(f"        {write_src} = {src}")
                if onehot:
                    states = {self.nodes[nid]["state"] for nid in nids}
                    em.line(f"    v{idx}_we: {u1_t} = {self._st_bits_or(states)}")
                else:
                    wel = [0] * (self.n_states + 1)
                    for nid in nids:
                        wel[self.nodes[nid]["state"]] = 1
                    em.line(f"    v{idx}_wel: {we_lut_t} = {wel!r}")
                    em.line(f"    v{idx}_we: {u1_t} = v{idx}_wel[st]")
                em.line(f"    if v{idx}_we:")
                em.line(f"        v{idx}_r = {write_src}")
            for pack in output_packs:
                pack_name = pack_names[pack["root"]]
                states = {step["state"] for step in pack["steps"]}
                if onehot:
                    em.line(
                        f"    {pack_name}_we: {u1_t} = " f"{self._st_bits_or(states)}"
                    )
                else:
                    wel = [0] * (self.n_states + 1)
                    for state in states:
                        wel[state] = 1
                    em.line(f"    {pack_name}_wel: {we_lut_t} = {wel!r}")
                    em.line(f"    {pack_name}_we: {u1_t} = {pack_name}_wel[st]")
                em.line(f"    if {pack_name}_we:")
                em.line(f"        {pack_name}_r = {pack_write_srcs[pack['root']]}")
            if onehot:
                em.line(
                    f"    ow: {u1_t} = {self._st_bit(self.n_states)}"
                    "  # last-state pulse"
                )
            else:
                ow = [0] * (self.n_states + 1)
                ow[self.n_states] = 1
                em.line(f"    ow_lut: {we_lut_t} = {ow!r}  # last-state pulse")
                em.line(f"    ow: {u1_t} = ow_lut[st]")
            if self.register_output:
                em.line("    if ow:")
                em.line(f"        out_data_r = {out_expr}")
                em.line("    out_valid_r = ow")
            else:
                em.line(f"    o.data = {out_expr}")
                em.line("    o.valid = ow")
        em.line("    return o")

        em.globals["hw_func"] = hw_func
        em.globals["Reg"] = Reg
        _seed_struct_globals(
            em, [tag.in_stream_t, tag.out_stream_t, tag.in_type, tag.out_type]
        )
        _seed_struct_globals(em, [t for t, _n in self.mux_shapes])
        _REGISTER_MUX_ENTITIES(self.parser_state, self.mux_shapes)
        return name, em.src(), em.globals

    def _emit_operand_factor_plan(self, plan, result_name, selector, memo):
        """Emit one plan made by :func:`_operand_factor_plan`.

        Every recursive result is materialized at its consumer's port type.
        Besides keeping the elaborator's narrowing semantics exact, named
        locals make bit slices safe (their base cannot be an arbitrary Python
        expression in the current frontend).
        """
        from pypeline import make_array_t

        em = self.em
        target_t_obj = self.types.resolve(plan["target_type"])
        target_t = em.inj(target_t_obj, "t")
        cached = memo.get(id(plan))
        if cached is not None:
            em.line(f"    {result_name}: {target_t} = {cached}")
            return result_name
        memo[id(plan)] = result_name
        kind = plan["kind"]

        if kind == "leaf":
            _user_i, ref, casts, state = plan["alternative"]
            self.cur_state = state
            expr = self._render_ref(ref)
            for ctype in casts:
                expr = self._cast_local(expr, ctype)
            em.line(f"    {result_name}: {target_t} = {expr}")
            return result_name

        if kind == "glue":
            node = self.nodes[plan["node_id"]]
            args = []
            for port_i, child in enumerate(plan["children"]):
                child_name = f"af{self._tmp_n}_f"
                self._tmp_n += 1
                args.append(self._emit_operand_factor_plan(child, child_name, selector, memo))
            expr = AUTO._render_op(node["op"], args, em, self.parser_state, node["entity"])
            for ctype in plan["casts"]:
                expr = self._cast_local(expr, ctype)
            em.line(f"    {result_name}: {target_t} = {expr}")
            return result_name

        if kind != "mux":
            raise AUTO.AutoError(f"AUTO_FSM: unknown operand factor-plan kind {kind!r}")

        choices = []
        for child in plan["choices"]:
            child_name = f"af{self._tmp_n}_f"
            self._tmp_n += 1
            choices.append(
                self._emit_operand_factor_plan(child, child_name, selector, memo)
            )
        sel_name = selector(plan["mapping"], len(choices))
        mux_fn = AUTO._mux_callable(target_t_obj, len(choices))
        if mux_fn is None:
            em.line(f"    {result_name}: {target_t} = {choices[0]}")
            for row, expr in enumerate(choices[1:], start=1):
                kw = "if" if row == 1 else "elif"
                em.line(f"    {kw} {sel_name} == {row}:")
                em.line(f"        {result_name} = {expr}")
            return result_name

        arr_name = f"af{self._tmp_n}_fc"
        self._tmp_n += 1
        arr_t = em.inj(make_array_t(target_t_obj, len(choices)), "t")
        em.line(f"    {arr_name}: {arr_t}")
        for row, expr in enumerate(choices):
            em.line(f"    {arr_name}[{row}] = {expr}")
        em.line(
            f"    {result_name}: {target_t} = "
            f"{em.inj(mux_fn, 'mux')}({sel_name}, {arr_name})"
        )
        self._note_mux_entity(target_t_obj, len(choices))
        return result_name

    def _emit_fu(self, fu, fu_nodes):
        """Emit one shared unit: its per-state operand multiplexers and its
        single call site.

        Every operand expression is rendered FIRST, at this block's own
        indentation, before any `if` is written. Rendering can emit typed locals
        (for narrowing casts and inline glue), and a local first declared inside
        one branch would have no type on the other paths -- so they must all
        land above the multiplexer, not inside it.

        The multiplexers themselves are ARRAY READS, not if/elif chains:

            u0_c0: int16_t[3]        # one array per unit input port
            u0_c0[0] = <state 1's operand>
            u0_c0[1] = <state 4's operand>
            u0_c0[2] = <state 6's operand>
            u0_a0: int16_t = _af_mux0(u0_sel, u0_c0)

        A variable array index elaborates to a BALANCED binary selection tree;
        the if/elif form v1 used elaborates to a PRIORITY chain, whose depth --
        and therefore delay -- grows linearly in the fold count instead of
        logarithmically. That difference is small at 2 users and dominant at 20,
        which is exactly the range the area sweep now explores.

        The narrow state->fold-index decode is itself a constant table read
        (`u0_sel = u0_slut[st]`) under ctl "v3", where v2 spent one equality
        comparator per fold plus a priority chain. Synthesis folds the table's
        constant leaves down to about one gate per select bit, and the read sits
        off the data path: `st` is a register output available at the start of
        the cycle, so it resolves in parallel with the operands it steers.
        """
        em = self.em
        self.emission_context = dict(
            fu=fu,
            node_ids=[nid for nid, _n in fu_nodes],
            states=sorted({n.get("launch_state", n["state"]) for _nid, n in fu_nodes}),
        )
        n_ports = len(fu_nodes[0][1]["operands"])
        fu_nodes = [
            (nid, dict(node, state=node.get("launch_state", node["state"])))
            for nid, node in fu_nodes
        ]
        prefix = f"u{self._tmp_n}"
        self._tmp_n += 1
        arg_names = [f"{prefix}_a{i}" for i in range(n_ports)]
        out_local = self.pipeline_output.get(fu, f"{prefix}_o")
        n_users = len(fu_nodes)

        em.line(
            f"    # {self.schedule['fus'].get(fu, fu)}: {n_users} "
            f"operation(s) sharing one unit"
        )
        first_nid, first_node = fu_nodes[0]
        _planned_nodes, port_plans = _operand_mux_plan(self.schedule, fu, self.reg_of)
        assert [nid for nid, _node in _planned_nodes] == [
            nid for nid, _node in fu_nodes
        ]

        # A selector belongs to a state-to-DISTINCT-CHOICE mapping, not to the
        # FU as a whole. Constant ports need none; two ports with the same
        # mapping share one table/encoder.
        selector_of = {}

        def selector(mapping, n_choices):
            selector_key = (tuple(mapping), n_choices)
            hit = selector_of.get(selector_key)
            if hit is not None:
                return hit
            sel_name = f"{prefix}_sel{len(selector_of)}"
            sel_elem_t = _mux_sel_type(n_choices)
            sel_t = em.inj(sel_elem_t, "t")

            if self.ctl == "onehot":
                # The operand mux is a MEASURED balanced tree and needs a
                # binary select, so one-hot has to encode back: select bit j is
                # the OR of the hot bits of every state whose fold index has
                # bit j set. This encoder is the price one-hot pays where v3
                # pays a constant table, and measuring which is cheaper is the
                # entire point of the ctl "onehot" experiment.
                em.line(f"    {sel_name}: {sel_t} = 0")
                selw = max(1, (n_choices - 1).bit_length())
                for j in range(selw):
                    hot = [
                        node["state"]
                        for row, (_nid, node) in zip(mapping, fu_nodes)
                        if (row >> j) & 1
                    ]
                    if hot:
                        em.line(f"    {sel_name}[{j}:{j}] = {self._st_bits_or(hot)}")
            elif self.ctl == "v2":
                em.line(f"    {sel_name}: {sel_t} = 0")
                branch = 0
                for row, (_nid, node) in zip(mapping, fu_nodes):
                    if row == 0:
                        continue
                    kw = "if" if branch == 0 else "elif"
                    em.line(f"    {kw} st == {node['state']}:")
                    em.line(f"        {sel_name} = {row}")
                    branch += 1
            else:
                # One constant table read instead of a comparator per fold: the
                # states this unit does NOT run in read 0, which is harmless
                # because the unit's output is only captured where a write
                # enable says so.
                lut = [0] * (self.n_states + 1)
                for row, (_nid, node) in zip(mapping, fu_nodes):
                    lut[node["state"]] = row
                lut_t = em.inj(sel_elem_t[self.n_states + 1], "t")
                lut_name = f"{sel_name}_lut"
                em.line(
                    f"    {lut_name}: {lut_t} = {lut!r}  " "# state -> distinct operand"
                )
                em.line(f"    {sel_name}: {sel_t} = {lut_name}[st]")
            selector_of[selector_key] = sel_name
            return sel_name

        implementation = self.schedule.get("implementations", {}).get(
            first_node["entity"]
        )
        if implementation is not None and implementation["registered_selection"]:
            from pypeline import make_array_t

            rows = implementation["selection_rows"]
            if n_users > rows:
                raise AutoFsmInternalError(
                    "AUTO_FSM: operand selection exceeded its concrete row count"
                )
            arguments = [selector(tuple(range(n_users)), rows)]
            for i, arg in enumerate(arg_names):
                ctype = self.types.resolve(first_node["port_types"][i])
                array_t = em.inj(make_array_t(ctype, rows), "t")
                em.line(f"    {arg}: {array_t}")
                for row in range(rows):
                    node = fu_nodes[row if row < n_users else 0][1]
                    self.cur_state = node["state"]
                    expression = self._render_operand(node, i, at_port_type=True)
                    em.line(f"    {arg}[{row}] = {expression}")
                arguments.append(arg)
        else:
            factor_emit_memo = {}
            for i, arg in enumerate(arg_names):
                port_plan = port_plans[i]
                self._emit_operand_factor_plan(
                    port_plan["factor_plan"], arg, selector, factor_emit_memo
                )
            arguments = arg_names

        out_ct = em.inj(
            self.types.resolve(
                first_node.get("physical_out_type", first_node["out_type"])
            ),
            "t",
        )
        self.cur_state = first_node["state"]
        if implementation is not None:
            pipeline = _make_unit_tag(
                self.parser_state, self.tag.canonical_key, first_node, implementation
            )
            call = em.inj(pipeline, "pipeline")
            em.line(f"    {out_local} = {call}({', '.join(arguments)})", kind="unit")
        else:
            em.line(
                f"    {out_local}: {out_ct} = "
                + AUTO._render_op(
                    first_node["op"],
                    arg_names,
                    em,
                    self.parser_state,
                    first_node["entity"],
                ),
                kind="unit",
            )
        for nid, node in fu_nodes:
            self.local_of_node[nid] = self._adapt_unit_result(node, out_local)

    def _note_mux_entity(self, t, n):
        """Remember that this FSM instantiates an operand mux of this shape, so
        SYN measures it on its own, apart from the FSM's one whole-module run.
        Measured once, cached on disk, and read straight back by the next
        schedule's mux delay lookup -- the loop that replaces v1's flat
        MUX_PENALTY_DU guess."""
        self.mux_shapes.append((t, n))


def _REGISTER_MUX_ENTITIES(parser_state, mux_shapes):
    """Mark the operand mux hw_funcs this FSM instantiates as things SYN should
    measure in their own right.

    A generated FSM holds state, so SYN measures it as one atomic span and
    collects nothing inside it. Its operand muxes remain independent
    calibration consumers for the scheduler and area search. Naming them lets
    COLLECT_PATH_DELAY_REQUIREMENTS measure them anyway.

    Records the live callables, not entity names: the names are only assigned
    when the generated source is elaborated, which has not happened yet at code
    generation time.
    """
    if not mux_shapes:
        return
    pending = parser_state.pypeline_auto_fsm_mux_callables
    for t, n in mux_shapes:
        fn = AUTO._mux_callable(t, n)
        if fn is not None and fn not in pending:
            pending.append(fn)


def AUTO_FSM_MEASURE_ENTITIES(parser_state):
    """FuncLogicLookupTable keys of the operand muxes SYN should measure on
    their own. Empty on any build without AUTO_FSM."""
    out = set()
    for fn in (
        parser_state.pypeline_auto_fsm_mux_callables
        + parser_state.pypeline_auto_fsm_measure_callables
    ):
        entity = AUTO._entity_key_for_callable(parser_state, fn)
        if entity is not None:
            out.add(entity)
    return out


def GENERATE_FSM_SOURCE(tag, schedule, parser_state):
    """Generate the resource-shared FSM as ordinary pypeline source."""
    generator = _Codegen(tag, schedule, parser_state)
    result = generator.generate()
    parser_state.pypeline_auto_fsm_provenance[tag.canonical_key] = {
        "schema_version": 1,
        "key": tag.canonical_key,
        "entity": schedule["entity"],
        "lines": generator.em.records,
        "registers": generator.register_nodes,
    }
    return result


def _PREPARE_CANDIDATES(tag, parser_state, elaborator):
    """Elaborate every alternative the schedule may bind: soft-operator and
    width-halving equivalents (see PREPARE_SOFT_EQUIVALENTS and
    PREPARE_SPLIT_EQUIVALENTS) and AUTO_COMB_OPT's area and delay graph
    alternatives.

    Runs identically on the bootstrap pass, where the area search chooses among
    them, and on the scheduled pass, whose fresh parse must record a live
    callable for every unit the carried schedule binds. AUTO_COMB_OPT.prepare
    alone does not cover the soft equivalents: it returns before preparing them
    for some functions (one calling a scoped operator implementation, say).
    """
    import AUTO_COMB_OPT

    AUTO.PREPARE_SOFT_EQUIVALENTS(tag, parser_state, elaborator)
    AUTO.PREPARE_SPLIT_EQUIVALENTS(tag, parser_state, elaborator)
    AUTO.PREPARE_CONSTANT_SPECIALIZATIONS(tag, parser_state, elaborator)

    _prepare_transform_candidates(tag, parser_state, elaborator)

    _prepare_unit_candidates(tag, parser_state, elaborator)
    AUTO_COMB_OPT.prepare(tag.func, parser_state, elaborator, strict=False)
    AUTO_COMB_OPT.prepare(tag.func, parser_state, elaborator, strict=False, objective="delay")
    entity = elaborator._elaborate_live_func(tag.func.__name__, tag.func).func_name
    parser_state.pypeline_auto_fsm_source_identities[tag.canonical_key] = (
        _source_identity(parser_state, entity)
    )


def BUILD_AUTO_FSM_FUNC(tag, parser_state, elaborator=None):
    """Elaborator entry point: what hardware an AUTO_FSM call site instantiates.

    No schedule installed (bootstrap pass, --comb, --no_synth) -> the
    combinational passthrough. Schedule installed -> the generated FSM.
    Memoized on the tag so several call sites of one tag share one entity.
    """
    tags = getattr(parser_state, "pypeline_auto_fsm_tags", None)
    if tags is None:
        tags = {}
        parser_state.pypeline_auto_fsm_tags = tags
    tags[tag.canonical_key] = tag

    if tag._generated is not None:
        return tag._generated
    schedule = tag.schedule
    if schedule is None:
        # Bootstrap pass: alongside putting the real function into the design so
        # its operations get measured, prepare the descent candidates the area
        # search will consider.
        if elaborator is not None:
            _PREPARE_CANDIDATES(tag, parser_state, elaborator)
        fn = BUILD_PASSTHROUGH_FUNC(tag)
        # Keep the passthrough estimated during scoped characterization. It
        # makes the tagged function's operations visible to delay measurement.
        forced = getattr(parser_state, "func_force_estimated", None)
        if forced is None:
            forced = set()
            parser_state.func_force_estimated = forced
        forced.add(fn.__name__)
    else:
        # Elaborate the pure function even though the FSM will not instantiate
        # it: code generation reads its Logic graph (which operations exist, how
        # they are wired) and needs the live callables of the units it binds.
        # On this pass nothing else would elaborate it -- the passthrough that
        # did so on the bootstrap pass is gone.
        if elaborator is not None:
            elaborator._elaborate_live_func(
                getattr(tag.func, "__name__", "auto_fsm_func"), tag.func
            )
            _PREPARE_CANDIDATES(tag, parser_state, elaborator)
        rejected = None
        if not SCHEDULE_CACHE_USABLE(schedule):
            rejected = "malformed or stale schedule data"
        elif (
            schedule["source_identity"]
            != parser_state.pypeline_auto_fsm_source_identities[tag.canonical_key]
        ):
            rejected = "the function's source geometry changed"
        elif schedule["target_context"] != _target_context(parser_state):
            rejected = "the target or delay-model context changed"
        # Pinned unit recipes are verified where they are applied: region
        # enforcement restores each recipe and checks its digest and latency
        # (RESTORE_UNIT_PLACEMENT, CHECK_UNIT_PLACEMENT). Re-characterizing them
        # here would hash untrimmed, mid-elaboration logic.
        if rejected is not None:
            # A stale carried schedule is a cache miss; the driver treats a
            # rejection of a schedule it has just produced as an internal error.
            parser_state.pypeline_auto_fsm_schedule_rejections[tag.canonical_key] = (
                rejected
            )
            tag._schedule = None
            return BUILD_AUTO_FSM_FUNC(tag, parser_state, elaborator)
        name, src, extra_globals = GENERATE_FSM_SOURCE(tag, schedule, parser_state)
        fn = AUTO._exec_generated(name, src, extra_globals)
    import inspect
    import pypeline

    original = inspect.unwrap(tag.func)
    origin = getattr(original, "_pypeline_name_info", None) or pypeline._describe(
        original, "function"
    )
    symbol = "auto_fsm_" + origin.symbol + ("_comb" if schedule is None else "")
    info = pypeline._replace_name_info(
        origin,
        symbol=symbol,
        params=origin.params + (("max_latency", str(tag.max_latency)),),
    )
    fn._pypeline_name_info = inspect.unwrap(fn)._pypeline_name_info = info
    fn._pypeline_generated_origin = inspect.unwrap(fn)._pypeline_generated_origin = True
    tag._generated = fn
    return fn


def DUMP_GENERATED_SOURCE(parser_state, out_dir, schedules=None):
    """Write every generated FSM's Python source next to the build output, so a
    problem inside generated code can be read as source instead of inferred from
    VHDL. Best-effort: never fails a build."""
    tags = GET_TAGS(parser_state)
    if not tags or not out_dir:
        return
    try:
        gen_dir = os.path.join(out_dir, "auto_fsm_generated")
        os.makedirs(gen_dir, exist_ok=True)
        for tag in tags.values():
            fn = tag._generated
            src = getattr(fn, "_auto_fsm_generated_src", None)
            if src is None:
                continue
            with open(os.path.join(gen_dir, f"{fn.__name__}.py"), "w") as f:
                f.write(src)
            provenance = parser_state.pypeline_auto_fsm_provenance.get(
                tag.canonical_key
            )
            if provenance is not None:
                with open(
                    os.path.join(gen_dir, f"{fn.__name__}.provenance.json"), "w"
                ) as f:
                    json.dump(provenance, f, indent=2, sort_keys=True)
                    f.write("\n")
            schedule = (schedules or {}).get(tag.canonical_key, tag.schedule)
            if schedule is not None:
                with open(
                    os.path.join(gen_dir, f"{fn.__name__}.schedule.json"), "w"
                ) as f:
                    json.dump(schedule, f, indent=2, sort_keys=True)
                    f.write("\n")
    except OSError:
        pass


# ─────────────────────────────────────────────
# Delay measurement coverage for AUTO_FSM (consumed by SYN's delay collection)
# ─────────────────────────────────────────────

def DEL_AUTO_FSM_SUBTREE_CACHE():
    global _FUNC_SUBTREE_HAS_AUTO_FSM_cache

    _FUNC_SUBTREE_HAS_AUTO_FSM_cache = {}


def AUTO_FSM_MUX_ENTITIES(parser_state):
    # Operand multiplexers inside generated AUTO_FSM state machines.
    #
    # A generated FSM holds state, so it is one measured atomic span and
    # nothing inside it is collected. Its muxes are independent scheduler
    # consumers whose real delay is
    # the single most load-bearing input to AUTO_FSM's decision about HOW FINELY
    # to share -- the thing v1 had to guess at with a flat constant. So these
    # few entities are collected for measurement in their own right. They are
    # small (one 3-to-8-way mux per shared unit input port), so this is a
    # handful of quick runs.
    #
    # They live under include/pypeline/operators/ with the other shipped
    # operator code. Each measurement is an ordinary synthesis run, reused
    # whenever its inputs are identical: from the output directory, or across
    # output directories with --syn_cache (SYN.REUSE_SYNTHESIS_LOG). They stay
    # out of the name-keyed cache/delay, which would not notice an edited
    # library (SYN.LOGIC_PATH_DELAY_IS_CACHEABLE).
    # New shapes can be registered after the first query in the same parse.
    # Resolve the current list instead of caching an incomplete one-time result.
    return AUTO_FSM_MEASURE_ENTITIES(parser_state)


_FUNC_SUBTREE_HAS_AUTO_FSM_cache = {}


def FUNC_SUBTREE_HAS_AUTO_FSM(func_name, parser_state):
    # Does this func (or anything below it) contain an AUTO_FSM-tagged call site?
    # Such funcs need their subtree delays resolved for the same reason
    # AUTO_PIPELINE ones do, though for a different consumer: not the slicer, but
    # AUTO_FSM's scheduler, which decides how many operations fit in one state
    # from the per-operation delays measured/estimated here. Without this, a
    # stateful MAIN containing an AUTO_FSM would otherwise have no delay
    # consumer. COLLECT_PATH_DELAY_REQUIREMENTS explicitly includes its
    # operation roots and registered operand muxes.
    #
    # On the bootstrap pass the call site points at a combinational passthrough.
    # Once scheduled, the tag remains on the caller and points at the generated
    # stateful FSM: one whole-module synthesis whose register-to-register path
    # is its worst state's delay. Nothing inside it is collected, so
    # rescheduling keeps the operation delays carried from the bootstrap pass.
    if func_name in _FUNC_SUBTREE_HAS_AUTO_FSM_cache:
        return _FUNC_SUBTREE_HAS_AUTO_FSM_cache[func_name]
    logic = parser_state.FuncLogicLookupTable[func_name]
    rv = len(logic.sub_inst_to_auto_fsm_key) > 0
    if not rv:
        for sub_func_name in logic.submodule_instances.values():
            if sub_func_name in parser_state.FuncLogicLookupTable:
                if FUNC_SUBTREE_HAS_AUTO_FSM(sub_func_name, parser_state):
                    rv = True
                    break
    _FUNC_SUBTREE_HAS_AUTO_FSM_cache[func_name] = rv
    return rv
