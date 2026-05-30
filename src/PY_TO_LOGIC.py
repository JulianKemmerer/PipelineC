import ast
import hashlib
import importlib.util
import inspect
import os
import re

import C_TO_LOGIC
import AST as pypeline_ast
from pypeline import _RegType, BIT_MANIP_FUNC_NAMES as _BIT_MANIP_FUNC_NAMES

UNARY_OP_MAP = {
    ast.Invert: C_TO_LOGIC.UNARY_OP_NOT_NAME,
    ast.USub: C_TO_LOGIC.UNARY_OP_NEGATE_NAME,
    ast.Not: C_TO_LOGIC.UNARY_OP_NOT_NAME,
}

BIN_OP_MAP = {
    ast.Add: C_TO_LOGIC.BIN_OP_PLUS_NAME,
    ast.Sub: C_TO_LOGIC.BIN_OP_MINUS_NAME,
    ast.Mult: C_TO_LOGIC.BIN_OP_MULT_NAME,
    ast.Div: C_TO_LOGIC.BIN_OP_DIV_NAME,
    ast.Mod: C_TO_LOGIC.BIN_OP_MOD_NAME,
    ast.LShift: C_TO_LOGIC.BIN_OP_SL_NAME,
    ast.RShift: C_TO_LOGIC.BIN_OP_SR_NAME,
    ast.BitAnd: C_TO_LOGIC.BIN_OP_AND_NAME,
    ast.BitOr: C_TO_LOGIC.BIN_OP_OR_NAME,
    ast.BitXor: C_TO_LOGIC.BIN_OP_XOR_NAME,
    ast.Gt: C_TO_LOGIC.BIN_OP_GT_NAME,
    ast.GtE: C_TO_LOGIC.BIN_OP_GTE_NAME,
    ast.Lt: C_TO_LOGIC.BIN_OP_LT_NAME,
    ast.LtE: C_TO_LOGIC.BIN_OP_LTE_NAME,
    ast.Eq: C_TO_LOGIC.BIN_OP_EQ_NAME,
    ast.NotEq: C_TO_LOGIC.BIN_OP_NEQ_NAME,
}

# Augmented assignment operators for const_env updates (b += 1 etc.)
AUG_OP_MAP = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
}

# Arithmetic ops where output width differs from inputs and sign promotion applies.
# (Bitwise, shift, compare ops are handled separately.)
_ARITH_OPS = frozenset(
    {
        C_TO_LOGIC.BIN_OP_PLUS_NAME,
        C_TO_LOGIC.BIN_OP_MINUS_NAME,
        C_TO_LOGIC.BIN_OP_MULT_NAME,
        C_TO_LOGIC.BIN_OP_DIV_NAME,
        C_TO_LOGIC.BIN_OP_MOD_NAME,
    }
)

# ─────────────────────────────────────────────
# Type system helpers
# ─────────────────────────────────────────────


def _is_array(c_type):
    return "[" in c_type


def _is_struct(c_type, parser_state):
    return c_type in parser_state.struct_to_field_type_dict


def _is_scalar(c_type, parser_state):
    return not _is_array(c_type) and not _is_struct(c_type, parser_state)


def _array_elem_type(c_type):
    """'point_t[100]' -> 'point_t',  'uint32_t[4][8]' -> 'uint32_t[8]'"""
    first_bracket = c_type.index("[")
    first_close = c_type.index("]")
    return c_type[:first_bracket] + c_type[first_close + 1 :]


def _array_first_dim(c_type):
    """'point_t[100]' -> 100"""
    return int(c_type[c_type.index("[") + 1 : c_type.index("]")])


def _is_var_tok(tok):
    """True if a ref tok is a variable index (Python AST expression node)."""
    return isinstance(tok, ast.AST)


def _has_variable_index(ref_toks):
    return any(_is_var_tok(tok) for tok in ref_toks)


def _select_type_for_dim(dim_size):
    """Minimum unsigned type to hold 0..dim_size-1. e.g. 10 -> 'uint4_t'"""
    bits = max(1, (dim_size - 1).bit_length()) if dim_size > 1 else 1
    return f"uint{bits}_t"


def _ref_toks_to_ctype(ref_toks, base_type, parser_state):
    """Traverse type according to ref_toks. Handles int, str, and AST (variable) tokens."""
    c_type = base_type
    for tok in ref_toks[1:]:
        if isinstance(tok, int) or _is_var_tok(tok):
            c_type = _array_elem_type(c_type)
        elif isinstance(tok, str):
            c_type = parser_state.struct_to_field_type_dict[c_type][tok]
        else:
            raise NotImplementedError(f"Unknown ref tok type: {type(tok)} {tok!r}")
    return c_type


def _get_leaf_ref_toks(base_ref_toks, c_type, parser_state):
    """Recursively enumerate all scalar leaf ref_toks under base_ref_toks (concrete tokens only)."""
    if _is_scalar(c_type, parser_state):
        return [base_ref_toks]
    elif _is_array(c_type):
        elem_type = _array_elem_type(c_type)
        dim = _array_first_dim(c_type)
        leaves = []
        for i in range(dim):
            leaves += _get_leaf_ref_toks(base_ref_toks + (i,), elem_type, parser_state)
        return leaves
    elif _is_struct(c_type, parser_state):
        fields = parser_state.struct_to_field_type_dict[c_type]
        leaves = []
        for field_name, field_type in fields.items():
            leaves += _get_leaf_ref_toks(
                base_ref_toks + (field_name,), field_type, parser_state
            )
        return leaves
    else:
        raise NotImplementedError(f"Unknown type for leaf enumeration: {c_type}")


def _get_var_ref_leaves(ref_toks, base_type, parser_state):
    """Enumerate all concrete scalar leaf ref_toks for a VAR_REF_RD.
    Variable tokens expand to ALL elements; constant tokens fix to their value.
    Ordering: outermost variable dim varies slowest, output type leaves vary fastest.
    This matches interm[D0][D1]...[output_leaf] indexing.
    """
    result = [ref_toks[:1]]
    current_type = base_type
    for tok in ref_toks[1:]:
        if isinstance(tok, int):
            result = [path + (tok,) for path in result]
            current_type = _array_elem_type(current_type)
        elif isinstance(tok, str):
            result = [path + (tok,) for path in result]
            current_type = parser_state.struct_to_field_type_dict[current_type][tok]
        else:  # variable: expand all elements
            dim = _array_first_dim(current_type)
            new_result = []
            for path in result:
                for k in range(dim):
                    new_result.append(path + (k,))
            result = new_result
            current_type = _array_elem_type(current_type)
    # expand remaining compound output type to scalar leaves
    all_leaves = []
    for path in result:
        all_leaves += _get_leaf_ref_toks(path, current_type, parser_state)
    return all_leaves


def _get_output_leaf_info(c_type, parser_state):
    """Get scalar leaf info for the output type of a VAR_REF_RD.
    Returns (leaf_count, leaf_paths, leaf_types) using dummy base '_out'.
    The 'output_leaf' dimension in the intermediate is of size leaf_count.
    """
    dummy_base = "_out"
    leaf_paths = _get_leaf_ref_toks((dummy_base,), c_type, parser_state)
    leaf_types = [_ref_toks_to_ctype(lp, c_type, parser_state) for lp in leaf_paths]
    return len(leaf_paths), leaf_paths, leaf_types


def _ref_toks_to_env_key(ref_toks):
    """("my_points", 3, "x") -> "my_points[3].x"  (concrete tokens only)"""
    result = str(ref_toks[0])
    for tok in ref_toks[1:]:
        if isinstance(tok, int):
            result += f"[{tok}]"
        else:
            result += f".{tok}"
    return result


def _largest_pow2_leq(n):
    """Largest power of 2 strictly less than n (split point for trimmed binary tree).
    n=100->64, n=64->32, n=4->2, n=2->1
    """
    assert n >= 2
    return 1 << ((n - 1).bit_length() - 1)


# ─────────────────────────────────────────────
# VAR_REF_ASSIGN helpers
# ─────────────────────────────────────────────


def _var_ref_toks_covers(var_ref_toks, concrete_ref_toks):
    """True if var_ref_toks is a prefix that covers concrete_ref_toks.
    AST node tokens in var_ref_toks act as wildcards matching any concrete value.
    e.g. ("points", i_ast, "dim", 1) covers ("points", 0, "dim", 1) ✓
         ("points", i_ast, "dim", 1) covers ("points", 0, "dim", 0) ✗  (1 != 0)
    """
    if len(var_ref_toks) > len(concrete_ref_toks):
        return False
    for vt, ct in zip(var_ref_toks, concrete_ref_toks):
        if _is_var_tok(vt):
            continue  # wildcard: AST node matches any concrete value
        if vt != ct:
            return False
    return True


def _var_alias_internal_path(cov_ref_toks, concrete_ref_toks):
    """Compute the internal path from a covering wire into a concrete leaf.
    For concrete covering wires this is just the suffix beyond the prefix.
    For variable alias covering wires, concrete values at AST node positions
    become the index path into the alias output type.

    e.g. cov=("points", i_ast, "dim", 1), concrete=("points", 0, "dim", 1)
         → (0,)   [i_ast matched 0; no remaining suffix]
         cov=("points", i_ast), concrete=("points", 0, "dim", 1)
         → (0, "dim", 1)  [i_ast matched 0; suffix "dim",1 appended]
         cov=("points",), concrete=("points", 0, "dim", 1)
         → (0, "dim", 1)  [no AST nodes; just the suffix]
    """
    path = []
    for vt, ct in zip(cov_ref_toks, concrete_ref_toks):
        if _is_var_tok(vt):
            path.append(ct)  # concrete value matched by wildcard becomes index
    path.extend(concrete_ref_toks[len(cov_ref_toks) :])  # remaining suffix
    return tuple(path)


def _var_ref_assign_output_type(ref_toks, base_type, parser_state):
    """Compute output type for VAR_REF_ASSIGN: leaf_scalar_type[var_dim_0][var_dim_1]...
    The leaf scalar type is the type at the constant-index suffix of ref_toks.
    Variable dimensions are prepended as outer array dimensions.

    e.g. points[i].dim[1] → leaf=uint32_t, var_dims=[3] → uint32_t[3]
         points[0].dim[j] → leaf=uint32_t, var_dims=[2] → uint32_t[2]
         points[i].dim[j] → leaf=uint32_t, var_dims=[3,2] → uint32_t[3][2]
    """
    current_type = base_type
    var_dims = []
    for tok in ref_toks[1:]:
        if _is_var_tok(tok):
            var_dims.append(_array_first_dim(current_type))
            current_type = _array_elem_type(current_type)
        elif isinstance(tok, int):
            current_type = _array_elem_type(current_type)
        elif isinstance(tok, str):
            current_type = parser_state.struct_to_field_type_dict[current_type][tok]
    # current_type is now the leaf type (scalar or inner array)
    # Unpack inner array dims, then rebuild with var dims prepended
    inner_dims = []
    t = current_type
    while _is_array(t):
        inner_dims.append(_array_first_dim(t))
        t = _array_elem_type(t)
    scalar = t  # innermost scalar type
    result = scalar
    for d in var_dims:
        result += f"[{d}]"
    for d in inner_dims:
        result += f"[{d}]"
    return result


def _ref_toks_to_alias_prefix(ref_toks):
    """Build an alias name prefix for ref_toks that may contain AST node tokens.
    AST nodes are encoded as 'VAR'.
    e.g. ("points", i_ast, "dim", 1) → "points_VAR_dim_1"
    """
    parts = [str(ref_toks[0])]
    for tok in ref_toks[1:]:
        parts.append("VAR" if _is_var_tok(tok) else str(tok))
    return "_".join(parts)


def _get_var_ref_elem_positions(ref_toks, base_type, parser_state):
    """Enumerate concrete element positions for VAR_REF_ASSIGN.
    Like _get_var_ref_leaves but stops at the elem type — does NOT decompose it.
    Variable index tokens expand to all concrete values; constant tokens are fixed.
    The elem type at the end of ref_toks may itself be compound (struct/array).
    Returns (positions_list, elem_c_type).
    """
    result = [ref_toks[:1]]
    current_type = base_type
    for tok in ref_toks[1:]:
        if isinstance(tok, int):
            result = [path + (tok,) for path in result]
            current_type = _array_elem_type(current_type)
        elif isinstance(tok, str):
            result = [path + (tok,) for path in result]
            current_type = parser_state.struct_to_field_type_dict[current_type][tok]
        else:  # variable index: expand all elements of this dimension
            dim = _array_first_dim(current_type)
            new_result = []
            for path in result:
                for k in range(dim):
                    new_result.append(path + (k,))
            result = new_result
            current_type = _array_elem_type(current_type)
    # current_type is now the elem_c_type — may be compound, do NOT expand further
    return result, current_type


def _get_elem_positions(base_path, c_type, elem_c_type):
    """Enumerate all positions of elem_c_type within c_type.
    output_type = elem_c_type[D0][D1]... so we walk only the outer array wrapping.
    Returns list of ref_toks path tuples.
    e.g. ("_out",), "point2d_t[3]", "point2d_t"
         → [("_out",0), ("_out",1), ("_out",2)]
    """
    if c_type == elem_c_type:
        return [base_path]
    if _is_array(c_type):
        dim = _array_first_dim(c_type)
        inner = _array_elem_type(c_type)
        result = []
        for k in range(dim):
            result.extend(_get_elem_positions(base_path + (k,), inner, elem_c_type))
        return result
    return []  # should not occur for well-formed output_type


def _var_ref_assign_func_name(output_type, base_type, ref_toks, covering_ref_toks_list):
    """Build VAR_REF_ASSIGN func name."""
    func_name = C_TO_LOGIC.VAR_REF_ASSIGN_FUNC_NAME_PREFIX
    func_name += "_" + output_type.replace("[", "_").replace("]", "")
    func_name += "_" + base_type.replace("[", "_").replace("]", "")
    for tok in ref_toks[1:]:
        func_name += "_VAR" if _is_var_tok(tok) else "_" + str(tok)
    input_str = "_".join(
        "_".join(str(t) for t in toks) for toks in covering_ref_toks_list
    )
    h = hashlib.md5(input_str.encode()).hexdigest()[: C_TO_LOGIC.C_AST_NODE_HASH_LEN]
    func_name += "_" + h
    return func_name


# ─────────────────────────────────────────────
# Annotation evaluation
# ─────────────────────────────────────────────


def _annotation_to_ctype(ann, eval_ns=None):
    """Convert Python AST annotation to C type string. Returns None if no annotation.
    If eval_ns provided, evaluates the annotation expression against that namespace.
    This handles: uint1_t[N], uint1_t[sum_widths(N,M)], point_t, etc.
    """
    if ann is None:
        return None
    # With eval_ns: evaluate the annotation expression as Python.
    # _CType objects give their C type string via str(); class objects give __name__.
    if eval_ns is not None:
        try:
            expr = ast.Expression(body=ann)
            ast.fix_missing_locations(expr)
            result = eval(compile(expr, "<annotation>", "eval"), eval_ns)
            if isinstance(result, type):
                return getattr(result, "_pypeline_ctype_name", None) or getattr(
                    result, "_pypeline_ctype_canonical", result.__name__
                )
            return str(result)
        except Exception:
            pass  # fall through to static handling
    # Static fallback (no eval_ns or eval failed)
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Attribute):
        return ann.attr
    if isinstance(ann, ast.Subscript):
        base = _annotation_to_ctype(ann.value, eval_ns)
        slc = ann.slice
        if isinstance(slc, ast.Index):  # Python 3.8 compat
            slc = slc.value
        if isinstance(slc, ast.Constant):
            return f"{base}[{slc.value}]"
        raise NotImplementedError(
            f"Non-constant subscript in annotation: {ast.dump(ann)}"
        )
    raise NotImplementedError(f"Unsupported type annotation: {ast.dump(ann)}")


# ─────────────────────────────────────────────
# Naming helpers
# ─────────────────────────────────────────────


def _canonical_func_name(func, closure_ns, module_globals=None):
    """Return a canonical name for a factory-produced closure, or None for top-level functions.

    Factory closures have '.<locals>.' in __qualname__. The canonical name is:

        <factory_prefix>_<param1>_<val1>_<param2>_<val2>_...

    where <factory_prefix> is the qualname chain (definition hierarchy, not call site),
    and only closure variables whose names match a factory parameter are included.

    Three cases:
      1. Factory not found in module_globals: fall back to all type/int closure vars.
      2. Factory has 0 params: name is just the factory prefix (no suffix).
      3. Factory has params but none are in the closure (e.g. T not captured in
         make_swap because only a derived local was used): fall back to all type/int
         closure vars so the name is still unique.
    """
    if ".<locals>." not in func.__qualname__:
        return None
    parts = func.__qualname__.split(".<locals>.")
    factory_prefix = "_".join(parts[:-1])  # drop inner func name, keep factory chain

    # Collect parameter names from each factory in the qualname chain.
    # None means "factory not found"; empty set means "0-param factory".
    factory_param_names = None
    if module_globals is not None:
        outermost_func = module_globals.get(parts[0])
        if callable(outermost_func) and hasattr(outermost_func, "__code__"):
            n = outermost_func.__code__.co_argcount
            factory_param_names = set(outermost_func.__code__.co_varnames[:n])
            # Middle factories in the chain may be in the closure as callables.
            for middle_name in parts[1:-1]:
                middle_func = closure_ns.get(middle_name)
                if callable(middle_func) and hasattr(middle_func, "__code__"):
                    m = middle_func.__code__.co_argcount
                    factory_param_names.update(middle_func.__code__.co_varnames[:m])

    if factory_param_names is None:
        # Factory not found — fall back to all type/int closure vars (legacy).
        filtered_ns = closure_ns
    elif factory_param_names:
        # Factory has params — only include those present in the closure.
        filtered_ns = {k: v for k, v in closure_ns.items() if k in factory_param_names}
        if not filtered_ns:
            # None of the factory params were captured (e.g. make_swap's T is only
            # used to compute local_pair_t and never referenced in swap's body).
            # Fall back to all closure vars so the name is still unique.
            filtered_ns = closure_ns
    else:
        # 0-param factory — name is just the factory prefix, no suffix.
        filtered_ns = {}

    name_parts = []
    for var_name in sorted(filtered_ns.keys()):
        val = filtered_ns[var_name]
        if isinstance(val, type):
            if hasattr(val, "_pypeline_ctype_name"):
                s = val._pypeline_ctype_name  # @struct type: already canonical
            else:
                s = str(val)
                if s.startswith("<"):
                    continue  # plain Python class without canonical C name, skip
                s = s.replace("[", "_").replace("]", "")  # mangle brackets
            name_parts.append(f"{var_name}_{s}")
        elif isinstance(val, (int, bool)) and not isinstance(val, type):
            name_parts.append(f"{var_name}_{val}")
        elif val is None:
            name_parts.append(f"{var_name}_None")
        elif callable(val):
            continue  # local function objects — elaborated separately, not part of name
        else:
            raise ElaborationError(
                f"Factory closure variable '{var_name}' has unsupported value "
                f"{val!r} (type: {type(val).__name__}). "
                f"Factory parameters must be C types, ints, bools, None, or callables."
            )
    return factory_prefix + ("_" + "_".join(name_parts) if name_parts else "")


def _loc_str(src_file, node):
    file_base = os.path.basename(src_file).replace(".", "_")
    end = (
        f"_e{node.end_col_offset}"
        if hasattr(node, "end_col_offset") and node.end_col_offset is not None
        else ""
    )
    return f"{file_base}_l{node.lineno}_c{node.col_offset}{end}"


def _inst_name(op_full_name, src_file, node):
    return f"{op_full_name}[{_loc_str(src_file, node)}]"


def _port_wire(inst, port):
    return f"{inst}{C_TO_LOGIC.SUBMODULE_MARKER}{port}"


def _alias(var_name, src_file, node):
    return f"{var_name}_{_loc_str(src_file, node)}"


def _unary_func_name(op_name, typ):
    return f"{C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX}_{op_name}_{typ}"


def _bin_func_name(op_name, l_type, r_type):
    return f"{C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX}_{op_name}_{l_type}_{r_type}"


# ─────────────────────────────────────────────
# Integer type helpers for arithmetic promotion
# ─────────────────────────────────────────────

_INT_CTYPE_RE = re.compile(r"(u?)int(\d+)_t$")


def _ctype_is_int(c_type):
    """True if c_type is a plain integer type (uint/int)."""
    return bool(_INT_CTYPE_RE.match(c_type))


def _ctype_info(c_type):
    """Parse integer C type string. Returns (is_signed, width).
    e.g. 'uint32_t' -> (False, 32),  'int16_t' -> (True, 16)
    """
    m = _INT_CTYPE_RE.match(c_type)
    if not m:
        raise NotImplementedError(f"Cannot get integer type info from: {c_type!r}")
    return (m.group(1) != "u", int(m.group(2)))  # (is_signed, width)


def _int_ctype(is_signed, width):
    """Build integer C type string. e.g. (True, 32) -> 'int32_t'"""
    return f"{'int' if is_signed else 'uint'}{width}_t"


def _arith_promote(l_type, r_type):
    """Compute effective input types after sign promotion for arithmetic/compare ops.

    If both types have the same signedness, they are returned unchanged.
    If there is a mismatch, the unsigned operand gains +1 bit and becomes signed
    so the VHDL backend can operate on matching-sign types:
      e.g. (int32_t, uint32_t) -> (int32_t, int33_t, True)

    Returns (eff_l_type, eff_r_type, result_is_signed).
    For non-integer types, returns the inputs unchanged with result_is_signed=None.
    """
    if not (_ctype_is_int(l_type) and _ctype_is_int(r_type)):
        return l_type, r_type, None
    l_signed, l_w = _ctype_info(l_type)
    r_signed, r_w = _ctype_info(r_type)
    if l_signed == r_signed:
        return l_type, r_type, l_signed
    if l_signed:
        return l_type, _int_ctype(True, r_w + 1), True  # promote r to signed
    else:
        return _int_ctype(True, l_w + 1), r_type, True  # promote l to signed


def _arith_output_type(op_name, eff_l_type, eff_r_type, result_signed):
    """Compute full-precision output type for an arithmetic op.

    Rules (after sign promotion, so both effective types have same signedness):
      add:  max(lw, rw) + 1  (one extra bit for carry)
      sub:  max(lw, rw)      if unsigned  (borrow is discarded)
            max(lw, rw) + 1  if signed    (sub of negative = add, needs extra bit)
      mult: lw + rw          (full product width)
      div, mod: max(lw, rw)  (output bounded by larger input)
    """
    _, l_w = _ctype_info(eff_l_type)
    _, r_w = _ctype_info(eff_r_type)
    max_w = max(l_w, r_w)
    if op_name == C_TO_LOGIC.BIN_OP_PLUS_NAME:
        out_w = max_w + 1
    elif op_name == C_TO_LOGIC.BIN_OP_MINUS_NAME:
        out_w = max_w if not result_signed else max_w + 1
    elif op_name == C_TO_LOGIC.BIN_OP_MULT_NAME:
        out_w = l_w + r_w
    else:  # div, mod
        out_w = max_w
    return _int_ctype(result_signed, out_w)


def _infer_const_ctype(val):
    """Minimum bit-accurate C type for an integer literal."""
    if isinstance(val, bool) or val in (0, 1):
        return C_TO_LOGIC.BOOL_C_TYPE
    if val > 1:
        return f"uint{val.bit_length()}_t"
    bits = max(1, (-val - 1).bit_length() + 1)
    return f"int{bits}_t"


def _const_ref_rd_func_name(
    output_c_type, base_c_type, ref_toks, covering_ref_toks_list
):
    """Build CONST_REF_RD func name. Only the prefix matters for backend recognition."""
    func_name = C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX
    func_name += "_" + output_c_type.replace("[", "_").replace("]", "")
    func_name += "_" + base_c_type.replace("[", "_").replace("]", "")
    for tok in ref_toks[1:]:
        func_name += "_" + str(tok)
    input_str = "_".join(
        "_".join(str(t) for t in toks) for toks in covering_ref_toks_list
    )
    h = hashlib.md5(input_str.encode()).hexdigest()[: C_TO_LOGIC.C_AST_NODE_HASH_LEN]
    func_name += "_" + h
    return func_name


def _var_ref_rd_func_name(output_c_type, base_c_type, ref_toks, covering_ref_toks_list):
    """Build VAR_REF_RD func name. Variable index positions encoded as '_VAR'."""
    func_name = C_TO_LOGIC.VAR_REF_RD_FUNC_NAME_PREFIX
    func_name += "_" + output_c_type.replace("[", "_").replace("]", "")
    func_name += "_" + base_c_type.replace("[", "_").replace("]", "")
    for tok in ref_toks[1:]:
        func_name += "_VAR" if _is_var_tok(tok) else "_" + str(tok)
    input_str = "_".join(
        "_".join(str(t) for t in toks) for toks in covering_ref_toks_list
    )
    h = hashlib.md5(input_str.encode()).hexdigest()[: C_TO_LOGIC.C_AST_NODE_HASH_LEN]
    func_name += "_" + h
    return func_name


# ─────────────────────────────────────────────
# Bit manipulation Logic() registration
# ─────────────────────────────────────────────


def _register_bit_manip_logic(
    func_name, port_names, input_types, output_type, parser_state
):
    """Register a bit manipulation built-in in FuncLogicLookupTable.
    Idempotent — no-op if func_name is already registered.
    Marks the logic as is_vhdl_func=True and is_new_style_bit_manip=True.
    Returns the registered Logic().
    """
    if func_name not in parser_state.FuncLogicLookupTable:
        logic = C_TO_LOGIC.Logic()
        logic.func_name = func_name
        for port_name, c_type in zip(port_names, input_types):
            logic.inputs.append(port_name)
            logic.wire_to_c_type[port_name] = c_type
        logic.outputs.append(C_TO_LOGIC.RETURN_WIRE_NAME)
        logic.wire_to_c_type[C_TO_LOGIC.RETURN_WIRE_NAME] = output_type
        logic.is_vhdl_func = True
        logic.is_new_style_bit_manip = True
        parser_state.FuncLogicLookupTable[func_name] = logic
    return parser_state.FuncLogicLookupTable[func_name]


# ─────────────────────────────────────────────
# Logic() wire helpers
# ─────────────────────────────────────────────


def _add_wire(logic, wire_name, c_type):
    logic.wires.add(wire_name)
    logic.wire_to_c_type[wire_name] = c_type


def _connect(logic, driver, driven):
    logic.wire_driven_by[driven] = driver
    logic.wire_drives.setdefault(driver, set()).add(driven)


def _add_submodule_instance(
    logic,
    inst_name,
    func_name,
    input_ports,
    output_wire,
    output_type,
    ast_node,
    src_file,
):
    """Shared wiring bookkeeping for all submodule instance types.
    input_ports: list of (port_name, driver_wire, port_type)
    ast_node may be None for programmatically-built Logic() internals.
    """
    if inst_name in logic.submodule_instances:
        raise ElaborationError(
            f"Duplicate submodule instance name '{inst_name}' in '{logic.func_name}'. "
            f"Existing: {logic.submodule_instances[inst_name]}, new: {func_name}"
        )
    logic.submodule_instances[inst_name] = func_name
    if ast_node is not None:
        logic.submodule_instance_to_c_ast_node[inst_name] = (
            pypeline_ast.Pypeline_ASTNode(ast_node, src_file)
        )
    logic.submodule_instance_to_input_port_names[inst_name] = [
        p[0] for p in input_ports
    ]
    for port_name, driver_wire, port_type in input_ports:
        port_wire = _port_wire(inst_name, port_name)
        _add_wire(logic, port_wire, port_type)
        _connect(logic, driver_wire, port_wire)
    _add_wire(logic, output_wire, output_type)


# ─────────────────────────────────────────────
# VAR_REF_RD Logic() builder helpers
# ─────────────────────────────────────────────


def _build_binary_mux_tree(logic, leaves, select_wire, select_type, leaf_type, counter):
    """Recursively build a trimmed binary mux tree.

    Splits at largest pow2 < n so left is a complete binary tree.
    Absolute bit extraction works correctly for all subtree index ranges.

    leaf_type: C type of each leaf wire (scalar type at this mux level).
    counter:   mutable [int] for unique internal instance naming.
    Returns output wire name.
    """
    n = len(leaves)
    assert n >= 1
    if n == 1:
        return leaves[0]

    split = _largest_pow2_leq(n)
    bit_pos = split.bit_length() - 1

    # ── bit extraction: uint<N>_<bit>_<bit>(x) -> uint1_t ──
    sel_prefix = select_type.replace("_t", "")
    bit_func = f"{sel_prefix}_{bit_pos}_{bit_pos}"
    bit_inst = f"{bit_func}[var_ref_internal_{counter[0]}]"
    counter[0] += 1
    bit_wire = _port_wire(bit_inst, C_TO_LOGIC.RETURN_WIRE_NAME)
    _add_submodule_instance(
        logic,
        bit_inst,
        bit_func,
        [("x", select_wire, select_type)],
        bit_wire,
        C_TO_LOGIC.BOOL_C_TYPE,
        None,
        None,
    )

    left_wire = _build_binary_mux_tree(
        logic, leaves[:split], select_wire, select_type, leaf_type, counter
    )
    right_wire = _build_binary_mux_tree(
        logic, leaves[split:], select_wire, select_type, leaf_type, counter
    )

    # MUX(bit, right, left): bit=1 -> index >= split -> select right
    mux_suffix = leaf_type.replace("[", "_").replace("]", "")
    mux_func = f"{C_TO_LOGIC.MUX_LOGIC_NAME}_{mux_suffix}"
    mux_inst = f"{mux_func}[var_ref_internal_{counter[0]}]"
    counter[0] += 1
    mux_output = _port_wire(mux_inst, C_TO_LOGIC.RETURN_WIRE_NAME)
    _add_submodule_instance(
        logic,
        mux_inst,
        mux_func,
        [
            ("cond", bit_wire, C_TO_LOGIC.BOOL_C_TYPE),
            ("iftrue", right_wire, leaf_type),
            ("iffalse", left_wire, leaf_type),
        ],
        mux_output,
        leaf_type,
        None,
        None,
    )
    return mux_output


def _emit_internal_const_ref_rd(
    logic, internal_ref_toks, port_name, port_type, parser_state, counter
):
    """Emit a CONST_REF_RD inside a programmatically-built Logic() object.
    internal_ref_toks: path with covering port name as base, e.g. ("ref_toks_0", 0, "dim", 1)
    Returns the output wire name.
    """
    leaf_type = _ref_toks_to_ctype(internal_ref_toks, port_type, parser_state)
    crd_func = _const_ref_rd_func_name(
        leaf_type, port_type, internal_ref_toks, [internal_ref_toks[:1]]
    )
    crd_inst = f"{crd_func}[internal_{counter[0]}]"
    counter[0] += 1
    leaf_wire = _port_wire(crd_inst, C_TO_LOGIC.RETURN_WIRE_NAME)
    _add_submodule_instance(
        logic,
        crd_inst,
        crd_func,
        [("ref_toks_0", port_name, port_type)],
        leaf_wire,
        leaf_type,
        None,
        None,
    )
    logic.ref_submodule_instance_to_ref_toks[crd_inst] = internal_ref_toks
    logic.ref_submodule_instance_to_input_port_driven_ref_toks[crd_inst] = [
        internal_ref_toks[:1]
    ]
    return leaf_wire


def _build_var_ref_rd_logic(
    func_name, c_type, base_type, ref_toks, covering_wires, var_dim_info, parser_state
):
    """Build the Logic() object for a VAR_REF_RD function definition.

    Conceptual structure (matching spec pseudo-code):
      Step 1 - Extract scalar leaf wires from covering inputs via CONST_REF_RDs.
               These correspond to the cells of:
               interm: leaf_scalar_type [D0][D1]...[output_leaf_count]
               where Di are variable dimension sizes and output_leaf_count comes
               from the scalar leaf count of the output type c_type.

      Step 2 - Mux trees: one per variable dimension.
               stride = product(later_var_dim_sizes) * output_leaf_count
               For each group: binary tree reduces Di inputs to 1 output.
               After all dims: output_leaf_count wires remain.

      Step 3 - If scalar output: direct connect.
               If compound output: assemble scalar wires into c_type via CONST_REF_RD.

    var_dim_info: list of (dim_size, select_type, _index_wire) in ref_toks order
    covering_wires: ordered dict  covering_ref_toks -> (call_site_wire, port_type)
    """
    logic = C_TO_LOGIC.Logic()
    logic.func_name = func_name

    # ── covering input ports (ref_toks_i) ──
    covering_port_info = {}  # cov_ref_toks -> (port_name, port_type)
    for i, (cov_ref_toks, (_, cov_typ)) in enumerate(covering_wires.items()):
        port_name = f"ref_toks_{i}"
        logic.inputs.append(port_name)
        _add_wire(logic, port_name, cov_typ)
        covering_port_info[cov_ref_toks] = (port_name, cov_typ)

    # ── variable index input ports (var_dim_i) ──
    var_dim_ports = []  # (dim_size, port_name, select_type)
    for i, (dim_size, select_type, _) in enumerate(var_dim_info):
        port_name = f"var_dim_{i}"
        logic.inputs.append(port_name)
        _add_wire(logic, port_name, select_type)
        var_dim_ports.append((dim_size, port_name, select_type))

    # ── output port ──
    logic.outputs.append(C_TO_LOGIC.RETURN_WIRE_NAME)
    _add_wire(logic, C_TO_LOGIC.RETURN_WIRE_NAME, c_type)

    # ── output leaf info ──
    output_leaf_count, output_leaf_paths, output_leaf_types = _get_output_leaf_info(
        c_type, parser_state
    )

    # ── Step 1: extract concrete leaf wires via CONST_REF_RD ──
    all_concrete_leaves = _get_var_ref_leaves(ref_toks, base_type, parser_state)
    counter = [0]
    leaf_wires = []

    for concrete_leaf in all_concrete_leaves:
        covering_port = None
        for cov_ref_toks, (port_name, port_type) in covering_port_info.items():
            if _var_ref_toks_covers(cov_ref_toks, concrete_leaf):
                covering_port = (cov_ref_toks, port_name, port_type)
                break
        if covering_port is None:
            raise ElaborationError(f"No covering port for leaf {concrete_leaf}")

        cov_ref_toks, port_name, port_type = covering_port
        # _var_alias_internal_path handles both concrete covering wires (just a suffix)
        # and variable alias covering wires (concrete values at AST node positions)
        internal_path = _var_alias_internal_path(cov_ref_toks, concrete_leaf)
        internal_ref_toks = (port_name,) + internal_path

        if len(internal_ref_toks) == 1:
            leaf_wire = port_name
        else:
            leaf_wire = _emit_internal_const_ref_rd(
                logic, internal_ref_toks, port_name, port_type, parser_state, counter
            )
        leaf_wires.append(leaf_wire)

    # ── Step 2: mux tree per variable dimension ──
    var_dim_sizes = [d[0] for d in var_dim_ports]
    current_wires = leaf_wires

    for dim_i, (dim_size, port_name, select_type) in enumerate(var_dim_ports):
        remaining_var = var_dim_sizes[dim_i + 1 :]
        stride = output_leaf_count
        for s in remaining_var:
            stride *= s

        n_groups = stride
        next_wires = []
        for group_idx in range(n_groups):
            leaf_type_for_group = output_leaf_types[group_idx % output_leaf_count]
            group = [current_wires[k * stride + group_idx] for k in range(dim_size)]
            result = _build_binary_mux_tree(
                logic, group, port_name, select_type, leaf_type_for_group, counter
            )
            next_wires.append(result)
        current_wires = next_wires

    assert (
        len(current_wires) == output_leaf_count
    ), f"Expected {output_leaf_count} wires after mux trees, got {len(current_wires)}"

    # ── Step 3: connect / assemble output ──
    if output_leaf_count == 1:
        _connect(logic, current_wires[0], C_TO_LOGIC.RETURN_WIRE_NAME)
    else:
        DUMMY_OUT = "var_ref_out"
        logic.wire_to_c_type[DUMMY_OUT] = c_type
        input_ports = []
        covering_rts = []
        for k, (leaf_path, leaf_type, leaf_wire) in enumerate(
            zip(output_leaf_paths, output_leaf_types, current_wires)
        ):
            input_ports.append((f"ref_toks_{k}", leaf_wire, leaf_type))
            covering_rts.append(leaf_path)

        asm_func = _const_ref_rd_func_name(c_type, c_type, (DUMMY_OUT,), covering_rts)
        asm_inst = f"{asm_func}[assembly_{counter[0]}]"
        counter[0] += 1
        asm_output = _port_wire(asm_inst, C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_submodule_instance(
            logic, asm_inst, asm_func, input_ports, asm_output, c_type, None, None
        )
        logic.ref_submodule_instance_to_ref_toks[asm_inst] = (DUMMY_OUT,)
        logic.ref_submodule_instance_to_input_port_driven_ref_toks[asm_inst] = (
            covering_rts
        )
        _connect(logic, asm_output, C_TO_LOGIC.RETURN_WIRE_NAME)

    return logic


def _build_var_ref_assign_logic(
    func_name,
    output_type,
    base_type,
    ref_toks,
    elem_c_type,
    covering_wires,
    var_dim_info,
    parser_state,
):
    """Build the Logic() object for a VAR_REF_ASSIGN function definition.

    Operates at the ELEM level — the type at the end of ref_toks — which may
    be compound (struct, array). MUXes are compound when elem_c_type is compound.
    No special-casing for scalar vs compound.

      Step 1 - CONST_REF_RD extracts old elem (elem_c_type) from each covering input.
      Step 2 - For each concrete elem position:
                 EQ(var_dim_k, concrete_val_k) per variable dim, ANDed → cond
                 MUX_elem_c_type(cond, elem_val, old_elem) → updated elem
      Step 3 - Assemble updated elems into output_type via CONST_REF_RD assembly.

    Port order: elem_val, ref_toks_i ..., var_dim_i ...
    output_type = elem_c_type[var_dim_0][var_dim_1]...
    """
    logic = C_TO_LOGIC.Logic()
    logic.func_name = func_name

    # ── elem_val input (value being written, type = elem_c_type) ──
    logic.inputs.append("elem_val")
    _add_wire(logic, "elem_val", elem_c_type)

    # ── covering input ports (ref_toks_i) ──
    covering_port_info = {}  # cov_ref_toks -> (port_name, port_type)
    for i, (cov_ref_toks, (_, cov_typ)) in enumerate(covering_wires.items()):
        port_name = f"ref_toks_{i}"
        logic.inputs.append(port_name)
        _add_wire(logic, port_name, cov_typ)
        covering_port_info[cov_ref_toks] = (port_name, cov_typ)

    # ── variable index input ports (var_dim_i) ──
    var_dim_ports = []  # (dim_size, port_name, select_type)
    for i, (dim_size, select_type, _) in enumerate(var_dim_info):
        port_name = f"var_dim_{i}"
        logic.inputs.append(port_name)
        _add_wire(logic, port_name, select_type)
        var_dim_ports.append((dim_size, port_name, select_type))

    # ── output port ──
    logic.outputs.append(C_TO_LOGIC.RETURN_WIRE_NAME)
    _add_wire(logic, C_TO_LOGIC.RETURN_WIRE_NAME, output_type)

    # Enumerate concrete positions at elem_c_type level (not decomposed to scalar)
    all_elem_positions, _ = _get_var_ref_elem_positions(
        ref_toks, base_type, parser_state
    )
    counter = [0]

    # ── Step 1: extract old elem wires from covering inputs via CONST_REF_RD ──
    old_elem_wires = {}  # concrete_pos -> wire name of type elem_c_type
    for concrete_pos in all_elem_positions:
        covering_port = None
        for cov_ref_toks, (port_name, port_type) in covering_port_info.items():
            if _var_ref_toks_covers(cov_ref_toks, concrete_pos):
                covering_port = (cov_ref_toks, port_name, port_type)
                break
        if covering_port is None:
            raise ElaborationError(f"No covering port for position {concrete_pos}")

        cov_ref_toks, port_name, port_type = covering_port
        internal_path = _var_alias_internal_path(cov_ref_toks, concrete_pos)
        internal_ref_toks = (port_name,) + internal_path

        if len(internal_ref_toks) == 1:
            old_elem_wires[concrete_pos] = port_name
        else:
            old_elem_wires[concrete_pos] = _emit_internal_const_ref_rd(
                logic, internal_ref_toks, port_name, port_type, parser_state, counter
            )

    # ── Step 2: EQ comparators + MUX per concrete elem position ──
    updated_elem_wires = {}  # concrete_pos -> updated wire of type elem_c_type

    for concrete_pos in all_elem_positions:
        pos_key = "_".join(str(t) for t in concrete_pos[1:])

        # Build condition: AND of EQ(var_dim_k, concrete_val_k) per variable dim
        cond_wire = None
        var_dim_i = 0
        for rt_tok, cl_tok in zip(ref_toks[1:], concrete_pos[1:]):
            if not _is_var_tok(rt_tok):
                continue
            dim_port = var_dim_ports[var_dim_i][1]
            dim_type = var_dim_ports[var_dim_i][2]
            var_dim_i += 1

            # Constant wire for the concrete slot value, typed to match the index
            const_name = (
                f"{C_TO_LOGIC.CONST_PREFIX}{cl_tok}_va_{pos_key}_d{var_dim_i - 1}"
            )
            _add_wire(logic, const_name, dim_type)

            # EQ: var_dim == concrete_val  (same-type comparison, no promotion)
            eq_func = _bin_func_name(C_TO_LOGIC.BIN_OP_EQ_NAME, dim_type, dim_type)
            eq_inst = f"{eq_func}[va_eq_{pos_key}_d{var_dim_i - 1}]"
            counter[0] += 1
            eq_wire = _port_wire(eq_inst, C_TO_LOGIC.RETURN_WIRE_NAME)
            _add_submodule_instance(
                logic,
                eq_inst,
                eq_func,
                [("left", dim_port, dim_type), ("right", const_name, dim_type)],
                eq_wire,
                C_TO_LOGIC.BOOL_C_TYPE,
                None,
                None,
            )

            if cond_wire is None:
                cond_wire = eq_wire
            else:
                and_func = _bin_func_name(
                    C_TO_LOGIC.BIN_OP_AND_NAME,
                    C_TO_LOGIC.BOOL_C_TYPE,
                    C_TO_LOGIC.BOOL_C_TYPE,
                )
                and_inst = f"{and_func}[va_and_{pos_key}_d{var_dim_i - 1}]"
                counter[0] += 1
                and_wire = _port_wire(and_inst, C_TO_LOGIC.RETURN_WIRE_NAME)
                _add_submodule_instance(
                    logic,
                    and_inst,
                    and_func,
                    [
                        ("left", cond_wire, C_TO_LOGIC.BOOL_C_TYPE),
                        ("right", eq_wire, C_TO_LOGIC.BOOL_C_TYPE),
                    ],
                    and_wire,
                    C_TO_LOGIC.BOOL_C_TYPE,
                    None,
                    None,
                )
                cond_wire = and_wire

        # MUX at elem_c_type level — compound types are fine
        mux_suffix = elem_c_type.replace("[", "_").replace("]", "")
        mux_func = f"{C_TO_LOGIC.MUX_LOGIC_NAME}_{mux_suffix}"
        mux_inst = f"{mux_func}[va_mux_{pos_key}]"
        counter[0] += 1
        mux_wire = _port_wire(mux_inst, C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_submodule_instance(
            logic,
            mux_inst,
            mux_func,
            [
                ("cond", cond_wire, C_TO_LOGIC.BOOL_C_TYPE),
                ("iftrue", "elem_val", elem_c_type),
                ("iffalse", old_elem_wires[concrete_pos], elem_c_type),
            ],
            mux_wire,
            elem_c_type,
            None,
            None,
        )
        updated_elem_wires[concrete_pos] = mux_wire

    # ── Step 3: assemble updated elems into output_type ──
    # output_type = elem_c_type[D0][D1]... so enumerate elem positions within it
    DUMMY_OUT = "var_assign_out"
    logic.wire_to_c_type[DUMMY_OUT] = output_type
    output_elem_paths = _get_elem_positions((DUMMY_OUT,), output_type, elem_c_type)

    assert len(all_elem_positions) == len(output_elem_paths), (
        f"VAR_REF_ASSIGN position count mismatch: "
        f"{len(all_elem_positions)} concrete vs {len(output_elem_paths)} output"
    )
    ordered_updated = [updated_elem_wires[pos] for pos in all_elem_positions]

    if len(output_elem_paths) == 1:
        _connect(logic, ordered_updated[0], C_TO_LOGIC.RETURN_WIRE_NAME)
    else:
        input_ports = []
        for k, (elem_path, elem_wire) in enumerate(
            zip(output_elem_paths, ordered_updated)
        ):
            input_ports.append((f"ref_toks_{k}", elem_wire, elem_c_type))
        asm_func = _const_ref_rd_func_name(
            output_type, output_type, (DUMMY_OUT,), output_elem_paths
        )
        asm_inst = f"{asm_func}[va_assembly_{counter[0]}]"
        counter[0] += 1
        asm_output = _port_wire(asm_inst, C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_submodule_instance(
            logic, asm_inst, asm_func, input_ports, asm_output, output_type, None, None
        )
        logic.ref_submodule_instance_to_ref_toks[asm_inst] = (DUMMY_OUT,)
        logic.ref_submodule_instance_to_input_port_driven_ref_toks[asm_inst] = (
            output_elem_paths
        )
        _connect(logic, asm_output, C_TO_LOGIC.RETURN_WIRE_NAME)

    return logic


def _reduce_driven_ref_toks(driven, env, parser_state):
    """Reduce a dict of key->(ref_toks, mux_type) to the minimal covering set.

    Two passes, repeated until stable:
      Pass 1 — Completeness: if ALL children of a concrete parent path are present,
               replace them with the parent.
               e.g. ("points",0), ("points",1), ("points",2) → ("points",) for size-3 array.
               e.g. ("rv","x"), ("rv","y") → ("rv",) when rv is a 2-field struct.
               Only applied when the parent path has no variable indices.
               Iterated bottom-up until no further reductions are possible.

      Pass 2 — Prefix coverage: remove any ref_toks A that is covered by a more
               general ref_toks B (B is a shorter prefix of A, or same length with
               B having wildcards where A has concrete values).
               e.g. ("points", i_ast) covers ("points", 0, "dim", 1) → remove latter.

    env: FuncElaborator.env (needed to resolve base variable types)
    parser_state: needed for struct field and array dim lookups.
    """
    current = dict(driven)

    # ── Pass 1: completeness reduction (bottom-up, iterate until stable) ──
    changed = True
    while changed:
        changed = False
        # Group entries by their immediate parent ref_toks (prefix without last token)
        # Key: alias_prefix of parent ref_toks; Value: list of (key, ref_toks, mux_type)
        by_parent: dict = {}
        for key, (ref_toks, mux_type) in current.items():
            if len(ref_toks) <= 1:
                continue  # base variable itself — no parent to merge into
            parent_ref_toks = ref_toks[:-1]
            # Only handle concrete parent paths for now
            # (variable-parent completeness reduction can be added later)
            if _has_variable_index(parent_ref_toks):
                continue
            parent_key = _ref_toks_to_alias_prefix(parent_ref_toks)
            by_parent.setdefault(parent_key, []).append((key, ref_toks, mux_type))

        for parent_key, children in by_parent.items():
            if not children:
                continue
            parent_ref_toks = children[0][1][:-1]
            base_var = parent_ref_toks[0]
            base_entry = env.get(base_var)
            if base_entry is None:
                continue
            _, base_type = base_entry
            parent_type = _ref_toks_to_ctype(parent_ref_toks, base_type, parser_state)

            # Determine the expected set of last-token children
            if _is_array(parent_type):
                dim = _array_first_dim(parent_type)
                expected_last = set(range(dim))
            elif _is_struct(parent_type, parser_state):
                fields = parser_state.struct_to_field_type_dict[parent_type]
                expected_last = set(fields.keys())
            else:
                continue  # scalar parent — no children possible

            # Collect last tokens actually present (concrete only)
            present_last = set()
            for _, ref_toks, _ in children:
                last = ref_toks[-1]
                if not _is_var_tok(last):
                    present_last.add(last)

            if present_last >= expected_last:
                # All children accounted for — replace with parent
                for child_key, _, _ in children:
                    del current[child_key]
                parent_mux_type = parent_type
                current[parent_key] = (parent_ref_toks, parent_mux_type)
                changed = True
                break  # restart outer while loop with updated current

    # ── Pass 2: prefix coverage reduction ──
    # Remove ref_toks A if another ref_toks B is a strictly more general prefix of A.
    keys = list(current.keys())
    to_remove = set()
    for i, ki in enumerate(keys):
        rti, _ = current[ki]
        for j, kj in enumerate(keys):
            if i == j:
                continue
            rtj, _ = current[kj]
            if _var_ref_toks_covers(rtj, rti):
                rtj_more_general = len(rtj) < len(rti) or any(
                    _is_var_tok(bv) and not _is_var_tok(av) for bv, av in zip(rtj, rti)
                )
                if rtj_more_general:
                    to_remove.add(ki)
                    break
    return {k: v for k, v in current.items() if k not in to_remove}


class ElaborationError(Exception):
    pass


class FuncElaborator:
    def __init__(self, func_def, parser_state, src_file, module_globals=None):
        self.func_def = func_def
        self.func_name = func_def.name
        self.parser_state = parser_state
        self.src_file = src_file
        # module_globals: live Python namespace from executing the design file.
        # Provides N, M, sum_widths etc. for elaboration-time evaluation.
        self.module_globals = module_globals or {}
        self.logic = C_TO_LOGIC.Logic()
        self.logic.func_name = self.func_name
        # env: hardware wires — ref_toks env key string -> (wire_name, c_type_str)
        self.env = {}
        # const_env: elaboration-time Python values — name -> plain Python value
        # Untyped variables used as loop counters, index vars, etc. (never hardware wires)
        self.const_env = {}
        # loop_instance_prefix: prepended to every submodule instance name so that
        # instances emitted inside unrolled loop iterations are uniquely named.
        # Nested loops accumulate: "FOR_i_0_FOR_j_2_" etc.
        self.loop_instance_prefix = ""

    def _inst(self, op_full_name, node):
        """Build a unique submodule instance name, prepending any active loop prefix."""
        return self.loop_instance_prefix + _inst_name(op_full_name, self.src_file, node)

    def _make_eval_ns(self):
        """Merged namespace for eval(): module globals + current const_env."""
        return {**self.module_globals, **self.const_env}

    def _try_eval_const(self, node):
        """Try to evaluate an AST expression as a plain Python elaboration-time value.
        Returns the Python value if successful, None if it involves hardware wires
        or fails for any reason.
        """
        try:
            expr = ast.Expression(body=node)
            ast.fix_missing_locations(expr)
            return eval(compile(expr, "<const_eval>", "eval"), self._make_eval_ns())
        except Exception:
            return None

    def elaborate(self):
        self.logic.c_ast_node = pypeline_ast.Pypeline_ASTNode(
            self.func_def, self.src_file
        )
        self._setup_inputs()
        self._setup_outputs()
        for stmt in self.func_def.body:
            self._elab_stmt(stmt)
        self._finalize_state_regs()
        return self.logic

    def _finalize_state_regs(self):
        """Drive each state register's base wire with its "next cycle" value.

        Mirrors _elab_return: _read_ref follows the alias chain (emitting CONST_REF_RD
        for compound types with partial writes) to produce the final covering wire, then
        _connect drives the base register wire with it.

        The apparent cycle (acc -> aliases -> acc) is broken by the VHDL backend at the
        register boundary: acc reads from the flip-flop, its driver wire becomes REG_COMB.

        If the register was never written, env[reg_name] still points to the base wire
        itself, so final_wire == reg_name; we skip the connect (no wire_driven_by entry),
        meaning the VHDL backend emits REG_COMB_x <= x (register holds its value).
        """
        for reg_name, var_info in self.logic.state_regs.items():
            c_type = var_info.type_name
            # _read_ref follows the alias chain from the current env state.
            # For scalar regs this returns env[reg_name] directly (no ast_node used).
            # For compound regs with partial writes it emits a CONST_REF_RD, using
            # self.func_def as the ast_node for instance naming.
            final_wire, _ = self._read_ref((reg_name,), c_type, self.func_def)
            if final_wire != reg_name:
                _connect(self.logic, final_wire, reg_name)

    def _setup_inputs(self):
        eval_ns = self._make_eval_ns()
        for arg in self.func_def.args.args:
            name = arg.arg
            typ = _annotation_to_ctype(arg.annotation, eval_ns)
            self.logic.inputs.append(name)
            _add_wire(self.logic, name, typ)
            self.env[name] = (name, typ)

    def _setup_outputs(self):
        eval_ns = self._make_eval_ns()
        ret_typ = _annotation_to_ctype(self.func_def.returns, eval_ns)
        self.logic.outputs.append(C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_wire(self.logic, C_TO_LOGIC.RETURN_WIRE_NAME, ret_typ)
        self._return_type = ret_typ

    # ── statements ───────────────────────────

    def _elab_stmt(self, stmt):
        if isinstance(stmt, ast.Assign):
            self._elab_assign(stmt)
        elif isinstance(stmt, ast.AnnAssign):
            self._elab_ann_assign(stmt)
        elif isinstance(stmt, ast.Return):
            self._elab_return(stmt)
        elif isinstance(stmt, ast.AugAssign):
            self._elab_aug_assign(stmt)
        elif isinstance(stmt, ast.For):
            self._elab_for(stmt)
        elif isinstance(stmt, ast.While):
            self._elab_while(stmt)
        elif isinstance(stmt, ast.If):
            self._elab_if(stmt)
        else:
            raise NotImplementedError(f"Unsupported statement: {ast.dump(stmt)}")

    def _elab_assign(self, stmt):
        target = stmt.targets[0]
        # For simple Name targets not already declared as hardware:
        # try to evaluate RHS as a pure Python elaboration constant first.
        if isinstance(target, ast.Name):
            name = target.id
            if name not in self.env:
                const_val = self._try_eval_const(stmt.value)
                if const_val is not None:
                    self.const_env[name] = const_val
                    return
        # Hardware path
        rhs_wire, rhs_type = self._elab_expr(stmt.value)
        # x[15:0] = y — bit-slice assign on a scalar integer wire
        if isinstance(target, ast.Subscript):
            if self._try_elab_bit_slice_assign(target, rhs_wire, rhs_type, stmt):
                return
        ref_toks = self._parse_ref_toks(target)
        base_var = ref_toks[0]
        # Variable indices on LHS → VAR_REF_ASSIGN
        if _has_variable_index(ref_toks):
            self._emit_var_ref_assign(ref_toks, rhs_wire, rhs_type, stmt.value)
            return
        if len(ref_toks) == 1 and base_var not in self.env:
            self._declare_var(base_var, rhs_type, target)
        self._write_ref(ref_toks, rhs_wire, rhs_type, stmt.value)

    def _elab_ann_assign(self, stmt):
        var_name = stmt.target.id
        # Detect Reg[T] annotation — hardware state register
        ann_val = self._try_eval_const(stmt.annotation)
        if isinstance(ann_val, _RegType):
            inner_ctype = str(ann_val.inner_ctype)
            self._declare_state_reg(var_name, inner_ctype, stmt.target)
            return
        # Normal local variable
        typ = _annotation_to_ctype(stmt.annotation, self._make_eval_ns())
        self._declare_var(var_name, typ, stmt.target)
        if stmt.value is not None:
            if isinstance(stmt.value, (ast.Dict, ast.List)):
                self._elab_compound_init(var_name, stmt.value, stmt.value)
            else:
                const_val = self._try_eval_const(stmt.value)
                if isinstance(const_val, (dict, list, tuple)):
                    self._elab_compound_init_from_pyval(var_name, const_val, stmt.value)
                else:
                    rhs_wire, _ = self._elab_expr(stmt.value)
                    self._write_ref((var_name,), rhs_wire, typ, stmt.value)

    def _elab_compound_init(self, base_name, init_node, context_node, path_toks=()):
        if isinstance(init_node, ast.List):
            for i, elt in enumerate(init_node.elts):
                self._elab_compound_init(base_name, elt, context_node, path_toks + (i,))
        elif isinstance(init_node, ast.Dict):
            for key_node, val_node in zip(init_node.keys, init_node.values):
                key = self._try_eval_const(key_node)
                if key is None:
                    raise ElaborationError(
                        f"Compound init dict key must be a constant, got: {ast.dump(key_node)}"
                    )
                if not isinstance(key, (str, int)):
                    raise ElaborationError(
                        f"Compound init dict key must be str or int, got: {type(key)}"
                    )
                self._elab_compound_init(
                    base_name, val_node, context_node, path_toks + (key,)
                )
        else:
            rhs_wire, rhs_type = self._elab_expr(init_node)
            self._write_ref((base_name,) + path_toks, rhs_wire, rhs_type, context_node)

    def _elab_compound_init_from_pyval(
        self, base_name, val, context_node, path_toks=()
    ):
        """Elaborate a compound init from a plain Python dict/list/tuple value.
        Used when a function call returning a dict/list is used as a variable initializer,
        e.g. x: point_t = make_point_const(3, 4) where make_point_const returns a dict.
        """
        if isinstance(val, dict):
            for key, sub_val in val.items():
                if not isinstance(key, (str, int)):
                    raise ElaborationError(
                        f"Compound init dict key must be str or int, got {type(key)}: {key!r}"
                    )
                self._elab_compound_init_from_pyval(
                    base_name, sub_val, context_node, path_toks + (key,)
                )
        elif isinstance(val, (list, tuple)):
            for i, sub_val in enumerate(val):
                self._elab_compound_init_from_pyval(
                    base_name, sub_val, context_node, path_toks + (i,)
                )
        else:
            rhs_wire, rhs_type = self._elab_python_value(val, context_node)
            self._write_ref((base_name,) + path_toks, rhs_wire, rhs_type, context_node)

    def _elab_return(self, stmt):
        result_wire, _ = self._elab_expr(stmt.value)
        _connect(self.logic, result_wire, C_TO_LOGIC.RETURN_WIRE_NAME)

    def _elab_aug_assign(self, stmt):
        """b += 1  etc.
        If target is in const_env: update the Python value directly.
        Otherwise convert to hardware assign: b = b op rhs.
        """
        if not isinstance(stmt.target, ast.Name):
            raise NotImplementedError(
                f"AugAssign on non-Name targets not yet supported: {ast.dump(stmt)}"
            )
        name = stmt.target.id
        if name in self.const_env:
            rhs_val = self._try_eval_const(stmt.value)
            if rhs_val is None:
                raise ElaborationError(
                    f"AugAssign on const_env var '{name}' with non-constant RHS"
                )
            op_fn = AUG_OP_MAP.get(type(stmt.op))
            if op_fn is None:
                raise NotImplementedError(
                    f"AugAssign op not supported: {type(stmt.op)}"
                )
            self.const_env[name] = op_fn(self.const_env[name], rhs_val)
        else:
            # Hardware: synthesize as b = b op rhs
            synth = ast.Assign(
                targets=[stmt.target],
                value=ast.BinOp(left=stmt.target, op=stmt.op, right=stmt.value),
            )
            ast.fix_missing_locations(synth)
            self._elab_assign(synth)

    def _elab_for(self, stmt):
        """for i in range(...): ...  or  for f in some_tuple: ...
        The iter must evaluate to a constant Python iterable at elaboration time.
        Loop variable stored in const_env at each iteration value.
        """
        iter_val = self._try_eval_const(stmt.iter)
        if not isinstance(iter_val, (range, tuple, list)):
            raise ElaborationError(
                f"for loop iter must be a constant range/tuple/list, got: {type(iter_val)} "
                f"from {ast.dump(stmt.iter)}"
            )
        if not isinstance(stmt.target, ast.Name):
            raise NotImplementedError("for loop target must be a simple name")
        loop_var = stmt.target.id
        outer_prefix = self.loop_instance_prefix
        for val in iter_val:
            self.const_env[loop_var] = val
            self.loop_instance_prefix = f"{outer_prefix}FOR_{loop_var}_{val}_"
            for s in stmt.body:
                self._elab_stmt(s)
        self.loop_instance_prefix = outer_prefix
        # leave loop_var at its last value (matches PipelineC behaviour)

    def _elab_while(self, stmt):
        """while condition: body
        Must be fully unrollable at elaboration time — the condition is evaluated
        with _try_eval_const each iteration and must resolve to a Python bool.
        Supports any body constructs: var ref assigns/reads, nested for/while,
        hardware if/mux, aug-assigns, etc.

        Loop-counter variables (i, b, etc.) live in const_env and are updated by
        plain Python assignments inside the body (_elab_assign routes them there
        when they don't exist in the hardware env).  Each unrolled iteration emits
        its own unique hardware wires because:
          - concrete-index writes include the index value in the alias name
          - VAR_REF_ASSIGN func_name hashes covering_ref_toks, which change each
            iteration as new aliases become covering inputs
          - CONST_REF_RD reads include the concrete path in the func_name

        A safety limit prevents infinite loops from hanging the compiler.
        """
        _MAX_UNROLL = 65536
        iteration = 0
        outer_prefix = self.loop_instance_prefix
        while True:
            cond_val = self._try_eval_const(stmt.test)
            if cond_val is None:
                raise ElaborationError(
                    f"while loop condition cannot be evaluated at elaboration time "
                    f"(may reference hardware wires). "
                    f"Condition: {ast.dump(stmt.test)}"
                )
            if not cond_val:
                break
            if iteration >= _MAX_UNROLL:
                raise ElaborationError(
                    f"while loop exceeded {_MAX_UNROLL} unroll iterations — "
                    f"ensure the condition becomes False at elaboration time. "
                    f"Condition: {ast.dump(stmt.test)}"
                )
            self.loop_instance_prefix = f"{outer_prefix}WHILE_{iteration}_"
            for s in stmt.body:
                self._elab_stmt(s)
            iteration += 1
        self.loop_instance_prefix = outer_prefix

    def _elab_if(self, stmt):
        """if condition: ... else: ...

        Compile-time constant condition: branch elimination (existing).
        Runtime hardware condition: snapshot/restore env + alias chains,
        elaborate both branches, then emit one MUX per driven ref_toks pattern.

        Key design:
          - Both branches elaborate into the SAME self.logic (wires/submodules accumulate).
            Only self.env and self.logic.wire_aliases_over_time are snapshot/restored.
          - After both branches, for each unique driven (ref_toks, mux_type):
              iftrue_wire  = read that coverage from env_true  / aliases_true
              iffalse_wire = read that coverage from env_false / aliases_false
              MUX(cond, iftrue, iffalse) → new alias inheriting the same ref_toks
          - For variable ref_toks (e.g. from a VAR_REF_ASSIGN inside the if), the
            coverage read enumerates all concrete positions and assembles them into
            mux_type via CONST_REF_RD assembly (_assemble_var_ref_coverage).
        """
        # ── Compile-time constant: branch elimination ──
        cond_val = self._try_eval_const(stmt.test)
        if cond_val is not None:
            branch = stmt.body if cond_val else stmt.orelse
            for s in branch:
                self._elab_stmt(s)
            return

        # ── Runtime condition ──
        cond_wire, _ = self._elab_expr(stmt.test)

        # Snapshot pre-if state (env and alias chains only; wires/instances accumulate)
        env_snap = dict(self.env)
        aliases_snap = {
            k: list(v) for k, v in self.logic.wire_aliases_over_time.items()
        }

        # ── True branch ──
        for s in stmt.body:
            self._elab_stmt(s)
        env_true = dict(self.env)
        aliases_true = {
            k: list(v) for k, v in self.logic.wire_aliases_over_time.items()
        }

        # ── Restore snapshot, then elaborate false branch ──
        self.env = dict(env_snap)
        self.logic.wire_aliases_over_time = {
            k: list(v) for k, v in aliases_snap.items()
        }
        for s in stmt.orelse:
            self._elab_stmt(s)
        env_false = dict(self.env)
        aliases_false = {
            k: list(v) for k, v in self.logic.wire_aliases_over_time.items()
        }

        # ── Restore snapshot again (MUX outputs will extend from here) ──
        self.env = dict(env_snap)
        self.logic.wire_aliases_over_time = {
            k: list(v) for k, v in aliases_snap.items()
        }

        # ── Collect driven ref_toks patterns from both branches ──
        # Key: alias_prefix string (encodes ref_toks shape, VAR positions as "VAR")
        # Value: (ref_toks, mux_type)
        driven: dict = {}

        def _collect_new(aliases_after, aliases_before):
            for base_var, after_list in aliases_after.items():
                # Skip variables first declared inside this if (not in pre-if env)
                if base_var not in env_snap:
                    continue
                before_list = aliases_before.get(base_var, [])
                for alias in after_list[len(before_list) :]:
                    ref_toks = self.logic.alias_to_driven_ref_toks.get(alias)
                    mux_type = self.logic.wire_to_c_type.get(alias)
                    if ref_toks is None or mux_type is None:
                        continue
                    key = _ref_toks_to_alias_prefix(ref_toks)
                    if key not in driven:
                        driven[key] = (ref_toks, mux_type)

        _collect_new(aliases_true, aliases_snap)
        _collect_new(aliases_false, aliases_snap)

        # ── Reduce to minimal covering set ──
        # Pass 1: if all children of a parent are driven, replace with parent.
        # Pass 2: remove ref_toks covered by a more general prefix in the set.
        driven = _reduce_driven_ref_toks(driven, env_snap, self.parser_state)

        # ── Emit one MUX per driven pattern ──
        for key, (ref_toks, mux_type) in driven.items():
            base_var = ref_toks[0]

            # Produce iftrue wire from the true-branch state
            true_wire = self._read_branch_coverage(
                ref_toks, mux_type, env_true, aliases_true, stmt, "true"
            )
            # Produce iffalse wire from the false-branch state (= pre-if if no else)
            false_wire = self._read_branch_coverage(
                ref_toks, mux_type, env_false, aliases_false, stmt, "false"
            )

            # Emit MUX(cond, iftrue, iffalse)
            mux_suffix = mux_type.replace("[", "_").replace("]", "")
            mux_func = f"{C_TO_LOGIC.MUX_LOGIC_NAME}_{mux_suffix}"
            # Include ref_toks key in tag so multiple MUXes from one if don't collide
            mux_tag = f"{mux_func}_if_{key}"
            mux_inst = self._inst(mux_tag, stmt)
            mux_output = _port_wire(mux_inst, C_TO_LOGIC.RETURN_WIRE_NAME)
            _add_submodule_instance(
                self.logic,
                mux_inst,
                mux_func,
                [
                    ("cond", cond_wire, C_TO_LOGIC.BOOL_C_TYPE),
                    ("iftrue", true_wire, mux_type),
                    ("iffalse", false_wire, mux_type),
                ],
                mux_output,
                mux_type,
                stmt,
                self.src_file,
            )

            # Record MUX output as a new alias, inheriting the driven ref_toks
            mux_alias = _alias(f"{key}_if_mux", self.src_file, stmt)
            _add_wire(self.logic, mux_alias, mux_type)
            _connect(self.logic, mux_output, mux_alias)
            self.logic.wire_aliases_over_time.setdefault(base_var, []).append(mux_alias)
            self.logic.alias_to_orig_var_name[mux_alias] = base_var
            self.logic.alias_to_driven_ref_toks[mux_alias] = ref_toks

            # For concrete ref_toks, update env so future reads use the MUX output
            if not _has_variable_index(ref_toks):
                env_key = _ref_toks_to_env_key(ref_toks)
                self.env[env_key] = (mux_alias, mux_type)

    def _read_branch_coverage(
        self, ref_toks, mux_type, env_branch, aliases_branch, ast_node, branch_tag
    ):
        """Read a wire of mux_type representing ref_toks coverage from a branch state.
        Temporarily swaps env/aliases to the branch snapshot, reads, then restores.
        branch_tag ("true"/"false") disambiguates assembly instance names.
        """
        saved_env = self.env
        saved_aliases = self.logic.wire_aliases_over_time
        self.env = env_branch
        self.logic.wire_aliases_over_time = aliases_branch
        try:
            if not _has_variable_index(ref_toks):
                wire, _ = self._read_ref(ref_toks, mux_type, ast_node)
            else:
                wire = self._assemble_var_ref_coverage(
                    ref_toks, mux_type, ast_node, branch_tag
                )
        finally:
            self.env = saved_env
            self.logic.wire_aliases_over_time = saved_aliases
        return wire

    def _assemble_var_ref_coverage(self, ref_toks, mux_type, ast_node, branch_tag=""):
        """Enumerate all concrete elem positions of variable ref_toks and assemble
        into mux_type via CONST_REF_RD assembly.
        Used to produce iftrue/iffalse MUX inputs for variable-indexed if-assignments.
        The branch_tag disambiguates the assembly instance name between true/false reads.
        """
        base_var = ref_toks[0]
        _, base_type = self.env[base_var]
        all_positions, elem_c_type = _get_var_ref_elem_positions(
            ref_toks, base_type, self.parser_state
        )

        # Read each concrete position from current (branch) env/aliases
        pos_wires = []
        for pos in all_positions:
            wire, _ = self._read_ref(pos, elem_c_type, ast_node)
            pos_wires.append(wire)

        if len(pos_wires) == 1:
            return pos_wires[0]

        # Assemble N elem wires into mux_type via CONST_REF_RD assembly.
        # DUMMY_OUT is a pseudo-variable used only for the ref_toks structure
        # passed to the backend. It must be in self.logic.wire_to_c_type so
        # BUILD_C_BUILT_IN_SUBMODULE_FUNC_LOGIC can look up the base type.
        # We add it to wire_to_c_type only (not wires) to avoid a spurious
        # VHDL signal declaration. Name is unique per mux_type; no underscores
        # at boundaries (VHDL identifiers cannot start/end with underscores).
        mux_type_tag = mux_type.replace("[", "x").replace("]", "")
        DUMMY_OUT = f"cov_assemble_{mux_type_tag}"
        self.logic.wire_to_c_type[DUMMY_OUT] = mux_type

        output_elem_paths = _get_elem_positions((DUMMY_OUT,), mux_type, elem_c_type)
        input_ports = []
        for k, (elem_path, elem_wire) in enumerate(zip(output_elem_paths, pos_wires)):
            input_ports.append((f"ref_toks_{k}", elem_wire, elem_c_type))
        ref_prefix = _ref_toks_to_alias_prefix(ref_toks)
        asm_func = _const_ref_rd_func_name(
            mux_type, mux_type, (DUMMY_OUT,), output_elem_paths
        )
        asm_tag = f"{asm_func}_if_cov_{ref_prefix}_{branch_tag}"
        asm_inst = self._inst(asm_tag, ast_node)
        asm_output = _port_wire(asm_inst, C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_submodule_instance(
            self.logic,
            asm_inst,
            asm_func,
            input_ports,
            asm_output,
            mux_type,
            ast_node,
            self.src_file,
        )
        self.logic.ref_submodule_instance_to_ref_toks[asm_inst] = (DUMMY_OUT,)
        self.logic.ref_submodule_instance_to_input_port_driven_ref_toks[asm_inst] = (
            output_elem_paths
        )
        return asm_output

    # ── expressions ──────────────────────────

    def _elab_expr(self, expr):
        if isinstance(expr, ast.Name):
            return self._elab_name(expr)
        elif isinstance(expr, ast.Constant):
            return self._elab_constant(expr)
        elif isinstance(expr, ast.UnaryOp):
            return self._elab_unary(expr)
        elif isinstance(expr, ast.BinOp):
            return self._elab_binop(expr)
        elif isinstance(expr, ast.Compare):
            return self._elab_compare(expr)
        elif isinstance(expr, ast.Call):
            return self._elab_call(expr)
        elif isinstance(expr, ast.Tuple):
            return self._elab_tuple_concat(expr)
        elif isinstance(expr, (ast.Subscript, ast.Attribute)):
            if isinstance(expr, ast.Subscript):
                result = self._try_elab_bit_slice(expr)
                if result is not None:
                    return result
            return self._elab_ref_read(expr)
        else:
            raise NotImplementedError(f"Unsupported expr: {ast.dump(expr)}")

    def _elab_name(self, expr):
        name = expr.id
        # 1. Hardware env
        if name in self.env:
            wire, typ = self.env[name]
            if _is_scalar(typ, self.parser_state):
                return wire, typ
            return self._read_ref((name,), typ, expr)
        # 2. Elaboration const_env — emit as CONST wire if used as hardware value
        if name in self.const_env:
            return self._elab_python_value(self.const_env[name], expr)
        # 3. Module globals (N, M, etc.) — emit as CONST wire if used as hardware value
        if name in self.module_globals:
            val = self.module_globals[name]
            if isinstance(val, (int, bool)):
                return self._elab_python_value(val, expr)
            raise ElaborationError(
                f"Module global '{name}' ({type(val).__name__}) "
                f"is not a hardware-usable value"
            )
        raise ElaborationError(f"Unknown name '{name}' in func '{self.func_name}'")

    def _elab_python_value(self, val, ast_node):
        """Emit a plain Python int/bool as a CONST wire in the hardware graph."""
        if not isinstance(val, (int, bool)):
            raise ElaborationError(
                f"Cannot emit non-int Python value as hardware: {val!r}"
            )
        typ = _infer_const_ctype(val)
        coord_str = _loc_str(self.src_file, ast_node)
        const_wire = f"{C_TO_LOGIC.CONST_PREFIX}{val}_{coord_str}"
        _add_wire(self.logic, const_wire, typ)
        return const_wire, typ

    def _elab_constant(self, expr):
        val = expr.value
        if not isinstance(val, (int, bool)):
            raise NotImplementedError(f"Unsupported constant value: {val!r}")
        typ = _infer_const_ctype(val)
        coord_str = _loc_str(self.src_file, expr)
        const_wire = f"{C_TO_LOGIC.CONST_PREFIX}{val}_{coord_str}"
        _add_wire(self.logic, const_wire, typ)
        return const_wire, typ

    def _elab_ref_read(self, expr):
        """Elaborate a subscript or attribute RHS. Routes to VAR or CONST path."""
        ref_toks = self._parse_ref_toks(expr)
        base_var = ref_toks[0]
        _, base_type = self.env[base_var]
        c_type = _ref_toks_to_ctype(ref_toks, base_type, self.parser_state)
        if _has_variable_index(ref_toks):
            return self._emit_var_ref_rd(ref_toks, c_type, expr)
        return self._read_ref(ref_toks, c_type, expr)

    def _try_elab_bit_slice(self, expr):
        """Attempt to elaborate x[bit] or x[high:low] as a bit-select/slice submodule.
        Returns (wire, type) on success, None if the expression is not a bit slice
        (falls through to _elab_ref_read for normal array/struct access).
        Both the bit index and slice bounds must be compile-time constants.
        """
        base_node = expr.value
        if not isinstance(base_node, ast.Name):
            return None
        base_name = base_node.id
        if base_name not in self.env:
            return None
        base_wire, base_type = self.env[base_name]
        if not _ctype_is_int(base_type):
            return None

        slc = expr.slice
        if isinstance(slc, ast.Index):  # Python 3.8 compat
            slc = slc.value

        if isinstance(slc, ast.Constant) and isinstance(slc.value, int):
            # x[15] — single bit select (literal)
            high = low = slc.value
        elif not isinstance(slc, ast.Slice):
            # x[i] — single bit select where i is a const_env/globals name or expr
            bit_val = self._try_resolve_int_constant(slc)
            if bit_val is None:
                # Variable index on a scalar int — not a valid bit slice
                return None
            high = low = bit_val
        else:
            # x[15:0] — bit range; both bounds must be constants
            if slc.lower is None or slc.upper is None:
                raise ElaborationError(
                    f"Bit slice on '{base_name}' requires both bounds: e.g. x[15:0]"
                )
            high_val = self._try_resolve_int_constant(slc.lower)
            low_val = self._try_resolve_int_constant(slc.upper)
            if high_val is None or low_val is None:
                raise ElaborationError(
                    f"Bit slice bounds on '{base_name}' must be compile-time constants"
                )
            high, low = max(high_val, low_val), min(high_val, low_val)

        _, width = _ctype_info(base_type)
        if low < 0 or high >= width:
            raise ElaborationError(
                f"Bit index [{high}:{low}] out of range for {base_type} (width={width})"
            )

        prefix = base_type.replace("_t", "")
        func_name = f"{prefix}_{high}_{low}"
        out_type = f"uint{high - low + 1}_t"
        _register_bit_manip_logic(
            func_name, ["x"], [base_type], out_type, self.parser_state
        )

        inst = self._inst(func_name, expr)
        port_return = _port_wire(inst, C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_submodule_instance(
            self.logic,
            inst,
            func_name,
            [("x", base_wire, base_type)],
            port_return,
            out_type,
            expr,
            self.src_file,
        )
        return port_return, out_type

    def _elab_tuple_concat(self, expr):
        """Elaborate (a, b, ...) as a chain of bit-concat submodule instances.
        All elements must be unsigned integer hardware wires. Chains left-associatively:
        (a, b, c) → uint{wa+wb+wc}_t = uint{wa+wb}_uint{wc}(uint{wa}_uint{wb}(a, b), c)
        """
        if len(expr.elts) < 2:
            raise ElaborationError("Tuple concat requires at least 2 elements")

        acc_wire, acc_type = self._elab_expr(expr.elts[0])
        if not _ctype_is_int(acc_type) or _ctype_info(acc_type)[0]:
            raise ElaborationError(
                f"Tuple concat element must be an unsigned integer type, got {acc_type!r}"
            )

        for elt in expr.elts[1:]:
            elt_wire, elt_type = self._elab_expr(elt)
            if not _ctype_is_int(elt_type) or _ctype_info(elt_type)[0]:
                raise ElaborationError(
                    f"Tuple concat element must be an unsigned integer type, got {elt_type!r}"
                )
            _, acc_w = _ctype_info(acc_type)
            _, elt_w = _ctype_info(elt_type)
            acc_prefix = acc_type.replace("_t", "")
            elt_prefix = elt_type.replace("_t", "")
            func_name = f"{acc_prefix}_{elt_prefix}"
            out_type = f"uint{acc_w + elt_w}_t"
            _register_bit_manip_logic(
                func_name, ["x", "y"], [acc_type, elt_type], out_type, self.parser_state
            )
            inst = self._inst(func_name, elt)
            port_return = _port_wire(inst, C_TO_LOGIC.RETURN_WIRE_NAME)
            _add_submodule_instance(
                self.logic,
                inst,
                func_name,
                [("x", acc_wire, acc_type), ("y", elt_wire, elt_type)],
                port_return,
                out_type,
                elt,
                self.src_file,
            )
            acc_wire, acc_type = port_return, out_type

        return acc_wire, acc_type

    def _try_elab_bit_slice_assign(self, target, rhs_wire, rhs_type, stmt):
        """Handle x[15:0] = y — bit-slice assignment on a scalar integer wire.
        Reads current wire for x, instantiates a bit_assign submodule, aliases x to result.
        Returns True if handled, False if the target is not a bit-slice assign.
        Both slice bounds must be compile-time constants.
        """
        base_node = target.value
        if not isinstance(base_node, ast.Name):
            return False
        x_name = base_node.id
        if x_name not in self.env:
            return False
        old_wire, base_type = self.env[x_name]
        if not _ctype_is_int(base_type):
            return False

        slc = target.slice
        if isinstance(slc, ast.Index):  # Python 3.8 compat
            slc = slc.value

        if not isinstance(slc, ast.Slice):
            return False  # x[i] = y on an integer is not a slice assign

        if slc.lower is None or slc.upper is None:
            raise ElaborationError(
                f"Bit-slice assign on '{x_name}' requires both bounds: e.g. x[15:0] = y"
            )
        high_val = self._try_resolve_int_constant(slc.lower)
        low_val = self._try_resolve_int_constant(slc.upper)
        if high_val is None or low_val is None:
            raise ElaborationError(
                f"Bit-slice assign bounds on '{x_name}' must be compile-time constants"
            )
        high, low = max(high_val, low_val), min(high_val, low_val)

        _, base_w = _ctype_info(base_type)
        if low < 0 or high >= base_w:
            raise ElaborationError(
                f"Bit-slice assign [{high}:{low}] out of range for {base_type} (width={base_w})"
            )
        expected_rhs_w = high - low + 1
        if not _ctype_is_int(rhs_type):
            raise ElaborationError(
                f"Bit-slice assign RHS must be an integer type, got {rhs_type!r}"
            )
        _, rhs_w = _ctype_info(rhs_type)
        if rhs_w != expected_rhs_w:
            raise ElaborationError(
                f"Bit-slice assign [{high}:{low}] expects {expected_rhs_w}-bit RHS, "
                f"got {rhs_type!r} ({rhs_w} bits)"
            )

        base_prefix = base_type.replace("_t", "")
        rhs_prefix = rhs_type.replace("_t", "")
        func_name = f"{base_prefix}_{rhs_prefix}_{low}"
        _register_bit_manip_logic(
            func_name, ["inp", "x"], [base_type, rhs_type], base_type, self.parser_state
        )

        inst = self._inst(func_name, target)
        result_wire = _port_wire(inst, C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_submodule_instance(
            self.logic,
            inst,
            func_name,
            [("inp", old_wire, base_type), ("x", rhs_wire, rhs_type)],
            result_wire,
            base_type,
            target,
            self.src_file,
        )
        self._write_ref((x_name,), result_wire, base_type, stmt)
        return True

    def _elab_unary(self, expr):
        op_name = UNARY_OP_MAP[type(expr.op)]
        operand_wire, typ = self._elab_expr(expr.operand)

        # Check for user-registered unary operator overload.
        import pypeline as _pypeline

        impl_name = _pypeline._unary_operator_registry.get((op_name, typ))
        if impl_name is not None:
            callee_def = self._resolve_registered_impl(impl_name, expr)
            inst = self._inst(
                impl_name if isinstance(impl_name, str) else impl_name.__name__, expr
            )
            ret_type = callee_def.wire_to_c_type[C_TO_LOGIC.RETURN_WIRE_NAME]
            port_return = _port_wire(inst, C_TO_LOGIC.RETURN_WIRE_NAME)
            _add_submodule_instance(
                self.logic,
                inst,
                callee_def.func_name,  # canonical name, not registered alias
                [(callee_def.inputs[0], operand_wire, typ)],
                port_return,
                ret_type,
                expr,
                self.src_file,
            )
            return port_return, ret_type

        # Built-in path.
        func_name = _unary_func_name(op_name, typ)
        inst = self._inst(f"{C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX}_{op_name}", expr)
        port_return = _port_wire(inst, C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_submodule_instance(
            self.logic,
            inst,
            func_name,
            [("expr", operand_wire, typ)],
            port_return,
            typ,
            expr,
            self.src_file,
        )
        return port_return, typ

    def _try_resolve_int_constant(self, expr):
        """Return the int value if expr is a compile-time integer constant, else None.
        Covers ast.Constant literals, ast.Name references into const_env/module_globals,
        and arbitrary arithmetic expressions (e.g. 1 << i where i is in const_env)."""
        if isinstance(expr, ast.Constant) and isinstance(expr.value, int):
            return expr.value
        if isinstance(expr, ast.Name):
            name = expr.id
            if name in self.const_env and isinstance(self.const_env[name], (int, bool)):
                return int(self.const_env[name])
            if name in self.module_globals and isinstance(
                self.module_globals[name], (int, bool)
            ):
                return int(self.module_globals[name])
        val = self._try_eval_const(expr)
        if isinstance(val, (int, bool)) and not isinstance(val, type):
            return int(val)
        return None

    def _elab_binop(self, expr):
        op_name = BIN_OP_MAP[type(expr.op)]

        # Shift ops: constant amount -> CONST_SL/SR_<n>_<type> built-in;
        # variable amount is not yet supported.
        if op_name in (C_TO_LOGIC.BIN_OP_SL_NAME, C_TO_LOGIC.BIN_OP_SR_NAME):
            amount = self._try_resolve_int_constant(expr.right)
            if amount is not None:
                left_wire, l_type = self._elab_expr(expr.left)
                amount_str = str(amount)
                func_base_name = f"{C_TO_LOGIC.CONST_PREFIX}{op_name}_{amount_str}"
                func_name = f"{func_base_name}_{l_type}"
                inst = self._inst(func_base_name, expr)
                port_return = _port_wire(inst, C_TO_LOGIC.RETURN_WIRE_NAME)
                _add_submodule_instance(
                    self.logic,
                    inst,
                    func_name,
                    [("x", left_wire, l_type)],
                    port_return,
                    l_type,
                    expr,
                    self.src_file,
                )
                return port_return, l_type
            else:
                # Variable shift — look up user-registered operator implementation.
                import pypeline as _pypeline

                left_wire, l_type = self._elab_expr(expr.left)
                right_wire, r_type = self._elab_expr(expr.right)
                key = (op_name, l_type, r_type)
                impl_name = _pypeline._operator_registry.get(key)
                if impl_name is None:
                    # Fall back to left-only match (right type derived from left)
                    impl_name = _pypeline._left_operator_registry.get((op_name, l_type))
                if impl_name is None:
                    raise NotImplementedError(
                        f"Variable shift ({l_type} {op_name} {r_type}) has no registered"
                        f" implementation. Call register_left_operator('{op_name}', {l_type},"
                        f" 'func_name') or register_operator('{op_name}', {l_type},"
                        f" {r_type}, 'func_name') in your design file."
                        f" (at {_loc_str(self.src_file, expr)})"
                    )
                callee_def = self._resolve_registered_impl(impl_name, expr)
                inst = self._inst(
                    impl_name if isinstance(impl_name, str) else impl_name.__name__,
                    expr,
                )
                ret_type = callee_def.wire_to_c_type[C_TO_LOGIC.RETURN_WIRE_NAME]
                port_return = _port_wire(inst, C_TO_LOGIC.RETURN_WIRE_NAME)
                input_ports = list(
                    zip(callee_def.inputs, [left_wire, right_wire], [l_type, r_type])
                )
                _add_submodule_instance(
                    self.logic,
                    inst,
                    callee_def.func_name,  # canonical name, not registered alias
                    input_ports,
                    port_return,
                    ret_type,
                    expr,
                    self.src_file,
                )
                return port_return, ret_type

        left_wire, l_type = self._elab_expr(expr.left)
        right_wire, r_type = self._elab_expr(expr.right)

        # General registered operator check — covers any op (e.g. + on struct types).
        import pypeline as _pypeline

        _gen_impl = _pypeline._operator_registry.get((op_name, l_type, r_type))
        if _gen_impl is None:
            _gen_impl = _pypeline._left_operator_registry.get((op_name, l_type))
        if _gen_impl is not None:
            _callee = self._resolve_registered_impl(_gen_impl, expr)
            _inst = self._inst(
                _gen_impl if isinstance(_gen_impl, str) else _gen_impl.__name__, expr
            )
            _ret_type = _callee.wire_to_c_type[C_TO_LOGIC.RETURN_WIRE_NAME]
            _port_ret = _port_wire(_inst, C_TO_LOGIC.RETURN_WIRE_NAME)
            _add_submodule_instance(
                self.logic,
                _inst,
                _callee.func_name,
                list(zip(_callee.inputs, [left_wire, right_wire], [l_type, r_type])),
                _port_ret,
                _ret_type,
                expr,
                self.src_file,
            )
            return _port_ret, _ret_type

        if op_name in _ARITH_OPS and _ctype_is_int(l_type) and _ctype_is_int(r_type):
            # Arithmetic ops: sign-promote inputs, compute full-precision output type.
            # e.g. uint32_t + uint8_t  -> eff: u32, u8;  out: uint33_t
            #      int32_t  + uint32_t -> eff: i32, i33; out: int34_t
            # Truncation to the LHS variable type happens at the assignment alias.
            eff_l_type, eff_r_type, result_signed = _arith_promote(l_type, r_type)
            out_type = _arith_output_type(
                op_name, eff_l_type, eff_r_type, result_signed
            )
        else:
            # Bitwise (and/or/xor) or non-integer types:
            # no sign promotion; output type matches left input.
            eff_l_type, eff_r_type = l_type, r_type
            out_type = l_type

        func_name = _bin_func_name(op_name, eff_l_type, eff_r_type)
        inst = self._inst(f"{C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX}_{op_name}", expr)
        port_return = _port_wire(inst, C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_submodule_instance(
            self.logic,
            inst,
            func_name,
            [("left", left_wire, eff_l_type), ("right", right_wire, eff_r_type)],
            port_return,
            out_type,
            expr,
            self.src_file,
        )
        return port_return, out_type

    def _elab_compare(self, expr):
        op_name = BIN_OP_MAP[type(expr.ops[0])]
        left_wire, l_type = self._elab_expr(expr.left)
        right_wire, r_type = self._elab_expr(expr.comparators[0])
        # Sign-promote so the VHDL backend compares matching-sign types.
        if _ctype_is_int(l_type) and _ctype_is_int(r_type):
            eff_l_type, eff_r_type, _ = _arith_promote(l_type, r_type)
        else:
            eff_l_type, eff_r_type = l_type, r_type
        func_name = _bin_func_name(op_name, eff_l_type, eff_r_type)
        inst = self._inst(f"{C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX}_{op_name}", expr)
        port_return = _port_wire(inst, C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_submodule_instance(
            self.logic,
            inst,
            func_name,
            [("left", left_wire, eff_l_type), ("right", right_wire, eff_r_type)],
            port_return,
            C_TO_LOGIC.BOOL_C_TYPE,
            expr,
            self.src_file,
        )
        return port_return, C_TO_LOGIC.BOOL_C_TYPE

    def _elab_call(self, expr):
        callee_name = expr.func.id
        if callee_name in _BIT_MANIP_FUNC_NAMES:
            return self._elab_bit_manip_call(expr)
        callee_def = self.parser_state.FuncLogicLookupTable.get(callee_name)
        if callee_def is None:
            # Not found in elaborated functions — check if it's a live callable
            # in module_globals (e.g. a closure returned by a factory function)
            live_func = self.module_globals.get(callee_name)
            if live_func is not None and callable(live_func):
                callee_def = self._elaborate_live_func(callee_name, live_func)
            else:
                raise NotImplementedError(f"Call to unknown function '{callee_name}'")
        inst = self._inst(callee_name, expr)
        ret_typ = callee_def.wire_to_c_type[C_TO_LOGIC.RETURN_WIRE_NAME]
        port_return = _port_wire(inst, C_TO_LOGIC.RETURN_WIRE_NAME)
        input_ports = []
        for arg_expr, port_name in zip(expr.args, callee_def.inputs):
            arg_wire, arg_typ = self._elab_expr(arg_expr)
            input_ports.append((port_name, arg_wire, arg_typ))
        _add_submodule_instance(
            self.logic,
            inst,
            callee_def.func_name,  # canonical name, not Python alias
            input_ports,
            port_return,
            ret_typ,
            expr,
            self.src_file,
        )
        return port_return, ret_typ

    def _elab_bit_manip_call(self, expr):
        """Elaborate a call to a bit manipulation primitive function.
        Builds the canonical C function name from argument types and constant parameters,
        registers a Logic() for it, and adds a submodule instance.
        """
        callee_name = expr.func.id
        args = expr.args

        def _require_const(arg, label):
            val = self._try_resolve_int_constant(arg)
            if val is None:
                raise ElaborationError(
                    f"{callee_name}: '{label}' must be a compile-time constant"
                )
            return val

        def _require_uint(wire, typ, label):
            if not _ctype_is_int(typ):
                raise ElaborationError(
                    f"{callee_name}: '{label}' must be an integer type, got {typ!r}"
                )
            if _ctype_info(typ)[0]:
                raise ElaborationError(
                    f"{callee_name}: '{label}' must be unsigned, got {typ!r}"
                )

        def _require_int(wire, typ, label):
            if not _ctype_is_int(typ):
                raise ElaborationError(
                    f"{callee_name}: '{label}' must be an integer type, got {typ!r}"
                )

        def _emit(func_name, port_names, in_types, out_type, port_wires):
            _register_bit_manip_logic(
                func_name, port_names, in_types, out_type, self.parser_state
            )
            inst = self._inst(func_name, expr)
            port_return = _port_wire(inst, C_TO_LOGIC.RETURN_WIRE_NAME)
            input_ports = list(zip(port_names, port_wires, in_types))
            _add_submodule_instance(
                self.logic,
                inst,
                func_name,
                input_ports,
                port_return,
                out_type,
                expr,
                self.src_file,
            )
            return port_return, out_type

        if callee_name == "bit_dup":
            if len(args) != 2:
                raise ElaborationError("bit_dup(x, n): requires exactly 2 arguments")
            x_wire, x_type = self._elab_expr(args[0])
            _require_uint(x_wire, x_type, "x")
            n = _require_const(args[1], "n")
            if n < 1:
                raise ElaborationError(f"bit_dup: n must be ≥ 1, got {n}")
            _, xw = _ctype_info(x_type)
            prefix = x_type.replace("_t", "")
            return _emit(f"{prefix}_{n}", ["x"], [x_type], f"uint{xw * n}_t", [x_wire])

        elif callee_name == "rotl":
            if len(args) != 2:
                raise ElaborationError("rotl(x, n): requires exactly 2 arguments")
            x_wire, x_type = self._elab_expr(args[0])
            _require_uint(x_wire, x_type, "x")
            n = _require_const(args[1], "n")
            _, xw = _ctype_info(x_type)
            return _emit(f"rotl{xw}_{n}", ["x"], [x_type], f"uint{xw}_t", [x_wire])

        elif callee_name == "rotr":
            if len(args) != 2:
                raise ElaborationError("rotr(x, n): requires exactly 2 arguments")
            x_wire, x_type = self._elab_expr(args[0])
            _require_uint(x_wire, x_type, "x")
            n = _require_const(args[1], "n")
            _, xw = _ctype_info(x_type)
            return _emit(f"rotr{xw}_{n}", ["x"], [x_type], f"uint{xw}_t", [x_wire])

        elif callee_name == "bswap":
            if len(args) != 1:
                raise ElaborationError("bswap(x): requires exactly 1 argument")
            x_wire, x_type = self._elab_expr(args[0])
            _require_uint(x_wire, x_type, "x")
            _, xw = _ctype_info(x_type)
            return _emit(f"bswap_{xw}", ["x"], [x_type], f"uint{xw}_t", [x_wire])

        elif callee_name == "bit_assign":
            if len(args) != 3:
                raise ElaborationError(
                    "bit_assign(base, x, pos): requires exactly 3 arguments"
                )
            base_wire, base_type = self._elab_expr(args[0])
            x_wire, x_type = self._elab_expr(args[1])
            pos = _require_const(args[2], "pos")
            _require_int(base_wire, base_type, "base")
            _require_int(x_wire, x_type, "x")
            base_prefix = base_type.replace("_t", "")
            x_prefix = x_type.replace("_t", "")
            func_name = f"{base_prefix}_{x_prefix}_{pos}"
            return _emit(
                func_name,
                ["inp", "x"],
                [base_type, x_type],
                base_type,
                [base_wire, x_wire],
            )

        elif callee_name in ("array_to_uint_be", "array_to_uint_le"):
            if len(args) != 1:
                raise ElaborationError(
                    f"{callee_name}(arr): requires exactly 1 argument"
                )
            arr_wire, arr_type = self._elab_expr(args[0])
            if not _is_array(arr_type):
                raise ElaborationError(
                    f"{callee_name}: argument must be an array type, got {arr_type!r}"
                )
            elem_type = _array_elem_type(arr_type)
            n = _array_first_dim(arr_type)
            if not _ctype_is_int(elem_type):
                raise ElaborationError(
                    f"{callee_name}: array element must be an integer type, got {elem_type!r}"
                )
            _, ew = _ctype_info(elem_type)
            ep = elem_type.replace("_t", "")
            endian = "be" if callee_name == "array_to_uint_be" else "le"
            func_name = f"{ep}_array{n}_{endian}"
            return _emit(func_name, ["x"], [arr_type], f"uint{ew * n}_t", [arr_wire])

        elif callee_name in ("uint_to_array_be", "uint_to_array_le"):
            if len(args) != 2:
                raise ElaborationError(
                    f"{callee_name}(x, elem_w): requires exactly 2 arguments"
                )
            x_wire, x_type = self._elab_expr(args[0])
            _require_uint(x_wire, x_type, "x")
            elem_w = _require_const(args[1], "elem_w")
            if elem_w < 1:
                raise ElaborationError(
                    f"{callee_name}: elem_w must be ≥ 1, got {elem_w}"
                )
            _, total_w = _ctype_info(x_type)
            if total_w % elem_w != 0:
                raise ElaborationError(
                    f"{callee_name}: elem_w={elem_w} does not divide total width {total_w} evenly"
                )
            n = total_w // elem_w
            endian = "be" if callee_name == "uint_to_array_be" else "le"
            func_name = f"uint{total_w}_{elem_w}_{endian}"
            out_type = f"uint{elem_w}_t[{n}]"
            return _emit(func_name, ["x"], [x_type], out_type, [x_wire])

        raise NotImplementedError(f"Unknown bit manip function: {callee_name!r}")

    def _resolve_registered_impl(self, impl_name, expr):
        """Resolve a registered operator impl (string name or callable) to a Logic().
        String names are looked up in module_globals; callables are elaborated directly.
        """
        if callable(impl_name):
            return self._elaborate_live_func(impl_name.__name__, impl_name)
        callee_def = self.parser_state.FuncLogicLookupTable.get(impl_name)
        if callee_def is None:
            live_func = self.module_globals.get(impl_name)
            if live_func is None or not callable(live_func):
                raise NotImplementedError(
                    f"Registered operator '{impl_name}' not found in module globals"
                    f" (at {_loc_str(self.src_file, expr)})"
                )
            callee_def = self._elaborate_live_func(impl_name, live_func)
        return callee_def

    def _elaborate_live_func(self, module_level_name, func):
        """Elaborate a live Python callable from module_globals.
        Handles closures returned by factory functions — extracts closure variables
        and merges them into the elaboration namespace so annotations like
        uint1_t[LO_SIZE] resolve correctly.
        Stores the result under module_level_name in FuncLogicLookupTable.
        """
        import inspect
        import textwrap

        source = textwrap.dedent(inspect.getsource(func))
        tree = ast.parse(source)

        func_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        if not func_nodes:
            raise ElaborationError(
                f"Could not find FunctionDef in source of '{module_level_name}'"
            )
        func_def = func_nodes[0]

        # Extract closure variables (e.g. LO_SIZE=3, HI_SIZE=4, OUT_SIZE=7)
        closure_ns = {}
        if func.__code__.co_freevars and func.__closure__:
            for var, cell in zip(func.__code__.co_freevars, func.__closure__):
                try:
                    closure_ns[var] = cell.cell_contents
                except ValueError:
                    pass

        # Python only captures names as closure cells when they appear in the
        # function *body*.  Names used only in annotations (e.g. VALUE_TYPE in
        # `v: VALUE_TYPE`) are NOT captured as closure cells, but Python DOES
        # evaluate them at definition time and store the result in __annotations__.
        # Recover those type variables here so annotation resolution works.
        ann_dict = getattr(func, "__annotations__", {})
        for ast_arg in func_def.args.args:
            if isinstance(ast_arg.annotation, ast.Name):
                var_name = ast_arg.annotation.id
                if var_name not in closure_ns and ast_arg.arg in ann_dict:
                    closure_ns[var_name] = ann_dict[ast_arg.arg]
        if func_def.returns is not None and isinstance(func_def.returns, ast.Name):
            var_name = func_def.returns.id
            if var_name not in closure_ns and "return" in ann_dict:
                closure_ns[var_name] = ann_dict["return"]

        # Canonical name: factory closures get a name derived from the factory chain
        # + closure vars, so the same factory+args always maps to the same Logic().
        # Top-level non-factory functions (no .<locals>. in qualname) keep their
        # Python name and are not subject to deduplication here.
        canonical = _canonical_func_name(func, closure_ns, self.module_globals)
        key = canonical if canonical is not None else module_level_name

        if canonical is not None:
            existing = self.parser_state.FuncLogicLookupTable.get(canonical)
            if existing is not None:
                return existing  # dedup: already elaborated, no alias stored

        merged_globals = {**self.module_globals, **closure_ns}

        # Register any struct types found in closure vars that were created inside
        # a factory (not visible to _discover_structs_from_module). The @struct
        # decorator already stamped _pypeline_ctype_name on them; we just need to
        # ensure they appear in struct_to_field_type_dict.
        for val in closure_ns.values():
            if (
                inspect.isclass(val)
                and issubclass(val, tuple)
                and hasattr(val, "_fields")
                and hasattr(val, "_pypeline_ctype_name")
            ):
                c_name = val._pypeline_ctype_name
                if c_name not in self.parser_state.struct_to_field_type_dict:
                    fields = {f: str(a) for f, a in val.__annotations__.items()}
                    self.parser_state.struct_to_field_type_dict[c_name] = fields

        # Register a stub under the canonical key so recursive calls resolve
        stub = C_TO_LOGIC.Logic()
        stub.func_name = key
        self.parser_state.FuncLogicLookupTable[key] = stub

        # Elaborate with merged namespace; push/pop any operator registrations
        # scoped to this function so nested callees inherit them.
        import pypeline as _pypeline

        saved = _pypeline._push_scoped_registrations(func)
        try:
            elab = FuncElaborator(
                func_def, self.parser_state, self.src_file, merged_globals
            )
            logic = elab.elaborate()
        finally:
            _pypeline._pop_scoped_registrations(saved)
        logic.func_name = key
        self.parser_state.FuncLogicLookupTable[key] = logic
        return logic

    # ── compound type read / write ────────────

    def _parse_ref_toks(self, node):
        """Parse AST node into ref_toks.
        Constant subscript indices and const_env values -> int tokens.
        Everything else -> AST node token (variable index -> VAR_REF path).
        """
        if isinstance(node, ast.Name):
            return (node.id,)
        elif isinstance(node, ast.Attribute):
            return self._parse_ref_toks(node.value) + (node.attr,)
        elif isinstance(node, ast.Subscript):
            parent = self._parse_ref_toks(node.value)
            slc = node.slice
            if isinstance(slc, ast.Index):  # Python 3.8 compat
                slc = slc.value
            if isinstance(slc, ast.Constant):
                return parent + (slc.value,)
            # Try to evaluate as elaboration-time constant (e.g. bits[b] where b in const_env,
            # or rv[f] where f is a string field name from _fields iteration)
            const_val = self._try_eval_const(slc)
            if const_val is not None and isinstance(const_val, (int, str)):
                return parent + (const_val,)
            return parent + (slc,)  # variable index: store raw AST expression
        else:
            raise NotImplementedError(f"Cannot parse ref toks from: {ast.dump(node)}")

    def _temporal_sort_covering_wires(self, covering_wires, base_var):
        """Sort covering_wires into temporal order: oldest assignment first.

        Algorithm (mirrors the user-facing description):
          1. Walk wire_aliases_over_time[base_var] BACKWARDS (newest first),
             collecting covering_wires entries as each alias's ref_toks is matched.
          2. Any entries not matched by any alias (= input wire or early const) are
             appended last (they will be FIRST after reversal = oldest).
          3. Reverse the collected list → oldest first.

        Both identity (is) and equality (==) are tried when matching, so the method
        handles both variable aliases (same Python object) and concrete aliases
        (new tuple created during env prefix search but same content).
        """
        aliases = self.logic.wire_aliases_over_time.get(base_var, [])

        # Walk aliases newest-to-oldest, pull matching entries out of `remaining`
        remaining = dict(covering_wires)
        collected_newest_first = []

        for alias in reversed(aliases):
            alias_rt = self.logic.alias_to_driven_ref_toks.get(alias)
            if alias_rt is None:
                continue
            # Find the covering_wires key that corresponds to this alias's ref_toks
            found_key = None
            for cov_rt in remaining:
                if cov_rt is alias_rt or cov_rt == alias_rt:
                    found_key = cov_rt
                    break
            if found_key is not None:
                collected_newest_first.append((found_key, remaining.pop(found_key)))

        # Anything left in remaining was never assigned (input wire / base fallback)
        # — append now so it ends up FIRST after reversal
        for cov_rt, val in remaining.items():
            collected_newest_first.append((cov_rt, val))

        # Reverse: input/oldest first, most-recent alias last
        return dict(reversed(collected_newest_first))

    def _find_covering_wire(self, leaf_ref_toks):
        """Find most specific wire covering this concrete leaf path.
        Checks two sources, preferring the longest (most specific) prefix:
          1. Concrete env entries (string-keyed, no AST nodes)
          2. Variable aliases (via wire_aliases_over_time + alias_to_driven_ref_toks,
             using wildcard matching for AST node positions)
        Returns (wire, covering_ref_toks, c_type).
        """
        base_var = leaf_ref_toks[0]

        # ── 1. Best concrete env match (longest prefix first) ──
        best_concrete = None
        for length in range(len(leaf_ref_toks), 0, -1):
            prefix = leaf_ref_toks[:length]
            env_key = _ref_toks_to_env_key(prefix)
            if env_key in self.env:
                wire, typ = self.env[env_key]
                best_concrete = (length, wire, prefix, typ)
                break

        # ── 2. Best variable alias match (most recent first, then by length) ──
        best_var = None
        for alias in reversed(self.logic.wire_aliases_over_time.get(base_var, [])):
            alias_ref_toks = self.logic.alias_to_driven_ref_toks.get(alias)
            if alias_ref_toks is None or not _has_variable_index(alias_ref_toks):
                continue  # concrete aliases already handled above via env
            if not _var_ref_toks_covers(alias_ref_toks, leaf_ref_toks):
                continue
            alias_type = self.logic.wire_to_c_type[alias]
            length = len(alias_ref_toks)
            # Most recent alias wins among same length; otherwise prefer longer
            if best_var is None or length > best_var[0]:
                best_var = (length, alias, alias_ref_toks, alias_type)

        # ── 3. Pick the more specific (longer) match; concrete wins on ties ──
        if best_concrete and best_var:
            winner = best_concrete if best_concrete[0] >= best_var[0] else best_var
        else:
            winner = best_concrete or best_var

        if winner is None:
            raise ElaborationError(
                f"No covering wire found for {leaf_ref_toks} in func '{self.func_name}'"
            )
        _, wire, covering_ref_toks, typ = winner
        return wire, covering_ref_toks, typ

    def _read_ref(self, ref_toks, c_type, ast_node):
        """Read from a concrete (non-variable) path. Returns (wire, c_type)."""
        if _is_scalar(c_type, self.parser_state):
            env_key = _ref_toks_to_env_key(ref_toks)
            if env_key in self.env:
                return self.env[env_key]
            wire, covering_ref_toks, covering_typ = self._find_covering_wire(ref_toks)
            if covering_ref_toks == ref_toks:
                return wire, covering_typ
            return self._emit_const_ref_rd(
                ref_toks, c_type, {covering_ref_toks: (wire, covering_typ)}, ast_node
            )

        # compound: enumerate leaves to catch partial writes
        all_leaves = _get_leaf_ref_toks(ref_toks, c_type, self.parser_state)
        covering_wires = {}
        for leaf in all_leaves:
            wire, cov_ref_toks, cov_typ = self._find_covering_wire(leaf)
            if cov_ref_toks not in covering_wires:
                covering_wires[cov_ref_toks] = (wire, cov_typ)
        covering_wires = self._temporal_sort_covering_wires(covering_wires, ref_toks[0])

        if len(covering_wires) == 1:
            sole_ref_toks, (sole_wire, sole_typ) = next(iter(covering_wires.items()))
            if sole_ref_toks == ref_toks:
                return sole_wire, sole_typ

        return self._emit_const_ref_rd(ref_toks, c_type, covering_wires, ast_node)

    def _emit_const_ref_rd(self, ref_toks, c_type, covering_wires, ast_node):
        """Emit a CONST_REF_RD submodule instance in the calling function's Logic()."""
        base_var = ref_toks[0]
        _, base_type = self.env[base_var]
        covering_ref_toks_list = list(covering_wires.keys())
        func_name = _const_ref_rd_func_name(
            c_type, base_type, ref_toks, covering_ref_toks_list
        )
        inst_name = self._inst(func_name, ast_node)
        input_ports = []
        input_port_driven_ref_toks = []
        for i, (cov_ref_toks, (cov_wire, cov_typ)) in enumerate(covering_wires.items()):
            input_ports.append((f"ref_toks_{i}", cov_wire, cov_typ))
            input_port_driven_ref_toks.append(cov_ref_toks)
        output_wire = _port_wire(inst_name, C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_submodule_instance(
            self.logic,
            inst_name,
            func_name,
            input_ports,
            output_wire,
            c_type,
            ast_node,
            self.src_file,
        )
        self.logic.ref_submodule_instance_to_ref_toks[inst_name] = ref_toks
        self.logic.ref_submodule_instance_to_input_port_driven_ref_toks[inst_name] = (
            input_port_driven_ref_toks
        )
        return output_wire, c_type

    def _emit_var_ref_assign(self, ref_toks, rhs_wire, rhs_type, ast_node):
        """Variable-index LHS assignment call site.
        e.g. points[i].dim[1] = test_u32   →   ref_toks = ("points", i_ast, "dim", 1)

        Computes output type (leaf_scalar[var_dim_0]...), finds covering wires,
        elaborates variable index expressions, builds/caches the VAR_REF_ASSIGN
        Logic() definition, emits the submodule instance, and records the alias
        with its variable ref_toks in wire_aliases_over_time so subsequent
        _find_covering_wire calls can discover it via wildcard matching.
        """
        base_var = ref_toks[0]
        _, base_type = self.env[base_var]

        # ── Output type: leaf_scalar_type[var_dim_0][var_dim_1]... ──
        output_type = _var_ref_assign_output_type(
            ref_toks, base_type, self.parser_state
        )
        elem_c_type = rhs_type  # scalar type of the value being written

        # ── Covering wires (same machinery as CONST/VAR_REF_RD) ──
        all_concrete_leaves = _get_var_ref_leaves(
            ref_toks, base_type, self.parser_state
        )
        covering_wires = {}
        for leaf in all_concrete_leaves:
            wire, cov_ref_toks, cov_typ = self._find_covering_wire(leaf)
            if cov_ref_toks not in covering_wires:
                covering_wires[cov_ref_toks] = (wire, cov_typ)
        covering_wires = self._temporal_sort_covering_wires(covering_wires, base_var)

        # ── Variable dim info ──
        var_dim_info = []  # (dim_size, select_type, index_wire)
        current_type = base_type
        for tok in ref_toks[1:]:
            if _is_var_tok(tok):
                dim_size = _array_first_dim(current_type)
                select_type = _select_type_for_dim(dim_size)
                index_wire, _ = self._elab_expr(tok)
                var_dim_info.append((dim_size, select_type, index_wire))
                current_type = _array_elem_type(current_type)
            elif isinstance(tok, int):
                current_type = _array_elem_type(current_type)
            elif isinstance(tok, str):
                current_type = self.parser_state.struct_to_field_type_dict[
                    current_type
                ][tok]

        # ── Build / reuse Logic() definition ──
        covering_ref_toks_list = list(covering_wires.keys())
        func_name = _var_ref_assign_func_name(
            output_type, base_type, ref_toks, covering_ref_toks_list
        )
        if func_name not in self.parser_state.FuncLogicLookupTable:
            logic_def = _build_var_ref_assign_logic(
                func_name,
                output_type,
                base_type,
                ref_toks,
                elem_c_type,
                covering_wires,
                var_dim_info,
                self.parser_state,
            )
            self.parser_state.FuncLogicLookupTable[func_name] = logic_def

        # ── Call-site input ports: elem_val, ref_toks_i, var_dim_i ──
        input_ports = [("elem_val", rhs_wire, elem_c_type)]
        input_port_driven_ref_toks = []
        for i, (cov_ref_toks, (cov_wire, cov_typ)) in enumerate(covering_wires.items()):
            input_ports.append((f"ref_toks_{i}", cov_wire, cov_typ))
            input_port_driven_ref_toks.append(cov_ref_toks)
        for i, (dim_size, select_type, index_wire) in enumerate(var_dim_info):
            input_ports.append((f"var_dim_{i}", index_wire, select_type))

        # ── Emit submodule instance ──
        inst_name = self._inst(func_name, ast_node)
        output_wire = _port_wire(inst_name, C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_submodule_instance(
            self.logic,
            inst_name,
            func_name,
            input_ports,
            output_wire,
            output_type,
            ast_node,
            self.src_file,
        )
        self.logic.ref_submodule_instance_to_ref_toks[inst_name] = ref_toks
        self.logic.ref_submodule_instance_to_input_port_driven_ref_toks[inst_name] = (
            input_port_driven_ref_toks
        )

        # ── Create alias wire with variable ref_toks preserved ──
        # The alias type is output_type (covers the variable path).
        # We record alias_to_driven_ref_toks with the original ref_toks (AST nodes
        # intact) so _find_covering_wire can wildcard-match later reads against it.
        alias_prefix = _ref_toks_to_alias_prefix(ref_toks)
        alias = _alias(alias_prefix, self.src_file, ast_node)
        _add_wire(self.logic, alias, output_type)
        _connect(self.logic, output_wire, alias)
        self.logic.wire_aliases_over_time.setdefault(base_var, []).append(alias)
        self.logic.alias_to_orig_var_name[alias] = base_var
        self.logic.alias_to_driven_ref_toks[alias] = ref_toks  # AST nodes preserved

    def _emit_var_ref_rd(self, ref_toks, c_type, ast_node):
        """Elaborate a VAR_REF_RD call site and build/cache its Logic() definition."""
        base_var = ref_toks[0]
        _, base_type = self.env[base_var]

        # ── covering wires from env (same machinery as CONST_REF_RD) ──
        all_concrete_leaves = _get_var_ref_leaves(
            ref_toks, base_type, self.parser_state
        )
        covering_wires = {}
        for leaf in all_concrete_leaves:
            wire, cov_ref_toks, cov_typ = self._find_covering_wire(leaf)
            if cov_ref_toks not in covering_wires:
                covering_wires[cov_ref_toks] = (wire, cov_typ)
        covering_wires = self._temporal_sort_covering_wires(covering_wires, base_var)

        # ── elaborate each variable index expression -> select wire ──
        var_dim_info = []  # (dim_size, select_type, index_wire)
        current_type = base_type
        for tok in ref_toks[1:]:
            if _is_var_tok(tok):
                dim_size = _array_first_dim(current_type)
                select_type = _select_type_for_dim(dim_size)
                index_wire, _ = self._elab_expr(tok)
                var_dim_info.append((dim_size, select_type, index_wire))
                current_type = _array_elem_type(current_type)
            elif isinstance(tok, int):
                current_type = _array_elem_type(current_type)
            elif isinstance(tok, str):
                current_type = self.parser_state.struct_to_field_type_dict[
                    current_type
                ][tok]

        # ── build / reuse Logic() definition ──
        covering_ref_toks_list = list(covering_wires.keys())
        func_name = _var_ref_rd_func_name(
            c_type, base_type, ref_toks, covering_ref_toks_list
        )
        if func_name not in self.parser_state.FuncLogicLookupTable:
            logic_def = _build_var_ref_rd_logic(
                func_name,
                c_type,
                base_type,
                ref_toks,
                covering_wires,
                var_dim_info,
                self.parser_state,
            )
            self.parser_state.FuncLogicLookupTable[func_name] = logic_def

        # ── call-site input ports ──
        input_ports = []
        input_port_driven_ref_toks = []
        for i, (cov_ref_toks, (cov_wire, cov_typ)) in enumerate(covering_wires.items()):
            input_ports.append((f"ref_toks_{i}", cov_wire, cov_typ))
            input_port_driven_ref_toks.append(cov_ref_toks)
        for i, (dim_size, select_type, index_wire) in enumerate(var_dim_info):
            input_ports.append((f"var_dim_{i}", index_wire, select_type))

        inst_name = self._inst(func_name, ast_node)
        output_wire = _port_wire(inst_name, C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_submodule_instance(
            self.logic,
            inst_name,
            func_name,
            input_ports,
            output_wire,
            c_type,
            ast_node,
            self.src_file,
        )
        self.logic.ref_submodule_instance_to_ref_toks[inst_name] = ref_toks
        self.logic.ref_submodule_instance_to_input_port_driven_ref_toks[inst_name] = (
            input_port_driven_ref_toks
        )
        return output_wire, c_type

    def _write_ref(self, ref_toks, rhs_wire, rhs_type, node):
        """Write to a path: create mangled alias, record in env and metadata."""
        env_key = _ref_toks_to_env_key(ref_toks)
        base_var = ref_toks[0]
        _, base_type = self.env[base_var]
        lhs_type = _ref_toks_to_ctype(ref_toks, base_type, self.parser_state)
        alias_prefix = env_key.replace("[", "_").replace("]", "").replace(".", "_")
        alias = _alias(alias_prefix, self.src_file, node)
        _add_wire(self.logic, alias, lhs_type)
        _connect(self.logic, rhs_wire, alias)
        self.logic.wire_aliases_over_time.setdefault(base_var, []).append(alias)
        self.logic.alias_to_orig_var_name[alias] = base_var
        self.logic.alias_to_driven_ref_toks[alias] = ref_toks
        self.env[env_key] = (alias, lhs_type)

    def _declare_var(self, var_name, typ, node):
        """First sight of a local variable: base wire driven by zeros, no alias."""
        _add_wire(self.logic, var_name, typ)
        zeros_wire = C_TO_LOGIC.BUILD_CONST_WIRE(
            C_TO_LOGIC.COMPOUND_NULL, pypeline_ast.Pypeline_ASTNode(node, self.src_file)
        )
        _add_wire(self.logic, zeros_wire, typ)
        _connect(self.logic, zeros_wire, var_name)
        self.env[var_name] = (var_name, typ)

    def _declare_state_reg(self, var_name, c_type, node):
        """Declare a hardware state register (Reg[T] annotation).

        The base wire represents the register's current (start-of-cycle) value.
        Unlike a local variable it has NO combinatorial driver — the VHDL backend
        sources it from the persistent flip-flop signal. All writes via _write_ref
        create aliases in wire_aliases_over_time; the final alias is the next-cycle
        value (drives REG_COMB_<var_name> in the generated VHDL).
        """
        var_info = C_TO_LOGIC.VariableInfo()
        var_info.name = var_name
        var_info.type_name = c_type
        var_info.resolved_const_str = "0"  # power-on reset value
        var_info.is_volatile = False
        var_info.is_static_local = True

        self.logic.state_regs[var_name] = var_info
        self.logic.uses_nonvolatile_state_regs = True

        _add_wire(self.logic, var_name, c_type)
        self.env[var_name] = (var_name, c_type)


# ─────────────────────────────────────────────
# Struct discovery
# ─────────────────────────────────────────────


def _discover_structs(tree, parser_state):
    """Walk AST for NamedTuple subclasses, populate struct_to_field_type_dict.
    Used as fallback when module execution is not available.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        is_named_tuple = any(
            (isinstance(b, ast.Name) and b.id == "NamedTuple")
            or (isinstance(b, ast.Attribute) and b.attr == "NamedTuple")
            for b in node.bases
        )
        if not is_named_tuple:
            continue
        fields = {}
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                fields[item.target.id] = _annotation_to_ctype(item.annotation)
        parser_state.struct_to_field_type_dict[node.name] = fields
        # print(f"  struct: {node.name} -> {fields}")


def _discover_structs_from_module(module, parser_state):
    """Inspect live module namespace for NamedTuple subclasses.
    Handles structs produced by factory functions at module level —
    not just static class definitions in the AST.
    The canonical C type name is stamped by @struct at decoration time;
    we use that name as the dict key rather than the Python variable name.
    """
    for name, obj in vars(module).items():
        if name.startswith("_"):
            continue
        if not (
            inspect.isclass(obj)
            and issubclass(obj, tuple)
            and hasattr(obj, "_fields")
            and hasattr(obj, "__annotations__")
        ):
            continue
        fields = {}
        for field, annotation in obj.__annotations__.items():
            # annotation may be a _CTypeMeta type or a plain string
            fields[field] = str(annotation)
        # Use the canonical name stamped by @struct (not the Python variable name)
        c_name = getattr(obj, "_pypeline_ctype_name", name)
        parser_state.struct_to_field_type_dict[c_name] = fields
        # print(f"  struct: {c_name} -> {fields}")


# ─────────────────────────────────────────────
# LogicInstLookupTable population (recursive)
# ─────────────────────────────────────────────


def _walk_instances(prefix, logic, parser_state):
    for inst_name, inst_func_name in logic.submodule_instances.items():
        inst_key = f"{prefix}{C_TO_LOGIC.SUBMODULE_MARKER}{inst_name}"
        if inst_func_name in parser_state.FuncLogicLookupTable:
            inst_logic = parser_state.FuncLogicLookupTable[inst_func_name]
        else:
            inst_logic = C_TO_LOGIC.BUILD_C_BUILT_IN_SUBMODULE_FUNC_LOGIC(
                logic, inst_name, parser_state
            )
            parser_state.FuncLogicLookupTable[inst_logic.func_name] = inst_logic
        parser_state.LogicInstLookupTable[inst_key] = inst_logic
        parser_state.FuncToInstances.setdefault(inst_logic.func_name, set()).add(
            inst_key
        )
        # print(f"  inst: {inst_key} -> {inst_logic.func_name}")
        _walk_instances(inst_key, inst_logic, parser_state)


def _is_hardware_func(func_def):
    """True if this function should be hardware-elaborated.
    Pure Python elaboration-time helpers like sum_widths(n, m) have no type
    annotations and should not be treated as hardware functions.
    A function is hardware if it has a return annotation OR any typed argument.
    """
    if func_def.returns is not None:
        return True
    for arg in func_def.args.args:
        if arg.annotation is not None:
            return True
    return False


def _build_inst_lookup(parser_state):
    for main_name in parser_state.main_mhz:
        main_logic = parser_state.FuncLogicLookupTable[main_name]
        parser_state.LogicInstLookupTable[main_name] = main_logic
        parser_state.FuncToInstances.setdefault(main_logic.func_name, set()).add(
            main_name
        )
        _walk_instances(main_name, main_logic, parser_state)


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────


def PARSE_FILE(py_file):
    print("PY_TO_LOGIC parsing:", py_file)

    # ── Step 1: execute the design file as a Python module ──
    # This runs all elaboration-time Python: type factory functions, constants,
    # @MAIN registrations, struct definitions etc.
    import pypeline

    pypeline._main_registry.clear()  # reset in case of multiple PARSE_FILE calls

    spec = importlib.util.spec_from_file_location("pypeline_design", py_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module_globals = vars(module)
    parser_state = C_TO_LOGIC.ParserState()

    # ── Step 2: discover structs from live module namespace ──
    # Handles both static class definitions and factory-generated types.
    _discover_structs_from_module(module, parser_state)

    # ── Step 3: collect MAINs from the pypeline registry ──
    main_names = {f.__name__ for f in pypeline._main_registry}

    # ── Step 4: AST parse for hardware elaboration ──
    with open(py_file, "r") as f:
        source = f.read()
    tree = ast.parse(source)

    # Only collect top-level function definitions — not nested functions inside
    # factory closures like make_concat. ast.walk descends into everything so
    # we instead look only at direct children of the module body.
    func_defs = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and _is_hardware_func(node)
    ]

    for node in func_defs:
        stub = C_TO_LOGIC.Logic()
        stub.func_name = node.name
        parser_state.FuncLogicLookupTable[node.name] = stub

    for node in func_defs:
        print(f"  elaborating func: {node.name}")
        elab = FuncElaborator(node, parser_state, py_file, module_globals)
        logic = elab.elaborate()
        parser_state.FuncLogicLookupTable[node.name] = logic
        if node.name in main_names:
            parser_state.main_mhz[node.name] = None
            parser_state.main_syn_mhz[node.name] = None
            parser_state.main_clk_group[node.name] = None

    _build_inst_lookup(parser_state)
    return parser_state
