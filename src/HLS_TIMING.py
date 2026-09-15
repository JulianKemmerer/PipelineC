"""Read-only combinational timing snapshots for HLS graph objectives.

No synthesis, register overhead, or sum-of-child-entity approximation. Pure
Python hierarchy is walked as a dependency DAG, retaining input-to-output
arcs. Primitive caches without timing components are labelled total proxies.
"""
import copy

import AUTO_FSM
import HLS
import SYN

VERSION = 1


class TimingModel:
    def __init__(self, parser_state, snapshot=None):
        self.parser = parser_state
        self.snapshot = copy.deepcopy(snapshot or {})
        self.active = set()

    def entity(self, entity):
        if entity in self.snapshot:
            return self.snapshot[entity]
        if entity in self.active:
            raise ValueError("recursive combinational timing hierarchy: " + entity)
        logic = self.parser.FuncLogicLookupTable.get(entity)
        if logic is None:
            raise ValueError("unresolved combinational timing: " + entity)
        self.active.add(entity)
        try:
            if (logic.submodule_instances
                    and AUTO_FSM._entity_callables(self.parser).get(entity) is not None):
                dag = AUTO_FSM._resolve_inlined(AUTO_FSM.BUILD_DAG(
                    self.parser, entity, dict.fromkeys(self.parser.FuncLogicLookupTable, 1), float("inf")))
                arcs, _, provenance = self._graph(dag)
                result = (arcs, provenance)
            else:
                components = getattr(logic, "delay_components", None)
                cached = SYN.GET_CACHED_PATH_DELAY(logic, self.parser)
                if not components and cached is not None:
                    components = SYN.GET_CACHED_PATH_DELAY_COMPONENTS(logic, self.parser, expected_delay_ns=cached)
                if components and components.get("combinational_delay_ns") is not None:
                    delay = components["combinational_delay_ns"] * SYN.DELAY_UNIT_MULT
                    source = "cached combinational components"
                elif cached is not None:
                    delay, source = cached * SYN.DELAY_UNIT_MULT, "cached total-delay proxy"
                elif logic.delay is not None and not getattr(logic, "delay_estimated", False):
                    delay, source = logic.delay, "live total-delay proxy"
                else:
                    delay = AUTO_FSM._heuristic_leaf_delay_du(entity, logic)
                    source = "wiring" if delay == 0 else "width heuristic"
                result = ({p: float(delay) for p in logic.inputs}, [source])
            self.snapshot[entity] = result
            return result
        finally:
            self.active.remove(entity)

    def _graph(self, dag):
        vectors, paths, sources = {}, {}, set()

        def value(ref):
            if ref[0] == "node":
                return vectors[ref[1]]
            return {ref[1] if ref[0] == "in" else "$constant": 0.0}

        for nid in HLS.order(dag):
            n = dag["nodes"][nid]
            kind = n["op"]["kind"]
            intrinsic = None
            if kind in ("copy", "ref", "assemble", "shift") or (kind == "bitmanip" and n["delay_du"] == 0):
                weights = [0.0] * len(n["operands"])
                sources.add("wiring")
            elif n["entity"] in self.parser.FuncLogicLookupTable:
                arcs, provenance = self.entity(n["entity"])
                intrinsic = arcs.get("$constant")
                logic = self.parser.FuncLogicLookupTable[n["entity"]]
                ports = [p for p in logic.inputs if p != "CLOCK_ENABLE"]
                weights = [arcs.get(p) for p in ports]
                sources.update(provenance)
            elif kind == "mux":
                weights = [AUTO_FSM._mux_delay_du(self.parser, AUTO_FSM._TypeResolver(), n["out_type"], 2, {})] * 3
                sources.add("mux model")
            else:
                raise ValueError("unresolved HLS timing node " + n["entity"])
            if len(weights) != len(n["operands"]):
                raise ValueError("HLS timing port mismatch: " + n["entity"])
            vector = {"$constant": intrinsic} if intrinsic is not None else {}
            path_choices = [(intrinsic, [])] if intrinsic is not None else []
            for ref, delay in zip(n["operands"], weights):
                if delay is None:
                    continue  # unused hierarchical input
                v = value(ref)
                for port, arrival in v.items():
                    vector[port] = max(vector.get(port, 0.0), arrival + delay)
                path_choices.append((max(v.values(), default=0.0) + delay,
                                     paths.get(ref[1], []) if ref[0] == "node" else []))
            vectors[nid] = vector or {"$constant": 0.0}
            paths[nid] = max(path_choices, key=lambda p: p[0], default=(0, []))[1] + [nid]
        output = dag["output"]
        return value(output), paths.get(output[1], []) if output[0] == "node" else [], sorted(sources)

    def report(self, dag):
        arcs, path, sources = self._graph(dag)
        return {"delay": max(arcs.values(), default=0.0), "delay_units": "0.1 ns",
                "critical_path": path, "timing_provenance": sources,
                "timing_model_version": VERSION, "timing_is_estimate": True}
