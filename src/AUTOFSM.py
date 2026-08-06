"""AUTOFSM: implement a pure combinational function as a resource-shared FSM.

This is the resource-minimizing dual of AUTOPIPELINE. Where AUTOPIPELINE cuts
one full copy of a function's hardware into N pipeline stages (initiation
interval 1, maximum throughput, maximum area), AUTOFSM keeps ONE copy of each
distinct operation and executes the function over N clock cycles (initiation
interval N, minimum area). Twelve identical adders become one adder used in
twelve different states.

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
                   is shared anywhere in the compiler by default -- AUTOFSM
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

  pypeline.AUTOFSM            the user-facing tag object (src/pypeline.py).
                              Holds .latency and the installed schedule.
  PY_TO_LOGIC._elab_call      probes for the tag at a call site and asks
                              BUILD_AUTOFSM_FUNC (below) what to instantiate.
  THIS MODULE                 builds the DAG from the elaborated Logic graph,
                              schedules + binds it, and GENERATES ORDINARY
                              PYPELINE PYTHON SOURCE implementing the FSM.
  src/pipelinec               drives the schedule-and-confirm loop: measure
                              delays -> schedule -> re-elaborate -> synthesize
                              -> if an FSM is blamed for a timing failure,
                              tighten its budget and reschedule.

Generating Python source (rather than a new backend IR) is what keeps this
feature small: the generated FSM is elaborated by the same path as hand-written
pypeline, and because it holds non-volatile Reg state, SYN and SWEEP already
treat it correctly -- unsliceable, zero added latency, measured as one atomic
block whose delay becomes an fmax floor.

See docs/AUTOFSM_DESIGN.md for the full design, and docs/SYN_DESIGN.md for the
delay model and the sweep this rides on.
"""

import hashlib
import json
import os

import C_TO_LOGIC

# Schedule dict format version, bumped if the shape changes incompatibly.
SCHEDULE_VERSION = 2

# Maximum schedule+synthesize passes before giving up on meeting timing by
# adding states (mirrors SYN.AUTOPIPELINE_MAX_LATENCY_PASSES). Six rather than
# four because a pass may now also be spent absorbing freshly MEASURED operand
# mux delays (see the mux section below): the first build of a given mux shape
# schedules against the model, and the pass after it knows the real number.
MAX_SCHEDULE_PASSES = 6

# Fraction of the target clock period a state's operation chain may fill by the
# delay model's own reckoning. Below 1.0 because the model does not account for
# the operand multiplexers and writeback enables the FSM itself adds around
# every functional unit. Overridable per build with --autofsm_budget_scale.
DEFAULT_BUDGET_SCALE = 0.9

# Multiplied into budget_scale for every AUTOFSM blamed for a timing failure,
# shrinking the per-state budget so the next schedule uses more, smaller states.
BUDGET_TIGHTEN_FACTOR = 0.75

# How many times the driver may apply BUDGET_TIGHTEN_FACTOR looking for a budget
# that actually changes the schedule, before concluding more states cannot help.
MAX_TIGHTEN_STEPS = 8

# Last-resort delay charged per scheduled operation when nothing better is
# known about its operand multiplexer -- notably before any fold count exists
# at all. In delay units, so 10 == 1.0 ns. v1 charged this flat for every
# operation; v2 uses the real per-shape numbers below and keeps this only as
# the floor/seed.
MUX_PENALTY_DU = 10

# Operand-mux delay MODEL, used only until a real measurement of that mux shape
# exists (see _mux_delay_du). An n-way mux built as an array read is a balanced
# binary selection tree, so its delay grows with log2(n), not n -- which is the
# whole reason AUTOFSM builds them that way (see
# include/pypeline/operators/autofsm_mux.py). Delay units.
MUX_BASE_DU = 2
MUX_PER_LEVEL_DU = 4

# Cap on generated entity/function name length, for VHDL identifier safety.
_MAX_NAME_LEN = 96

# ── Area model ────────────────────────────────────────────────────────────
# Abstract units, per bit of operand width unless noted, normalised so that one
# bit of an adder is 1.0.
#
# These exist because AREA CANNOT BE READ BACK FROM THE USER'S TOOL: only
# timing/fmax is parsed uniformly from every supported backend (Vivado,
# Quartus, PYRTL, ...), so an area-minimizing search cannot be closed around a
# real utilization number the way the fmax loop is closed around a real timing
# report. The model therefore only ever RANKS candidate schedules against each
# other, and the search always keeps the plain share-everything schedule as its
# anchor -- so a mis-ranking costs an opportunity, never a regression.
#
# CALIBRATION. The ratios come from real yosys cell counts, which is the one
# place in this project real area numbers exist (they are used in the test
# suite, never in the search itself -- see
# src/tests/pypeline_tests/inst/autofsm_area_sweep_compare_test.py):
#
#     16-bit add   ~100 cells    -> 6.25 cells per bit   -> 1.00 here
#     32-bit add   ~200 cells    -> 6.25 cells per bit
#     16x16 fabric multiply ~1800 cells -> ~7 cells per partial product
#     one DFF, one 2-input gate, one 2:1 mux bit: ~1 cell each -> ~0.16 here
#
# The single most important ratio is ARITHMETIC vs MULTIPLEXER-AND-REGISTER,
# because that is the entire sharing trade. An early cut of this model priced a
# 16-bit adder at the same cost as a 16-bit register and duly decided that
# unsharing cheap adders was a win; real synthesis said it was 4.5% worse. An
# adder bit is about six of the things sharing costs, not one.
AREA_PER_BIT_ADD = 1.0  # ripple add/sub: a full adder per bit
AREA_PER_BIT_CMP = 1.0  # compare == subtract + sign bit
AREA_PER_BIT_BITWISE = 0.16  # one 2-input gate per bit
AREA_PER_BIT_MUX = 0.16  # one 2:1 mux per bit
AREA_PER_BIT_SHIFT_VAR = 0.7  # barrel shifter ~ log2(W) layers of muxes
# Array multiplier, per PARTIAL PRODUCT (Wl*Wr of them). Slightly above the
# per-bit adder cost, which is what yosys actually reports: a 16x16 fabric
# multiply lands around 1800 cells against a 32-bit add's ~200, i.e. ~1.1x an
# adder bit per partial product. The first cut of this model used 0.5 and
# under-priced multipliers by better than 2x -- which matters, because
# under-pricing the unit is exactly what makes sharing it look not worth doing.
AREA_PER_BIT_PAIR_MULT = 1.1
AREA_PER_BIT_PAIR_DIV = 2.5  # restoring divider: worse than a multiplier
AREA_PER_BIT_DEFAULT = 1.0  # unknown leaf: priced like an adder
# One flip-flop. Deliberately a little above the ~0.16 a yosys cell count
# implies: on an FPGA a flip-flop comes paired with the LUT in front of it and
# is nearly free, but registers are also what the FSM's own control has to
# route and enable, and a schedule holding dozens of live values is genuinely
# harder than one holding three.
AREA_PER_BIT_FF = 0.2
AREA_PER_STATE_DECODE = 1.0  # per-state next-state/enable decode

# ── Area sweep ────────────────────────────────────────────────────────────
# How many "open one more entity" moves the search may accept before stopping.
# Each move costs one full reschedule per remaining candidate entity, so this
# bounds the search at O(MAX_SWEEP_MOVES * n_entities) schedules -- all pure
# computation, no synthesis.
MAX_SWEEP_MOVES = 24

# A move must beat the BEST-SO-FAR by at least this fraction of its estimated
# area to become the new best. Without it the search would chase model noise,
# churning the schedule (and therefore the generated entity name) for no real
# gain.
SWEEP_MIN_IMPROVEMENT = 0.01

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

# How many times the scheduler may add a functional unit to try to fit a hard
# max_latency cap before declaring the cap infeasible.
MAX_REPLICATION_STEPS = 8


class AutofsmError(Exception):
    """A design-level AUTOFSM problem (unschedulable function, unsupported
    construct). Always raised with a message naming the offending
    function/operation: failing loudly is required here, because the
    alternative is generating an FSM that quietly computes something other than
    the pure function it replaces."""


# ─────────────────────────────────────────────
# Tag discovery
# ─────────────────────────────────────────────


def DESIGN_HAS_AUTOFSM(parser_state) -> bool:
    """True if any elaborated function instantiates an AUTOFSM call site."""
    for logic in parser_state.FuncLogicLookupTable.values():
        if logic.sub_inst_to_autofsm_key:
            return True
    return False


def COLLECT_AUTOFSM_KEYS(parser_state):
    """Set of AUTOFSM canonical keys instantiated anywhere in the design."""
    keys = set()
    for logic in parser_state.FuncLogicLookupTable.values():
        keys.update(logic.sub_inst_to_autofsm_key.values())
    return keys


def GET_TAGS(parser_state) -> dict:
    """canonical_key -> live pypeline.AUTOFSM tag object, recorded by
    BUILD_AUTOFSM_FUNC as call sites elaborate."""
    return getattr(parser_state, "pypeline_autofsm_tags", {})


def _entity_callables(parser_state):
    return getattr(parser_state, "pypeline_entity_callables", {})


def _entity_key_for_callable(parser_state, func):
    """Reverse-lookup the FuncLogicLookupTable key a live callable was
    elaborated under, using the pypeline_entity_callables side table PY_TO_LOGIC
    populates. Identity-based, and deliberately a lookup rather than a
    re-derivation: the elaborator's canonical-naming rules are intricate, and a
    second implementation of them here would be one more thing to keep in sync.
    """
    for key, recorded in _entity_callables(parser_state).items():
        if recorded is func:
            return key
    return None


# ─────────────────────────────────────────────
# Type resolution: ctype string -> live pypeline type object
# ─────────────────────────────────────────────


class _TypeResolver:
    """Maps the compiler's C type name strings (all a Logic graph carries) back
    to live pypeline type objects, which generated source needs for its
    variable annotations.

    Scalars are reconstructible from the name alone; struct/array types are not,
    so they are seeded from the live objects actually in play: the AUTOFSM'd
    function's own input/output types and every unit callable's annotations.
    Any type reaching generated source came from one of those, so an
    unresolvable name is a genuine gap -- raise rather than guess.
    """

    def __init__(self):
        import pypeline

        self._pypeline = pypeline
        self._by_name = {}

    def seed(self, t):
        if t is None:
            return
        try:
            name = self._pypeline.ctype_name(t)
        except Exception:
            return
        if name in self._by_name:
            return
        self._by_name[name] = t
        # Seed struct fields and array elements too: an operand may be a field
        # of a seeded struct without that field type ever appearing standalone.
        fields = getattr(t, "_fields", None)
        if fields:
            anns = getattr(t, "__annotations__", {})
            for f in fields:
                self.seed(anns.get(f))
        elem = self._pypeline._array_elem_ctype(t)
        if elem is not None:
            self.seed(elem)

    def seed_callable(self, func):
        from pypeline import hw_arg_types, hw_return_type

        try:
            for t in hw_arg_types(func):
                self.seed(t)
            self.seed(hw_return_type(func))
        except Exception:
            pass

    def resolve(self, ctype_str: str):
        t = self._by_name.get(ctype_str)
        if t is not None:
            return t
        scalar = _scalar_ctype_to_type(ctype_str)
        if scalar is not None:
            self._by_name[ctype_str] = scalar
            return scalar
        raise AutofsmError(
            f"AUTOFSM: cannot reconstruct a live Python type for C type "
            f"{ctype_str!r} needed by the generated FSM. Only scalar integer "
            f"types, and types reachable from the AUTOFSM'd function's own "
            f"signature or a shared unit's signature, can be regenerated."
        )


# ─────────────────────────────────────────────
# Operand multiplexers: the price of sharing
# ─────────────────────────────────────────────


def _mux_callable(t, n):
    """The memoized hw_func implementing an n-way mux over type `t`, or None if
    this type cannot be arrayed (in which case the caller falls back to an
    inline if/elif chain).

    Lives in include/pypeline/operators/autofsm_mux.py rather than being
    generated here so that it is (a) one stable canonical entity per (type, n),
    (b) shipped-library rather than user code, and therefore delay-cacheable on
    disk, and (c) THE SAME OBJECT the scheduler measured and the code generator
    instantiates. See that module's docstring."""
    if n < 2:
        return None
    try:
        from operators.autofsm_mux import make_operand_mux

        return make_operand_mux(t, n)
    except Exception:
        # An unarrayable port type (or an operators package that is not on the
        # path) is not a build failure: sharing still works, it just falls back
        # to the older inline multiplexer.
        return None


def _mux_sel_type(n):
    """Live type of an n-way mux's select input."""
    from operators.autofsm_mux import mux_sel_t

    return mux_sel_t(n)


def _mux_entity(parser_state, t, n):
    """FuncLogicLookupTable key the n-way mux over `t` was elaborated under, or
    None if it has not been elaborated in this pass. Identity-based reverse
    lookup, which works precisely because make_operand_mux is memoized."""
    fn = _mux_callable(t, n)
    if fn is None:
        return None
    return _entity_key_for_callable(parser_state, fn)


def _mux_delay_du(parser_state, types, ctype, n, snapshot):
    """Delay of the operand mux feeding one shared-unit port, in delay units.

    Preference order, and the reason for it:
      1. MEASURED this pass -- the mux is a real entity instantiated inside the
         generated FSM, and SYN measures it like any other combinational leaf
         (see RECURSIVE_GET_FUNCS_FOR_PATH_DELAYS' autofsm_measure_entities
         hook). This is the number the user asked for: measured, not modelled.
      2. Measured on an earlier pass, carried in the previous schedule's
         snapshot -- later passes rebuild the design with the FSM in place, so
         a shape that is no longer instantiated is no longer measured.
      3. The model. Only reached on the very first build of a given mux shape;
         from the next pass (and, via path_delay_cache, from the next BUILD)
         onwards the real number is available.
    """
    if n < 2:
        return 0
    key = f"{ctype}#{n}"
    cached = (snapshot or {}).get(key)
    try:
        t = types.resolve(ctype)
    except AutofsmError:
        t = None
    if t is not None:
        entity = _mux_entity(parser_state, t, n)
        if entity is not None:
            logic = parser_state.FuncLogicLookupTable.get(entity)
            if logic is not None and logic.delay is not None:
                return max(1, int(logic.delay))
    if cached is not None:
        return cached
    levels = max(1, (n - 1).bit_length())
    return MUX_BASE_DU + MUX_PER_LEVEL_DU * levels


def _ctype_width(ctype_str) -> int:
    """Bit width of a C type name, for the delay/area models. Compound types
    are summed through their scalar leaves; anything unrecognisable is priced
    as one bit rather than crashing a model that only ever ranks."""
    import re

    if not ctype_str:
        return 1
    m = re.fullmatch(r"u?int(\d+)_t", ctype_str)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"(.+)\[(\d+)\]", ctype_str)
    if m:
        return _ctype_width(m.group(1)) * int(m.group(2))
    if ctype_str in ("float", "double"):
        return 32 if ctype_str == "float" else 64
    return _STRUCT_WIDTHS.get(ctype_str, 1)


_STRUCT_WIDTHS = {}


def _seed_struct_widths(parser_state):
    """Record every struct type's total width, so the models can price a
    struct-typed operand or register properly instead of calling it one bit."""
    fields_of = getattr(parser_state, "struct_to_field_type_dict", {})
    # Two passes: nested structs whose own width is not known yet on the first
    # visit resolve on the second. Deeper nesting just falls back to the
    # one-bit default, which only ever costs ranking accuracy.
    for _ in range(2):
        for name, fields in fields_of.items():
            width = sum(_ctype_width(ft) for ft in fields.values())
            _STRUCT_WIDTHS[name] = max(1, width)


def _scalar_ctype_to_type(ctype_str: str):
    """uint13_t / int9_t -> the live pypeline type; None if not a scalar int."""
    import re

    from pypeline import make_int_t, make_uint_t

    m = re.fullmatch(r"(u?)int(\d+)_t", ctype_str)
    if not m:
        return None
    width = int(m.group(2))
    return make_uint_t(width) if m.group(1) == "u" else make_int_t(width)


# ─────────────────────────────────────────────
# Decoding elaborated operations back into Python expressions
# ─────────────────────────────────────────────

# Entity-name operator token -> Python binary operator source text.
_BIN_OP_SRC = {
    C_TO_LOGIC.BIN_OP_PLUS_NAME: "+",
    C_TO_LOGIC.BIN_OP_MINUS_NAME: "-",
    C_TO_LOGIC.BIN_OP_INFERRED_MULT_NAME: "*",
    C_TO_LOGIC.BIN_OP_MULT_NAME: "*",
    C_TO_LOGIC.BIN_OP_DIV_NAME: "/",
    C_TO_LOGIC.BIN_OP_MOD_NAME: "%",
    C_TO_LOGIC.BIN_OP_AND_NAME: "&",
    C_TO_LOGIC.BIN_OP_OR_NAME: "|",
    C_TO_LOGIC.BIN_OP_XOR_NAME: "^",
    C_TO_LOGIC.BIN_OP_GT_NAME: ">",
    C_TO_LOGIC.BIN_OP_GTE_NAME: ">=",
    C_TO_LOGIC.BIN_OP_LT_NAME: "<",
    C_TO_LOGIC.BIN_OP_LTE_NAME: "<=",
    C_TO_LOGIC.BIN_OP_EQ_NAME: "==",
    C_TO_LOGIC.BIN_OP_NEQ_NAME: "!=",
}
_UNARY_OP_SRC = {
    C_TO_LOGIC.UNARY_OP_NOT_NAME: "~",
    C_TO_LOGIC.UNARY_OP_NEGATE_NAME: "-",
}


def DECODE_OP(logic, inst, entity, parser_state):
    """Work out which Python construct produced one elaborated operation, so
    generated source can re-create it.

    The FSM's operand multiplexers change WHICH values reach an operation, never
    what the operation is -- so re-emitting the original construct with locals
    declared at the original port types reproduces the identical entity, and
    therefore the identical hardware and the identical cached delay.

    Returns a dict {"kind", ...} understood by _render_op. Note the deliberate
    absence of a catch-all: an operation this cannot decode raises, rather than
    risking an FSM that computes something subtly different.
    """
    # Compound reference operations. The same builtin covers two very different
    # things, told apart by how many input ports the instance has:
    #   one port   -> a READ of part of a value:  x.field, x[3]
    #   many ports -> ASSEMBLY of a compound value from its parts, which is what
    #                 `return my_struct_t(a=..., b=...)` elaborates to. Each
    #                 port carries one piece, and the per-port ref tokens say
    #                 where that piece belongs.
    if entity.startswith(C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX):
        out_toks = logic.ref_submodule_instance_to_ref_toks.get(inst)
        if not out_toks:
            raise AutofsmError(
                f"AUTOFSM: reference operation {inst!r} has no recorded ref tokens"
            )
        port_toks = (
            logic.ref_submodule_instance_to_input_port_driven_ref_toks.get(inst) or []
        )
        n_ports = len(logic.submodule_instance_to_input_port_names.get(inst, []))
        if n_ports <= 1 and len(out_toks) > 1:
            # out_toks[0] is the base variable; the rest is the path read from it.
            return {"kind": "ref", "toks": list(out_toks[1:])}
        if len(port_toks) != n_ports:
            raise AutofsmError(
                f"AUTOFSM: compound assembly {inst!r} has {n_ports} inputs but "
                f"{len(port_toks)} recorded destination paths"
            )
        # Each port's path, relative to the value being assembled.
        paths = [list(pt[len(out_toks) :]) for pt in port_toks]
        if n_ports == 1 and not paths[0]:
            return {"kind": "copy"}
        return {"kind": "assemble", "paths": paths}

    # Constant-amount shift: x << 3 / x >> 3, entity CONST_SL_3_int16_t
    for op_name, py_op in (
        (C_TO_LOGIC.BIN_OP_SL_NAME, "<<"),
        (C_TO_LOGIC.BIN_OP_SR_NAME, ">>"),
    ):
        prefix = f"{C_TO_LOGIC.CONST_PREFIX}{op_name}_"
        if entity.startswith(prefix):
            amount = entity[len(prefix) :].split("_")[0]
            if amount.isdigit():
                return {"kind": "shift", "op": py_op, "amount": int(amount)}

    # Multiplexer from an if / conditional expression: ports (cond, iftrue, iffalse)
    if entity.startswith(C_TO_LOGIC.MUX_LOGIC_NAME + "_"):
        return {"kind": "mux"}

    # Binary operator: BIN_OP_<OP>_<ltype>_<rtype>
    bin_prefix = C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_"
    if entity.startswith(bin_prefix):
        rest = entity[len(bin_prefix) :]
        # Longest match first so e.g. INFERRED_MULT is not read as a shorter op.
        for op_name in sorted(_BIN_OP_SRC, key=len, reverse=True):
            if rest.startswith(op_name + "_"):
                return {"kind": "binop", "op": _BIN_OP_SRC[op_name]}

    # Unary operator: UNARY_OP_<OP>_<type>
    un_prefix = C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX + "_"
    if entity.startswith(un_prefix):
        rest = entity[len(un_prefix) :]
        for op_name in sorted(_UNARY_OP_SRC, key=len, reverse=True):
            if rest.startswith(op_name + "_"):
                return {"kind": "unaryop", "op": _UNARY_OP_SRC[op_name]}

    # A bit-manipulation primitive: bit_assign / bit_dup / rotl / concat / ...
    # Re-emitted as a call to the pypeline builtin of the same name, with the
    # constant arguments the elaborator baked into the entity name appended
    # back on. Soft adders are built almost entirely out of bit_assign, so
    # without this, descending into one would not be regenerable at all.
    bm = getattr(parser_state, "pypeline_bit_manip_info", {}).get(entity)
    if bm is not None:
        return {"kind": "bitmanip", "builtin": bm[0], "consts": list(bm[1])}

    # Anything else must be an ordinary function whose live callable we kept.
    if _entity_callables(parser_state).get(entity) is not None:
        return {"kind": "call"}

    raise AutofsmError(
        f"AUTOFSM: operation {inst!r} (entity {entity!r}) cannot be regenerated "
        f"as Python source, so this function cannot be turned into an FSM. "
        f"Supported: arithmetic/comparison/bitwise operators, constant shifts, "
        f"struct-field and constant-index reads, if/conditional muxes, and "
        f"calls to @hw_func functions."
    )


def _path_suffix(toks):
    """Render a field/index path: numeric tokens are constant array indices,
    names are struct fields."""
    out = ""
    for tok in toks:
        out += f"[{tok}]" if str(tok).isdigit() else f".{tok}"
    return out


def _render_op(op, operand_exprs, em, parser_state, entity):
    """Render one decoded operation as a Python expression string."""
    kind = op["kind"]
    if kind == "ref":
        return operand_exprs[0] + _path_suffix(op["toks"])
    if kind == "copy":
        return operand_exprs[0]
    if kind == "assemble":
        raise AutofsmError(
            "AUTOFSM: compound assembly needs statements, not an expression "
            "(internal error -- it should have been rendered as glue)"
        )
    if kind == "shift":
        return f"({operand_exprs[0]} {op['op']} {op['amount']})"
    if kind == "mux":
        cond, iftrue, iffalse = operand_exprs
        return f"({iftrue} if {cond} else {iffalse})"
    if kind == "binop":
        return f"({operand_exprs[0]} {op['op']} {operand_exprs[1]})"
    if kind == "unaryop":
        return f"({op['op']}{operand_exprs[0]})"
    if kind == "bitmanip":
        import pypeline

        if op["builtin"] == "__slice__":
            # A bit read/slice is Python subscript syntax, not a function call.
            high, low = op["consts"]
            idx = f"{high}" if high == low else f"{high}:{low}"
            return f"({operand_exprs[0]})[{idx}]"
        fn = getattr(pypeline, op["builtin"], None)
        if fn is None:
            raise AutofsmError(
                f"AUTOFSM: no pypeline builtin named {op['builtin']!r} to "
                f"re-emit entity {entity!r}"
            )
        args = list(operand_exprs) + [repr(c) for c in op["consts"]]
        return f"{em.inj(fn, 'bm')}({', '.join(args)})"
    if kind == "call":
        func = _entity_callables(parser_state).get(entity)
        if func is None:
            raise AutofsmError(
                f"AUTOFSM: entity {entity!r} has no live Python callable "
                f"recorded, so it cannot be emitted."
            )
        return f"{em.inj(func, 'f')}({', '.join(operand_exprs)})"
    raise AutofsmError(f"AUTOFSM: unsupported operation kind {kind!r}")


# ─────────────────────────────────────────────
# DAG construction
# ─────────────────────────────────────────────


def _trace_operand(logic, port_wire):
    """Follow a consumer port back through the wire graph to whatever actually
    produces its value.

    Returns (ref, cast_types) where ref is a ValueRef:
        ["node", inst]      another operation's result
        ["in", name]        one of this function's inputs, by port name
        ["const", text]     a literal
    and cast_types is the list of intermediate wire types between the producer
    and this port. Those matter because assigning a wire narrows to the
    destination's width: a value that passed through a narrower intermediate
    variable in the original code must pass through the same narrowing here, or
    the FSM would compute something the pure function does not.
    """
    wire = port_wire
    port_type = logic.wire_to_c_type.get(wire)
    chain = []
    seen = set()
    while True:
        driver = logic.wire_driven_by.get(wire)
        if driver is None:
            # An undriven wire is a real elaboration hole, not something to
            # paper over with a default value.
            raise AutofsmError(
                f"AUTOFSM: wire {wire!r} in {logic.func_name!r} has no driver "
                f"(tracing back from {port_wire!r})"
            )
        if driver in seen:
            raise AutofsmError(
                f"AUTOFSM: combinational loop reaching {port_wire!r} in "
                f"{logic.func_name!r}"
            )
        seen.add(driver)
        if C_TO_LOGIC.SUBMODULE_MARKER in driver:
            inst = driver.rsplit(C_TO_LOGIC.SUBMODULE_MARKER, 1)[0]
            return ["node", inst], _clean_cast_chain(chain, port_type)
        if C_TO_LOGIC.WIRE_IS_CONSTANT(driver):
            return ["const", driver], _clean_cast_chain(chain, port_type)
        if driver in logic.inputs:
            # Named, not positional: a descended function may have several
            # inputs (a float multiplier takes two), and the name is what maps
            # its body's reads back onto the call's operands.
            return ["in", driver], _clean_cast_chain(chain, port_type)
        chain.append(logic.wire_to_c_type.get(driver))
        wire = driver


def _clean_cast_chain(chain, port_type):
    """Reduce a traced wire-type chain to the casts that actually change the
    value. `chain` is collected port-first, so reverse it to producer-first,
    then drop consecutive duplicates and anything equal to the port type (the
    operand local is declared at the port type and performs that cast itself)."""
    out = []
    for t in reversed(chain):
        if t is None or t == port_type:
            continue
        if out and out[-1] == t:
            continue
        out.append(t)
    return out


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


_DELAY_MEMO_ATTR = "_autofsm_delay_memo"


def _resolve_delay_du(parser_state, entity, delays, _stack=None):
    """Delay of one operation, in delay units, however little is known about it.

    In order:
      1. what this pass measured, or the previous schedule's snapshot -- the
         normal case for anything the design actually instantiates;
      2. the Logic's own measured delay;
      3. the on-disk path delay cache -- which is how a DESCENT CANDIDATE gets
         a real number. A soft-operator equivalent is never instantiated, so it
         is never measured; but its leaves are the universal bitwise operators
         every design uses, so their measurements are almost always already
         sitting in path_delay_cache;
      4. bottom-up from its own submodules;
      5. a width heuristic, as the last resort.

    Steps 3-5 exist entirely for candidates. Getting them wrong costs ranking
    accuracy in the area search; getting them ABSENT (v1's behavior: no Logic
    means delay 0) would be worse than wrong, because a zero-delay operation is
    treated as free wiring and never shared at all.
    """
    known = delays.get(entity)
    if known is not None:
        return known
    logic = parser_state.FuncLogicLookupTable.get(entity)
    if logic is None:
        return 0
    if logic.delay is not None:
        return logic.delay

    memo = getattr(parser_state, _DELAY_MEMO_ATTR, None)
    if memo is None:
        memo = {}
        setattr(parser_state, _DELAY_MEMO_ATTR, memo)
    hit = memo.get(entity)
    if hit is not None:
        return hit
    _stack = set() if _stack is None else _stack
    if entity in _stack:
        return 0
    _stack.add(entity)

    du = None
    try:
        import SYN

        cached_ns = SYN.GET_CACHED_PATH_DELAY(logic, parser_state)
        if cached_ns is not None:
            du = max(0, int(cached_ns * SYN.DELAY_UNIT_MULT))
    except Exception:
        du = None
    if du is None and logic.submodule_instances:
        du = sum(
            _resolve_delay_du(parser_state, sub, delays, _stack)
            for sub in set(logic.submodule_instances.values())
        )
    if du is None:
        du = _heuristic_leaf_delay_du(entity, logic)
    _stack.discard(entity)
    memo[entity] = du
    return du


def _heuristic_leaf_delay_du(entity, logic):
    """Rough delay for a leaf operation nothing has ever measured. Only ever
    reached for a descent candidate on a machine with a cold path_delay_cache;
    one real build replaces it with a measurement."""
    from math import log2

    if _leaf_area(entity, logic) <= 0.0:
        return 0  # genuine wiring: field reads, constant shifts, bit assigns
    widths = [_ctype_width(logic.wire_to_c_type.get(p)) for p in logic.inputs] or [1]
    w = max(widths)
    if entity.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_"):
        rest = entity[len(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX) + 1 :]
        if rest.startswith(
            (
                C_TO_LOGIC.BIN_OP_AND_NAME + "_",
                C_TO_LOGIC.BIN_OP_OR_NAME + "_",
                C_TO_LOGIC.BIN_OP_XOR_NAME + "_",
            )
        ):
            return 1  # one gate, regardless of width (bit-parallel)
        if rest.startswith(
            (
                C_TO_LOGIC.BIN_OP_MULT_NAME + "_",
                C_TO_LOGIC.BIN_OP_INFERRED_MULT_NAME + "_",
            )
        ):
            return max(2, int(4 * log2(max(2, w))))
    # Carry-chain-ish: logarithmic in width, which is what a synthesizer builds.
    return max(1, int(2 * log2(max(2, w))))


def _is_decomposable(parser_state, entity, logic):
    """Can this operation be opened up into smaller operations to fit a state?

    Only if it came from Python source we can re-express: a live callable was
    recorded for it during elaboration. A built-in operator entity (BIN_OP_*,
    MUX_*, a constant shift) is atomic no matter how slow it is -- its innards
    are the C/VHDL support library, not Python, so there is nothing to
    regenerate. Trying anyway is how you end up staring at an error about some
    internal bit-slice helper.
    """
    return (
        logic is not None
        and len(logic.submodule_instances) > 0
        and logic.vhdl_module_text is None
        and _entity_callables(parser_state).get(entity) is not None
    )


def _soft_equivalents(parser_state):
    """built-in op entity -> equivalent Python-sourced entity, as prepared by
    PREPARE_SOFT_EQUIVALENTS during the bootstrap elaboration."""
    return getattr(parser_state, "pypeline_autofsm_soft_equiv", {})


# Which soft-operator factory implements each built-in operator. One fixed
# flavor per op: the library ships several (ripple vs carry-select adders,
# shift-add vs Karatsuba multipliers, subtract vs bitwise comparators) and
# choosing between them is a second search axis, deliberately not opened here.
# The flavors picked are the ones whose structure decomposes most evenly, which
# is what makes them useful as SHARING candidates rather than as fast hardware.
_SOFT_FACTORY_FOR_OP = {
    "PLUS": ("operators.soft_add", "make_soft_ripple_add", None),
    "MINUS": ("operators.soft_add", "make_soft_sub", None),
    "INFERRED_MULT": ("operators.soft_mult", "make_soft_shift_add_mult", None),
    "MULT": ("operators.soft_mult", "make_soft_shift_add_mult", None),
    "GT": ("operators.soft_cmp", "make_soft_sub_cmp_swapped", "GT"),
    "GTE": ("operators.soft_cmp", "make_soft_sub_cmp_swapped", "GTE"),
    "LT": ("operators.soft_cmp", "make_soft_sub_cmp_swapped", "LT"),
    "LTE": ("operators.soft_cmp", "make_soft_sub_cmp_swapped", "LTE"),
    "EQ": ("operators.soft_misc", "make_soft_eq", False),
    "NEQ": ("operators.soft_misc", "make_soft_eq", True),
}

# Ceiling on how many distinct built-in operator shapes get a soft equivalent
# elaborated. Bounded by the number of DISTINCT (op, operand types) triples in
# a function -- normally a handful, however many thousand operations use them
# -- so this only ever trips on something pathological.
_MAX_SOFT_EQUIVALENTS = 64


def _soft_equivalent_callable(parser_state, entity):
    """A live, decomposable hw_func computing exactly what a built-in operator
    entity computes -- or None.

    This is the ONLY place AUTOFSM knows the soft-operator library exists. When
    the library is not importable everything below simply degrades to v1's
    behavior: built-in operators stay atomic and descent bottoms out at them.
    """
    info = getattr(parser_state, "pypeline_builtin_op_info", {}).get(entity)
    if info is None:
        return None
    op_name, operand_ctypes = info
    spec = _SOFT_FACTORY_FOR_OP.get(op_name)
    if spec is None or len(operand_ctypes) != 2:
        return None
    module_name, factory_name, arg = spec
    types = [_scalar_ctype_to_type(ct) for ct in operand_ctypes]
    if any(t is None for t in types):
        return None  # non-integer operands: no soft equivalent exists
    try:
        import importlib

        factory = getattr(importlib.import_module(module_name), factory_name)
        if arg is not None:
            factory = factory(arg)
        return factory(types[0], types[1])
    except Exception:
        return None


def PREPARE_SOFT_EQUIVALENTS(tag, parser_state, elaborator):
    """Elaborate soft-operator equivalents for the built-in operators inside an
    AUTOFSM'd function, so the area search has something to descend INTO.

    Why here: this runs on the bootstrap pass, the one moment where a live
    elaborator, the design's module globals, and the tagged function are all in
    hand at once. The results sit in FuncLogicLookupTable uninstantiated --
    candidates, not hardware -- exactly as the tagged function's own Logic does
    on every later pass. Nothing is built unless the search actually picks it.

    Best-effort throughout: a shape with no soft equivalent, or an operators
    package that is not importable, just means one fewer descent candidate.
    """
    equiv = getattr(parser_state, "pypeline_autofsm_soft_equiv", None)
    if equiv is None:
        equiv = {}
        parser_state.pypeline_autofsm_soft_equiv = equiv
    try:
        func_logic = elaborator._elaborate_live_func(
            getattr(tag.func, "__name__", "autofsm_func"), tag.func
        )
    except Exception:
        return
    builtin_ops = getattr(parser_state, "pypeline_builtin_op_info", {})
    if not builtin_ops:
        return

    seen = set()
    todo = [func_logic.func_name]
    candidates = []
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        # Checked BEFORE the table lookup: at bootstrap-elaboration time a
        # built-in operator is still only a submodule REFERENCE -- its Logic is
        # filled in later by the compiler's built-in resolution -- so requiring
        # a Logic here would find no candidates at all.
        if name in builtin_ops:
            candidates.append(name)
            continue
        logic = parser_state.FuncLogicLookupTable.get(name)
        if logic is None:
            continue
        todo.extend(logic.submodule_instances.values())

    for entity in sorted(candidates)[:_MAX_SOFT_EQUIVALENTS]:
        if entity in equiv:
            continue
        fn = _soft_equivalent_callable(parser_state, entity)
        if fn is None:
            continue
        try:
            soft_logic = elaborator._elaborate_live_func(fn.__name__, fn)
        except Exception:
            continue
        # Whether this really is an equivalent is checked in _open_target, once
        # the built-in's own Logic exists to compare against.
        equiv[entity] = soft_logic.func_name
        _RESOLVE_BUILTIN_SUBMODULES(parser_state, soft_logic.func_name)


def _RESOLVE_BUILTIN_SUBMODULES(parser_state, entity, _seen=None):
    """Materialize the Logic of every built-in operator inside a candidate
    subtree.

    The compiler builds built-in operator Logic lazily, while walking the
    INSTANCE tree from the MAINs (_build_inst_lookup). A soft-operator
    equivalent is deliberately not instantiated -- it is a candidate, not
    hardware -- so its bitwise leaves would otherwise have no Logic at all, and
    an operation with no Logic looks to the scheduler like zero delay and to
    the area model like zero cost. Which would make decomposition appear free,
    and the search would happily decompose everything.
    """
    _seen = set() if _seen is None else _seen
    if entity in _seen:
        return
    _seen.add(entity)
    logic = parser_state.FuncLogicLookupTable.get(entity)
    if logic is None:
        return
    for inst, sub_entity in logic.submodule_instances.items():
        if sub_entity not in parser_state.FuncLogicLookupTable:
            try:
                sub_logic = C_TO_LOGIC.BUILD_C_BUILT_IN_SUBMODULE_FUNC_LOGIC(
                    logic, inst, parser_state
                )
            except Exception:
                continue
            parser_state.FuncLogicLookupTable[sub_logic.func_name] = sub_logic
        _RESOLVE_BUILTIN_SUBMODULES(parser_state, sub_entity, _seen)


def _openable(parser_state, entity, logic):
    """Can the area sweep choose to open this operation up?

    Either it has Python source of its own (_is_decomposable), or it is a
    built-in operator for which the soft-operator library provided an
    equivalent -- which is what lets descent continue PAST the built-in
    operators v1 bottomed out at, all the way down to bitwise leaves.
    """
    return _open_target(parser_state, entity, logic)[0] is not None


def _open_target(parser_state, entity, logic):
    """(entity, logic) whose body should be inlined when opening `entity` up:
    itself if it has source, otherwise its soft-operator equivalent.

    The soft equivalent's SIGNATURE is verified here rather than where it was
    prepared, because at preparation time (bootstrap elaboration) the built-in
    operator it replaces is still only a submodule reference with no Logic of
    its own to compare against. An "equivalent" whose result type or arity
    differs is not one, and silently swapping it in would build hardware
    computing something other than the function the user wrote.
    """
    if _is_decomposable(parser_state, entity, logic):
        return entity, logic
    soft = _soft_equivalents(parser_state).get(entity)
    if soft is None:
        return None, None
    soft_logic = parser_state.FuncLogicLookupTable.get(soft)
    if not _is_decomposable(parser_state, soft, soft_logic):
        return None, None
    if logic is not None:
        ret = C_TO_LOGIC.RETURN_WIRE_NAME
        if soft_logic.wire_to_c_type.get(ret) != logic.wire_to_c_type.get(ret):
            return None, None
        ce = C_TO_LOGIC.CLOCK_ENABLE_NAME
        if len([i for i in soft_logic.inputs if i != ce]) != len(
            [i for i in logic.inputs if i != ce]
        ):
            return None, None
    return soft, soft_logic


def BUILD_DAG(parser_state, func_entity, delays, budget_du, opened=()):
    """Flatten the AUTOFSM'd function into a dataflow DAG of operations.

    Walks the elaborated Logic graph. Each submodule instance becomes a node.
    An operation whose own delay already exceeds one state's budget is DESCENDED
    into -- its body's operations are inlined into this DAG -- so that something
    too slow to fit a state can still be split across several. Everything else
    stays atomic, which is what makes it shareable as a unit: two calls to the
    same entity are two nodes bound to one FU.

    Zero-delay operations (field reads, constant shifts, pure rewiring) are
    marked as glue: never scheduled, never shared, just re-rendered inline at
    each point of use, since duplicating free wiring costs nothing.

    `opened` is the set of entities the AREA SWEEP has chosen to open up, on
    top of whatever the budget forces. That is the whole difference between v1
    and v2 granularity: v1 descended only when an operation could not fit a
    state, which is a correctness-driven last resort; the sweep descends when
    doing so is estimated to make the design SMALLER, which is a search. Per
    ENTITY rather than per node, because every use of one entity must stay
    bound to one shared unit for sharing to mean anything.
    """
    nodes = {}
    _build_dag_level(
        parser_state,
        func_entity,
        delays,
        budget_du,
        nodes,
        prefix="",
        depth=0,
        opened=frozenset(opened),
    )
    logic = parser_state.FuncLogicLookupTable[func_entity]
    output_ref, output_casts = _trace_operand(logic, C_TO_LOGIC.RETURN_WIRE_NAME)
    return {
        "nodes": nodes,
        "output": output_ref,
        "output_casts": output_casts,
        "out_type": logic.wire_to_c_type.get(C_TO_LOGIC.RETURN_WIRE_NAME),
    }


_MAX_DESCEND_DEPTH = 8


def _build_dag_level(
    parser_state, entity, delays, budget_du, nodes, prefix, depth, opened=frozenset()
):
    """Add one function's operations to the DAG, descending where needed.

    `prefix` namespaces node ids when inlining a descended function's body, so
    ids stay unique and remain a pure function of the source (op name + source
    coordinates, joined by the same submodule marker the compiler uses for
    instance paths).
    """
    if depth > _MAX_DESCEND_DEPTH:
        raise AutofsmError(
            f"AUTOFSM: gave up descending into {entity!r} after "
            f"{_MAX_DESCEND_DEPTH} levels looking for operations small enough "
            f"to fit one state; the clock goal may simply be unreachable."
        )
    logic = parser_state.FuncLogicLookupTable.get(entity)
    if logic is None:
        raise AutofsmError(f"AUTOFSM: no elaborated Logic for entity {entity!r}")
    if logic.uses_nonvolatile_state_regs or logic.feedback_vars:
        raise AutofsmError(
            f"AUTOFSM: {entity!r} holds Reg/Feedback state. Only a PURE "
            f"combinational function can be turned into an FSM -- move the "
            f"state out into the calling function."
        )
    if logic.read_only_global_wires or logic.write_only_global_wires:
        raise AutofsmError(
            f"AUTOFSM: {entity!r} reads or writes global wires. Only a pure "
            f"function of its argument can be turned into an FSM."
        )

    for inst, sub_entity in logic.submodule_instances.items():
        if C_TO_LOGIC.CLOCK_ENABLE_NAME in inst:
            # Clock-enable plumbing (TRUE_CLOCK_ENABLE_mux / FALSE_...), added
            # to a Logic by the backend when it gates submodules inside an `if`.
            # Not a data operation, and it only appears on passes where that
            # backend step has already run over these Logic objects -- which the
            # driver's later reschedules see, because they reuse the parser
            # state a full build has already been through. Skipping it by name
            # is safe: user operation instance names come from operator names
            # and source coordinates, never from CLOCK_ENABLE.
            continue
        sub_logic = parser_state.FuncLogicLookupTable.get(sub_entity)
        delay_du = _resolve_delay_du(parser_state, sub_entity, delays)
        node_id = prefix + inst
        # CLOCK_ENABLE is a control wire the backend threads through instances
        # that need gating -- it is not a data operand, it appears only on some
        # passes (whichever ones have run the clock-enable connection), and
        # tracing it back would look for a driver that the pure function
        # naturally does not have. Filtered here rather than tolerated in
        # _trace_operand so an operand that genuinely has no driver still
        # fails loudly.
        port_names = [
            p
            for p in logic.submodule_instance_to_input_port_names.get(inst, [])
            if p != C_TO_LOGIC.CLOCK_ENABLE_NAME
        ]
        operands = []
        casts = []
        port_types = []
        for port in port_names:
            port_wire = f"{inst}{C_TO_LOGIC.SUBMODULE_MARKER}{port}"
            ref, cast_chain = _trace_operand(logic, port_wire)
            operands.append(_prefix_ref(ref, prefix, _parent_call_id(prefix)))
            casts.append(cast_chain)
            port_types.append(logic.wire_to_c_type.get(port_wire))

        # Two independent reasons to open this operation up:
        #   forced  -- it is slower than one whole state, so keeping it atomic
        #              would make the clock goal unreachable (v1's only rule);
        #   chosen  -- the area sweep asked for it, because opening it is
        #              estimated to shrink the design (v2).
        too_slow_for_a_state = delay_du + MUX_PENALTY_DU > budget_du
        want_open = too_slow_for_a_state or sub_entity in opened
        open_entity, open_logic = (
            _open_target(parser_state, sub_entity, sub_logic)
            if want_open
            else (None, None)
        )
        if open_entity is not None:
            # Open it up and schedule its innards instead. The node itself does
            # not exist in the DAG; references to it are rewritten to whatever
            # its body produced (see _resolve_inlined). When `sub_entity` is a
            # built-in operator, the body inlined here is its SOFT-OPERATOR
            # EQUIVALENT (open_entity != sub_entity): same function, expressed
            # in Python that can be taken apart further.
            #
            # Descent is an OPTIMIZATION, so a body we cannot regenerate is not
            # fatal: fall back to keeping the operation atomic, which the
            # scheduler will report as a floor. Child nodes are built into a
            # scratch dict so a failed attempt leaves nothing behind.
            child_prefix = node_id + C_TO_LOGIC.SUBMODULE_MARKER
            child_nodes = {}
            try:
                _build_dag_level(
                    parser_state,
                    open_entity,
                    delays,
                    budget_du,
                    child_nodes,
                    child_prefix,
                    depth + 1,
                    opened,
                )
                child_out_ref, child_out_casts = _trace_operand(
                    open_logic, C_TO_LOGIC.RETURN_WIRE_NAME
                )
            except AutofsmError:
                child_nodes = None
            if child_nodes is not None:
                nodes.update(child_nodes)
                nodes[node_id] = {
                    "kind": "inlined",
                    "entity": sub_entity,
                    "delay_du": 0,
                    "operands": operands,
                    "casts": casts,
                    "port_types": port_types,
                    "out_type": sub_logic.wire_to_c_type.get(
                        C_TO_LOGIC.RETURN_WIRE_NAME
                    ),
                    # How to reach the descended body's result, and how the
                    # body's own input maps back onto this call's operands.
                    # The input NAMES are the opened body's own (a soft adder
                    # calls them a/b where the built-in called them left/right);
                    # positional order is what matches them to the operands,
                    # and both orders are the call's argument order.
                    "inlined_out": _prefix_ref(child_out_ref, child_prefix, node_id),
                    "inlined_out_casts": child_out_casts,
                    "inlined_inputs": [
                        i
                        for i in open_logic.inputs
                        if i != C_TO_LOGIC.CLOCK_ENABLE_NAME
                    ],
                }
                continue

        op = DECODE_OP(logic, inst, sub_entity, parser_state)
        nodes[node_id] = {
            "kind": op["kind"],
            "op": op,
            "entity": sub_entity,
            "delay_du": delay_du,
            "operands": operands,
            "casts": casts,
            "port_types": port_types,
            "out_type": logic.wire_to_c_type.get(
                f"{inst}{C_TO_LOGIC.SUBMODULE_MARKER}{C_TO_LOGIC.RETURN_WIRE_NAME}"
            ),
        }


def _parent_call_id(prefix):
    """The descended call whose body a prefixed node belongs to: the prefix is
    that call's node id plus the submodule marker."""
    return prefix[: -len(C_TO_LOGIC.SUBMODULE_MARKER)] if prefix else ""


def _prefix_ref(ref, prefix, node_id):
    """Namespace a ValueRef into a descended function's node-id space."""
    if not prefix:
        return ref
    if ref[0] == "node":
        return ["node", prefix + ref[1]]
    if ref[0] == "in":
        # A read of the descended function's own input. Leave it marked as such,
        # carrying the call it belongs to and which input it is; _resolve_inlined
        # rewrites it to the matching operand of that call.
        return ["inlined_in", node_id, ref[1]]
    return ref


def _resolve_inlined(dag):
    """Rewrite references that point at descended (inlined) call nodes.

    A descended node produces no hardware of its own: reading its result means
    reading whatever its body produced, and its body's reads of its own inputs
    mean the operands passed at the call. Collapsing both here keeps every later
    stage -- scheduling, register allocation, code generation -- working on a
    single flat graph with no notion of descent.

    Cast chains have to be spliced together across the boundary too. A value
    flowing out of a descended body passed through that body's own intermediate
    types before reaching the call's result type, and the consumer's chain picks
    up from there; dropping the inner half would skip a narrowing the original
    code performed.
    """
    nodes = dag["nodes"]

    def resolve(ref, _seen=None):
        """Returns (ref, extra_casts) where extra_casts apply BEFORE whatever
        cast chain the consumer already recorded."""
        _seen = _seen or set()
        extra = []
        while True:
            if ref[0] == "node" and nodes.get(ref[1], {}).get("kind") == "inlined":
                if ref[1] in _seen:
                    raise AutofsmError("AUTOFSM: cyclic inlined reference")
                _seen.add(ref[1])
                node = nodes[ref[1]]
                # The body's own trailing casts, then the type the call's result
                # was seen as -- the consumer's chain starts after that.
                extra = list(node["inlined_out_casts"]) + [node["out_type"]] + extra
                ref = node["inlined_out"]
                continue
            if ref[0] == "inlined_in":
                _, call_id, input_name = ref
                node = nodes.get(call_id)
                if node is None or node["kind"] != "inlined":
                    raise AutofsmError(
                        f"AUTOFSM: dangling inlined input reference {ref!r}"
                    )
                try:
                    idx = node["inlined_inputs"].index(input_name)
                except ValueError:
                    raise AutofsmError(
                        f"AUTOFSM: descended function {node['entity']!r} has no "
                        f"input named {input_name!r}"
                    )
                # Reading the body's input means reading what the call passed,
                # through the call's own cast chain for that operand.
                extra = list(node["casts"][idx]) + [node["port_types"][idx]] + extra
                ref = node["operands"][idx]
                continue
            return ref, extra

    def splice(ref, casts):
        new_ref, extra = resolve(ref)
        return new_ref, _dedupe_casts(extra + list(casts))

    for node in nodes.values():
        if node["kind"] == "inlined":
            continue
        spliced = [splice(r, c) for r, c in zip(node["operands"], node["casts"])]
        node["operands"] = [r for r, _ in spliced]
        node["casts"] = [c for _, c in spliced]
    dag["output"], dag["output_casts"] = splice(dag["output"], dag["output_casts"])
    # Drop the placeholders now that nothing points at them.
    dag["nodes"] = {k: v for k, v in nodes.items() if v["kind"] != "inlined"}
    return dag


def _dedupe_casts(chain):
    """Collapse consecutive identical types out of a cast chain."""
    out = []
    for t in chain:
        if t is None:
            continue
        if out and out[-1] == t:
            continue
        out.append(t)
    return out


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
    return {nid: t for nid, (t, _lo, _hi) in _LIVE_RANGES(
        nodes, output_ref, n_states
    ).items()}


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
                used_in_states[dep].add(consumer["state"])
    # The final result is assembled in the last state.
    for dep in _scheduled_deps(dag, output_ref, sched, set()):
        used_in_states[dep].add(n_states)
    out = {}
    for nid in sched:
        born = nodes[nid]["state"]
        later = [s for s in used_in_states[nid] if s > born]
        if later:
            out[nid] = (nodes[nid]["out_type"], born + 1, max(later))
    return out


def ALLOCATE_REGISTERS(nodes, output_ref, n_states):
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

    TWO values may share a register only if they have the same c type AND COME
    FROM THE SAME FUNCTIONAL UNIT. The type rule is obvious (a register is
    declared at one type, and storing a narrower value in a wider one reads
    back differently). The same-unit rule is the interesting one, and it is
    what makes this optimization FREE:

      * Same unit  -> the register's data input is that unit's output local in
        every state that writes it. The register gains extra write states, i.e.
        a wider enable term. No data path is added at all.
      * Different units -> the register's input becomes a multiplexer between
        two units' outputs, sitting directly in front of a flip-flop, on what
        is usually already the critical path.

    That second case is not a theoretical worry. Allowing it on the donut
    example dropped the FSM from 42.4 MHz to 37.5 MHz -- one extra multiplexer
    level in front of every shared register -- in exchange for a handful of
    flip-flops. Registers are cheap and the clock period is not, so the
    unconstrained version of this optimization is a bad trade even though it
    does what it says on the tin.

    Returns (nid -> register index, register index -> c type).
    """
    ranges = _LIVE_RANGES(nodes, output_ref, n_states)
    order = sorted(ranges, key=lambda nid: (ranges[nid][1], ranges[nid][2], nid))
    free_at = []  # per register: (c type, producing unit, first state free)
    assignment = {}
    reg_types = {}
    for nid in order:
        ctype, lo, hi = ranges[nid]
        fu = nodes[nid].get("fu")
        chosen = None
        for idx, (reg_type, reg_fu, busy_until) in enumerate(free_at):
            if reg_type == ctype and reg_fu == fu and busy_until < lo:
                chosen = idx
                break
        if chosen is None:
            chosen = len(free_at)
            free_at.append((ctype, fu, hi))
            reg_types[chosen] = ctype
        else:
            free_at[chosen] = (ctype, fu, hi)
        assignment[nid] = chosen
    return assignment, reg_types


def _critical_path(dag, sched, preds):
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
            raise AutofsmError(f"AUTOFSM: dependency cycle at {nid!r}")
        stack.add(nid)
        best = 0
        for s in succs[nid]:
            best = max(best, walk(s, stack))
        stack.discard(nid)
        memo[nid] = best + dag["nodes"][nid]["delay_du"]
        return memo[nid]

    for nid in sched:
        walk(nid, set())
    return memo


def _fu_id(entity, copy_index):
    """Identity of one physical shared unit. Normally one per entity; a second
    copy only appears when a hard max_latency cap cannot be met by sharing
    everything (see SCHEDULE_DAG). The schedule keeps fu_id -> entity as an
    explicit map rather than assuming they are the same string, which is also
    the seam a future width-subsumption binding would use."""
    return entity if copy_index == 0 else f"{entity}#{copy_index}"


def SCHEDULE_DAG(dag, budget_du, mux_du_of=None, max_states=None, copies=None):
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

    `copies[entity]` allows more than one physical unit for an entity. That is
    the ONLY way a hard max_latency cap can be met once sharing alone needs
    more states than the cap allows: trade area back for latency.
    """
    nodes = dag["nodes"]
    sched = _scheduled_ids(dag)
    copies = copies or {}
    mux_du_of = mux_du_of or (lambda nid: MUX_PENALTY_DU)
    # What each scheduled operation must wait for: the scheduled operations
    # feeding its OPERANDS, seen through any zero-delay glue in between.
    preds = {}
    for nid in sched:
        deps = set()
        for operand in nodes[nid]["operands"]:
            _scheduled_deps(dag, operand, sched, deps)
        preds[nid] = deps - {nid}
    prio = _critical_path(dag, sched, preds)

    state_of = {}
    fu_of = {}
    fu_edges = {}  # fu -> set of fus it feeds (within some state)
    at_floor = False
    worst_state_du = 0
    state = 0

    def free_fu(entity, fus_used):
        """Lowest-numbered copy of `entity` not yet busy this state. Lowest
        first (rather than round-robin) deliberately: it keeps the extra copies
        lightly loaded, so their operand muxes stay small and any copy that
        ends up unused disappears entirely."""
        for i in range(max(1, copies.get(entity, 1))):
            fu = _fu_id(entity, i)
            if fu not in fus_used:
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
        while heap:
            item = heapq.heappop(heap)
            nid = item[1]
            fu = free_fu(nodes[nid]["entity"], fus_used)
            if fu is None:
                deferred.append(item)
                continue
            same_state_preds = [p for p in preds[nid] if state_of[p] == state]
            start = max((chain_end[p] for p in same_state_preds), default=0)
            end = start + nodes[nid]["delay_du"] + mux_du_of(nid)
            if end > budget_du and (fus_used or chain_end):
                deferred.append(item)
                continue
            new_edges = {(fu_of[p], fu) for p in same_state_preds}
            if not _edges_stay_acyclic(fu_edges, new_edges):
                deferred.append(item)
                continue
            if end > budget_du:
                # Nothing fits an empty state: force this one in alone.
                at_floor = True
            for a, b in new_edges:
                fu_edges.setdefault(a, set()).add(b)
            state_of[nid] = state
            fu_of[nid] = fu
            chain_end[nid] = end
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
        if not fus_used:
            # No progress at all: only possible if every ready node was blocked
            # by the acyclicity rule, which an empty state cannot reproduce.
            raise AutofsmError(
                "AUTOFSM: scheduling stalled with operations left to place "
                "(internal error)"
            )
        worst_state_du = max(worst_state_du, state_worst)
        # Deliberately no early exit once past max_states: scheduling to
        # completion is what tells the caller how many states this REALLY
        # needs, which is the one thing a user staring at an infeasible
        # latency cap actually wants told.

    n_states = max(1, state)
    used_fus = sorted(set(fu_of.values()))
    return {
        "n_states": n_states,
        "state_of": state_of,
        "fu_of": fu_of,
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
    trial = {k: set(v) for k, v in fu_edges.items()}
    for a, b in new_edges:
        if a == b:
            # A unit feeding itself within one state would need two copies of
            # it live at once -- exactly what sharing forbids.
            return False
        trial.setdefault(a, set()).add(b)
    return _is_acyclic(trial)


def _is_acyclic(edges):
    color = {}

    def visit(n):
        state = color.get(n)
        if state == 1:
            return False
        if state == 2:
            return True
        color[n] = 1
        for m in edges.get(n, ()):
            if not visit(m):
                return False
        color[n] = 2
        return True

    return all(visit(n) for n in list(edges))


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

    The schedule's content is hashed in, so rescheduling with a different budget
    produces a DIFFERENT entity. That is deliberate: it makes stale cross-pass
    reuse structurally impossible -- nothing can seed pipelining onto, or reuse
    a cached delay for, an entity whose contents changed underneath it.
    """
    h = hashlib.sha256(
        json.dumps(schedule_core, sort_keys=True, default=str).encode()
    ).hexdigest()[:8]
    base = f"autofsm_{func_entity}"
    budget = _MAX_NAME_LEN - 9  # "_" + 8 hex chars
    if len(base) > budget:
        base = base[:budget].rstrip("_")
    return f"{base}_{h}"


def BUILD_SCHEDULE(
    parser_state,
    key,
    tag,
    budget_scale,
    prev_schedule=None,
    opened=(),
    max_nodes=None,
    unshared=(),
):
    """Schedule + bind one AUTOFSM'd function into a plain (picklable,
    comparable) schedule dict.

    Pure function of (the function's Logic graphs, its operations' delays,
    budget_scale, `opened`, `unshared`) -- deliberately independent of the
    surrounding design, which is what makes the driver's loop converge
    trivially: only an explicit budget tightening, or the area sweep choosing
    different grain/binding, can change the answer.

    `unshared` is a sequence of (entity, n_units) pairs: how many physical
    copies of an operation to build instead of the default one. Sharing is not
    free -- it buys one unit at the price of a multiplexer on every input port
    and, when it forces extra states, a register for every value that now has
    to cross one. For a CHEAP operation (a one-bit OR costs less than the
    two-bit multiplexer selecting its operands) sharing is a straight loss, and
    v1 had no way to decline it.
    """
    func_entity = _entity_key_for_callable(parser_state, tag.func)
    if func_entity is None:
        raise AutofsmError(
            f"AUTOFSM: the function tagged by {key!r} was never elaborated, so "
            f"there is nothing to schedule (internal error)."
        )
    budget_du = _budget_du(parser_state, budget_scale)
    # Delays: what this pass measured, falling back to the previous pass's
    # snapshot for anything unmeasured. The fallback is what makes rescheduling
    # possible at all -- on every pass after the first, the FSM has replaced the
    # pure function, so none of its operations are instantiated and none of them
    # get measured, yet the scheduler still needs their delays to decide how
    # many fit in a (now smaller) state.
    snapshot = (prev_schedule or {}).get("entity_delays_snapshot", {})
    live = _snapshot_subtree_delays(parser_state, func_entity)
    delays = {
        k: (v if v is not None else snapshot.get(k, 0)) for k, v in live.items()
    }
    for k, v in snapshot.items():
        delays.setdefault(k, v)

    _seed_struct_widths(parser_state)
    opened = tuple(sorted(set(opened)))
    dag = _resolve_inlined(
        BUILD_DAG(parser_state, func_entity, delays, budget_du, opened)
    )
    if max_nodes is not None and len(dag["nodes"]) > max_nodes:
        # Checked BEFORE scheduling: this is the area search asking "what if I
        # opened that up", and scheduling something this size to find out it
        # was never going to be worth it is the expensive way to learn it.
        raise AutofsmError(
            f"AUTOFSM: opening {sorted(opened)!r} flattens {key} into "
            f"{len(dag['nodes'])} operations, past the {max_nodes} the area "
            f"search will consider"
        )

    # Operand-mux delays. A unit's fold count -- how many operations share it,
    # and therefore how wide its operand mux must be -- is known BEFORE
    # scheduling, because binding is by entity: every node of one entity binds
    # to that entity's unit. So there is no fixpoint to chase here; the numbers
    # the scheduler charges are the ones the generated FSM will actually build.
    types = _TypeResolver()
    for t in (tag.in_type, tag.out_type):
        types.seed(t)
    mux_snapshot = dict((prev_schedule or {}).get("mux_delays_snapshot", {}))
    sched_ids = _scheduled_ids(dag)
    folds = {}
    for nid in sched_ids:
        e = dag["nodes"][nid]["entity"]
        folds[e] = folds.get(e, 0) + 1
    max_latency = getattr(tag, "max_latency", None)
    max_states = (max_latency - 1) if max_latency else None
    copies = _replication_for_latency(folds, max_states)
    # The area search's unsharing choices, floored by whatever the latency cap
    # already forces and capped at one unit per operation (past which extra
    # units could never be used).
    for entity, n in unshared:
        if entity in folds:
            copies[entity] = min(folds[entity], max(copies.get(entity, 1), int(n)))

    mux_du_cache = {}

    def mux_du_of(nid):
        node = dag["nodes"][nid]
        e = node["entity"]
        n = _fold_count_per_unit(folds.get(e, 1), copies.get(e, 1))
        cached = mux_du_cache.get((e, n))
        if cached is None:
            cached = 0
            for ctype in node["port_types"]:
                du = _mux_delay_du(parser_state, types, ctype, n, mux_snapshot)
                mux_snapshot.setdefault(f"{ctype}#{n}", du)
                cached = max(cached, du)
            mux_du_cache[(e, n)] = cached
        return cached

    plan = SCHEDULE_DAG(dag, budget_du, mux_du_of, max_states, copies)
    # A cap that sharing alone cannot meet: hand more units to whatever is
    # still forcing states, and try again. Bounded, and each step is a pure
    # (cheap) recomputation -- no synthesis is involved in any of this.
    for _ in range(MAX_REPLICATION_STEPS):
        if not plan["latency_infeasible"]:
            break
        bumped = _bump_replication(plan, folds, copies)
        if not bumped:
            break
        plan = SCHEDULE_DAG(dag, budget_du, mux_du_of, max_states, copies)
    # Recorded after the latency-driven bumps above, so the schedule always
    # states the binding it actually has.
    unshared = tuple(sorted((e, n) for e, n in copies.items() if n > 1))

    nodes = {}
    for nid, node in dag["nodes"].items():
        nodes[nid] = dict(node)
        nodes[nid]["state"] = plan["state_of"].get(nid)
        nodes[nid]["fu"] = plan["fu_of"].get(nid)
    n_states = plan["n_states"]
    schedule_core = {
        "version": SCHEDULE_VERSION,
        "key": key,
        "func_entity": func_entity,
        "n_states": n_states,
        "latency": n_states + 1,
        "max_latency": max_latency,
        "latency_infeasible": plan["latency_infeasible"],
        "budget_scale": budget_scale,
        "budget_du": budget_du,
        "worst_state_du": plan["worst_state_du"],
        "at_floor": plan["at_floor"],
        "nodes": nodes,
        "node_order": sorted(nodes),
        "fus": plan["fus"],
        "fu_order": plan["fu_order"],
        "output": dag["output"],
        "output_casts": dag["output_casts"],
        "out_type": dag["out_type"],
        "entity_delays_snapshot": delays,
        "mux_delays_snapshot": mux_snapshot,
        "opened": list(opened),
        "unshared": [list(pair) for pair in unshared],
    }
    schedule = dict(schedule_core)
    schedule["entity"] = _schedule_entity_name(func_entity, schedule_core)
    return schedule


def _fold_count_per_unit(folds, n_copies):
    """Operations per physical unit, rounded up -- what its operand mux has to
    select between."""
    n_copies = max(1, n_copies)
    return max(1, -(-folds // n_copies))


def _replication_for_latency(folds, max_states):
    """Minimum unit copies per entity implied by a hard latency cap.

    An entity used F times with R copies needs at least ceil(F/R) states, since
    one copy runs at most one operation per state. So a cap of S states forces
    R >= ceil(F/S), computed directly rather than searched for."""
    if not max_states:
        return {}
    return {
        entity: -(-count // max_states)
        for entity, count in folds.items()
        if count > max_states
    }


def _bump_replication(plan, folds, copies):
    """Give one more unit to whatever is most loaded, in place. Returns False
    when no entity can usefully be replicated further (the schedule is then
    bounded by a dependency chain or the delay budget, neither of which more
    units can fix)."""
    best = None
    for entity, count in sorted(folds.items()):
        n = copies.get(entity, 1)
        if n >= count:
            continue  # already one unit per operation: nothing left to unshare
        load = count / float(n)
        if best is None or load > best[0]:
            best = (load, entity)
    if best is None:
        return False
    entity = best[1]
    copies[entity] = copies.get(entity, 1) + 1
    return True


# ─────────────────────────────────────────────
# Area model and the minimum-area search
# ─────────────────────────────────────────────


def _leaf_area(entity, logic):
    """Estimated area of one indivisible operation, in the abstract units
    documented at the top of this module."""
    widths = [
        _ctype_width(logic.wire_to_c_type.get(p)) for p in logic.inputs
    ] or [1]
    w = max(widths)
    pair = widths[0] * widths[1] if len(widths) >= 2 else w * w

    if entity.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_"):
        rest = entity[len(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX) + 1 :]
        for op_name in sorted(_BIN_OP_SRC, key=len, reverse=True):
            if not rest.startswith(op_name + "_"):
                continue
            if op_name in (
                C_TO_LOGIC.BIN_OP_MULT_NAME,
                C_TO_LOGIC.BIN_OP_INFERRED_MULT_NAME,
            ):
                return pair * AREA_PER_BIT_PAIR_MULT
            if op_name in (C_TO_LOGIC.BIN_OP_DIV_NAME, C_TO_LOGIC.BIN_OP_MOD_NAME):
                return pair * AREA_PER_BIT_PAIR_DIV
            if op_name in (
                C_TO_LOGIC.BIN_OP_AND_NAME,
                C_TO_LOGIC.BIN_OP_OR_NAME,
                C_TO_LOGIC.BIN_OP_XOR_NAME,
            ):
                return w * AREA_PER_BIT_BITWISE
            if op_name in (C_TO_LOGIC.BIN_OP_SL_NAME, C_TO_LOGIC.BIN_OP_SR_NAME):
                return w * AREA_PER_BIT_SHIFT_VAR
            if op_name in (
                C_TO_LOGIC.BIN_OP_PLUS_NAME,
                C_TO_LOGIC.BIN_OP_MINUS_NAME,
            ):
                return w * AREA_PER_BIT_ADD
            return w * AREA_PER_BIT_CMP
    if entity.startswith(C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX + "_"):
        rest = entity[len(C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX) + 1 :]
        if rest.startswith(C_TO_LOGIC.UNARY_OP_NOT_NAME + "_"):
            return w * AREA_PER_BIT_BITWISE
        return w * AREA_PER_BIT_ADD
    if entity.startswith(C_TO_LOGIC.MUX_LOGIC_NAME + "_"):
        return _ctype_width(logic.wire_to_c_type.get(C_TO_LOGIC.RETURN_WIRE_NAME)) * (
            AREA_PER_BIT_MUX
        )
    if entity.startswith(C_TO_LOGIC.CONST_PREFIX) or entity.startswith(
        C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX
    ):
        return 0.0  # constant shifts and field reads are wiring
    if getattr(logic, "is_new_style_bit_manip", False):
        return 0.0  # bit_assign / concat / rotate: wiring
    if entity.startswith(C_TO_LOGIC.VAR_REF_RD_FUNC_NAME_PREFIX):
        # A variable array index: a balanced mux tree over the array.
        out_w = _ctype_width(logic.wire_to_c_type.get(C_TO_LOGIC.RETURN_WIRE_NAME))
        in_w = max(widths)
        n = max(2, in_w // max(1, out_w))
        return out_w * (n - 1) * AREA_PER_BIT_MUX
    return w * AREA_PER_BIT_DEFAULT


def ESTIMATE_ENTITY_AREA(parser_state, entity, memo=None):
    """Estimated area of one entity INCLUDING everything it instantiates.

    Memoized per entity, which matters: a float64 multiplier's tree is large,
    and the sweep asks for these numbers hundreds of times.
    """
    memo = {} if memo is None else memo
    hit = memo.get(entity)
    if hit is not None:
        return hit
    logic = parser_state.FuncLogicLookupTable.get(entity)
    if logic is None:
        return 0.0
    memo[entity] = 0.0  # cycle guard; real value written below
    if not logic.submodule_instances:
        total = _leaf_area(entity, logic)
    else:
        total = sum(
            ESTIMATE_ENTITY_AREA(parser_state, sub, memo)
            for sub in logic.submodule_instances.values()
        )
    memo[entity] = total
    return total


def ESTIMATE_SCHEDULE_AREA(parser_state, schedule, memo=None):
    """Estimated area of the FSM a schedule describes, in abstract units.

    Three terms, which are exactly the three things sharing trades between:

      units      one copy of each bound entity, however many operations use it.
                 This is the term sharing SHRINKS, and the reason AUTOFSM
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

    Ranking only -- see the note on the AREA_* constants for why this cannot be
    a real utilization number.
    """
    memo = {} if memo is None else memo
    _seed_struct_widths(parser_state)
    nodes = schedule["nodes"]
    fus = schedule["fus"]

    total = 0.0
    for fu, entity in sorted(fus.items()):
        total += ESTIMATE_ENTITY_AREA(parser_state, entity, memo)
    for nid in schedule["node_order"]:
        node = nodes[nid]
        if not node.get("fu"):
            total += ESTIMATE_ENTITY_AREA(parser_state, node["entity"], memo)

    users = {}
    for nid in schedule["node_order"]:
        node = nodes[nid]
        fu = node.get("fu")
        if fu:
            users.setdefault(fu, []).append(nid)
    for fu, nids in sorted(users.items()):
        n = len(nids)
        if n < 2:
            continue
        for ctype in nodes[nids[0]]["port_types"]:
            total += _ctype_width(ctype) * (n - 1) * AREA_PER_BIT_MUX

    reg_of, reg_types = ALLOCATE_REGISTERS(
        nodes, schedule["output"], schedule["n_states"]
    )
    reg_bits = sum(_ctype_width(t) for t in reg_types.values())
    reg_bits += _ctype_width(schedule["out_type"])
    reg_bits += max(1, int(schedule["n_states"]).bit_length())
    # The input latch is deliberately not counted: it is the same width in
    # every candidate for a given function, so it cannot change a ranking.
    total += reg_bits * AREA_PER_BIT_FF
    # No multiplexer term for shared registers: ALLOCATE_REGISTERS only merges
    # values coming from the same unit, so a shared register's data input is
    # one unchanged wire and only its write enable widens.
    total += schedule["n_states"] * AREA_PER_STATE_DECODE
    return total


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


def SWEEP_MIN_AREA_SCHEDULE(
    parser_state, key, tag, budget_scale, prev_schedule=None
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
    anchor = BUILD_SCHEDULE(parser_state, key, tag, budget_scale, prev_schedule)
    anchor_cost = ESTIMATE_SCHEDULE_AREA(parser_state, anchor, memo)
    best, best_cost = anchor, anchor_cost
    cur = anchor
    opened = []
    unshared = {}
    n_considered = 0
    uphill = 0

    def evaluate(trial_opened, trial_unshared):
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
            )
        except AutofsmError:
            return None
        if sched["latency_infeasible"] and not anchor["latency_infeasible"]:
            return None
        if sched["at_floor"] and not anchor["at_floor"]:
            # This made some state unschedulable at the clock goal. More area
            # for worse timing is never the trade being looked for here.
            return None
        if sched["worst_state_du"] > anchor["worst_state_du"]:
            # THE SEARCH MAY NOT SPEND TIMING MARGIN. A candidate whose worst
            # state is longer than the anchor's still "fits the budget" by the
            # delay model's reckoning, but the delay model is an estimate and
            # the budget is a guess at how much of the clock period the FSM's
            # own control will leave -- so a schedule that eats the difference
            # is buying area with margin that may not have been there.
            #
            # This is not hypothetical: the donut example's search found a real
            # 8% area saving by opening three comparators onto a shared
            # subtractor, pushed the worst state from 13.7 ns to 17.1 ns, and
            # turned a design that met 40 MHz into one that missed it at 36 MHz.
            # Trading latency for timing is the DRIVER's job (it tightens the
            # per-state budget and reschedules); the search's job is area at
            # equal-or-better timing, and nothing else.
            return None
        return sched

    for _move in range(MAX_SWEEP_MOVES):
        candidates = []  # (cost, tie-break label, schedule, opened, unshared)
        for entity in sorted(_openable_entities(parser_state, cur, opened)):
            trial_opened = sorted(opened + [entity])
            sched = evaluate(trial_opened, unshared)
            n_considered += 1
            if sched is not None:
                candidates.append(
                    (
                        ESTIMATE_SCHEDULE_AREA(parser_state, sched, memo),
                        ("open", entity),
                        sched,
                        trial_opened,
                        unshared,
                    )
                )
        for entity, n_units in sorted(_unshareable_entities(cur, unshared).items()):
            trial_unshared = dict(unshared)
            trial_unshared[entity] = n_units
            sched = evaluate(opened, trial_unshared)
            n_considered += 1
            if sched is not None:
                candidates.append(
                    (
                        ESTIMATE_SCHEDULE_AREA(parser_state, sched, memo),
                        ("unshare", entity),
                        sched,
                        opened,
                        trial_unshared,
                    )
                )
        if not candidates:
            break
        candidates.sort(key=lambda c: (c[0], c[1]))
        cost, _label, sched, opened, unshared = candidates[0]
        # Always take the cheapest available move, even uphill -- see
        # MAX_SWEEP_UPHILL. The incumbent BEST is what gets returned, so
        # walking uphill can only ever discover something, never lose anything.
        cur = sched
        if cost < best_cost * (1.0 - SWEEP_MIN_IMPROVEMENT):
            best, best_cost = sched, cost
            uphill = 0
        else:
            uphill += 1
            if uphill > MAX_SWEEP_UPHILL:
                break

    best["est_area"] = round(best_cost, 3)
    best["est_area_anchor"] = round(anchor_cost, 3)
    best["sweep_candidates"] = n_considered
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
    import SYN

    mhz_values = [
        mhz for mhz in parser_state.main_mhz.values() if mhz is not None and mhz > 0
    ]
    if not mhz_values:
        # No clock goal anywhere: nothing to schedule against, so keep the whole
        # function in one state.
        return 1 << 30
    period_ns = 1000.0 / max(mhz_values)
    return max(1, int(period_ns * SYN.DELAY_UNIT_MULT * budget_scale))


def HARVEST_AUTOFSM_SCHEDULES(
    parser_state, budget_scales=None, prev_schedules=None, area_sweep=True
):
    """Schedule every AUTOFSM call site in the design.

    Returns canonical_key -> schedule dict, ready to hand to
    pypeline.SET_AUTOFSM_SCHEDULE_CACHE before re-executing the design file.
    prev_schedules carries forward the delay snapshot, so a reschedule on a
    later pass (where the pure function is no longer instantiated and therefore
    no longer measured) works from the same numbers as the first one.
    """
    budget_scales = budget_scales or {}
    prev_schedules = prev_schedules or {}
    tags = GET_TAGS(parser_state)
    schedules = {}
    for key in sorted(COLLECT_AUTOFSM_KEYS(parser_state)):
        tag = tags.get(key)
        if tag is None:
            raise AutofsmError(
                f"AUTOFSM: no live tag object recorded for call site {key!r} "
                f"(internal error)"
            )
        build = SWEEP_MIN_AREA_SCHEDULE if area_sweep else BUILD_SCHEDULE
        schedules[key] = build(
            parser_state,
            key,
            tag,
            budget_scales.get(key, DEFAULT_BUDGET_SCALE),
            prev_schedules.get(key),
        )
    return schedules


def LATENCY_INFEASIBLE_MESSAGE(key, schedule) -> str:
    """What to print when a hard max_latency cap cannot be met. Names the FSM,
    the cap, and the latency it actually needs -- the number the user has to
    know to decide between raising the cap, relaxing the clock goal, or
    rewriting the function."""
    return (
        f"AUTOFSM {key}: max_latency={schedule['max_latency']} cannot be met. "
        f"The shortest schedule meeting the {schedule['budget_du'] / 10.0:.2f} "
        f"ns/state delay budget needs {schedule['n_states']} states "
        f"(latency {schedule['latency']}), even after replicating shared units "
        f"to unshare what could be unshared. Raise max_latency to at least "
        f"{schedule['latency']}, lower the clock goal, or shorten the "
        f"function's dependency chain."
    )


def BLAMED_AUTOFSM_KEYS(parser_state, multimain_timing_params, schedules):
    """Which AUTOFSM regions could plausibly be responsible for a timing failure.

    The sweep's failure records name the MAIN that missed its clock and, when it
    could attribute one, the function to blame. A generated FSM entity is
    stateful, so the sweep already treats it as an unsliceable atomic block
    whose delay is a floor -- exactly what it reports as blame when it cannot
    pipeline its way out.

    With no attribution available (notably the PYRTL software timing model,
    which reports no path detail), fall back to blaming every AUTOFSM under the
    failing MAIN. Over-blaming costs one extra schedule pass at a tighter
    budget; under-blaming would silently give up.
    """
    failures = getattr(multimain_timing_params, "sweep_timing_failures", None)
    if not failures:
        return set()
    entity_to_key = {sched["entity"]: key for key, sched in schedules.items()}
    blamed = set()
    for main_func_name, _goal, _achieved, why in failures:
        named = {
            entity_to_key[entity] for entity in entity_to_key if entity in (why or "")
        }
        if named:
            blamed |= named
            continue
        blamed |= _AUTOFSM_KEYS_UNDER_MAIN(parser_state, main_func_name)
    return {key for key in blamed if key in schedules}


def _AUTOFSM_KEYS_UNDER_MAIN(parser_state, main_func_name):
    """AUTOFSM keys instantiated anywhere in one MAIN's instance hierarchy."""
    keys = set()
    for inst_name, logic in parser_state.LogicInstLookupTable.items():
        if not logic.sub_inst_to_autofsm_key:
            continue
        root = inst_name.split(C_TO_LOGIC.SUBMODULE_MARKER)[0]
        if root == main_func_name:
            keys.update(logic.sub_inst_to_autofsm_key.values())
    return keys


def SCHEDULES_EQUAL(a, b) -> bool:
    """Structural comparison used as the driver loop's convergence test."""
    if a is None or b is None:
        return a is b
    if set(a) != set(b):
        return False
    return all(a[k] == b[k] for k in sorted(a))


def DESCRIBE_SCHEDULE(key, schedule) -> str:
    """One-line build-log summary: what got folded onto what, and at what cost.

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
        f"AUTOFSM {key}: {n_ops} ops -> {n_fus} shared unit(s), "
        f"{schedule['n_states']} states, latency {schedule['latency']}{cap_txt} clks, "
        f"budget {budget_ns:.2f} ns/state (scale {schedule['budget_scale']:.3f}), "
        f"worst state {worst_ns:.2f} ns{floor}"
    )
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
        for entity in schedule.get("opened") or ():
            line += f"\n    opened up: {entity}"
        for entity, n_units in schedule.get("unshared") or ():
            line += f"\n    {n_units} units of: {entity}"
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


# ─────────────────────────────────────────────
# Code generation
# ─────────────────────────────────────────────


class _Emitter:
    """Accumulates generated source lines plus the namespace of live objects
    (types, callables) the source refers to by injected name.

    Injected names are assigned in emission order and derived only from the
    schedule, so one schedule always produces byte-identical source -- the
    property that keeps entity names stable across the driver's repeated
    re-elaborations of one design.
    """

    def __init__(self):
        self.lines = []
        self.globals = {}
        self._by_obj_key = {}
        self._n = 0

    def inj(self, obj, hint="v"):
        """Inject a live object, returning the generated name that refers to it."""
        # Keyed on identity: two same-named struct classes from different
        # elaboration passes are different objects and must not collapse.
        k = id(obj)
        name = self._by_obj_key.get(k)
        if name is None:
            name = f"_af_{hint}{self._n}"
            self._n += 1
            self._by_obj_key[k] = name
            self.globals[name] = obj
        return name

    def line(self, text=""):
        self.lines.append(text)

    def src(self):
        return "\n".join(self.lines) + "\n"


def _exec_generated(func_name, src, extra_globals):
    """exec generated FSM source into a synthetic module, mirroring
    pypeline._exec_generated_func: a flat top-level def plus a linecache entry
    so inspect.getsource works during elaboration, under a fake path with no
    characters illegal in a VHDL identifier (PY_TO_LOGIC._loc_str embeds the
    file's basename into generated instance names)."""
    import linecache

    fake_file = f"/pypeline_autofsm_gen/{func_name}.py"
    linecache.cache[fake_file] = (len(src), None, src.splitlines(True), fake_file)
    code = compile(src, fake_file, "exec")
    ns = dict(extra_globals)
    exec(code, ns)
    fn = ns[func_name]
    fn._autofsm_generated_src = src
    return fn


def _passthrough_name(tag) -> str:
    h = hashlib.sha256(tag.canonical_key.encode()).hexdigest()[:8]
    base = f"autofsm_{tag.canonical_key}"
    budget = _MAX_NAME_LEN - 14  # "_" + 8 hex + "_comb"
    if len(base) > budget:
        base = base[:budget].rstrip("_")
    return f"{base}_{h}_comb"


def BUILD_PASSTHROUGH_FUNC(tag):
    """Bootstrap-pass hardware for an AUTOFSM call site: a plain combinational
    wrapper, `o.data = func(s.data); o.valid = s.valid`.

    Its job is to put the real function -- and therefore every operation inside
    it -- into the design, so SYN.ADD_PATH_DELAY_TO_LOOKUP measures/estimates
    the per-operation delays the scheduler needs. Being fully combinational also
    makes this wrapper a measurement frontier (SYN.FUNC_IS_TOPMOST_COMB) inside
    the stateful function that calls it, which is what calibrates those delays.
    """
    from pypeline import hw_func

    name = _passthrough_name(tag)
    em = _Emitter()
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
    return _exec_generated(name, em.src(), em.globals)


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


class _Codegen:
    """Renders one scheduled DAG as pypeline source.

    The generated function's shape (see docs/AUTOFSM_DESIGN.md for a worked
    example):

        state + value registers
        -> snapshot every register into a local, so all reads see the value
           committed at the last clock edge (pypeline assignment is sequential,
           so a later write in the same body would otherwise be visible to an
           earlier-written read)
        -> drive outputs from the output registers
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
        self.nodes = schedule["nodes"]
        self.n_states = schedule["n_states"]
        self.em = _Emitter()
        self.types = _TypeResolver()
        self.local_of_node = {}  # node id -> local name holding its result
        self.reg_of_node = {}  # node id -> snapshot local of its register
        self.cur_state = None
        self._tmp_n = 0
        self.mux_shapes = []  # (type, fold count) of every operand mux emitted

        for t in (tag.in_type, tag.out_type, tag.in_stream_t, tag.out_stream_t):
            self.types.seed(t)
        for entity in schedule["fus"].values():
            f = _entity_callables(parser_state).get(entity)
            if f is not None:
                self.types.seed_callable(f)
        for node in self.nodes.values():
            f = _entity_callables(parser_state).get(node["entity"])
            if f is not None:
                self.types.seed_callable(f)

    # ── value rendering ────────────────────────────────────────────────
    def _render_ref(self, ref):
        """Render a ValueRef as an expression valid in the current state."""
        kind = ref[0]
        if kind == "in":
            return "in_v"
        if kind == "const":
            return self._render_const(ref[1])
        if kind != "node":
            raise AutofsmError(f"AUTOFSM: unsupported value reference {ref!r}")
        nid = ref[1]
        node = self.nodes.get(nid)
        if node is None:
            raise AutofsmError(f"AUTOFSM: reference to unknown operation {nid!r}")
        if node["delay_du"] > 0:
            # A shared unit's output local holds whichever operation that unit
            # is running THIS state. Only a same-state producer can be read
            # from it; anything computed earlier must come from its register.
            if node["state"] == self.cur_state and nid in self.local_of_node:
                return self.local_of_node[nid]
            if nid in self.reg_of_node:
                return self.reg_of_node[nid]
            raise AutofsmError(
                f"AUTOFSM: operation {nid!r} (state {node['state']}) is read in "
                f"state {self.cur_state} but was not given a register "
                f"(internal scheduling error)"
            )
        # Zero-delay glue: re-render it inline, here, in this state.
        return self._render_glue(nid, node)

    def _render_glue(self, nid, node):
        operand_exprs = [
            self._render_operand(node, i) for i in range(len(node["operands"]))
        ]
        if node["op"]["kind"] == "assemble":
            return self._render_assemble(node, operand_exprs)
        return _render_op(
            node["op"], operand_exprs, self.em, self.parser_state, node["entity"]
        )

    def _render_assemble(self, node, operand_exprs):
        """Build a compound value (what `return my_struct_t(a=..., b=...)`
        elaborates to) into a typed local, field by field, and return its name.

        Unlike every other operation this needs statements rather than an
        expression, which is fine: assembly is pure rewiring, so it is glue and
        gets re-rendered wherever its value is used.

        Assignments go shortest-path-first so that a whole-value base (a port
        carrying the value being partially updated) lands before the field
        writes that override parts of it.
        """
        name = f"asm{self._tmp_n}"
        self._tmp_n += 1
        t = self.em.inj(self.types.resolve(node["out_type"]), "t")
        self.em.line(f"    {name}: {t}")
        order = sorted(
            range(len(operand_exprs)), key=lambda i: len(node["op"]["paths"][i])
        )
        for i in order:
            target = name + _path_suffix(node["op"]["paths"][i])
            self.em.line(f"    {target} = {operand_exprs[i]}")
        return name

    def _render_operand(self, node, i):
        """Render operand i of a node, replaying any narrowing the original
        code performed between the producer and this port."""
        expr = self._render_ref(node["operands"][i])
        for ctype in node["casts"][i]:
            expr = self._cast_local(expr, ctype)
        return expr

    def _cast_local(self, expr, ctype):
        """Materialize an intermediate narrowing as a typed local."""
        name = f"cast{self._tmp_n}"
        self._tmp_n += 1
        t = self.em.inj(self.types.resolve(ctype), "t")
        self.em.line(f"    {name}: {t} = {expr}")
        return name

    def _render_const(self, wire_name):
        """A literal operand, recovered from the constant wire's name (the
        compiler encodes the literal text there; see
        C_TO_LOGIC.GET_VAL_STR_FROM_CONST_WIRE)."""
        logic = self.parser_state.FuncLogicLookupTable.get(
            self.schedule["func_entity"]
        )
        try:
            val = C_TO_LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                wire_name, logic, self.parser_state
            )
        except Exception as e:
            raise AutofsmError(
                f"AUTOFSM: cannot recover the value of constant {wire_name!r}: {e}"
            )
        text = str(val).strip()
        try:
            return repr(int(text, 0))
        except ValueError:
            raise AutofsmError(
                f"AUTOFSM: constant {wire_name!r} has non-integer value "
                f"{text!r}, which cannot be regenerated as a literal yet"
            )

    # ── register allocation ────────────────────────────────────────────
    def _cross_state_nodes(self):
        return _CROSS_STATE_NODES(self.nodes, self.schedule["output"], self.n_states)

    # ── main ───────────────────────────────────────────────────────────
    def generate(self):
        from pypeline import Reg, hw_func

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

        # Values crossing a state boundary, bound to registers -- SHARING one
        # register between values that are never live at the same time (see
        # ALLOCATE_REGISTERS; on a heavily shared FSM this is typically the
        # largest single area saving available).
        reg_of, reg_types = ALLOCATE_REGISTERS(
            self.nodes, schedule["output"], self.n_states
        )
        cross = sorted(reg_of)
        reg_names = {nid: f"v{reg_of[nid]}" for nid in cross}

        em.line("@hw_func")
        em.line(f"def {name}(s: {in_stream_t}) -> {out_stream_t}:")
        em.line(f"    st_r: Reg[{st_t}]")
        em.line(f"    in_r: Reg[{in_t}]")
        for idx in sorted(reg_types):
            t = em.inj(self.types.resolve(reg_types[idx]), "t")
            em.line(f"    v{idx}_r: Reg[{t}]")
        em.line(f"    out_data_r: Reg[{out_t}]")
        em.line(f"    out_valid_r: Reg[{u1_t}]")
        em.line(
            "    # Snapshot committed state before any write below "
            "(pypeline assignment is sequential)"
        )
        em.line(f"    st: {st_t} = st_r")
        em.line(f"    in_v: {in_t} = in_r")
        for idx in sorted(reg_types):
            t = em.inj(self.types.resolve(reg_types[idx]), "t")
            em.line(f"    v{idx}: {t} = v{idx}_r")
        for nid in cross:
            self.reg_of_node[nid] = reg_names[nid]
        em.line(f"    o: {out_stream_t}")
        em.line("    o.data = out_data_r")
        em.line("    o.valid = out_valid_r")
        em.line("    out_valid_r = 0")
        em.line("    # Accept a new input only while idle (II == latency)")
        em.line("    if (st == 0) & s.valid:")
        em.line("        in_r = s.data")
        em.line("        st_r = 1")

        # ── shared functional units ──
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

        # ── the final result ──
        # Rendered here, at this indentation, BEFORE the state branches below:
        # assembling a struct or replaying a narrowing cast needs typed locals,
        # and a local first declared inside one branch would have no type on
        # the other paths. Computing it unconditionally costs nothing -- it is
        # combinational either way, and only the register's enable is gated.
        em.line("    # Final result (registered in the last state below)")
        self.cur_state = self.n_states
        out_expr = self._render_ref(schedule["output"])
        for ctype in schedule["output_casts"]:
            out_expr = self._cast_local(out_expr, ctype)

        # ── writebacks and next state ──
        em.line("    # Writebacks and next state")
        for state in range(1, self.n_states + 1):
            kw = "if" if state == 1 else "elif"
            em.line(f"    {kw} st == {state}:")
            for nid in cross:
                if self.nodes[nid]["state"] == state:
                    em.line(f"        {reg_names[nid]}_r = {self.local_of_node[nid]}")
            if state == self.n_states:
                em.line(f"        out_data_r = {out_expr}")
                em.line("        out_valid_r = 1")
                em.line("        st_r = 0")
            else:
                em.line(f"        st_r = {state + 1}")
        em.line("    return o")

        em.globals["hw_func"] = hw_func
        em.globals["Reg"] = Reg
        _seed_struct_globals(
            em, [tag.in_stream_t, tag.out_stream_t, tag.in_type, tag.out_type]
        )
        _seed_struct_globals(em, [t for t, _n in self.mux_shapes])
        _REGISTER_MUX_ENTITIES(self.parser_state, self.mux_shapes)
        return name, em.src(), em.globals

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
        which is exactly the range the area sweep now explores. The narrow
        state->fold-index decode stays an if/elif chain: it is a couple of bits
        wide and feeds the tree's select input, not the data path.
        """
        em = self.em
        n_ports = len(fu_nodes[0][1]["operands"])
        prefix = f"u{self._tmp_n}"
        self._tmp_n += 1
        arg_names = [f"{prefix}_a{i}" for i in range(n_ports)]
        out_local = f"{prefix}_o"
        n_users = len(fu_nodes)

        em.line(
            f"    # {self.schedule['fus'].get(fu, fu)}: {n_users} "
            f"operation(s) sharing one unit"
        )
        exprs = {}
        for nid, node in fu_nodes:
            self.cur_state = node["state"]
            exprs[nid] = [self._render_operand(node, i) for i in range(n_ports)]

        first_nid, first_node = fu_nodes[0]
        if n_users > 1:
            # Which of this unit's users is running: 0 for the first, 1 for the
            # next, and so on in ascending state order (fu_nodes is emitted in
            # node_order, so sort explicitly to make the mapping deterministic).
            sel_name = f"{prefix}_sel"
            sel_t = em.inj(_mux_sel_type(n_users), "t")
            em.line(f"    {sel_name}: {sel_t} = 0")
            for idx, (nid, node) in enumerate(fu_nodes[1:], start=1):
                kw = "if" if idx == 1 else "elif"
                em.line(f"    {kw} st == {node['state']}:")
                em.line(f"        {sel_name} = {idx}")

        for i, arg in enumerate(arg_names):
            port_t = self.types.resolve(first_node["port_types"][i])
            t = em.inj(port_t, "t")
            mux_fn = _mux_callable(port_t, n_users) if n_users > 1 else None
            if mux_fn is None:
                # One user, or a port type that cannot be arrayed: no mux entity
                # (the fallback keeps v1's inline form, which is correct just
                # not as fast).
                em.line(f"    {arg}: {t} = {exprs[first_nid][i]}")
                if n_users > 1:
                    for idx, (nid, node) in enumerate(fu_nodes[1:], start=1):
                        kw = "if" if idx == 1 else "elif"
                        em.line(f"    {kw} st == {node['state']}:")
                        em.line(f"        {arg} = {exprs[nid][i]}")
                continue
            arr_name = f"{prefix}_c{i}"
            arr_t = em.inj(port_t[n_users], "t")
            em.line(f"    {arr_name}: {arr_t}")
            for idx, (nid, _node) in enumerate(fu_nodes):
                em.line(f"    {arr_name}[{idx}] = {exprs[nid][i]}")
            em.line(
                f"    {arg}: {t} = {em.inj(mux_fn, 'mux')}({sel_name}, {arr_name})"
            )
            self._note_mux_entity(port_t, n_users)

        out_ct = em.inj(self.types.resolve(first_node["out_type"]), "t")
        self.cur_state = first_node["state"]
        em.line(
            f"    {out_local}: {out_ct} = "
            + _render_op(
                first_node["op"], arg_names, em, self.parser_state, first_node["entity"]
            )
        )
        for nid, _node in fu_nodes:
            self.local_of_node[nid] = out_local

    def _note_mux_entity(self, t, n):
        """Remember that this FSM instantiates an operand mux of this shape, so
        SYN measures it as its own combinational leaf rather than folding it
        into the FSM's one whole-module timing number. Measured once, cached on
        disk, and read straight back by the next schedule's mux delay lookup --
        the loop that replaces v1's flat MUX_PENALTY_DU guess."""
        self.mux_shapes.append((t, n))


def _REGISTER_MUX_ENTITIES(parser_state, mux_shapes):
    """Mark the operand mux hw_funcs this FSM instantiates as things SYN should
    measure in their own right.

    Needed because a generated FSM holds state, and SYN deliberately treats a
    stateful module as ONE atomic span: it synthesizes the whole module for its
    register-to-register path and never looks inside (see
    SYN.FUNC_PATH_DELAY_IS_ESTIMABLE). That is right for the FSM's own fmax
    number, but it would leave the multiplexers -- the one thing whose cost the
    area search most needs to know honestly -- permanently unmeasured. This
    names them so RECURSIVE_GET_FUNCS_FOR_PATH_DELAYS collects them anyway.

    Records the live callables, not entity names: the names are only assigned
    when the generated source is elaborated, which has not happened yet at code
    generation time.
    """
    if not mux_shapes:
        return
    pending = getattr(parser_state, "pypeline_autofsm_mux_callables", None)
    if pending is None:
        pending = []
        parser_state.pypeline_autofsm_mux_callables = pending
    for t, n in mux_shapes:
        fn = _mux_callable(t, n)
        if fn is not None and fn not in pending:
            pending.append(fn)


def AUTOFSM_MEASURE_ENTITIES(parser_state):
    """FuncLogicLookupTable keys of the operand muxes SYN should measure on
    their own. Empty on any build without AUTOFSM."""
    out = set()
    for fn in getattr(parser_state, "pypeline_autofsm_mux_callables", ()):
        entity = _entity_key_for_callable(parser_state, fn)
        if entity is not None:
            out.add(entity)
    return out


def GENERATE_FSM_SOURCE(tag, schedule, parser_state):
    """Generate the resource-shared FSM as ordinary pypeline source."""
    return _Codegen(tag, schedule, parser_state).generate()


def BUILD_AUTOFSM_FUNC(tag, parser_state, elaborator=None):
    """Elaborator entry point: what hardware an AUTOFSM call site instantiates.

    No schedule installed (bootstrap pass, --comb, --no_synth) -> the
    combinational passthrough. Schedule installed -> the generated FSM.
    Memoized on the tag so several call sites of one tag share one entity.
    """
    tags = getattr(parser_state, "pypeline_autofsm_tags", None)
    if tags is None:
        tags = {}
        parser_state.pypeline_autofsm_tags = tags
    tags[tag.canonical_key] = tag

    if tag._generated is not None:
        return tag._generated
    schedule = tag.schedule
    if schedule is None:
        # Bootstrap pass: alongside putting the real function into the design so
        # its operations get measured, prepare the descent candidates the area
        # search will consider (see PREPARE_SOFT_EQUIVALENTS).
        if elaborator is not None:
            PREPARE_SOFT_EQUIVALENTS(tag, parser_state, elaborator)
        fn = BUILD_PASSTHROUGH_FUNC(tag)
        # Never synthesize the passthrough itself -- see the matching note in
        # SYN.FUNC_PATH_DELAY_IS_ESTIMABLE. It exists to make the tagged
        # function's operations visible to delay measurement, not to be built.
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
                getattr(tag.func, "__name__", "autofsm_func"), tag.func
            )
        name, src, extra_globals = GENERATE_FSM_SOURCE(tag, schedule, parser_state)
        fn = _exec_generated(name, src, extra_globals)
    tag._generated = fn
    return fn


def DUMP_GENERATED_SOURCE(parser_state, out_dir):
    """Write every generated FSM's Python source next to the build output, so a
    problem inside generated code can be read as source instead of inferred from
    VHDL. Best-effort: never fails a build."""
    tags = GET_TAGS(parser_state)
    if not tags or not out_dir:
        return
    try:
        gen_dir = os.path.join(out_dir, "autofsm_generated")
        os.makedirs(gen_dir, exist_ok=True)
        for tag in tags.values():
            fn = tag._generated
            src = getattr(fn, "_autofsm_generated_src", None)
            if src is None:
                continue
            with open(os.path.join(gen_dir, f"{fn.__name__}.py"), "w") as f:
                f.write(src)
    except OSError:
        pass
