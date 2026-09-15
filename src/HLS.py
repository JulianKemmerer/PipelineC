"""Typed combinational candidates shared by AUTO_COMB_SHARE and AUTO_FSM.

The graph format is AUTO_FSM's decoded DAG, including edge cast chains. Graphs
contain no scheduler state. Candidates are emitted and re-elaborated before
FSM scheduling, so its binding/area model always sees the hardware it builds.
"""
import copy
import hashlib
import json

MAX_CANDIDATES = 96
MAX_NODES = 4096
BEAM_WIDTH = 4
MAX_EMITTED_CANDIDATES = 8
MAX_ROUNDS = 8
MAX_BDD_NODES = 8192
VERSION = 4


def frozen(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def fingerprint(dag):
    return hashlib.sha256(frozen(dag).encode()).hexdigest()


def order(dag):
    """Topological order of live nodes; detect even selector-induced cycles."""
    result, visiting, done = [], set(), set()

    stack = [(dag["output"], False)]
    while stack:
        ref, finished = stack.pop()
        if ref[0] != "node":
            continue
        nid = ref[1]
        if nid in done:
            continue
        if finished:
            visiting.remove(nid)
            done.add(nid)
            result.append(nid)
            continue
        if nid in visiting:
            raise ValueError("combinational cycle in HLS candidate")
        visiting.add(nid)
        stack.append((ref, True))
        stack.extend((operand, False) for operand in reversed(dag["nodes"][nid]["operands"]))
    return result


def prune(dag):
    live = order(dag)
    dag["nodes"] = {nid: dag["nodes"][nid] for nid in live}
    return dag


def replace(dag, old, new):
    for node in dag["nodes"].values():
        node["operands"] = [new if r == ["node", old] else r for r in node["operands"]]
    if dag["output"] == ["node", old]:
        dag["output"] = list(new)


def integer(t):
    import pypeline

    return t is not None and pypeline._ctype_is_int(t)


def width(t):
    import AUTO_FSM

    return AUTO_FSM._ctype_width(t)


def common_expressions(dag):
    """Hash-cons typed expressions, including legal commutative matches."""
    dag = copy.deepcopy(dag)
    seen = {}
    for nid in order(dag):
        node = dag["nodes"][nid]
        args = list(zip(node["operands"], node["casts"], node["port_types"]))
        if (node["op"].get("kind") == "binop"
                and node["op"].get("op") in ("+", "*", "&", "|", "^", "==", "!=")
                and len(set(node["port_types"])) == 1
                and all(integer(t) for t in node["port_types"])):
            args.sort(key=frozen)
            node["operands"] = [a[0] for a in args]
            node["casts"] = [a[1] for a in args]
        key = frozen((node["entity"], node["op"], node["out_type"], args))
        if key in seen:
            replace(dag, nid, ["node", seen[key]])
        else:
            seen[key] = nid
    return prune(dag)


def add_node(dag, node):
    nid = "hls_" + hashlib.sha256(frozen(node).encode()).hexdigest()[:16]
    previous = dag["nodes"].get(nid)
    if previous is not None and previous != node:
        raise ValueError("HLS node identity collision")
    dag["nodes"][nid] = node
    return ["node", nid]


def mux(dag, cond, yes, no, ctype, yes_casts=(), no_casts=()):
    if yes == no and yes_casts == no_casts:
        return cast(dag, yes, list(yes_casts) + [ctype], ctype)
    return add_node(dag, {
        "kind": "mux", "op": {"kind": "mux"}, "entity": "MUX_" + ctype,
        "delay_du": max(1, width(ctype)), "out_type": ctype,
        "port_types": ["uint1_t", ctype, ctype],
        "operands": [cond, yes, no], "casts": [[], list(yes_casts), list(no_casts)],
    })


def cast(dag, ref, chain, ctype):
    return add_node(dag, {
        "kind": "copy", "op": {"kind": "copy"}, "entity": "hls_cast_" + ctype,
        "delay_du": 0, "out_type": ctype, "port_types": [ctype],
        "operands": [ref], "casts": [chain],
    })


def area(dag, parser_state):
    import AUTO_FSM

    memo, tally = {}, {}
    total = 0.0
    for nid in order(dag):
        node = dag["nodes"][nid]
        if node["op"]["kind"] in ("copy", "ref", "assemble", "shift", "bitmanip"):
            # Only known wiring primitives are free; variable bit operations
            # still use their actual entity cost.
            if node["op"]["kind"] != "bitmanip" or node["delay_du"] == 0:
                continue
        if node["op"]["kind"] == "mux":
            total += AUTO_FSM._mux_bank_area_um2(parser_state, node["out_type"], tally)
        else:
            if node["entity"] not in parser_state.FuncLogicLookupTable:
                raise ValueError("unresolved HLS area for " + node["entity"])
            total += AUTO_FSM.ESTIMATE_ENTITY_AREA(parser_state, node["entity"], memo, tally)
    return total, tally


class BudgetExceeded(Exception):
    pass


class BDD:
    """Small reduced ordered BDD. Unknown expressions are independent atoms."""

    def __init__(self):
        self.nodes = {0: None, 1: None}
        self.unique = {}
        self.cache = {}
        self.atoms = {}

    def make(self, key, lo, hi):
        if lo == hi:
            return lo
        triple = (key, lo, hi)
        if triple not in self.unique:
            if len(self.nodes) >= MAX_BDD_NODES:
                raise BudgetExceeded("predicate node limit")
            n = len(self.nodes)
            self.unique[triple] = n
            self.nodes[n] = triple
        return self.unique[triple]

    def atom(self, ref, casts=()):
        key = frozen((ref, casts))
        self.atoms[key] = (ref, list(casts))
        return self.make(key, 0, 1)

    def apply(self, op, a, b):
        cache_key = (op, a, b)
        if cache_key in self.cache:
            return self.cache[cache_key]
        if a < 2 and b < 2:
            return {"and": a & b, "or": a | b, "xor": a ^ b}[op]
        keys = [self.nodes[n][0] for n in (a, b) if n >= 2]
        key = min(keys)

        def child(n, i):
            return self.nodes[n][i] if n >= 2 and self.nodes[n][0] == key else n

        lo = self.apply(op, child(a, 1), child(b, 1))
        hi = self.apply(op, child(a, 2), child(b, 2))
        result = self.make(key, lo, hi)
        self.cache[cache_key] = result
        return result

    def negate(self, a):
        return self.apply("xor", a, 1)

    def expression(self, dag, ref, casts=()):
        if casts or ref[0] != "node":
            if ref[0] == "lit":
                return int(bool(ref[1] & 1))
            return self.atom(ref, casts)
        node = dag["nodes"][ref[1]]
        if node["out_type"] not in ("uint1_t", "int1_t"):
            return self.atom(ref)
        op = node["op"].get("op")
        if op in ("==", "!=") and all(integer(t) and t.startswith("uint") for t in node["port_types"]):
            for i in range(2):
                literal = node["operands"][i]
                value = literal[1] if literal[0] == "lit" else dag.get("constants", {}).get(literal[1]) if literal[0] == "const" else None
                if value is None:
                    continue
                types = node["casts"][i] + [node["port_types"][i]]
                # Masking is sufficient only for unsigned casts. A signed
                # intermediate can sign-extend before the unsigned comparison.
                if any(not integer(t) or not t.startswith("uint") for t in types):
                    continue
                for t in types:
                    value &= (1 << width(t)) - 1
                other = 1 - i
                t = node["port_types"][other]
                if t != node["port_types"][i] or width(t) > 64:
                    continue
                result = 1
                for bit in range(width(t)):
                    atom = self.atom(["hls_bit", node["operands"][other], node["casts"][other], t, bit])
                    result = self.apply("and", result, atom if (value >> bit) & 1 else self.negate(atom))
                return self.negate(result) if op == "!=" else result
        if node["op"]["kind"] == "unaryop" and op in ("~", "!"):
            return self.negate(self.expression(dag, node["operands"][0], node["casts"][0]))
        if op in ("&", "|", "^") and all(width(t) == 1 for t in node["port_types"]):
            a, b = [self.expression(dag, r, c) for r, c in zip(node["operands"], node["casts"])]
            return self.apply({"&": "and", "|": "or", "^": "xor"}[op], a, b)
        return self.atom(ref)

    def render(self, dag, n, cache=None):
        cache = {} if cache is None else cache
        if n < 2:
            return ["lit", n, "uint1_t"]
        if n not in cache:
            key, lo, hi = self.nodes[n]
            ref, casts = self.atoms[key]
            if ref[0] == "hls_bit":
                _, base, chain, t, bit = ref
                base = cast(dag, base, chain, t)
                ref = add_node(dag, {"kind": "bitmanip", "op": {"kind": "bitmanip", "builtin": "__slice__", "consts": [bit, bit]},
                    "entity": "hls_predicate_bit", "delay_du": 0, "out_type": "uint1_t",
                    "operands": [base], "casts": [[]], "port_types": [t]})
            cond = cast(dag, ref, casts, "uint1_t") if casts else ref
            if lo == 0 and hi == 1:
                cache[n] = cond
            else:
                cache[n] = mux(dag, cond, self.render(dag, hi, cache),
                               self.render(dag, lo, cache), "uint1_t")
        return cache[n]


def demand_predicates(dag):
    bdd = BDD()
    demands = {nid: 0 for nid in dag["nodes"]}
    if dag["output"][0] == "node":
        demands[dag["output"][1]] = 1
    for nid in reversed(order(dag)):
        node = dag["nodes"][nid]
        demand = demands[nid]
        incoming = [demand] * len(node["operands"])
        if node["op"]["kind"] == "mux":
            cond = bdd.expression(dag, node["operands"][0], node["casts"][0])
            incoming[1] = bdd.apply("and", demand, cond)
            incoming[2] = bdd.apply("and", demand, bdd.negate(cond))
        for ref, active in zip(node["operands"], incoming):
            if ref[0] == "node":
                demands[ref[1]] = bdd.apply("or", demands[ref[1]], active)
    return bdd, demands


def share_candidates(dag):
    """Bind mutually exclusive nodes, checking all consumers and cycles."""
    bdd, demands = demand_predicates(dag)
    groups = {}
    for nid in order(dag):
        n = dag["nodes"][nid]
        if n["op"]["kind"] in ("mux", "copy", "ref", "assemble", "shift", "bitmanip"):
            continue
        key = frozen((n["entity"], n["op"], n["port_types"], n["out_type"]))
        groups.setdefault(key, []).append(nid)
    pair_checks = 0
    for ids in groups.values():
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                pair_checks += 1
                if pair_checks > MAX_NODES:
                    raise BudgetExceeded("sharing pair limit")
                if not demands[a] or not demands[b] or bdd.apply("and", demands[a], demands[b]):
                    continue
                trial = copy.deepcopy(dag)
                left, right = trial["nodes"][a], trial["nodes"][b]
                condition = bdd.render(trial, demands[a])
                operands = [mux(trial, condition, x, y, t, cx, cy)
                            for x, y, t, cx, cy in zip(left["operands"], right["operands"],
                                left["port_types"], left["casts"], right["casts"])]
                left["operands"] = operands
                left["casts"] = [[] for _ in operands]
                replace(trial, b, ["node", a])
                try:
                    yield "exclusive sharing", common_expressions(trial)
                except ValueError:
                    # Selector/operand dependencies can make an otherwise
                    # exclusive binding cyclic. It is never a legal candidate.
                    continue


def factor_candidates(dag):
    """Move muxes through identical pure operations, including wiring glue."""
    for nid in order(dag):
        n = dag["nodes"][nid]
        if n["op"]["kind"] != "mux":
            continue
        a, b = n["operands"][1:]
        if a == b and n["casts"][1] == n["casts"][2]:
            trial = copy.deepcopy(dag)
            ref = cast(trial, a, n["casts"][1] + [n["port_types"][1]], n["out_type"])
            replace(trial, nid, ref)
            yield "duplicate mux choice", common_expressions(trial)
            continue
        if a[0] != "node" or b[0] != "node":
            continue
        left, right = dag["nodes"][a[1]], dag["nodes"][b[1]]
        if any(left[k] != right[k] for k in ("entity", "op", "port_types", "out_type")):
            continue
        if n["casts"][1] != n["casts"][2]:
            continue
        trial = copy.deepcopy(dag)
        cond = cast(trial, n["operands"][0], n["casts"][0], "uint1_t")
        factored = copy.deepcopy(left)
        factored["operands"] = [mux(trial, cond, x, y, t, cx, cy)
            for x, y, t, cx, cy in zip(left["operands"], right["operands"],
                left["port_types"], left["casts"], right["casts"])]
        factored["casts"] = [[] for _ in left["operands"]]
        ref = add_node(trial, factored)
        ref = cast(trial, ref, n["casts"][1] + [n["port_types"][1]], n["out_type"])
        replace(trial, nid, ref)
        yield "mux factoring", common_expressions(trial)


def algebra_candidates(dag):
    """Exact distributive factoring within a uniform modular integer width."""
    rules = {"+": "*", "|": "&", "&": "|", "^": "&"}
    for nid in order(dag):
        n = dag["nodes"][nid]
        op = n["op"].get("op")
        if n["op"]["kind"] != "binop" or op not in rules or not integer(n["out_type"]):
            continue
        if any(r[0] != "node" for r in n["operands"]):
            continue
        a, b = [dag["nodes"][r[1]] for r in n["operands"]]
        t = n["out_type"]
        if (any(x["op"].get("op") != rules[op] or x["op"]["kind"] != "binop" for x in (a, b))
                or a["entity"] != b["entity"]
                or any(x["out_type"] != t or any(p != t for p in x["port_types"])
                       or any(any(c != t for c in chain) for chain in x["casts"])
                       for x in (n, a, b))):
            continue
        for ai in range(2):
            for bi in range(2):
                if a["operands"][ai] != b["operands"][bi]:
                    continue
                trial = copy.deepcopy(dag)
                inner = copy.deepcopy(n)
                inner["operands"] = [a["operands"][1 - ai], b["operands"][1 - bi]]
                inner["casts"] = [[], []]
                outer = copy.deepcopy(a)
                outer["operands"] = [a["operands"][ai], add_node(trial, inner)]
                outer["casts"] = [[], []]
                replace(trial, nid, add_node(trial, outer))
                yield "integer factoring", common_expressions(trial)


def search(dag, parser_state, seeds=()):
    """Return area-ranked alternatives, including uphill shapes for FSM scoring."""
    original = prune(copy.deepcopy(dag))
    cleaned = common_expressions(original)
    graphs = {fingerprint(original): (original, [])}
    if fingerprint(cleaned) not in graphs:
        graphs[fingerprint(cleaned)] = (cleaned, ["common expressions"])
    for seed, labels in seeds:
        if len(graphs) >= MAX_CANDIDATES:
            break
        seed = common_expressions(seed)
        graphs.setdefault(fingerprint(seed), (seed, labels))
    beam = list(graphs.values())
    reasons = set()
    for _round in range(MAX_ROUNDS):
        trials = []
        for current, moves in beam:
            if len(graphs) >= MAX_CANDIDATES:
                break
            try:
                generators = (factor_candidates(current), share_candidates(current), algebra_candidates(current))
                for generator in generators:
                    for label, trial in generator:
                        if len(trial["nodes"]) > MAX_NODES:
                            reasons.add("graph node limit")
                            continue
                        key = fingerprint(trial)
                        if key in graphs:
                            continue
                        item = (trial, moves + [label])
                        graphs[key] = item
                        trials.append(item)
                        if len(graphs) >= MAX_CANDIDATES:
                            raise BudgetExceeded("candidate limit")
            except (BudgetExceeded, RecursionError) as e:
                reasons.add(str(e) or "predicate recursion limit")
        if not trials or len(graphs) >= MAX_CANDIDATES:
            break
        beam = sorted(trials, key=lambda p: (area(p[0], parser_state)[0], len(p[0]["nodes"]), fingerprint(p[0])))[:BEAM_WIDTH]
    else:
        reasons.add("round limit")
    ranked = sorted(graphs.values(), key=lambda p: (area(p[0], parser_state)[0], len(p[0]["nodes"]), fingerprint(p[0])))
    return ranked, {"candidates": len(graphs), "limits": sorted(reasons)}
