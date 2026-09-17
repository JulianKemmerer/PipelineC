"""Machinery shared by more than one AUTO feature.

AUTO_COMB_AREA_OPT, AUTO_COMB_DELAY_OPT and AUTO_FSM all work on one typed
combinational DAG (see docs/AUTO_DESIGN.md): operations, input/constant/node
references, port and result types, and ordered edge cast chains. Graphs contain
no scheduler state. This module holds:

- graph utilities, typed CSE, bounded BDD predicate proofs and the bounded
  candidate search (`search`);
- the delay-oriented rewrite families and implementation seeds;
- the read-only combinational timing model (`TimingModel`);
- decoding elaborated functions into the DAG (`BUILD_DAG`), live type
  resolution (`_TypeResolver`), soft operator equivalents, the operation delay
  heuristics and the entity area model (`ESTIMATE_ENTITY_AREA`);
- source emission helpers (`_Emitter`, `_exec_generated`) and the
  scheduler-free node renderer `_GraphCodegen`;
- `AutoError`, the design-level error every AUTO feature raises.

Candidates are emitted and re-elaborated before any consumer scores them, so
area and timing models always see the hardware that will be built.
"""
import copy
import hashlib
import json

import C_TO_LOGIC
import SYN

MAX_CANDIDATES = 96
MAX_NODES = 4096
BEAM_WIDTH = 4
MAX_EMITTED_CANDIDATES = 8
MAX_ROUNDS = 8
MAX_BDD_NODES = 8192
GRAPH_VERSION = 6
TIMING_VERSION = 1


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
    return _ctype_width(t)


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
    source_type = (dag["nodes"][ref[1]]["out_type"] if ref[0] == "node"
                   else ref[2] if ref[0] == "lit" else None)
    if source_type == ctype and all(t == ctype for t in chain):
        return list(ref)
    return add_node(dag, {
        "kind": "copy", "op": {"kind": "copy"}, "entity": "hls_cast_" + ctype,
        "delay_du": 0, "out_type": ctype, "port_types": [ctype],
        "operands": [ref], "casts": [chain],
    })


def area(dag, parser_state):
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
            total += _mux_bank_area_um2(parser_state, node["out_type"], tally)
        else:
            if node["entity"] not in parser_state.FuncLogicLookupTable:
                raise ValueError("unresolved HLS area for " + node["entity"])
            total += ESTIMATE_ENTITY_AREA(parser_state, node["entity"], memo, tally)
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


def search(dag, parser_state, seeds=(), timing=None):
    """Bounded objective-ranked search; timing=None retains area-first behavior."""
    costs = {}

    def rank(item):
        graph = item[0]
        key = fingerprint(graph)
        if key not in costs:
            a = area(graph, parser_state)[0]
            costs[key] = ((timing.report(graph)["delay"], a) if timing else (a,)) + (len(graph["nodes"]), key)
        return costs[key]
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
                if timing is not None:
                    generators = (speculate(current), balanced(current),
                                  expand(current), factor_candidates(current))
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
        beam = sorted(trials, key=rank)[:BEAM_WIDTH]
    else:
        reasons.add("round limit")
    ranked = sorted(graphs.values(), key=rank)
    return ranked, {"candidates": len(graphs), "limits": sorted(reasons)}


def _unsigned(t):
    return integer(t) and t.startswith("uint")


def _demanded_bits(dag):
    needed = {nid: 0 for nid in dag["nodes"]}
    def demand(ref, n, casts):
        if ref[0] != "node":
            return
        producer = dag["nodes"][ref[1]]
        if not _unsigned(producer["out_type"]) or any(not _unsigned(t) for t in casts):
            n = width(producer["out_type"])
        else:
            n = min([n, width(producer["out_type"])] + [width(t) for t in casts])
        needed[ref[1]] = max(needed[ref[1]], n)
    demand(dag["output"], width(dag["out_type"]), dag["output_casts"])
    for nid in reversed(order(dag)):
        n = dag["nodes"][nid]
        low_bits = n["op"].get("op") in ("+", "-", "*", "&", "|", "^") or n["kind"] == "copy"
        for ref, casts, t in zip(n["operands"], n["casts"], n["port_types"]):
            amount = needed[nid] if low_bits else width(t)
            demand(ref, amount, casts + [t])
    return needed


# ----------------------------------------------------------------------
# Delay-oriented candidates (AUTO_COMB_DELAY_OPT and the FSM's delay finalists)


def delay_implementation_seeds(func, dag, parser_state, elaborator):
    """Reuse exact library implementations; timing decides, not their names."""
    from operators.comb_opt import _primitive_math, make_carry_save_sum3
    from operators.soft_add import make_soft_add_carry_select
    from operators.soft_cmp import make_soft_cmp_prefix
    from operators.soft_mult import make_soft_mult_shift_add, make_soft_mult_karatsuba

    types = _TypeResolver()
    types.seed_callable(func)
    seeds, replacements = [], {}
    for nid in order(dag):
        n = dag["nodes"][nid]
        op = n["op"].get("op")
        if (n["op"]["kind"] != "binop" or op not in ("+", "*", "<", "<=", ">", ">=")
                or not all(integer(t) and t.startswith("uint") for t in n["port_types"])
                or max(width(t) for t in n["port_types"]) > 64):
            continue
        key = (op, tuple(n["port_types"]), n["out_type"])
        if key not in replacements:
            if len(replacements) >= 16:
                continue
            left, right = [types.resolve(t) for t in n["port_types"]]
            if op == "+":
                factories = [make_soft_add_carry_select(left, right)]
            elif op == "*":
                factories = [make_soft_mult_shift_add(left, right), make_soft_mult_karatsuba(left, right)]
            else:
                factories = [make_soft_cmp_prefix({"<": "LT", "<=": "LTE", ">": "GT", ">=": "GTE"}[op])(left, right)]
            replacements[key] = []
            for factory in factories:
                factory = _primitive_math(factory)
                logic = elaborator._elaborate_live_func(factory.__name__, factory)
                _RESOLVE_BUILTIN_SUBMODULES(parser_state, logic.func_name)
                replacements[key].append((logic.func_name, factory.__name__))
        for index, (entity, label) in enumerate(replacements[key]):
            family = (op, index)
            item = next((item for item in seeds if item[0] == family), None)
            if item is None:
                item = (family, copy.deepcopy(dag), ["operator alternative: " + label])
                seeds.append(item)
            item[1]["nodes"][nid] = dict(n, kind="call", op={"kind": "call"}, entity=entity)
    result = [(graph, labels) for _, graph, labels in seeds]

    demanded = _demanded_bits(dag)
    csa = copy.deepcopy(dag)
    count = 0
    for nid in order(dag):
        n = dag["nodes"][nid]
        if n["op"] != {"kind": "binop", "op": "+"} or not demanded[nid] or count >= 16:
            continue
        for side, ref in enumerate(n["operands"]):
            child = dag["nodes"].get(ref[1]) if ref[0] == "node" else None
            if not child or child["op"] != n["op"]:
                continue
            bits = demanded[nid]
            intermediate = [child["out_type"], n["port_types"][side]] + n["casts"][side]
            if any(not _unsigned(t) or width(t) < bits for t in intermediate):
                continue
            port_types = child["port_types"] + [n["port_types"][1 - side]]
            if not all(_unsigned(t) for t in port_types + [n["out_type"]]):
                continue
            factory = make_carry_save_sum3(*[types.resolve(t) for t in port_types], types.resolve(n["out_type"]), bits)
            logic = elaborator._elaborate_live_func(factory.__name__, factory)
            _RESOLVE_BUILTIN_SUBMODULES(parser_state, logic.func_name)
            csa["nodes"][nid] = dict(n, kind="call", op={"kind": "call"}, entity=logic.func_name,
                operands=child["operands"] + [n["operands"][1 - side]],
                casts=child["casts"] + [n["casts"][1 - side]], port_types=port_types)
            count += 1
            break
    if count:
        result.append((prune(csa), ["carry-save sum reduction"]))
    return result


def speculate(dag):
    """Move a common selector after a total primitive; keep operands correlated.

    Calls, division/modulo and variable shifts are deliberately not speculated:
    a previously unselected input might not have defined behavior there.
    """
    for nid in order(dag):
        node = dag["nodes"][nid]
        if (node["op"].get("kind") not in ("binop", "unaryop")
                or node["op"].get("op") not in ("+", "-", "*", "&", "|", "^", "~", "!", "==", "!=", "<", "<=", ">", ">=")
                or not all(integer(t) for t in node["port_types"] + [node["out_type"]])):
            continue
        selectors = {}
        for i, ref in enumerate(node["operands"]):
            child = dag["nodes"].get(ref[1]) if ref[0] == "node" else None
            if child and child["op"]["kind"] == "mux":
                key = frozen((child["operands"][0], child["casts"][0]))
                selectors.setdefault(key, []).append((i, child))
        for selected in selectors.values():
            trial = copy.deepcopy(dag)
            branches = []
            for arm in (1, 2):
                branch = copy.deepcopy(node)
                for i, child in selected:
                    branch["operands"][i] = child["operands"][arm]
                    branch["casts"][i] = (child["casts"][arm] + [child["port_types"][arm], child["out_type"]]
                                            + node["casts"][i])
                branches.append(add_node(trial, branch))
            selector = selected[0][1]
            cond = cast(trial, selector["operands"][0], selector["casts"][0], "uint1_t")
            result = mux(trial, cond, branches[0], branches[1], node["out_type"])
            replace(trial, nid, result)
            yield "correlated mux speculation", common_expressions(trial)


def balanced(dag):
    """Balance modular unsigned sums/bitwise trees without losing edge casts."""

    demanded = _demanded_bits(dag)
    for nid in order(dag):
        root = dag["nodes"][nid]
        op = root["op"].get("op")
        if root["op"]["kind"] != "binop" or op not in ("+", "&", "|", "^"):
            continue
        bits = demanded[nid]
        if not bits or len(set(root["port_types"])) != 1:
            continue

        def legal(node):
            return (node["op"] == root["op"]
                    and all(_unsigned(t) and width(t) >= bits
                            for t in node["port_types"] + [node["out_type"]]
                            + [t for chain in node["casts"] for t in chain]))

        if not legal(root):
            continue
        trial, leaves = copy.deepcopy(dag), []
        pending = [(ref, chain) for ref, chain in zip(root["operands"], root["casts"])]
        while pending and len(leaves) + len(pending) <= 64:
            ref, chain = pending.pop(0)
            child = dag["nodes"].get(ref[1]) if ref[0] == "node" else None
            if child and legal(child) and all(_unsigned(t) and width(t) >= bits for t in chain):
                pending[0:0] = list(zip(child["operands"], child["casts"]))
            else:
                leaves.append(cast(trial, ref, chain, root["port_types"][0]))
        if pending or len(leaves) < 3:
            continue
        while len(leaves) > 1:
            level = []
            for i in range(0, len(leaves), 2):
                if i + 1 == len(leaves):
                    level.append(leaves[i])
                else:
                    n = copy.deepcopy(root)
                    n["operands"], n["casts"] = leaves[i:i + 2], [[], []]
                    level.append(add_node(trial, n))
            leaves = level
        replace(trial, nid, leaves[0])
        yield "balanced unsigned " + op, common_expressions(trial)


def expand(dag):
    """Distribute in a uniform modular ring / Boolean algebra."""

    demanded = _demanded_bits(dag)
    rules = {"*": ("+",), "&": ("|", "^"), "|": ("&",)}
    for nid in order(dag):
        n = dag["nodes"][nid]
        op, bits = n["op"].get("op"), demanded[nid]
        if n["op"]["kind"] != "binop" or op not in rules or not bits:
            continue
        for side in range(2):
            ref = n["operands"][side]
            child = dag["nodes"].get(ref[1]) if ref[0] == "node" else None
            if not child or child["op"]["kind"] != "binop" or child["op"].get("op") not in rules[op]:
                continue
            # All intermediate operations agree modulo the demanded width.
            # Narrowing below that width or any signed casts prohibit expansion.
            types = [t for x in (n, child) for t in x["port_types"] + [x["out_type"]]]
            types += [t for x in (n, child) for chain in x["casts"] for t in chain]
            if any(not _unsigned(t) or width(t) < bits for t in types):
                continue
            trial, branches = copy.deepcopy(dag), []
            for i in range(2):
                branch = copy.deepcopy(n)
                branch["operands"][side] = child["operands"][i]
                branch["casts"][side] = child["casts"][i] + [child["port_types"][i]]
                branches.append(add_node(trial, branch))
            outer = copy.deepcopy(child)
            outer["operands"], outer["casts"] = branches, [[], []]
            # Preserve the written root's full return type; only demanded bits
            # may differ above the ring width and are truncated by consumers.
            result = cast(trial, add_node(trial, outer), [], n["out_type"])
            replace(trial, nid, result)
            yield "distributive expansion", common_expressions(trial)


# ----------------------------------------------------------------------
# Read-only combinational timing snapshots: no synthesis, no register
# overhead, no sum-of-child-entity approximation. Pure Python hierarchy is
# walked as a dependency DAG, retaining input-to-output arcs. Primitive caches
# without timing components are labelled total-delay proxies.




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
                    and _entity_callables(self.parser).get(entity) is not None):
                dag = _resolve_inlined(BUILD_DAG(
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
                    delay = _heuristic_leaf_delay_du(entity, logic)
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

        for nid in order(dag):
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
                weights = [_mux_delay_du(self.parser, _TypeResolver(), n["out_type"], 2, {})] * 3
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
                "timing_model_version": TIMING_VERSION, "timing_is_estimate": True}


# ======================================================================
# Shared typed-DAG decoding, type resolution, soft equivalents, delay and area
# models, and source emission helpers. AUTO_FSM, AUTO_COMB_OPT and the timing
# model above all build on these.
# ======================================================================

# Last-resort delay charged per scheduled operation when nothing better is
# known about its operand multiplexer -- notably before any fold count exists
# at all. In delay units, so 10 == 1.0 ns. v1 charged this flat for every
# operation; v2 uses the real per-shape numbers below and keeps this only as
# the floor/seed.
MUX_PENALTY_DU = 10


# Operand-mux delay MODEL, used only until a real measurement of that mux shape
# exists (see _mux_delay_du). An n-way mux built as an array read is a balanced
# binary selection tree, so its delay grows with log2(n), not n -- which is the
# whole reason AUTO_FSM builds them that way (see
# include/pypeline/operators/auto_fsm_mux.py). Delay units.
MUX_BASE_DU = 2


MUX_PER_LEVEL_DU = 4


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
# anchor -- so it cannot regress according to the model. Whole-design synthesis
# tests remain the authority for catching a model ranking that is wrong in
# physical cells (especially under limited no-hierarchy/no-sweep synthesis).
#
# CALIBRATION. The ratios come from real yosys cell counts, which is the one
# place in this project real area numbers exist (they are used in the test
# suite, never in the search itself -- see
# src/tests/pypeline_tests/inst/auto_fsm_area_sweep_compare_test.py):
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


# One 2:1 multiplexer bit. MEASURED, and the measurement is why this is not the
# 0.16 the other per-bit gate terms use -- an operand multiplexer costs about
# twice a plain gate. Built as balanced trees and counted in yosys (the div
# design behind auto_fsm_min_area_verify_test):
#
#     36-way over uint10   726 cells / 350 mux bits = 2.07 cells per bit
#     27-way over uint10   545 cells / 260 mux bits = 2.10
#     36-way over uint2    150 cells /  70 mux bits = 2.14
#
# against the ~1 cell that 0.16 implies at this model's 6.25-cells-per-unit
# scale. (Two- and three-way muxes run higher still, 3-4 cells per bit, but
# fixed overhead on a tiny mux never decides anything.)
#
# This is the term that decides whether DECOMPOSITION pays, so a 2x error here
# is not a rounding matter: opening one unit into N pieces necessarily spreads
# them across N states and therefore buys an N-way multiplexer on every operand
# port. Under-priced, descent looks nearly free. On that div design the search
# duly opened a shared divider, paying 1271 cells of operand multiplexing to
# save one divider -- its model called it a win, yosys called it 70% worse.
AREA_PER_BIT_MUX = 0.34


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
#
# This is the one term real sky130 measurement (see UM2_PER_ABSTRACT_AREA_UNIT
# below) shows is badly off, not just approximate: a real dfxtp_1 flip-flop
# measures 0.494 abstract units, 2.5x this constant. AREA_PER_BIT_FF stays the
# FALLBACK for tools with no area measurement -- under DEVICE_MODELS,
# _ff_area_um2 uses the real cell area instead and this constant is not
# consulted at all.
AREA_PER_BIT_FF = 0.2


# um2 of one abstract area unit (one ripple-adder bit -- AREA_PER_BIT_ADD's
# 1.0). Used ONLY to express an abstract fallback term in real um2 when
# DEVICE_MODELS has no measurement for a shape (a cold cache, or a term like
# control-path decode that has no synthesizable entity of its own to measure).
# Measured, not chosen: least-squares fit (through the origin) of area vs
# width across every BIN_OP_PLUS_uintA_t_uintB_t / BIN_OP_MINUS_uintA_t_uintB_t
# entry in the committed area_cache, width = max(A, B) (both operators cost
# AREA_PER_BIT_ADD per _leaf_area, so one joint fit covers both) -- 5 points,
# widths 17-34, absolute residuals 29-159 um2 (1.2-6.3 um2/bit), MAE ~100
# um2/point. Refit from the committed cache by area_model_test.py, so a
# library/corner/recipe change that moves this value fails a test instead of
# silently rescaling every fallback term.
UM2_PER_ABSTRACT_AREA_UNIT = 98.93


class AutoError(Exception):
    """A design-level AUTO feature problem (unschedulable or impure function,
    unsupported construct). Always raised with a message naming the feature
    and the offending function/operation: failing loudly is required here,
    because the alternative is generating hardware that quietly computes
    something other than the pure function it replaces."""


def _entity_callables(parser_state):
    return getattr(parser_state, "pypeline_entity_callables", {})


def _entity_key_for_callable(parser_state, func):
    """Reverse-lookup the FuncLogicLookupTable key a live callable was
    elaborated under, using the pypeline_entity_callables side table PY_TO_LOGIC
    populates. Identity-based, and deliberately a lookup rather than a
    re-derivation: the elaborator's canonical-naming rules are intricate, and a
    second implementation of them here would be one more thing to keep in sync.
    """
    if (getattr(func, "_is_auto_comb_area_opt_pragma", False)
            or getattr(func, "_is_auto_comb_delay_opt_pragma", False)):
        return getattr(parser_state, "pypeline_comb_opt_tag_entities", {}).get(func.canonical_key)
    for key, recorded in _entity_callables(parser_state).items():
        if recorded is func:
            return key
    return None


class _TypeResolver:
    """Maps the compiler's C type name strings (all a Logic graph carries) back
    to live pypeline type objects, which generated source needs for its
    variable annotations.

    Scalars are reconstructible from the name alone, and so is any array whose
    element type is (recursively) reconstructible -- 'uint16_t[16]' is just
    'uint16_t' plus a dimension, regardless of whether anything in the design
    ever carried that exact array type standalone. Only a struct genuinely
    cannot be rebuilt from its name, so those are seeded from the live objects
    actually in play: the AUTO_FSM'd function's own input/output types, every
    unit callable's annotations, and (see _Codegen.__init__) every entity in
    its elaborated subtree, including ones fully consumed by descent. Any
    struct type reaching generated source came from one of those, so an
    unresolvable name at that point is a genuine gap -- raise rather than
    guess.
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
            # Best-effort: func is anything _entity_callables handed us, not
            # necessarily a plain @hw_func with clean annotations (a bit-manip
            # builtin, a partial, ...). A seeding miss here is not fatal by
            # itself -- resolve() only raises later if some generated line
            # actually needed the type this call would have provided.
            pass

    def resolve(self, ctype_str: str):
        t = self._by_name.get(ctype_str)
        if t is not None:
            return t
        scalar = _scalar_ctype_to_type(ctype_str)
        if scalar is not None:
            self._by_name[ctype_str] = scalar
            return scalar
        # BASE[d1][d2]... is reconstructible whenever BASE is: rebuild it by
        # indexing BASE with each dimension in source (outer-to-inner) order,
        # matching how _CTypeMeta.__getitem__ builds the name in the first
        # place (each further bracket is APPENDED to the name and pushed onto
        # the current leaf element -- see its own comment). Recursing through
        # `resolve` for BASE means a struct-typed leaf that genuinely cannot
        # be rebuilt still raises naming itself, not the whole array name.
        base_name, dims = _split_array_ctype(ctype_str)
        if dims:
            t = self.resolve(base_name)
            for d in dims:
                t = t[d]
            self._by_name[ctype_str] = t
            return t
        raise AutoError(
            f"AUTO_FSM: cannot reconstruct a live Python type for C type "
            f"{ctype_str!r} needed by the generated FSM. Only scalar integer "
            f"types, arrays of a reconstructible type, and struct types "
            f"reachable from the AUTO_FSM'd function's own elaborated subtree "
            f"can be regenerated."
        )


def _mux_callable(t, n):
    """The memoized hw_func implementing an n-way mux over type `t`, or None if
    this type cannot be arrayed (in which case the caller falls back to an
    inline if/elif chain).

    Lives in include/pypeline/operators/auto_fsm_mux.py rather than being
    generated here so that it is (a) one stable canonical entity per (type, n),
    (b) shipped-library rather than user code, and therefore delay-cacheable on
    disk, and (c) THE SAME OBJECT the scheduler measured and the code generator
    instantiates. See that module's docstring."""
    if n < 2:
        return None
    try:
        from operators.auto_fsm_mux import make_operand_mux

        return make_operand_mux(t, n)
    except Exception:
        # An unarrayable port type (or an operators package that is not on the
        # path) is not a build failure: sharing still works, it just falls back
        # to the older inline multiplexer.
        return None


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
         (see RECURSIVE_GET_FUNCS_FOR_PATH_DELAYS' auto_fsm_measure_entities
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
    except AutoError:
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


def _split_array_ctype(ctype_str: str):
    """'BASE[d1][d2]...' -> (BASE, [d1, d2, ...]), dimensions in SOURCE
    (left-to-right, outer-to-inner, C-declaration) order. (BASE, []) if
    ctype_str carries no trailing bracket at all.

    Peels one bracket at a time from the right (same regex shape as
    _ctype_width), which finds dimensions in right-to-left order -- reversed
    before returning so callers can re-apply them left-to-right and get the
    same name back (see _TypeResolver.resolve)."""
    import re

    dims = []
    rest = ctype_str
    m = re.fullmatch(r"(.+)\[(\d+)\]", rest)
    while m:
        dims.append(int(m.group(2)))
        rest = m.group(1)
        m = re.fullmatch(r"(.+)\[(\d+)\]", rest)
    dims.reverse()
    return rest, dims


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
            raise AutoError(
                f"AUTO_FSM: reference operation {inst!r} has no recorded ref tokens"
            )
        port_toks = (
            logic.ref_submodule_instance_to_input_port_driven_ref_toks.get(inst) or []
        )
        n_ports = len(logic.submodule_instance_to_input_port_names.get(inst, []))
        if n_ports <= 1 and len(out_toks) > 1:
            # out_toks[0] is the base variable; the rest is the path read from it.
            return {"kind": "ref", "toks": list(out_toks[1:])}
        if len(port_toks) != n_ports:
            raise AutoError(
                f"AUTO_FSM: compound assembly {inst!r} has {n_ports} inputs but "
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

    raise AutoError(
        f"AUTO_FSM: operation {inst!r} (entity {entity!r}) cannot be regenerated "
        f"as Python source, so this function cannot be turned into an FSM. "
        f"Supported: arithmetic/comparison/bitwise operators, constant shifts, "
        f"struct-field and constant-index reads, if/conditional muxes, and "
        f"calls to @hw_func functions."
    )


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
            raise AutoError(
                f"AUTO_FSM: wire {wire!r} in {logic.func_name!r} has no driver "
                f"(tracing back from {port_wire!r})"
            )
        if driver in seen:
            raise AutoError(
                f"AUTO_FSM: combinational loop reaching {port_wire!r} in "
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


def _subtree_entities(parser_state, entity, out=None):
    """Every entity in a subtree, including ones fully consumed by descent and
    therefore absent from a schedule's `fus`/node entities. Same traversal
    shape as _snapshot_subtree_delays (FuncLogicLookupTable.submodule_instances
    recursion with a seen set), used by _Codegen to seed _TypeResolver from
    types that live only inside a descended body -- see that class's
    docstring for why seeding from `fus`/nodes alone is not enough."""
    if out is None:
        out = set()
    if entity in out:
        return out
    logic = parser_state.FuncLogicLookupTable.get(entity)
    if logic is None:
        return out
    out.add(entity)
    for sub_entity in logic.submodule_instances.values():
        _subtree_entities(parser_state, sub_entity, out)
    return out


_DELAY_MEMO_ATTR = "_auto_fsm_delay_memo"


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
    return getattr(parser_state, "pypeline_auto_fsm_soft_equiv", {})


# Which soft-operator factory implements each built-in operator. One fixed
# flavor per op: the library ships several (ripple vs carry-select adders,
# shift-add vs Karatsuba multipliers, subtract vs bitwise vs parallel-prefix
# comparators) and choosing between them is a second search axis, deliberately
# not opened here. The flavors picked are the ones whose structure decomposes
# most evenly, which is what makes them useful as SHARING candidates rather
# than as fast hardware -- NOTE this is a different criterion than fmax, so
# this map intentionally still pins the comparator to make_soft_cmp_sub_swapped
# even though make_soft_cmp_prefix is now the fmax-optimized default elsewhere
# (soft.py:register_soft_cmp, see docs/SYN_DESIGN.md#comparator-implementation-selection)
# -- prefix's even-decomposition properties as a sharing candidate haven't been evaluated.
#
# Same reasoning is WHY INFERRED_MULT/MULT stay pinned to
# make_soft_mult_shift_add even though register_soft_mult() (the registry
# default everything else goes through) switched to make_soft_mult_carry_save
# -- do not "fix" this inconsistency. Carry-save is the worst possible shape by
# THIS map's own criterion: at max_width=2 it is a 30-level serial tail-call
# chain (uint16 x uint16), and _MAX_DESCEND_DEPTH=8 cannot reach a fitting
# stage, so descent strands a slow atomic node instead of decomposing evenly.
# Confirmed directly: qor/multiplier/auto_fsm.py registered plain
# register_soft_mult() and AUTO_FSM (which reaches a multiplier through THIS
# map, not the registry, only when descending a BUILT-IN MULT/INFERRED_MULT --
# that test's own soft_mult_carry_save call site is reached by descent, not by
# this map, and still hung) folded 247 adds onto one shared unit and never
# finished scheduling; see qor/multiplier/auto_fsm.py's own comment and
# docs/AUTO_FSM_DESIGN.md section 3.7. Switching this pin would carry the same
# failure mode into every OTHER AUTO_FSM design that multiplies without
# registering a soft flavor itself, e.g. examples/pypeline/
# vga_donut_auto_fsm_next_state.py.
_SOFT_FACTORY_FOR_OP = {
    "PLUS": ("operators.soft_add", "make_soft_add_ripple", None),
    "MINUS": ("operators.soft_add", "make_soft_sub", None),
    "INFERRED_MULT": ("operators.soft_mult", "make_soft_mult_shift_add", None),
    "MULT": ("operators.soft_mult", "make_soft_mult_shift_add", None),
    "DIV": ("operators.soft_div", "make_soft_div_radix", 1),
    "MOD": ("operators.soft_div", "make_soft_mod_radix", 1),
    "GT": ("operators.soft_cmp", "make_soft_cmp_sub_swapped", "GT"),
    "GTE": ("operators.soft_cmp", "make_soft_cmp_sub_swapped", "GTE"),
    "LT": ("operators.soft_cmp", "make_soft_cmp_sub_swapped", "LT"),
    "LTE": ("operators.soft_cmp", "make_soft_cmp_sub_swapped", "LTE"),
    "EQ": ("operators.soft_misc", "make_soft_eq", False),
    "NEQ": ("operators.soft_misc", "make_soft_eq", True),
}


# SIGNEDNESS IS PART OF THE CHOICE, and getting it wrong is not a missed
# optimization -- it silently builds hardware computing something else.
# operators/soft.py encodes the same policy in what each register_soft_* call
# accepts (any_uint_t vs any_integer_t); AUTO_FSM bypasses that registry and so
# has to repeat it here.
#
#   * A SIGNED operand needs a different algorithm for divide, so it gets a
#     different factory -- restoring division works on magnitudes and applies
#     the sign afterwards.
#   * Both soft multipliers sum `a << i` over the set bits of b treating b as
#     UNSIGNED; for a signed b the top bit carries weight -2**(n-1) and its
#     partial product would have to be SUBTRACTED. No signed soft multiplier
#     exists yet, so a signed multiply is simply not openable and stays an
#     atomic unit. (Verified, not assumed: make_soft_mult_shift_add(int16_t,
#     int16_t) builds without complaint and computes -3 * 4 = 1048564.)
_SOFT_FACTORY_FOR_SIGNED_OP = {
    "DIV": ("operators.soft_div", "make_soft_div_signed_radix", 1),
    "MOD": ("operators.soft_div", "make_soft_mod_signed_radix", 1),
}


_SOFT_UNSIGNED_ONLY_OPS = frozenset({"MULT", "INFERRED_MULT"})


# Ceiling on how many distinct built-in operator shapes get a soft equivalent
# elaborated. Bounded by the number of DISTINCT (op, operand types) triples in
# a function -- normally a handful, however many thousand operations use them
# -- so this only ever trips on something pathological.
_MAX_SOFT_EQUIVALENTS = 64


def _soft_equivalent_callable(parser_state, entity):
    """A live, decomposable hw_func computing exactly what a built-in operator
    entity computes -- or None.

    This is the ONLY place AUTO_FSM knows the soft-operator library exists. When
    the library is not importable everything below simply degrades to v1's
    behavior: built-in operators stay atomic and descent bottoms out at them.
    """
    info = getattr(parser_state, "pypeline_builtin_op_info", {}).get(entity)
    if info is None:
        return None
    op_name, operand_ctypes = info
    if op_name not in _SOFT_FACTORY_FOR_OP or len(operand_ctypes) != 2:
        return None
    types = [_scalar_ctype_to_type(ct) for ct in operand_ctypes]
    if any(t is None for t in types):
        return None  # non-integer operands: no soft equivalent exists
    any_signed = any(not ct.startswith("u") for ct in operand_ctypes)
    if any_signed and op_name in _SOFT_UNSIGNED_ONLY_OPS:
        return None
    spec = (
        _SOFT_FACTORY_FOR_SIGNED_OP.get(op_name, _SOFT_FACTORY_FOR_OP[op_name])
        if any_signed
        else _SOFT_FACTORY_FOR_OP[op_name]
    )
    module_name, factory_name, arg = spec
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
    AUTO_FSM'd function, so the area search has something to descend INTO.

    Why here: this runs on the bootstrap pass, the one moment where a live
    elaborator, the design's module globals, and the tagged function are all in
    hand at once. The results sit in FuncLogicLookupTable uninstantiated --
    candidates, not hardware -- exactly as the tagged function's own Logic does
    on every later pass. Nothing is built unless the search actually picks it.

    Best-effort throughout: a shape with no soft equivalent, or an operators
    package that is not importable, just means one fewer descent candidate.
    """
    equiv = getattr(parser_state, "pypeline_auto_fsm_soft_equiv", None)
    if equiv is None:
        equiv = {}
        parser_state.pypeline_auto_fsm_soft_equiv = equiv
    try:
        func_logic = elaborator._elaborate_live_func(
            getattr(tag.func, "__name__", "auto_fsm_func"), tag.func
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
    """Flatten the AUTO_FSM'd function into a dataflow DAG of operations.

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
    truncated = []
    _build_dag_level(
        parser_state,
        func_entity,
        delays,
        budget_du,
        nodes,
        prefix="",
        depth=0,
        truncated=truncated,
        opened=frozenset(opened),
    )
    logic = parser_state.FuncLogicLookupTable[func_entity]
    output_ref, output_casts = _trace_operand(logic, C_TO_LOGIC.RETURN_WIRE_NAME)
    return {
        "nodes": nodes,
        "output": output_ref,
        "output_casts": output_casts,
        "out_type": logic.wire_to_c_type.get(C_TO_LOGIC.RETURN_WIRE_NAME),
        # Entities the depth cap stopped AUTO_FSM from descending into further
        # (see _MAX_DESCEND_DEPTH) -- diagnostic only, read by
        # DESCRIBE_SCHEDULE's AT FLOOR text, never consulted by scheduling.
        "descend_truncated": truncated,
    }


_MAX_DESCEND_DEPTH = 8


def _build_dag_level(
    parser_state,
    entity,
    delays,
    budget_du,
    nodes,
    prefix,
    depth,
    truncated,
    opened=frozenset(),
):
    """Add one function's operations to the DAG, descending where needed.

    `prefix` namespaces node ids when inlining a descended function's body, so
    ids stay unique and remain a pure function of the source (op name + source
    coordinates, joined by the same submodule marker the compiler uses for
    instance paths).

    `truncated` collects (node_id, sub_entity, delay_du) for every operation
    the depth cap stopped from descending further -- see the append below and
    _MAX_DESCEND_DEPTH.
    """
    if depth > _MAX_DESCEND_DEPTH:
        raise AutoError(
            f"AUTO_FSM: gave up descending into {entity!r} after "
            f"{_MAX_DESCEND_DEPTH} levels looking for operations small enough "
            f"to fit one state; the clock goal may simply be unreachable."
        )
    logic = parser_state.FuncLogicLookupTable.get(entity)
    if logic is None:
        raise AutoError(f"AUTO_FSM: no elaborated Logic for entity {entity!r}")
    if logic.uses_nonvolatile_state_regs or logic.feedback_vars:
        raise AutoError(
            f"AUTO_FSM: {entity!r} holds Reg/Feedback state. Only a PURE "
            f"combinational function can be turned into an FSM -- move the "
            f"state out into the calling function."
        )
    if logic.read_only_global_wires or logic.write_only_global_wires:
        raise AutoError(
            f"AUTO_FSM: {entity!r} reads or writes global wires. Only a pure "
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
                    truncated,
                    opened,
                )
                child_out_ref, child_out_casts = _trace_operand(
                    open_logic, C_TO_LOGIC.RETURN_WIRE_NAME
                )
            except AutoError:
                child_nodes = None
                # depth+1 exceeding the cap is the ONLY raise _build_dag_level
                # can hit before any other check (see its first line) -- so
                # this condition being true means that is exactly why the
                # child call failed, not some other AutoError deeper in it.
                if depth + 1 > _MAX_DESCEND_DEPTH:
                    truncated.append((node_id, sub_entity, delay_du))
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
                    raise AutoError("AUTO_FSM: cyclic inlined reference")
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
                    raise AutoError(
                        f"AUTO_FSM: dangling inlined input reference {ref!r}"
                    )
                try:
                    idx = node["inlined_inputs"].index(input_name)
                except ValueError:
                    raise AutoError(
                        f"AUTO_FSM: descended function {node['entity']!r} has no "
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


def _leaf_area(entity, logic):
    """Estimated area of one indivisible operation, in the abstract units
    documented with the AREA_PER_BIT_* constants above."""
    widths = [_ctype_width(logic.wire_to_c_type.get(p)) for p in logic.inputs] or [1]
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


# Set by src/pipelinec from --auto_fsm_abstract_area (default False = off).
# _area_unit_scale consults this before SYN_TOOL: real sky130 um2 is used
# automatically whenever it is available, and this is the only escape hatch
# back to the abstract model, for A/B comparison against it. Module-level
# rather than threaded through every area function's signature, matching
# SYN.SYN_TOOL/SYN.MUX_DELAY_KEY_BY_WIDTH's own convention -- ESTIMATE_* is
# called directly by tests and by the compare harness with fixed signatures,
# not only through HARVEST_AUTO_FSM_SCHEDULES.
FORCE_ABSTRACT_AREA = False


def _area_unit_scale(parser_state):
    """The multiplier that converts one abstract area unit (one ripple-adder
    bit, AREA_PER_BIT_ADD's 1.0) into the model's current output unit: 1.0 --
    unchanged from every tool's existing abstract-units-only behavior -- for
    every SYN_TOOL with no area measurement or when FORCE_ABSTRACT_AREA is
    set, or UM2_PER_ABSTRACT_AREA_UNIT under DEVICE_MODELS so est_area lands
    in real um2, directly comparable to a build's own "Measured area:" line
    and to latchup.app's reported numbers."""
    if FORCE_ABSTRACT_AREA:
        return 1.0
    try:
        if SYN.SYN_TOOL is SYN.DEVICE_MODELS:
            return UM2_PER_ABSTRACT_AREA_UNIT
    except Exception:
        pass
    return 1.0


def _tally(tally, key):
    if tally is not None:
        tally[key] = tally.get(key, 0) + 1


def _leaf_area_um2(parser_state, entity, logic, tally=None):
    """One leaf's area, in the model's current output unit (_area_unit_scale):
    the real cached sky130 measurement when there is one, the abstract
    estimate scaled into that unit otherwise. Mirrors _resolve_delay_du's own
    tiering for exactly the same reason -- a leaf that resolved to zero would
    read as free wiring and never get shared. Ground truth throughout this
    model is real synthesis output, never the abstract estimate: a cache hit
    always wins regardless of how far it sits from _leaf_area's guess.

    A leaf _leaf_area already prices at 0.0 (genuine wiring -- field reads,
    constant shifts, bit_assign/concat/rotate) stays 0.0 with no cache lookup
    and no tally: it was never a candidate for measurement, so counting it as
    "estimated" would understate how much of a schedule's priced area is
    real.

    `tally`, when given, counts real-vs-fallback PRICED leaves so the caller
    can report how much of a schedule's area came from measurement (see
    _describe_area_model) -- a cold cache silently pulls a ranking onto
    fallback numbers, which needs to be visible in the build log, not just in
    the resulting number.
    """
    abstract = _leaf_area(entity, logic)
    if abstract <= 0.0:
        return 0.0
    scale = _area_unit_scale(parser_state)
    if scale != 1.0:
        try:
            cached = SYN.GET_CACHED_LEAF_AREA(logic, parser_state)
        except Exception:
            cached = None
        if cached is not None and cached[0] > 0.0:
            _tally(tally, "measured")
            return cached[0]
    _tally(tally, "estimated")
    return abstract * scale


def _ff_area_um2(parser_state):
    """One flip-flop's area, in the model's current output unit: the real
    sky130 sequential cell area under DEVICE_MODELS (no cache needed --
    DEVICE_MODELS.GET_SEQUENTIAL_CELL_AREA is a closed-form liberty lookup,
    not a per-shape measurement), or the scaled AREA_PER_BIT_FF fallback
    otherwise. This is the single largest correction real sky130 data makes
    to this model: AREA_PER_BIT_FF is an FPGA number (a flip-flop paired with
    its LUT is nearly free); a real sky130 dfxtp_1 measures 2.5x it."""
    scale = _area_unit_scale(parser_state)
    if scale != 1.0:
        try:
            import DEVICE_MODELS

            value, _unit = DEVICE_MODELS.GET_SEQUENTIAL_CELL_AREA()
            if value > 0.0:
                return value
        except Exception:
            pass
    return AREA_PER_BIT_FF * scale


def _mux_bank_area_um2(parser_state, ctype, tally=None):
    """One 2:1 multiplexer bank's area over `ctype`, in the model's current
    output unit: the real cached sky130 measurement for this width's mux bank
    when there is one, the scaled AREA_PER_BIT_MUX fallback otherwise.

    Priced by width alone (no Logic object exists yet -- this is called
    while SCHEDULING, before any mux entity is built), using the same
    _ctype_width the abstract term already assumed as the physical SLV
    width; a real cache entry for a struct or array ctype with padding would
    disagree, but that approximation is not new here -- it is the one
    AREA_PER_BIT_MUX already made.

    The cache key itself goes through SYN.GET_MUX_CACHE_KEY rather than
    being reconstructed here: under --no_mux_delay_by_width every mux width
    collapses onto one shared "mux" key (SYN.GET_CACHED_LOGIC_FILE_KEY), and
    a caller that always asked for "MUX_uint{width}_t" directly would miss
    every real measurement in that mode, silently and without a wrong
    answer -- just a 100% fallback rate this function's own tally would not
    even flag as unusual, since a genuinely cold cache looks the same.
    """
    width = _ctype_width(ctype)
    scale = _area_unit_scale(parser_state)
    if scale != 1.0:
        try:
            key = SYN.GET_MUX_CACHE_KEY(width)
            cached = SYN.GET_CACHED_LEAF_AREA_BY_KEY(key, parser_state)
        except Exception:
            cached = None
        if cached is not None and cached[0] > 0.0:
            _tally(tally, "measured")
            return cached[0]
    _tally(tally, "estimated")
    return width * AREA_PER_BIT_MUX * scale


def ESTIMATE_ENTITY_AREA(parser_state, entity, memo=None, tally=None):
    """Estimated area of one entity INCLUDING everything it instantiates, in
    the model's current output unit (see _area_unit_scale).

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
        total = _leaf_area_um2(parser_state, entity, logic, tally)
    else:
        total = sum(
            ESTIMATE_ENTITY_AREA(parser_state, sub, memo, tally)
            for sub in logic.submodule_instances.values()
        )
    memo[entity] = total
    return total


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

    def inj_named(self, obj, name):
        """Inject a live object under an EXACT name, for the few callees the
        elaborator recognizes by name rather than by value.

        The bit-manipulation builtins (concat, bit_assign, rotl, ...) are
        intercepted in _elab_call by literal name; injected as `_af_bm0` they
        instead look like an ordinary callable, and the elaborator tries to
        elaborate their SIMULATION body -- which is plain Python (`concat` maps
        a list comprehension over its varargs) and not hardware at all.
        """
        if self.globals.get(name) not in (None, obj):
            raise AutoError(
                f"AUTO_FSM: generated-source name {name!r} is already bound to a "
                f"different object (internal error)"
            )
        self.globals[name] = obj
        return name

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

    fake_file = f"/pypeline_auto_fsm_gen/{func_name}.py"
    linecache.cache[fake_file] = (len(src), None, src.splitlines(True), fake_file)
    code = compile(src, fake_file, "exec")
    ns = dict(extra_globals)
    exec(code, ns)
    fn = ns[func_name]
    fn._auto_fsm_generated_src = src
    return fn


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
        raise AutoError(
            "AUTO_FSM: compound assembly needs statements, not an expression "
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
            raise AutoError(
                f"AUTO_FSM: no pypeline builtin named {op['builtin']!r} to "
                f"re-emit entity {entity!r}"
            )
        args = list(operand_exprs) + [repr(c) for c in op["consts"]]
        return f"{em.inj_named(fn, op['builtin'])}({', '.join(args)})"
    if kind == "call":
        func = _entity_callables(parser_state).get(entity)
        if func is None:
            raise AutoError(
                f"AUTO_FSM: entity {entity!r} has no live Python callable "
                f"recorded, so it cannot be emitted."
            )
        return f"{em.inj(func, 'f')}({', '.join(operand_exprs)})"
    raise AutoError(f"AUTO_FSM: unsupported operation kind {kind!r}")


class _GraphCodegen:
    """Render nodes of a typed combinational DAG as Pypeline expressions.

    The part of source emission that needs no scheduler: operand casts, glue,
    compound assembly, constants. Subclasses provide `self.nodes` (the DAG's
    node table), `self.em` (an _Emitter), `self.types` (a _TypeResolver),
    `self.parser_state`, `self.func_entity` (the entity whose constant wires
    are decoded), a `self._tmp_n` counter, and `_render_ref(ref)` -- how a
    value reference reads in the subclass's context (AUTO_FSM: per-state
    registers and shared-unit outputs; AUTO_COMB_OPT: one local per node).
    """

    def _render_ref(self, ref):
        raise NotImplementedError

    def _render_glue(self, nid, node):
        # Glue is rendered as a bare INLINE EXPRESSION, so -- unlike a scheduled
        # operation, whose operands land in an array declared at the port type,
        # and unlike assembly, which writes into a typed local's fields --
        # nothing here performs the port's own cast. _clean_cast_chain drops
        # that cast on exactly that assumption, so replay it here.
        assemble = node["op"]["kind"] == "assemble"
        # A bit slice's base must be a plain name: the elaborator resolves it
        # by looking the identifier up, so a base that is itself an expression
        # -- notably another slice, which happens as soon as one opened
        # operation feeds a second -- is not recognized as a slice at all and
        # is misread as an array index (`((v0)[15:0])[13:0]`).
        slicing = node["op"].get("builtin") == "__slice__"
        operand_exprs = [
            self._render_operand(
                node, i, at_port_type=not assemble, force_local=slicing
            )
            for i in range(len(node["operands"]))
        ]
        if assemble:
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
    def _render_operand(self, node, i, at_port_type=False, force_local=False):
        """Render operand i of a node, replaying any narrowing the original
        code performed between the producer and this port.

        `at_port_type` additionally materializes the port's own type, for
        consumers that render the operand inline instead of assigning it to
        something declared at that type. It is not cosmetic: a literal is typed
        at its own minimal width, so an operation reading `440` on a 16-bit port
        sees a 9-bit value unless the widening the real wire performs is
        replayed -- which is how descending into a soft multiplier used to
        produce "Bit index [14:14] out of range for uint9_t".
        """
        expr = self._render_ref(node["operands"][i])
        chain = list(node["casts"][i])
        if at_port_type:
            port_type = node["port_types"][i]
            # Scalar integer ports only: width is the whole point, and a
            # compound port carries its value through unreinterpreted anyway.
            if (
                port_type is not None
                and _scalar_ctype_to_type(port_type) is not None
                and self._expr_ctype(node, i, chain) != port_type
            ):
                chain.append(port_type)
        for ctype in chain:
            expr = self._cast_local(expr, ctype)
        if force_local and not expr.isidentifier():
            ctype = node["port_types"][i] or node["out_type"]
            expr = self._cast_local(expr, ctype)
        return expr
    def _expr_ctype(self, node, i, chain):
        """The type a rendered operand expression already carries, or None when
        that cannot be known (a constant literal carries only its own width)."""
        if chain:
            return chain[-1]
        ref = node["operands"][i]
        if ref[0] == "node":
            producer = self.nodes.get(ref[1])
            return producer.get("out_type") if producer else None
        return None
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
        logic = self.parser_state.FuncLogicLookupTable.get(self.func_entity)
        try:
            val = C_TO_LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                wire_name, logic, self.parser_state
            )
        except Exception as e:
            raise AutoError(
                f"AUTO_FSM: cannot recover the value of constant {wire_name!r}: {e}"
            )
        text = str(val).strip()
        try:
            return repr(int(text, 0))
        except ValueError:
            raise AutoError(
                f"AUTO_FSM: constant {wire_name!r} has non-integer value "
                f"{text!r}, which cannot be regenerated as a literal yet"
            )
