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
SCHEDULE_VERSION = 1

# Maximum schedule+synthesize passes before giving up on meeting timing by
# adding states (mirrors SYN.AUTOPIPELINE_MAX_LATENCY_PASSES).
MAX_SCHEDULE_PASSES = 4

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

# Flat delay charged per scheduled operation on top of its own delay, modelling
# the operand mux + writeback enable that sharing introduces. In delay units,
# so 10 == 1.0 ns.
MUX_PENALTY_DU = 10

# Cap on generated entity/function name length, for VHDL identifier safety.
_MAX_NAME_LEN = 96


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
                f"AUTOFSM: wire {wire!r} in {logic.func_name!r} has no driver"
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


def BUILD_DAG(parser_state, func_entity, delays, budget_du):
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
    """
    nodes = {}
    _build_dag_level(
        parser_state, func_entity, delays, budget_du, nodes, prefix="", depth=0
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


def _build_dag_level(parser_state, entity, delays, budget_du, nodes, prefix, depth):
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
        sub_logic = parser_state.FuncLogicLookupTable.get(sub_entity)
        delay_du = delays.get(sub_entity)
        if delay_du is None:
            delay_du = (sub_logic.delay or 0) if sub_logic is not None else 0
        node_id = prefix + inst
        port_names = logic.submodule_instance_to_input_port_names.get(inst, [])
        operands = []
        casts = []
        port_types = []
        for port in port_names:
            port_wire = f"{inst}{C_TO_LOGIC.SUBMODULE_MARKER}{port}"
            ref, cast_chain = _trace_operand(logic, port_wire)
            operands.append(_prefix_ref(ref, prefix, _parent_call_id(prefix)))
            casts.append(cast_chain)
            port_types.append(logic.wire_to_c_type.get(port_wire))

        too_slow_for_a_state = delay_du + MUX_PENALTY_DU > budget_du
        if too_slow_for_a_state and _is_decomposable(
            parser_state, sub_entity, sub_logic
        ):
            # Open it up and schedule its innards instead, so something too slow
            # to fit one state can still be split across several. The node
            # itself does not exist in the DAG; references to it are rewritten
            # to whatever its body produced (see _resolve_inlined).
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
                    sub_entity,
                    delays,
                    budget_du,
                    child_nodes,
                    child_prefix,
                    depth + 1,
                )
                child_out_ref, child_out_casts = _trace_operand(
                    sub_logic, C_TO_LOGIC.RETURN_WIRE_NAME
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
                    "inlined_out": _prefix_ref(child_out_ref, child_prefix, node_id),
                    "inlined_out_casts": child_out_casts,
                    "inlined_inputs": list(sub_logic.inputs),
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


def _scheduled_deps(dag, ref, sched, out):
    """Collect the scheduled nodes a value depends on, seeing through glue."""
    if ref[0] != "node":
        return out
    nid = ref[1]
    if nid in sched:
        out.add(nid)
        return out
    node = dag["nodes"].get(nid)
    if node is None:
        return out
    for operand in node["operands"]:
        _scheduled_deps(dag, operand, sched, out)
    return out


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


def SCHEDULE_DAG(dag, budget_du):
    """List-schedule the DAG into states, binding same-entity operations to one
    shared functional unit each.

    The greedy rule, per state: walk the ready operations in longest-remaining-
    chain order and place one if
      (a) its unit is not already busy this state -- one operation per unit per
          state is exactly what makes the unit shareable rather than duplicated;
      (b) the chain of operations it would join still fits the delay budget; and
      (c) placing it keeps the units' emission order acyclic. Generated source
          declares units in a fixed order, so if unit A feeds unit B in one
          state, B can never feed A in another.
    If nothing at all fits an empty state, the cheapest ready operation is
    forced in alone and the schedule is flagged as at its floor -- one
    indivisible operation that no amount of extra states can speed up.
    """
    nodes = dag["nodes"]
    sched = _scheduled_ids(dag)
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
    fu_of = {nid: nodes[nid]["entity"] for nid in sched}
    fu_edges = {}  # fu -> set of fus it feeds (within some state)
    at_floor = False
    worst_state_du = 0
    unplaced = set(sched)
    state = 0

    while unplaced:
        state += 1
        fus_used = set()
        chain_end = {}
        state_worst = 0
        while True:
            ready = [
                nid
                for nid in unplaced
                if all(p in state_of for p in preds[nid])
                and fu_of[nid] not in fus_used
            ]
            # Deterministic: longest chain first, node id breaks ties.
            ready.sort(key=lambda nid: (-prio[nid], nid))
            placed = None
            for nid in ready:
                same_state_preds = [p for p in preds[nid] if state_of[p] == state]
                start = max((chain_end[p] for p in same_state_preds), default=0)
                end = start + nodes[nid]["delay_du"] + MUX_PENALTY_DU
                if end > budget_du and (fus_used or chain_end):
                    continue
                new_edges = {(fu_of[p], fu_of[nid]) for p in same_state_preds}
                if not _edges_stay_acyclic(fu_edges, new_edges):
                    continue
                if end > budget_du:
                    # Nothing fits an empty state: force this one in alone.
                    at_floor = True
                for a, b in new_edges:
                    fu_edges.setdefault(a, set()).add(b)
                state_of[nid] = state
                chain_end[nid] = end
                fus_used.add(fu_of[nid])
                state_worst = max(state_worst, end)
                placed = nid
                break
            if placed is None:
                break
            unplaced.discard(placed)
        if not fus_used:
            # No progress at all: only possible if every ready node was blocked
            # by the acyclicity rule, which an empty state cannot reproduce.
            raise AutofsmError(
                "AUTOFSM: scheduling stalled with operations left to place "
                "(internal error)"
            )
        worst_state_du = max(worst_state_du, state_worst)

    return {
        "n_states": max(1, state),
        "state_of": state_of,
        "fu_of": fu_of,
        "at_floor": at_floor,
        "worst_state_du": worst_state_du,
        "fu_order": _topological_fu_order(sorted(set(fu_of.values())), fu_edges),
    }


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


def BUILD_SCHEDULE(parser_state, key, tag, budget_scale, prev_schedule=None):
    """Schedule + bind one AUTOFSM'd function into a plain (picklable,
    comparable) schedule dict.

    Pure function of (the function's Logic graphs, its operations' delays,
    budget_scale) -- deliberately independent of the surrounding design, which
    is what makes the driver's loop converge trivially: only an explicit budget
    tightening can change the answer.
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

    dag = _resolve_inlined(BUILD_DAG(parser_state, func_entity, delays, budget_du))
    plan = SCHEDULE_DAG(dag, budget_du)

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
        "budget_scale": budget_scale,
        "budget_du": budget_du,
        "worst_state_du": plan["worst_state_du"],
        "at_floor": plan["at_floor"],
        "nodes": nodes,
        "node_order": sorted(nodes),
        "fus": {fu: fu for fu in plan["fu_order"]},
        "fu_order": plan["fu_order"],
        "output": dag["output"],
        "output_casts": dag["output_casts"],
        "out_type": dag["out_type"],
        "entity_delays_snapshot": delays,
    }
    schedule = dict(schedule_core)
    schedule["entity"] = _schedule_entity_name(func_entity, schedule_core)
    return schedule


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


def HARVEST_AUTOFSM_SCHEDULES(parser_state, budget_scales=None, prev_schedules=None):
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
        schedules[key] = BUILD_SCHEDULE(
            parser_state,
            key,
            tag,
            budget_scales.get(key, DEFAULT_BUDGET_SCALE),
            prev_schedules.get(key),
        )
    return schedules


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
    return (
        f"AUTOFSM {key}: {n_ops} ops -> {n_fus} shared unit(s), "
        f"{schedule['n_states']} states, latency {schedule['latency']} clks, "
        f"budget {budget_ns:.2f} ns/state (scale {schedule['budget_scale']:.3f}), "
        f"worst state {worst_ns:.2f} ns{floor}"
    )


def DESCRIBE_FUS(schedule):
    """Per-unit fold counts: 'this operation appears N times in the pure
    function and became 1 instance'. Sorted lines for the build log."""
    counts = {}
    for node in schedule["nodes"].values():
        if not node.get("fu"):
            continue
        counts[node["entity"]] = counts.get(node["entity"], 0) + 1
    return [
        f"  {entity} x{count} -> 1 unit" for entity, count in sorted(counts.items())
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

        for t in (tag.in_type, tag.out_type, tag.in_stream_t, tag.out_stream_t):
            self.types.seed(t)
        for entity in schedule["fus"]:
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
        """Scheduled results that must survive into a later state, and so need
        a register. Everything else stays a combinational local.

        Uses is computed through glue: a field read in state 5 of a value
        produced in state 2 is still a state-2-to-state-5 use, because the glue
        itself is re-rendered in state 5 rather than stored.
        """
        dag = {"nodes": self.nodes}
        sched = {nid for nid, n in self.nodes.items() if n["delay_du"] > 0}
        used_in_states = {nid: set() for nid in sched}
        for consumer in self.nodes.values():
            if consumer["delay_du"] <= 0:
                continue  # glue is recomputed where used, never stored
            for operand in consumer["operands"]:
                for dep in _scheduled_deps(dag, operand, sched, set()):
                    used_in_states[dep].add(consumer["state"])
        # The final result is assembled in the last state.
        for dep in _scheduled_deps(dag, self.schedule["output"], sched, set()):
            used_in_states[dep].add(self.n_states)
        return {
            nid: self.nodes[nid]["out_type"]
            for nid in sched
            if any(s > self.nodes[nid]["state"] for s in used_in_states[nid])
        }

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

        cross = self._cross_state_nodes()
        reg_names = {nid: f"v{i}" for i, nid in enumerate(sorted(cross))}

        em.line("@hw_func")
        em.line(f"def {name}(s: {in_stream_t}) -> {out_stream_t}:")
        em.line(f"    st_r: Reg[{st_t}]")
        em.line(f"    in_r: Reg[{in_t}]")
        for nid in sorted(cross):
            t = em.inj(self.types.resolve(cross[nid]), "t")
            em.line(f"    {reg_names[nid]}_r: Reg[{t}]")
        em.line(f"    out_data_r: Reg[{out_t}]")
        em.line(f"    out_valid_r: Reg[{u1_t}]")
        em.line(
            "    # Snapshot committed state before any write below "
            "(pypeline assignment is sequential)"
        )
        em.line(f"    st: {st_t} = st_r")
        em.line(f"    in_v: {in_t} = in_r")
        for nid in sorted(cross):
            t = em.inj(self.types.resolve(cross[nid]), "t")
            em.line(f"    {reg_names[nid]}: {t} = {reg_names[nid]}_r")
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
            fu_nodes = [
                (nid, self.nodes[nid])
                for nid in schedule["node_order"]
                if self.nodes[nid].get("fu") == fu
            ]
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
            for nid in sorted(cross):
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
        return name, em.src(), em.globals

    def _emit_fu(self, fu, fu_nodes):
        """Emit one shared unit: its per-state operand multiplexers and its
        single call site.

        Every operand expression is rendered FIRST, at this block's own
        indentation, before any `if` is written. Rendering can emit typed locals
        (for narrowing casts and inline glue), and a local first declared inside
        one branch would have no type on the other paths -- so they must all
        land above the multiplexer, not inside it.
        """
        em = self.em
        n_ports = len(fu_nodes[0][1]["operands"])
        prefix = f"u{self._tmp_n}"
        self._tmp_n += 1
        arg_names = [f"{prefix}_a{i}" for i in range(n_ports)]
        out_local = f"{prefix}_o"

        em.line(f"    # {fu}: {len(fu_nodes)} operation(s) sharing one unit")
        exprs = {}
        for nid, node in fu_nodes:
            self.cur_state = node["state"]
            exprs[nid] = [self._render_operand(node, i) for i in range(n_ports)]

        # The first user's operands double as the multiplexer default, so no
        # zero literal is needed for struct-typed ports (and the mux is smaller).
        first_nid, first_node = fu_nodes[0]
        for i, arg in enumerate(arg_names):
            t = em.inj(self.types.resolve(first_node["port_types"][i]), "t")
            em.line(f"    {arg}: {t} = {exprs[first_nid][i]}")
        for idx, (nid, node) in enumerate(fu_nodes[1:], start=1):
            kw = "if" if idx == 1 else "elif"
            em.line(f"    {kw} st == {node['state']}:")
            for i, arg in enumerate(arg_names):
                em.line(f"        {arg} = {exprs[nid][i]}")

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
