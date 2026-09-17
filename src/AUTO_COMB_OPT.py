"""Combinational HLS lowering and shared candidate preparation.

See docs/AUTO_COMB_OPT_DESIGN.md. The generated function is ordinary pure
Pypeline, so all backends and the pipeline placer see its internal graph.
"""
import copy
import inspect
import os

import AUTO

# Immutable graph choices, never live functions/types from an earlier parse.
# A choice stays pinned while timing measurements accumulate during a build.
_PLANS = {}


def check_pure(parser_state, entity, seen=None):
    seen = set() if seen is None else seen
    if entity in seen:
        return
    seen.add(entity)
    logic = parser_state.FuncLogicLookupTable.get(entity)
    if logic is None:
        raise AUTO.AutoError("AUTO_COMB_OPT: unresolved operation " + entity)
    if (logic.state_regs or logic.feedback_vars or logic.read_only_global_wires
            or logic.write_only_global_wires or logic.sub_inst_to_auto_pipeline_key
            or logic.sub_inst_to_auto_fsm_key
            or parser_state.func_fixed_latency.get(entity, 0) > 0):
        raise AUTO.AutoError(
            "AUTO_COMB_OPT: " + entity + " is not pure combinational logic (state, global wires or temporal AUTO call)"
        )
    if logic.vhdl_module_text is not None:
        raise AUTO.AutoError("AUTO_COMB_OPT: raw VHDL purity cannot be established: " + entity)
    for sub in logic.submodule_instances.values():
        if "CLOCK_ENABLE" not in sub:
            check_pure(parser_state, sub, seen)


class CombEmitter(AUTO._GraphCodegen):
    """Emit one candidate graph as a pure @hw_func: one local per node."""

    def __init__(self, func, entity, dag, parser_state):
        self.parser_state = parser_state
        self.nodes = dag["nodes"]
        self.func_entity = entity
        self.em = AUTO._Emitter()
        self.types = AUTO._TypeResolver()
        self.types.seed_callable(func)
        for callable_ in AUTO._entity_callables(parser_state).values():
            self.types.seed_callable(callable_)
        self._tmp_n = 0
        self.locals = {}
        self.dag = dag
        self.func = func

    def _render_ref(self, ref):
        if ref[0] == "in":
            return ref[1]
        if ref[0] == "const":
            return self._render_const(ref[1])
        if ref[0] == "lit":
            return self._cast_local(repr(ref[1]), ref[2])
        if ref[0] != "node":
            raise AUTO.AutoError("AUTO_COMB_OPT: unknown reference " + repr(ref))
        nid = ref[1]
        if nid not in self.locals:
            node = self.nodes[nid]
            expression = self._render_glue(nid, node)
            self.locals[nid] = self._cast_local(expression, node["out_type"])
        return self.locals[nid]

    def generate(self, name):
        import pypeline

        signature = inspect.signature(self.func)
        args = []
        params = list(signature.parameters.values())
        for index, p in enumerate(params):
            if p.kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY):
                raise AUTO.AutoError("AUTO_COMB_OPT: variadic hardware arguments are unsupported")
            if p.kind == p.KEYWORD_ONLY and (index == 0 or params[index - 1].kind != p.KEYWORD_ONLY):
                args.append("*")
            arg = f"{p.name}: {self.em.inj(p.annotation, 't')}"
            if p.default is not p.empty:
                arg += " = " + self.em.inj(p.default, "default")
            args.append(arg)
            if p.kind == p.POSITIONAL_ONLY and (index + 1 == len(params) or params[index + 1].kind != p.POSITIONAL_ONLY):
                args.append("/")
        result_t = self.em.inj(pypeline.hw_return_type(self.func), "t")
        self.em.inj_named(pypeline.hw_func, "hw_func")
        self.em.line("@hw_func")
        self.em.line(f"def {name}({', '.join(args)}) -> {result_t}:")
        # Eager topological emission avoids Python recursion on arithmetic chains.
        for nid in AUTO.order(self.dag):
            self._render_ref(["node", nid])
        result = self._render_ref(self.dag["output"])
        for t in self.dag["output_casts"]:
            result = self._cast_local(result, t)
        self.em.line(f"    return {result}")
        source = self.em.src()
        fn = AUTO._exec_generated(name, source, self.em.globals)
        fn._auto_comb_opt_generated_src = source
        return fn


def _semantic_graph(dag):
    rv = copy.deepcopy(dag)
    for n in rv["nodes"].values():
        n["delay_du"] = 0
    return rv


def _literal(parser_state, entity, ref):
    if ref[0] == "lit":
        return ref[1]
    if ref[0] != "const":
        return None
    import C_TO_LOGIC

    try:
        return int(str(C_TO_LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
            ref[1], parser_state.FuncLogicLookupTable[entity], parser_state)), 0)
    except (ValueError, TypeError):
        return None


def _known_bits(dag, parser_state, entity):
    """Conservative unsigned upper-bit bounds; unknown/signed values stay full."""
    known = {}
    logic = parser_state.FuncLogicLookupTable[entity]

    def operand_bits(ref, casts, port_type):
        if not AUTO._unsigned(port_type) or any(not AUTO._unsigned(t) for t in casts):
            return AUTO.width(port_type)
        if ref[0] == "node":
            producer = dag["nodes"][ref[1]]
            n = known.get(ref[1], AUTO.width(producer["out_type"])) if AUTO._unsigned(producer["out_type"]) else AUTO.width(port_type)
        elif ref[0] == "in":
            t = logic.wire_to_c_type[ref[1]]
            n = AUTO.width(t) if AUTO._unsigned(t) else AUTO.width(port_type)
        else:
            value = _literal(parser_state, entity, ref)
            n = max(1, value.bit_length()) if value is not None and value >= 0 else AUTO.width(port_type)
        return min([n, AUTO.width(port_type)] + [AUTO.width(t) for t in casts])

    inputs = {}
    for nid in AUTO.order(dag):
        node = dag["nodes"][nid]
        bounds = [operand_bits(r, c, t) for r, c, t in zip(node["operands"], node["casts"], node["port_types"])]
        inputs[nid] = bounds
        result = AUTO.width(node["out_type"])
        if AUTO._unsigned(node["out_type"]) and all(AUTO._unsigned(t) for t in node["port_types"]):
            op = node["op"].get("op")
            if node["kind"] == "binop" and op in ("+", "*", "&", "|", "^"):
                result = {"+": max(bounds) + 1, "*": sum(bounds), "&": min(bounds), "|": max(bounds), "^": max(bounds)}[op]
            elif node["kind"] == "mux":
                result = max(bounds[1:])
            elif node["kind"] == "copy":
                result = bounds[0]
        known[nid] = min(result, AUTO.width(node["out_type"]))
    return inputs


def _implementation_seeds(func, entity, dag, parser_state, elaborator):
    """Materialize exact integer choices and selective hierarchy opening."""
    from types import SimpleNamespace

    seeds = []
    # Existing soft equivalents carry the signedness/oversized-shift safeguards.
    AUTO.PREPARE_SOFT_EQUIVALENTS(SimpleNamespace(func=func), parser_state, elaborator)
    subtree = AUTO._subtree_entities(parser_state, entity)
    openable = [e for e in sorted(subtree) if e != entity
                and AUTO._is_decomposable(parser_state, e, parser_state.FuncLogicLookupTable.get(e))]
    if openable:
        try:
            opened = AUTO._resolve_inlined(AUTO.BUILD_DAG(
                parser_state, entity, {}, float("inf"), opened=openable))
            if len(opened["nodes"]) <= AUTO.MAX_NODES:
                seeds.append((opened, ["helper decomposition"]))
        except AUTO.AutoError:
            pass
    # Opening both DIV and MOD exposes their common restoring arithmetic;
    # ordinary typed CSE then retains one copy, including shared remainder work.
    equiv = AUTO._soft_equivalents(parser_state)
    available = sorted({n["entity"] for n in dag["nodes"].values()} & set(equiv))
    if available:
        try:
            opened = AUTO._resolve_inlined(AUTO.BUILD_DAG(
                parser_state, entity, {}, float("inf"), opened=available + openable))
            if len(opened["nodes"]) <= AUTO.MAX_NODES:
                seeds.append((opened, ["soft operator decomposition"]))
        except AUTO.AutoError:
            pass
    try:
        from operators.comb_opt import make_constant_mult, make_power_of_two, make_narrow_binary, make_distributed
    except ImportError:
        return seeds
    types = AUTO._TypeResolver()
    types.seed_callable(func)
    needed = AUTO._demanded_bits(dag)
    known_inputs = _known_bits(dag, parser_state, entity)
    trial = copy.deepcopy(dag)
    moves = []
    for nid in AUTO.order(dag):
        n = dag["nodes"][nid]
        op = n["op"].get("op")
        live = AUTO._entity_callables(parser_state).get(n["entity"])
        if live is not None:
            original = inspect.unwrap(live)
            if original.__module__ == "operators.soft_div" and original.__name__ in ("soft_div_radix", "soft_div_restoring"):
                closure = inspect.getclosurevars(original).nonlocals
                if "want_remainder" in closure:
                    op = "%" if closure["want_remainder"] else "/"
        if op is None or len(n["operands"]) != 2 or not all(AUTO._unsigned(t) for t in n["port_types"] + [n["out_type"]]):
            continue
        factory_func = None
        indices = list(range(len(n["operands"])))
        for i in range(2):
            value = _literal(parser_state, entity, n["operands"][i])
            if value is None:
                continue
            if any(not AUTO._unsigned(t) for t in n["casts"][i]):
                # Keep signed intermediate casts: masking alone would lose
                # sign extension when the final operand type is unsigned.
                continue
            for t in n["casts"][i] + [n["port_types"][i]]:
                value &= (1 << AUTO.width(t)) - 1
            if op == "*":
                factory_func = make_constant_mult(types.resolve(n["port_types"][1 - i]), types.resolve(n["out_type"]), value)
                indices = [1 - i]
                label = "constant multiply"
            elif op in ("/", "%") and i == 1 and value > 0 and value & (value - 1) == 0:
                factory_func = make_power_of_two(types.resolve(n["port_types"][0]), types.resolve(n["out_type"]), value.bit_length() - 1, op == "%")
                indices = [0]
                label = "power-of-two arithmetic"
            if factory_func is not None:
                break
        bits = needed[nid]
        widths = [min(bits, bound) for bound in known_inputs[nid]]
        if (factory_func is None and op in ("+", "-", "*", "&", "|", "^") and bits > 0
                and any(w < AUTO.width(t) for w, t in zip(widths, n["port_types"]))):
            factory_func = make_narrow_binary(types.resolve(n["port_types"][0]), types.resolve(n["port_types"][1]), types.resolve(n["out_type"]), bits, ("+", "-", "*", "&", "|", "^").index(op), *widths)
            label = "demanded/known-bit narrowing"
        if factory_func is None:
            continue
        replacement = elaborator._elaborate_live_func(factory_func.__name__, factory_func)
        AUTO._RESOLVE_BUILTIN_SUBMODULES(parser_state, replacement.func_name)
        trial["nodes"][nid] = dict(n, kind="call", op={"kind": "call"}, entity=replacement.func_name,
            operands=[n["operands"][i] for i in indices], casts=[n["casts"][i] for i in indices],
            port_types=[n["port_types"][i] for i in indices])
        moves.append(label)
    if moves:
        seeds.append((trial, sorted(set(moves))))
    # Uniform low-bit arithmetic is a modular ring even when the elaborator's
    # full multiply/add outputs are wider than their annotated consumers.
    for nid in AUTO.order(dag):
        n = dag["nodes"][nid]
        bits = needed[nid]
        if n["op"].get("op") != "+" or n["kind"] != "binop" or bits <= 0 or any(r[0] != "node" for r in n["operands"]):
            continue
        a, b = [dag["nodes"][r[1]] for r in n["operands"]]
        if any(x["op"].get("op") != "*" or x["kind"] != "binop" for x in (a, b)):
            continue
        if any(not AUTO._unsigned(t) for x in (n, a, b)
               for t in x["port_types"] + [x["out_type"]] + [t for c in x["casts"] for t in c]):
            continue
        # Leaf operand casts are replayed before widening in the helper. Only
        # truncations between the products and sum must preserve all K bits.
        if any(AUTO.width(t) < bits for t in n["port_types"] + [a["out_type"], b["out_type"]]
               + [t for chain in n["casts"] for t in chain]):
            continue
        for ai in range(2):
            for bi in range(2):
                if (a["operands"][ai], a["casts"][ai], a["port_types"][ai]) != (b["operands"][bi], b["casts"][bi], b["port_types"][bi]):
                    continue
                factory = make_distributed(types.resolve(a["port_types"][ai]),
                    types.resolve(a["port_types"][1-ai]), types.resolve(b["port_types"][1-bi]),
                    types.resolve(n["out_type"]), bits)
                logic = elaborator._elaborate_live_func(factory.__name__, factory)
                AUTO._RESOLVE_BUILTIN_SUBMODULES(parser_state, logic.func_name)
                factored = copy.deepcopy(dag)
                factored["nodes"][nid] = dict(n, kind="call", op={"kind": "call"}, entity=logic.func_name,
                    operands=[a["operands"][ai], a["operands"][1-ai], b["operands"][1-bi]],
                    casts=[a["casts"][ai], a["casts"][1-ai], b["casts"][1-bi]],
                    port_types=[a["port_types"][ai], a["port_types"][1-ai], b["port_types"][1-bi]])
                seeds.append((AUTO.prune(factored), ["modular arithmetic factoring"]))
    return seeds


def prepare(func, parser_state, elaborator, strict=True, objective="area"):
    """Materialize graph alternatives once per parser state for AUTO_COMB_*_OPT and AUTO_FSM."""
    import SYN

    if (getattr(func, "_is_auto_comb_area_opt_pragma", False)
            or getattr(func, "_is_auto_comb_delay_opt_pragma", False)):
        chosen = BUILD_FUNC(func, parser_state, elaborator)
        return prepare(chosen, parser_state, elaborator, strict, objective)
    logic = elaborator._elaborate_live_func(getattr(func, "__name__", "comb"), func)
    entity = logic.func_name
    table_attr = "pypeline_comb_delay_opt_candidates" if objective == "delay" else "pypeline_comb_area_opt_candidates"
    table = getattr(parser_state, table_attr, None)
    if table is None:
        table = {}
        setattr(parser_state, table_attr, table)
    if entity in table:
        return table[entity]
    AUTO._RESOLVE_BUILTIN_SUBMODULES(parser_state, entity)
    try:
        check_pure(parser_state, entity)
    except AUTO.AutoError:
        if strict:
            raise
        return []
    # A scoped implementation may affect its entire call tree. Flattening that
    # tree into a new Python scope would lose the inherited dispatch context.
    # Until scopes are carried on DAG nodes, retain the exact original instead.
    import pypeline

    callables = AUTO._entity_callables(parser_state)
    if any(id(callables.get(e)) in pypeline._scoped_funcs
           and not getattr(callables.get(e), "_hls_primitive_scope", False)
           for e in AUTO._subtree_entities(parser_state, entity)):
        table[entity] = [(func, {"moves": [], "unsupported": "scoped operator implementations retained"})]
        return table[entity]
    # Initialize the same target selection the driver uses after parsing.
    SYN.PART_SET_TOOL(parser_state.part, allow_fail=True)
    AUTO._seed_struct_widths(parser_state)
    try:
        dag = AUTO._resolve_inlined(AUTO.BUILD_DAG(parser_state, entity, {}, float("inf")))
    except AUTO.AutoError as e:
        table[entity] = [(func, {"moves": [], "unsupported": str(e)})]
        return table[entity]
    dag = AUTO.prune(dag)
    dag["constants"] = {r[1]: _literal(parser_state, entity, r)
                        for n in dag["nodes"].values() for r in n["operands"] if r[0] == "const"}
    if len(dag["nodes"]) > AUTO.MAX_NODES:
        table[entity] = [(func, {"moves": [], "limits": ["graph node limit"]})]
        return table[entity]
    seed_cache = getattr(parser_state, "pypeline_hls_seeds", None)
    if seed_cache is None:
        seed_cache = {}
        parser_state.pypeline_hls_seeds = seed_cache
    if entity not in seed_cache:
        seed_cache[entity] = _implementation_seeds(func, entity, dag, parser_state, elaborator)
    seeds = list(seed_cache[entity])
    if objective == "delay":
        seeds.extend(AUTO.delay_implementation_seeds(func, dag, parser_state, elaborator))
    dependencies = set(AUTO._subtree_entities(parser_state, entity))
    for seed, _moves in seeds:
        for node in seed["nodes"].values():
            dependencies.update(AUTO._subtree_entities(parser_state, node["entity"]))
    dependency_shapes = []
    for name in sorted(dependencies):
        child = parser_state.FuncLogicLookupTable.get(name)
        if child is not None:
            dependency_shapes.append((name, child.submodule_instances,
                                      child.wire_driven_by, child.wire_to_c_type))
    key = (AUTO.GRAPH_VERSION, AUTO.TIMING_VERSION, objective, entity, AUTO.fingerprint(_semantic_graph(dag)),
           AUTO.fingerprint(dependency_shapes),
           getattr(SYN.SYN_TOOL, "__name__", None), parser_state.part,
           getattr(SYN.DEVICE_MODELS, "SELECTED_LIBRARY", None), AUTO.FORCE_ABSTRACT_AREA)
    if key not in _PLANS:
        timing = AUTO.TimingModel(parser_state) if objective == "delay" else None
        ranked, report = AUTO.search(dag, parser_state, seeds, timing=timing)
        # Keep the written graph as candidate zero, plus distinct alternatives.
        original_key = AUTO.fingerprint(dag)
        alternatives = [(g, moves) for g, moves in ranked if AUTO.fingerprint(g) != original_key]
        # Keep distinct rewrite families for FSM scoring, not only several
        # nearby versions of AUTO_COMB_AREA_OPT's minimum-combinational-area winner.
        selected, families = [], set()
        for g, moves in alternatives:
            if not selected or set(moves) - families:
                selected.append((g, moves))
                families.update(moves)
            if len(selected) >= AUTO.MAX_EMITTED_CANDIDATES:
                break
        for item in alternatives:
            if len(selected) >= AUTO.MAX_EMITTED_CANDIDATES:
                break
            if item not in selected:
                selected.append(item)
        original_cost = AUTO.area(dag, parser_state)
        scored = [(g, moves, AUTO.area(g, parser_state)) for g, moves in selected]
        report["area_units"] = "um2" if AUTO._area_unit_scale(parser_state) != 1.0 else "abstract"
        report["objective"] = objective
        if timing:
            report.update(timing.report(dag))
            report["delay_before"] = report["delay"]
            report["timing_snapshot"] = copy.deepcopy(timing.snapshot)
        _PLANS[key] = (copy.deepcopy(scored), report, original_cost)
    alternatives, report, (original_area, tally) = _PLANS[key]
    results = [(func, dict(report, moves=[], area=original_area, area_before=original_area, coverage=tally))]
    # Register first to prevent recursive candidate preparation.
    table[entity] = results
    for graph, moves, (cost, coverage) in alternatives:
        ports = [(p, logic.wire_to_c_type[p]) for p in logic.inputs]
        graph_key = AUTO.fingerprint((entity, ports, _semantic_graph(graph)))
        name = ("auto_comb_delay_opt_" if objective == "delay" else "auto_comb_area_opt_") + graph_key[:20]
        generated = CombEmitter(func, entity, graph, parser_state).generate(name)
        from operators.comb_opt import _primitive_math

        generated = _primitive_math(generated)
        generated._hls_candidate = True
        new_logic = elaborator._elaborate_live_func(name, generated)
        AUTO._RESOLVE_BUILTIN_SUBMODULES(parser_state, new_logic.func_name)
        info = dict(report, moves=moves, area=cost, area_before=original_area, coverage=coverage)
        if objective == "delay":
            # Score emitted hardware, including actual cast/cleanup/helper
            # structure. Snapshot and final choice stay pinned across reparses.
            actual = AUTO.prune(AUTO._resolve_inlined(AUTO.BUILD_DAG(
                parser_state, new_logic.func_name, {}, float("inf"))))
            model = AUTO.TimingModel(parser_state, report["timing_snapshot"])
            info.update(model.report(actual))
            info["area"], info["coverage"] = AUTO.area(actual, parser_state)
            report["timing_snapshot"].update(model.snapshot)
        results.append((generated, info))
    if objective == "delay":
        results[1:] = sorted(results[1:], key=lambda item: (item[1]["delay"], item[1]["area"]))
    return results


def BUILD_FUNC(tag, parser_state, elaborator):
    delay_opt = getattr(tag, "_is_auto_comb_delay_opt_pragma", False)
    objective = "delay" if delay_opt else "area"
    label = "AUTO_COMB_DELAY_OPT" if delay_opt else "AUTO_COMB_AREA_OPT"
    candidates = prepare(tag.func, parser_state, elaborator, objective=objective)
    # Strictly lower area (or delay) wins; preserve the original when costs tie.
    if delay_opt:
        original_delay = candidates[0][1].get("delay", float("inf"))
        improving = [item for item in candidates[1:] if item[1].get("delay", float("inf")) < original_delay]
        chosen, report = min(improving, key=lambda item: (item[1]["delay"], item[1]["area"])) if improving else candidates[0]
    else:
        chosen, report = min(candidates, key=lambda item: item[1].get("area", float("inf")))
    attr = "pypeline_comb_delay_opt_reports" if delay_opt else "pypeline_comb_area_opt_reports"
    reports = getattr(parser_state, attr, None)
    if reports is None:
        reports = {}
        setattr(parser_state, attr, reports)
    if tag.canonical_key not in reports:
        reports[tag.canonical_key] = report
        score = (f"estimated area {report['area_before']:.2f} -> {report['area']:.2f} "
                 f"{report['area_units']}" if "area" in report else "area unavailable")
        if delay_opt and "delay" in report:
            score = f"estimated delay {report['delay_before']:.2f} -> {report['delay']:.2f} {report['delay_units']}; " + score
        print(f"{label} {tag.canonical_key}: {score}; "
              f"{report.get('candidates', 1)} candidate(s); "
              + (", ".join(report["moves"]) or "original retained")
              + ("; " + report["unsupported"] if report.get("unsupported") else "")
              + ("; bounded by " + ", ".join(report["limits"]) if report.get("limits") else ""), flush=True)
    return chosen


def DUMP_GENERATED_SOURCE(parser_state, out_dir):
    if not out_dir:
        return
    entries = dict(getattr(parser_state, "pypeline_comb_area_opt_candidates", {}))
    entries.update({"delay:" + k: v for k, v in getattr(parser_state, "pypeline_comb_delay_opt_candidates", {}).items()})
    sources = {fn.__name__: fn._auto_comb_opt_generated_src
               for values in entries.values() for fn, _ in values
               if hasattr(fn, "_auto_comb_opt_generated_src")}
    if sources:
        path = os.path.join(out_dir, "auto_comb_opt_generated")
        os.makedirs(path, exist_ok=True)
        for name, source in sources.items():
            with open(os.path.join(path, name + ".py"), "w") as output:
                output.write(source)
    reports = getattr(parser_state, "pypeline_comb_area_opt_reports", {})
    if reports:
        import json

        with open(os.path.join(out_dir, "auto_comb_area_opt_report.json"), "w") as output:
            json.dump(reports, output, indent=2, sort_keys=True)
    reports = getattr(parser_state, "pypeline_comb_delay_opt_reports", {})
    if reports:
        import json

        with open(os.path.join(out_dir, "auto_comb_delay_opt_report.json"), "w") as output:
            json.dump(reports, output, indent=2, sort_keys=True)
