"""Exact delay-oriented candidates over the shared typed HLS graph."""
import copy

import HLS


def implementation_seeds(func, dag, parser_state, elaborator):
    """Reuse exact library implementations; timing decides, not their names."""
    import AUTO_FSM
    from operators.comb_share import _primitive_math, make_carry_save_sum3
    from operators.soft_add import make_soft_add_carry_select
    from operators.soft_cmp import make_soft_cmp_prefix
    from operators.soft_mult import make_soft_mult_shift_add, make_soft_mult_karatsuba

    types = AUTO_FSM._TypeResolver()
    types.seed_callable(func)
    seeds, replacements = [], {}
    for nid in HLS.order(dag):
        n = dag["nodes"][nid]
        op = n["op"].get("op")
        if (n["op"]["kind"] != "binop" or op not in ("+", "*", "<", "<=", ">", ">=")
                or not all(HLS.integer(t) and t.startswith("uint") for t in n["port_types"])
                or max(HLS.width(t) for t in n["port_types"]) > 64):
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
                AUTO_FSM._RESOLVE_BUILTIN_SUBMODULES(parser_state, logic.func_name)
                replacements[key].append((logic.func_name, factory.__name__))
        for index, (entity, label) in enumerate(replacements[key]):
            family = (op, index)
            item = next((item for item in seeds if item[0] == family), None)
            if item is None:
                item = (family, copy.deepcopy(dag), ["operator alternative: " + label])
                seeds.append(item)
            item[1]["nodes"][nid] = dict(n, kind="call", op={"kind": "call"}, entity=entity)
    result = [(graph, labels) for _, graph, labels in seeds]
    from AUTO_COMB_SHARE import _demanded_bits, _unsigned

    demanded = _demanded_bits(dag)
    csa = copy.deepcopy(dag)
    count = 0
    for nid in HLS.order(dag):
        n = dag["nodes"][nid]
        if n["op"] != {"kind": "binop", "op": "+"} or not demanded[nid] or count >= 16:
            continue
        for side, ref in enumerate(n["operands"]):
            child = dag["nodes"].get(ref[1]) if ref[0] == "node" else None
            if not child or child["op"] != n["op"]:
                continue
            bits = demanded[nid]
            intermediate = [child["out_type"], n["port_types"][side]] + n["casts"][side]
            if any(not _unsigned(t) or HLS.width(t) < bits for t in intermediate):
                continue
            port_types = child["port_types"] + [n["port_types"][1 - side]]
            if not all(_unsigned(t) for t in port_types + [n["out_type"]]):
                continue
            factory = make_carry_save_sum3(*[types.resolve(t) for t in port_types], types.resolve(n["out_type"]), bits)
            logic = elaborator._elaborate_live_func(factory.__name__, factory)
            AUTO_FSM._RESOLVE_BUILTIN_SUBMODULES(parser_state, logic.func_name)
            csa["nodes"][nid] = dict(n, kind="call", op={"kind": "call"}, entity=logic.func_name,
                operands=child["operands"] + [n["operands"][1 - side]],
                casts=child["casts"] + [n["casts"][1 - side]], port_types=port_types)
            count += 1
            break
    if count:
        result.append((HLS.prune(csa), ["carry-save sum reduction"]))
    return result


def speculate(dag):
    """Move a common selector after a total primitive; keep operands correlated.

    Calls, division/modulo and variable shifts are deliberately not speculated:
    a previously unselected input might not have defined behavior there.
    """
    for nid in HLS.order(dag):
        node = dag["nodes"][nid]
        if (node["op"].get("kind") not in ("binop", "unaryop")
                or node["op"].get("op") not in ("+", "-", "*", "&", "|", "^", "~", "!", "==", "!=", "<", "<=", ">", ">=")
                or not all(HLS.integer(t) for t in node["port_types"] + [node["out_type"]])):
            continue
        selectors = {}
        for i, ref in enumerate(node["operands"]):
            child = dag["nodes"].get(ref[1]) if ref[0] == "node" else None
            if child and child["op"]["kind"] == "mux":
                key = HLS.frozen((child["operands"][0], child["casts"][0]))
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
                branches.append(HLS.add_node(trial, branch))
            selector = selected[0][1]
            cond = HLS.cast(trial, selector["operands"][0], selector["casts"][0], "uint1_t")
            result = HLS.mux(trial, cond, branches[0], branches[1], node["out_type"])
            HLS.replace(trial, nid, result)
            yield "correlated mux speculation", HLS.common_expressions(trial)


def balanced(dag):
    """Balance modular unsigned sums/bitwise trees without losing edge casts."""
    from AUTO_COMB_SHARE import _demanded_bits, _unsigned

    demanded = _demanded_bits(dag)
    for nid in HLS.order(dag):
        root = dag["nodes"][nid]
        op = root["op"].get("op")
        if root["op"]["kind"] != "binop" or op not in ("+", "&", "|", "^"):
            continue
        bits = demanded[nid]
        if not bits or len(set(root["port_types"])) != 1:
            continue

        def legal(node):
            return (node["op"] == root["op"]
                    and all(_unsigned(t) and HLS.width(t) >= bits
                            for t in node["port_types"] + [node["out_type"]]
                            + [t for chain in node["casts"] for t in chain]))

        if not legal(root):
            continue
        trial, leaves = copy.deepcopy(dag), []
        pending = [(ref, chain) for ref, chain in zip(root["operands"], root["casts"])]
        while pending and len(leaves) + len(pending) <= 64:
            ref, chain = pending.pop(0)
            child = dag["nodes"].get(ref[1]) if ref[0] == "node" else None
            if child and legal(child) and all(_unsigned(t) and HLS.width(t) >= bits for t in chain):
                pending[0:0] = list(zip(child["operands"], child["casts"]))
            else:
                leaves.append(HLS.cast(trial, ref, chain, root["port_types"][0]))
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
                    level.append(HLS.add_node(trial, n))
            leaves = level
        HLS.replace(trial, nid, leaves[0])
        yield "balanced unsigned " + op, HLS.common_expressions(trial)


def expand(dag):
    """Distribute in a uniform modular ring / Boolean algebra."""
    from AUTO_COMB_SHARE import _demanded_bits, _unsigned

    demanded = _demanded_bits(dag)
    rules = {"*": ("+",), "&": ("|", "^"), "|": ("&",)}
    for nid in HLS.order(dag):
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
            if any(not _unsigned(t) or HLS.width(t) < bits for t in types):
                continue
            trial, branches = copy.deepcopy(dag), []
            for i in range(2):
                branch = copy.deepcopy(n)
                branch["operands"][side] = child["operands"][i]
                branch["casts"][side] = child["casts"][i] + [child["port_types"][i]]
                branches.append(HLS.add_node(trial, branch))
            outer = copy.deepcopy(child)
            outer["operands"], outer["casts"] = branches, [[], []]
            # Preserve the written root's full return type; only demanded bits
            # may differ above the ring width and are truncated by consumers.
            result = HLS.cast(trial, HLS.add_node(trial, outer), [], n["out_type"])
            HLS.replace(trial, nid, result)
            yield "distributive expansion", HLS.common_expressions(trial)
