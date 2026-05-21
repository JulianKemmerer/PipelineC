import ast
import hashlib
import os

import C_TO_LOGIC
import AST as pypeline_ast

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
# Naming helpers
# ─────────────────────────────────────────────


def _loc_str(src_file, node):
    file_base = os.path.basename(src_file).replace(".", "_")
    return f"{file_base}_l{node.lineno}_c{node.col_offset}"


def _inst_name(op_full_name, src_file, node):
    return f"{op_full_name}[{_loc_str(src_file, node)}]"


def _port_wire(inst, port):
    return f"{inst}{C_TO_LOGIC.SUBMODULE_MARKER}{port}"


def _alias(var_name, src_file, node):
    return f"{var_name}_{_loc_str(src_file, node)}"


def _unary_func_name(op_name, typ):
    return f"{C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX}_{op_name}_{typ}"


def _bin_func_name(op_name, typ):
    return f"{C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX}_{op_name}_{typ}"


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
    # output_leaf_count is the number of scalar leaves in c_type.
    # For scalar output: 1.  For compound output: number of leaves.
    # This forms the innermost dimension of the intermediate.
    output_leaf_count, output_leaf_paths, output_leaf_types = _get_output_leaf_info(
        c_type, parser_state
    )

    # ── Step 1: extract concrete leaf wires via CONST_REF_RD ──
    # All concrete leaves are in order: outermost var dim varies slowest,
    # output type leaves vary fastest — matching interm[D0][D1]...[L] indexing.
    all_concrete_leaves = _get_var_ref_leaves(ref_toks, base_type, parser_state)
    counter = [0]
    leaf_wires = []

    for concrete_leaf in all_concrete_leaves:
        # find which covering port covers this leaf (longest prefix match)
        covering_port = None
        for cov_ref_toks, (port_name, port_type) in covering_port_info.items():
            if (
                len(concrete_leaf) >= len(cov_ref_toks)
                and concrete_leaf[: len(cov_ref_toks)] == cov_ref_toks
            ):
                covering_port = (cov_ref_toks, port_name, port_type)
                break
        if covering_port is None:
            raise ElaborationError(f"No covering port for leaf {concrete_leaf}")

        cov_ref_toks, port_name, port_type = covering_port
        # build ref_toks relative to the covering port (substitute port name as base)
        internal_ref_toks = (port_name,) + concrete_leaf[len(cov_ref_toks) :]

        if len(internal_ref_toks) == 1:
            # covering port IS the leaf (e.g. scalar port exactly covers this element)
            leaf_wire = port_name
        else:
            leaf_wire = _emit_internal_const_ref_rd(
                logic, internal_ref_toks, port_name, port_type, parser_state, counter
            )
        leaf_wires.append(leaf_wire)

    # ── Step 2: mux tree per variable dimension ──
    #
    # Leaf ordering: position of leaf at (v0, v1, ..., vk, l):
    #   v0*(stride0) + v1*(stride1) + ... + vk*(strideK) + l
    # where stride_i = product(var_dim_sizes[i+1:]) * output_leaf_count
    #
    # For each dimension i with size Di:
    #   stride    = product(later_var_dim_sizes) * output_leaf_count
    #   n_groups  = stride
    #   group g   = Di wires: current_wires[0*stride+g, 1*stride+g, ..., (Di-1)*stride+g]
    #   leaf type = output_leaf_types[g % output_leaf_count]
    #   result    = binary mux tree over those Di wires
    #
    # After processing dimension i: stride / Di wires remain.
    # After all dimensions: output_leaf_count wires (one per output leaf position).

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
            # leaf type for this group based on which output leaf slot it targets
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
        # scalar output: direct wire to return_output
        _connect(logic, current_wires[0], C_TO_LOGIC.RETURN_WIRE_NAME)
    else:
        # compound output: assemble scalar result wires into c_type via CONST_REF_RD.
        # current_wires[k] corresponds to output_leaf_paths[k] within c_type.
        # Uses a synthetic dummy base "var_ref_out" for the assembly ref_toks.
        DUMMY_OUT = "var_ref_out"
        logic.wire_to_c_type[DUMMY_OUT] = c_type
        input_ports = []
        covering_rts = []
        for k, (leaf_path, leaf_type, leaf_wire) in enumerate(
            zip(output_leaf_paths, output_leaf_types, current_wires)
        ):
            input_ports.append((f"ref_toks_{k}", leaf_wire, leaf_type))
            covering_rts.append(leaf_path)  # e.g. ("_out", "dim", 0)

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


# ─────────────────────────────────────────────
# Single-function elaborator
# ─────────────────────────────────────────────


class ElaborationError(Exception):
    pass


class FuncElaborator:
    def __init__(self, func_def, parser_state, src_file):
        self.func_def = func_def
        self.func_name = func_def.name
        self.parser_state = parser_state
        self.src_file = src_file
        self.logic = C_TO_LOGIC.Logic()
        self.logic.func_name = self.func_name
        # env: ref_toks env key string -> (wire, c_type)
        self.env = {}

    def elaborate(self):
        self.logic.c_ast_node = pypeline_ast.Pypeline_ASTNode(
            self.func_def, self.src_file
        )
        self._setup_inputs()
        self._setup_outputs()
        for stmt in self.func_def.body:
            self._elab_stmt(stmt)
        return self.logic

    def _setup_inputs(self):
        for arg in self.func_def.args.args:
            name = arg.arg
            typ = _annotation_to_ctype(arg.annotation)
            self.logic.inputs.append(name)
            _add_wire(self.logic, name, typ)
            self.env[name] = (name, typ)

    def _setup_outputs(self):
        ret_typ = _annotation_to_ctype(self.func_def.returns)
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
        else:
            raise NotImplementedError(f"Unsupported statement: {ast.dump(stmt)}")

    def _elab_assign(self, stmt):
        target = stmt.targets[0]
        rhs_wire, rhs_type = self._elab_expr(stmt.value)
        ref_toks = self._parse_ref_toks(target)
        base_var = ref_toks[0]
        if len(ref_toks) == 1 and base_var not in self.env:
            self._declare_var(base_var, rhs_type, target)
        self._write_ref(ref_toks, rhs_wire, rhs_type, stmt.value)

    def _elab_ann_assign(self, stmt):
        var_name = stmt.target.id
        typ = _annotation_to_ctype(stmt.annotation)
        self._declare_var(var_name, typ, stmt.target)
        if stmt.value is not None:
            rhs_wire, _ = self._elab_expr(stmt.value)
            self._write_ref((var_name,), rhs_wire, typ, stmt.value)

    def _elab_return(self, stmt):
        result_wire, _ = self._elab_expr(stmt.value)
        _connect(self.logic, result_wire, C_TO_LOGIC.RETURN_WIRE_NAME)

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
        elif isinstance(expr, (ast.Subscript, ast.Attribute)):
            return self._elab_ref_read(expr)
        else:
            raise NotImplementedError(f"Unsupported expr: {ast.dump(expr)}")

    def _elab_name(self, expr):
        name = expr.id
        wire, typ = self.env[name]
        if _is_scalar(typ, self.parser_state):
            return wire, typ
        return self._read_ref((name,), typ, expr)

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

    def _elab_unary(self, expr):
        op_name = UNARY_OP_MAP[type(expr.op)]
        operand_wire, typ = self._elab_expr(expr.operand)
        func_name = _unary_func_name(op_name, typ)
        inst = _inst_name(
            f"{C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX}_{op_name}", self.src_file, expr
        )
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

    def _elab_binop(self, expr):
        op_name = BIN_OP_MAP[type(expr.op)]
        left_wire, typ = self._elab_expr(expr.left)
        right_wire, _ = self._elab_expr(expr.right)
        func_name = _bin_func_name(op_name, typ)
        inst = _inst_name(
            f"{C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX}_{op_name}", self.src_file, expr
        )
        port_return = _port_wire(inst, C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_submodule_instance(
            self.logic,
            inst,
            func_name,
            [("left", left_wire, typ), ("right", right_wire, typ)],
            port_return,
            typ,
            expr,
            self.src_file,
        )
        return port_return, typ

    def _elab_compare(self, expr):
        op_name = BIN_OP_MAP[type(expr.ops[0])]
        left_wire, typ = self._elab_expr(expr.left)
        right_wire, _ = self._elab_expr(expr.comparators[0])
        func_name = _bin_func_name(op_name, typ)
        inst = _inst_name(
            f"{C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX}_{op_name}", self.src_file, expr
        )
        port_return = _port_wire(inst, C_TO_LOGIC.RETURN_WIRE_NAME)
        _add_submodule_instance(
            self.logic,
            inst,
            func_name,
            [("left", left_wire, typ), ("right", right_wire, typ)],
            port_return,
            C_TO_LOGIC.BOOL_C_TYPE,
            expr,
            self.src_file,
        )
        return port_return, C_TO_LOGIC.BOOL_C_TYPE

    def _elab_call(self, expr):
        callee_name = expr.func.id
        callee_def = self.parser_state.FuncLogicLookupTable.get(callee_name)
        if callee_def is None:
            raise NotImplementedError(f"Call to unknown function '{callee_name}'")
        inst = _inst_name(callee_name, self.src_file, expr)
        ret_typ = callee_def.wire_to_c_type[C_TO_LOGIC.RETURN_WIRE_NAME]
        port_return = _port_wire(inst, C_TO_LOGIC.RETURN_WIRE_NAME)
        input_ports = []
        for arg_expr, port_name in zip(expr.args, callee_def.inputs):
            arg_wire, arg_typ = self._elab_expr(arg_expr)
            input_ports.append((port_name, arg_wire, arg_typ))
        _add_submodule_instance(
            self.logic,
            inst,
            callee_name,
            input_ports,
            port_return,
            ret_typ,
            expr,
            self.src_file,
        )
        return port_return, ret_typ

    # ── compound type read / write ────────────

    def _parse_ref_toks(self, node):
        """Parse AST node into ref_toks. Variable subscripts stored as AST expression tokens."""
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
            return parent + (slc,)  # variable index: store raw AST expression
        else:
            raise NotImplementedError(f"Cannot parse ref toks from: {ast.dump(node)}")

    def _find_covering_wire(self, leaf_ref_toks):
        """Find most specific wire in env covering this leaf path (longest prefix match).
        Returns (wire, covering_ref_toks, c_type).
        """
        for length in range(len(leaf_ref_toks), 0, -1):
            prefix = leaf_ref_toks[:length]
            env_key = _ref_toks_to_env_key(prefix)
            if env_key in self.env:
                wire, typ = self.env[env_key]
                return wire, prefix, typ
        raise ElaborationError(
            f"No covering wire found for {leaf_ref_toks} in func '{self.func_name}'"
        )

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
        inst_name = _inst_name(func_name, self.src_file, ast_node)
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

        inst_name = _inst_name(func_name, self.src_file, ast_node)
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
        alias_prefix = env_key.replace("[", "_").replace("]", "").replace(".", "_")
        alias = _alias(alias_prefix, self.src_file, node)
        _add_wire(self.logic, alias, rhs_type)
        _connect(self.logic, rhs_wire, alias)
        self.logic.wire_aliases_over_time.setdefault(base_var, []).append(alias)
        self.logic.alias_to_orig_var_name[alias] = base_var
        self.logic.alias_to_driven_ref_toks[alias] = ref_toks
        self.env[env_key] = (alias, rhs_type)

    def _declare_var(self, var_name, typ, node):
        """First sight of a local variable: base wire driven by zeros, no alias."""
        _add_wire(self.logic, var_name, typ)
        zeros_wire = C_TO_LOGIC.BUILD_CONST_WIRE(
            C_TO_LOGIC.COMPOUND_NULL, pypeline_ast.Pypeline_ASTNode(node, self.src_file)
        )
        _add_wire(self.logic, zeros_wire, typ)
        _connect(self.logic, zeros_wire, var_name)
        self.env[var_name] = (var_name, typ)


# ─────────────────────────────────────────────
# Type annotation helper
# ─────────────────────────────────────────────


def _annotation_to_ctype(ann):
    """Convert Python AST annotation to C type string. Returns None if no annotation."""
    if ann is None:
        return None
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Attribute):
        return ann.attr
    if isinstance(ann, ast.Subscript):
        base = _annotation_to_ctype(ann.value)
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
# Struct discovery
# ─────────────────────────────────────────────


def _discover_structs(tree, parser_state):
    """Walk AST for NamedTuple subclasses, populate struct_to_field_type_dict."""
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
        print(f"  struct: {node.name} -> {fields}")


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
        print(f"  inst: {inst_key} -> {inst_logic.func_name}")
        _walk_instances(inst_key, inst_logic, parser_state)


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
    with open(py_file, "r") as f:
        source = f.read()
    tree = ast.parse(source)
    parser_state = C_TO_LOGIC.ParserState()

    _discover_structs(tree, parser_state)

    func_defs = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    for node in func_defs:
        stub = C_TO_LOGIC.Logic()
        stub.func_name = node.name
        parser_state.FuncLogicLookupTable[node.name] = stub

    for node in func_defs:
        print(f"  elaborating func: {node.name}")
        elab = FuncElaborator(node, parser_state, py_file)
        logic = elab.elaborate()
        parser_state.FuncLogicLookupTable[node.name] = logic
        if _has_main_decorator(node):
            parser_state.main_mhz[node.name] = None
            parser_state.main_syn_mhz[node.name] = None
            parser_state.main_clk_group[node.name] = None

    _build_inst_lookup(parser_state)
    return parser_state


def _has_main_decorator(func_def):
    for dec in func_def.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "MAIN":
            return True
    return False
