"""Selective native execution of graphs containing user fixed-latency pipelines.

Imported only after pypeline's live-dependency gate finds a nonzero declaration.
The stage map and register lifetimes are the same objects used by VHDL emission;
user pipeline bodies remain ordinary register-aware Python calls.
"""

import ast
import copy
import inspect
import os
import weakref

import AUTOFSM
import C_TO_LOGIC as C
import PY_TO_LOGIC as PY
import SYN
import VHDL
import pypeline as p

_prepared = weakref.WeakKeyDictionary()
_installed = weakref.WeakSet()
_native_body = 0
_REG_KEY = "__sim_pipeline_wires__"
_DELAY_KEY = "__sim_pipeline_leaf__"


def _native(func, args, kwargs=None, atomic=False):
    global _native_body
    cell = getattr(func, "_sim_model_cell", None)
    saved = cell[0] if cell is not None else None
    if saved is not None and getattr(saved[0], "_pipeline_dispatch", False):
        cell[0] = saved[0]._original
    _native_body += int(atomic)
    try:
        return func(*args, **(kwargs or {}))
    finally:
        _native_body -= int(atomic)
        if cell is not None:
            cell[0] = saved


def _delay(value, cycles, typ, key):
    if not cycles:
        return value
    path = p._sim_current_inst_path()
    old = p._sim_reg_read(path, key, None)
    if old is None:
        old = [p.sim_zero(typ) for _ in range(cycles)]
    p._sim_reg_write(path, key, old[1:] + [copy.deepcopy(value)])
    return copy.deepcopy(old[0])


class _Graph:
    def __init__(self, inst, state, timing, types, contains):
        self.inst, self.state, self.timing, self.types = inst, state, timing, types
        self.logic = state.LogicInstLookupTable[inst]
        self.tp = timing[inst]
        self.timing_signature = [
            (
                name[len(inst) :],
                tuple(tp._slices),
                tp._has_input_regs,
                tp._has_output_regs,
                tp._exact_bit_boundaries,
            )
            for name, tp in sorted(timing.items())
            if name == inst or name.startswith(inst + C.SUBMODULE_MARKER)
        ]
        self.map = SYN.GET_PIPELINE_MAP(inst, self.logic, state, timing)
        self.ranges = VHDL.PiplineHDLParams(
            inst, self.logic, state, timing, self.map
        ).wire_to_reg_stage_start_end
        self.children = {}
        self.ops = {}
        self.callables = state.pypeline_entity_callables
        for sub, entity in self.logic.submodule_instances.items():
            child_inst = inst + C.SUBMODULE_MARKER + sub
            child = state.LogicInstLookupTable[child_inst]
            if (
                contains(entity)
                and entity not in state.func_fixed_latency
                and child.CAN_HAVE_ADDED_LATENCY(state)
            ) or entity.startswith(
                (C.VAR_REF_RD_FUNC_NAME_PREFIX, C.VAR_REF_ASSIGN_FUNC_NAME_PREFIX)
            ):
                self.children[sub] = _Graph(child_inst, state, timing, types, contains)
            elif entity not in self.callables:
                self.ops[sub] = AUTOFSM.DECODE_OP(self.logic, sub, entity, state)
        self.constants = {}
        for wire in self.logic.wires:
            if C.WIRE_IS_CONSTANT(wire):
                text = C.GET_VAL_STR_FROM_CONST_WIRE(wire, self.logic, state)
                typ = self.type(wire)
                value = (
                    p.sim_zero(typ)
                    if text == C.COMPOUND_NULL
                    else ast.literal_eval(text)
                )
                self.constants[wire] = self.cast(wire, value)

    def type(self, wire):
        return self.types.resolve(self.logic.wire_to_c_type[wire])

    def cast(self, wire, value):
        return p._sim_cast_deep(value, self.type(wire))

    def _op(self, sub, values):
        op = self.ops[sub]
        kind = op["kind"]
        if kind == "copy":
            return values[0]
        if kind == "ref":
            result = values[0]
            for tok in op["toks"]:
                result = (
                    result[int(tok)] if str(tok).isdigit() else getattr(result, tok)
                )
            return result
        if kind == "assemble":
            result = p.sim_zero(
                self.type(sub + C.SUBMODULE_MARKER + C.RETURN_WIRE_NAME)
            )
            for path, value in zip(op["paths"], values):
                result = p._sim_lens_set(result, path, value)
            return result
        if kind == "mux":
            return values[1] if values[0] else values[2]
        if kind == "bitmanip":
            if op["builtin"] == "__slice__":
                high, low = op["consts"]
                return values[0][high] if high == low else values[0][high:low]
            return getattr(p, op["builtin"])(*values, *op["consts"])
        if kind == "shift":
            return eval("a " + op["op"] + " b", {}, {"a": values[0], "b": op["amount"]})
        if kind == "unaryop":
            return eval(op["op"] + "a", {}, {"a": values[0]})
        if kind == "binop":
            return eval("a " + op["op"] + " b", {}, {"a": values[0], "b": values[1]})
        raise RuntimeError(f"pipeline_latency: unsupported operation {op}")

    def _call(self, sub, args, enable):
        entity = self.logic.submodule_instances[sub]
        inst = self.inst + C.SUBMODULE_MARKER + sub
        child = self.state.LogicInstLookupTable[inst]
        meta = self.logic.submodule_instance_to_ast_meta.get(sub)
        loc = (
            getattr(meta, "src_file", ""),
            getattr(meta, "line", 0),
            getattr(meta, "col", None),
            getattr(meta, "end_col", None),
        )
        p._sim_inst_stack.append(("PIPELINE:" + inst, loc))
        # Disabled hardware still has combinational outputs, but its registers
        # must not advance. Discard only this evaluation's pending state writes.
        buffer = p._sim_reg_write_buffer
        if not enable:
            p._sim_reg_write_buffer = {}
        try:
            if sub in self.children:
                return self.children[sub](*args)
            if entity in self.callables:
                result = _native(
                    self.callables[entity],
                    args,
                    atomic=entity in self.state.func_fixed_latency,
                )
            else:
                result = self._op(sub, args)
            if not child.outputs:
                return result
            typ = self.types.resolve(child.wire_to_c_type[C.RETURN_WIRE_NAME])
            result = p._sim_cast_deep(result, typ)
            # Stateful/fixed bodies supply their own clocks; ordinary pure
            # leaves can be emulated with the existing output-delay technique.
            latency = self.timing[inst].GET_TOTAL_LATENCY(self.state, self.timing)
            if (
                entity in self.state.func_fixed_latency
                or child.uses_nonvolatile_state_regs
            ):
                latency = 0
            return _delay(result, latency, typ, _DELAY_KEY)
        finally:
            if not enable:
                p._sim_reg_write_buffer = buffer
            p._sim_inst_stack.pop()

    def __call__(self, *args, **kwargs):
        logic = self.logic
        path = p._sim_current_inst_path()
        old = p._sim_reg_read(path, _REG_KEY, {})
        values = dict(self.constants)
        for port, arg in zip(logic.inputs, args):
            values[port] = self.cast(port, arg)
        for port, arg in kwargs.items():
            values[port] = self.cast(port, arg)
        values[C.CLOCK_ENABLE_NAME] = p.uint1_t(1)
        if self.tp._has_input_regs:
            current = {port: values[port] for port in logic.inputs}
            for port in logic.inputs:
                values[port] = copy.deepcopy(
                    old.get(("input", port), p.sim_zero(self.type(port)))
                )
        else:
            current = {}
        for wire in logic.read_only_global_wires:
            original = next(
                (
                    name
                    for name, rb in logic.readback_global_wires.items()
                    if rb == wire
                ),
                wire,
            )
            values[wire] = p._sim_wire_read(
                self.state.pypeline_global_wire_names[original]
            )
        pending = {}
        outputs = {}

        def read(wire, stage):
            # VHDL expressions/functions have no physical input-port wire.
            # Their driver is read at the operation's stage, even when the
            # graph recorded the alias connection in an earlier stage.
            if wire not in self.ranges and wire in logic.wire_driven_by:
                return self.cast(wire, read(logic.wire_driven_by[wire], stage))
            start, end = self.ranges.get(wire, (None, None))
            if start is not None and start < stage and wire not in self.constants:
                return copy.deepcopy(
                    old.get((wire, stage - 1), p.sim_zero(self.type(wire)))
                )
            if wire in values:
                return values[wire]
            driver = logic.wire_driven_by.get(wire)
            if driver is not None:
                return self.cast(wire, read(driver, stage))
            raise RuntimeError(
                f"pipeline_latency: undriven {logic.func_name}.{wire} at stage {stage}"
            )

        def level(info, stage):
            for driver, driven in info.driver_driven_wire_pairs:
                values[driven] = self.cast(driven, read(driver, stage))
            for sub in info.submodule_insts:
                entity = logic.submodule_instances[sub]
                child = self.state.FuncLogicLookupTable[entity]
                prefix = sub + C.SUBMODULE_MARKER
                arguments = [read(prefix + port, stage) for port in child.inputs]
                enable = (
                    read(prefix + C.CLOCK_ENABLE_NAME, stage)
                    if C.LOGIC_NEEDS_CLOCK_ENABLE(child, self.state)
                    else True
                )
                result = self._call(sub, arguments, enable)
                for port in child.outputs:
                    outputs[prefix + port] = result
                    values[prefix + port] = result

        for network in (
            self.map.const_network_stage_info,
            self.map.read_only_global_network_stage_info,
        ):
            if network:
                for info in network.submodule_level_infos:
                    level(info, 0)
        for stage, info in enumerate(self.map.stage_infos[: self.map.num_stages]):
            for wire in info.submodule_output_ports:
                values[wire] = outputs[wire]
            for sublevel in info.submodule_level_infos:
                level(sublevel, stage)
            for wire, (start, end) in self.ranges.items():
                if start is not None and end is not None and start <= stage <= end:
                    pending[(wire, stage)] = copy.deepcopy(read(wire, stage))
        for port, value in current.items():
            pending[("input", port)] = copy.deepcopy(value)
        p._sim_reg_write(path, _REG_KEY, pending)
        for wire in logic.write_only_global_wires:
            start, _ = self.ranges.get(wire, (0, 0))
            p._sim_wire_write(
                self.state.pypeline_global_wire_names[wire],
                copy.deepcopy(read(wire, start or 0)),
            )
        if C.RETURN_WIRE_NAME not in logic.outputs:
            return None
        result = read(C.RETURN_WIRE_NAME, self.map.num_stages - 1)
        if self.tp._has_output_regs:
            result = _delay(
                result, 1, self.type(C.RETURN_WIRE_NAME), "__sim_pipeline_output__"
            )
        return copy.deepcopy(result)


def prepare(roots, build_timing=None):
    """Prepare affected live roots, retaining native bodies wherever sufficient."""
    roots = [
        fn
        for fn in roots
        if getattr(fn, "_pipeline_latency", None) is None
        and p._pipeline_latency_reachable(fn)
    ]
    if not roots:
        return set()
    if set(roots) == set(_prepared) and all(
        _prepared[fn] == build_timing for fn in roots
    ):
        return set(_installed)
    # A dispatch closure belongs to one prepared hierarchy. Switching live
    # roots must also switch shared helper models; retaining an old per-root
    # cache entry after another hierarchy replaced its cells loses state paths.
    # The ordinary register store retains each root's state across switches.
    for fn in _installed:
        cell = fn._sim_model_cell
        if cell[0] is not None and getattr(cell[0][0], "_pipeline_dispatch", False):
            cell[0] = cell[0][0]._original
    _installed.clear()
    _prepared.clear()
    p._pipeline_latency_preparing = True
    try:
        state = PY.ELABORATE_LIVE_ROOTS(roots)
        timing = {
            name: SYN.TimingParams(name, logic)
            for name, logic in state.LogicInstLookupTable.items()
        }
        if build_timing:
            for name, tp in timing.items():
                if name in build_timing:
                    slices, inputs, outputs, bits, delay = build_timing[name]
                    tp._slices, tp._has_input_regs, tp._has_output_regs = (
                        list(slices),
                        inputs,
                        outputs,
                    )
                    tp._exact_bit_boundaries = copy.copy(bits)
                    tp.logic.delay = delay
        types = AUTOFSM._TypeResolver()
        for fn in state.pypeline_entity_callables.values():
            types.seed_callable(fn)
            for value in inspect.unwrap(fn).__globals__.values():
                if PY._is_real_hw_ctype(value):
                    types.seed(value)
        memo = {}

        def contains(entity):
            if entity not in memo:
                memo[entity] = state.func_fixed_latency.get(entity, 0) > 0
                if entity not in state.func_fixed_latency:
                    memo[entity] = any(
                        contains(sub)
                        for sub in state.FuncLogicLookupTable[
                            entity
                        ].submodule_instances.values()
                    )
            return memo[entity]

        models = {}
        # Only outermost sliceable regions need dispatch. Their graph evaluator
        # recursively handles inner instances with their exact timing variants.
        def visit(inst):
            logic = state.LogicInstLookupTable[inst]
            entity = logic.func_name
            if entity in state.func_fixed_latency:
                return
            if contains(entity) and logic.CAN_HAVE_ADDED_LATENCY(state):
                fn = state.pypeline_entity_callables.get(entity)
                if fn is not None:
                    graph = _Graph(inst, state, timing, types, contains)
                    needs = any(
                        a is not None and b is not None and a <= b
                        for a, b in graph.ranges.values()
                    )
                    needs |= graph.tp._has_input_regs or graph.tp._has_output_regs
                    needs |= bool(build_timing)
                    # The ordinary simulator can identify two stateful calls
                    # on the same source line as one instance (Python 3.8 has
                    # no instruction columns). The graph carries both exact
                    # hardware paths, even if no balancing registers are needed.
                    entities = list(logic.submodule_instances.values())
                    needs |= any(
                        contains(entity) and entities.count(entity) > 1
                        for entity in set(entities)
                    )
                    if needs:
                        models.setdefault(fn, []).append(graph)
                        return
            for sub in logic.submodule_instances:
                visit(inst + C.SUBMODULE_MARKER + sub)

        for root in state.main_mhz:
            visit(root)
        for fn, graphs in models.items():
            cell = fn._sim_model_cell
            signature = inspect.signature(fn)
            original = cell[0]
            if original is not None and getattr(
                original[0], "_pipeline_dispatch", False
            ):
                original = original[0]._original

            def dispatch(
                *args,
                _fn=fn,
                _graphs=graphs,
                _original=original,
                _signature=signature,
                **kwargs,
            ):
                if _native_body:
                    cell = _fn._sim_model_cell
                    saved, cell[0] = cell[0], _original
                    try:
                        return _fn(*args, **kwargs)
                    finally:
                        cell[0] = saved
                graph = _graphs[0]
                if len(_graphs) > 1:
                    loc = p._sim_inst_stack[-1][1]
                    locations = [frame[1] for frame in p._sim_inst_stack]
                    matches = []
                    for candidate in _graphs:
                        parent, _, sub = candidate.inst.rpartition(C.SUBMODULE_MARKER)
                        if parent:
                            meta = state.LogicInstLookupTable[
                                parent
                            ].submodule_instance_to_ast_meta.get(sub)
                            if meta and any(
                                os.path.abspath(meta.src_file)
                                == os.path.abspath(site[0])
                                and meta.line == site[1]
                                and (site[2] is None or meta.col == site[2])
                                for site in locations
                            ):
                                matches.append(candidate)
                    if len(matches) == 1:
                        graph = matches[0]
                    elif any(
                        g.timing_signature != graph.timing_signature
                        for g in _graphs[1:]
                    ):
                        raise RuntimeError(
                            f"pipeline_latency: ambiguous timing variant for {_fn.__qualname__} at {loc}"
                        )
                bound = _signature.bind(*args, **kwargs)
                bound.apply_defaults()
                return graph(**bound.arguments)

            dispatch._pipeline_dispatch = True
            dispatch._original = original
            cell[0] = (dispatch, "hw_func", True)
            _installed.add(fn)
        for fn in roots:
            _prepared[fn] = build_timing
        return set(models)
    finally:
        p._pipeline_latency_preparing = False
