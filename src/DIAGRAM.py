"""Design diagram: diagram.html, a self-contained page every build writes into
its output directory, showing the design's files, its MAINs joined by global
wires, and one graph per function of the call hierarchy, labeled with latency,
measured delay, clock domain and the types the wires carry. See
docs/DIAGRAM_DESIGN.md.

Reads only what parsing and timing already computed: the shared Logic and
ParserState tables of both front ends, plus the Pypeline-only tables (import
edges, Python clock names, global instances and FIFOs, field-level wire
access records, type descriptions) where they exist. Those, and the Logic
fields newer than the first C front end, are read with getattr as the rest of
the shared back end reads them: a C build can reuse a parser state an older
compiler pickled (C_TO_LOGIC.GET_PARSER_STATE_CACHE) that lacks them."""

import json
import os

import AUTO_PIPELINE
import LOGIC
import PY_TO_LOGIC
import SYN
import VHDL

# The page's file name in the output directory
DIAGRAM_FILE = "diagram.html"
# Version of the embedded design data (DIAGRAM_DESIGN.md#3-data-model)
SCHEMA_VERSION = 2
# The viewer page the design data is embedded into
_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "diagram", "viewer.html"
)
# Placeholder in the template replaced by the design JSON
_DATA_PLACEHOLDER = "__DIAGRAM_DESIGN_JSON__"
# The compiler's own source directory (pypeline.py is a library file)
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
# Libraries shipped with the compiler (include/pypeline, the C headers)
_INCLUDE_DIR = os.path.join(os.path.dirname(_SRC_DIR), "include") + os.sep
# Description kinds (pypeline.py's _NameInfo.kind) of an @interface's halves
_HALF_ROLES = {"interface_fwd": "fwd", "interface_fb": "fb"}


def FORGET_DIAGRAM(out_dir):
    """Remove a previous build's diagram from out_dir, so a build that stops
    before writing its own leaves no page describing other hardware."""
    path = os.path.join(out_dir, DIAGRAM_FILE)
    if os.path.exists(path):
        os.remove(path)


def WRITE_DIAGRAM(parser_state, timing_params, src_file):
    """Write DIAGRAM_FILE into SYN.SYN_OUTPUT_DIRECTORY from the final parse and
    its timing params (None: zero added clocks). Returns the page's path."""
    data = _design_data(parser_state, timing_params, src_file)
    text = json.dumps(data, sort_keys=True, separators=(",", ":"))
    # A "</script>" inside a string would end the data block early
    text = text.replace("</", "<\\/")
    with open(_TEMPLATE_PATH) as f:
        template = f.read()
    if template.count(_DATA_PLACEHOLDER) != 1:
        raise Exception(f"{_TEMPLATE_PATH} must hold {_DATA_PLACEHOLDER} once")
    path = os.path.join(SYN.SYN_OUTPUT_DIRECTORY, DIAGRAM_FILE)
    with open(path, "w") as f:
        f.write(template.replace(_DATA_PLACEHOLDER, text))
    print(f"Design diagram: {path}", flush=True)
    return path


def _design_data(parser_state, timing_params, src_file):
    """The page's design data (schema SCHEMA_VERSION), every collection sorted
    so the same design always gives the same page."""
    ps = parser_state
    is_python = src_file.endswith(".py")
    if timing_params is not None:
        lookup = timing_params.TimingParamsLookupTable
    else:
        lookup = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(ps)
    types = _Types(ps)
    mains = _mains(ps, lookup)
    funcs, inst_latency = _funcs(ps, lookup, types)
    files = _files(ps, src_file, mains)
    data = {
        "schema": SCHEMA_VERSION,
        "build": {
            "top": os.path.abspath(src_file),
            "front_end": "pypeline" if is_python else "c",
            "part": ps.part,
            "tool": None if SYN.SYN_TOOL is None else SYN.SYN_TOOL.__name__,
            "delays_known": sum(
                1 for f in funcs.values() if f.get("delay_ns") is not None
            ),
        },
        "files": files,
        "clocks": _clocks(ps),
        "mains": mains,
        "pins": _pins(ps, types),
        "wires": _wires(ps, types),
        "links": _links(ps, types),
        "funcs": funcs,
        "inst_latency": inst_latency,
    }
    return types.resolve(data)


class _TypeRef:
    """Where the design data names a C type, until _Types.resolve replaces it
    by the type's index into the page's type table."""

    __slots__ = ("c_type",)

    def __init__(self, c_type):
        self.c_type = c_type


class _Types:
    """The page's type table: every C type a drawn port, register, global wire,
    link or edge carries, with its bit width, interface role and readable name
    (DIAGRAM_DESIGN.md#types-and-interface-roles). The data names a type by
    its index; ref() holds the place until resolve() has seen every type."""

    def __init__(self, parser_state):
        self.ps = parser_state
        # C type -> its Pypeline descriptions (pypeline.py's _NameInfo); the
        # same table holds function keys, and nothing for a C design
        self.descriptions = getattr(parser_state, "pypeline_name_descriptions", {})
        self.used = set()  # C types ref() was given
        self._bits = {}  # C type -> width memo
        self._roles = {}  # C type -> role memo
        self._halves = None  # @interface half fields -> [(role, half C type)]

    def ref(self, c_type):
        if c_type is None:
            return None
        self.used.add(c_type)
        return _TypeRef(c_type)

    def bits(self, c_type):
        """Bit width (VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM), memoized; None for
        a type with no width (void, say), which the VHDL helper would treat as
        a fatal error."""
        if c_type is None:
            return None
        if c_type not in self._bits:
            known = (
                LOGIC.GET_WIDTH_FROM_C_TYPE_STR(self.ps, c_type, allow_fail=True)
                is not None
                or LOGIC.C_TYPE_IS_STRUCT(c_type, self.ps)
                or LOGIC.C_TYPE_IS_ARRAY(c_type)
            )
            self._bits[c_type] = (
                VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM(c_type, self.ps) if known else None
            )
        return self._bits[c_type]

    def field_type(self, c_type, path):
        """The type of the field `path` (struct field names, array indices) of
        c_type, or None."""
        for tok in path:
            if c_type is None:
                return None
            if isinstance(tok, int):
                if not LOGIC.C_TYPE_IS_ARRAY(c_type):
                    return None
                elem, dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
                c_type = elem + "".join(f"[{d}]" for d in dims[1:])
            else:
                c_type = self.ps.struct_to_field_type_dict.get(c_type, {}).get(tok)
        return c_type

    def _info(self, c_type):
        """The type's description, or None (a scalar, an array, a C type)."""
        infos = self.descriptions.get(c_type)
        if not infos:
            return None
        return min(infos, key=lambda i: (i.kind, i.symbol, i.module, i.source, i.line))

    def _halves_like(self, c_type):
        """[(role, half C type)] of the @interface halves with c_type's fields.
        A generated interface function types each Feedback with a plain copy
        of a half (interface_func._plain_shape_of), which keeps the fields but
        not the role; every stream interface's .fb_t has the same fields."""
        if self._halves is None:
            self._halves = {}
            for key in sorted(self.descriptions):
                roles = {
                    _HALF_ROLES[i.kind]
                    for i in self.descriptions[key]
                    if i.kind in _HALF_ROLES
                }
                fields = self.ps.struct_to_field_type_dict.get(key)
                if len(roles) == 1 and fields:
                    shape = tuple(sorted(fields.items()))
                    self._halves.setdefault(shape, []).append((roles.pop(), key))
        fields = self.ps.struct_to_field_type_dict.get(c_type)
        if not fields:
            return []
        return self._halves.get(tuple(sorted(fields.items())), [])

    def role(self, c_type):
        """fwd: an @interface's .fwd_t, a plain {data, valid} stream, or a type
        holding one; fb: an .fb_t, or a type holding one and nothing forward;
        plain: anything else."""
        if c_type is None:
            return "plain"
        if c_type in self._roles:
            return self._roles[c_type]
        self._roles[c_type] = "plain"  # guards a type that holds itself
        if LOGIC.C_TYPE_IS_ARRAY(c_type):
            elem, _dims = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
            role = self.role(elem)
        else:
            role = self._struct_role(c_type)
        self._roles[c_type] = role
        return role

    def _struct_role(self, c_type):
        own = {
            _HALF_ROLES[i.kind]
            for i in self.descriptions.get(c_type, ())
            if i.kind in _HALF_ROLES
        }
        if len(own) == 1:
            return own.pop()
        halves = {role for role, _half in self._halves_like(c_type)}
        if len(halves) == 1:
            return halves.pop()
        fields = self.ps.struct_to_field_type_dict.get(c_type)
        if not fields:
            return "plain"
        if set(fields) == {"data", "valid"} and fields["valid"] == "uint1_t":
            return "fwd"  # stream.make_stream_t's shape
        held = {self.role(t) for t in fields.values()}
        if "fwd" in held:
            return "fwd"
        return "fb" if "fb" in held else "plain"

    def _name_parts(self, c_type):
        """(Python name, its factory arguments' names, array dims) of a type
        with a description, else None: its C name is what the source says."""
        dims = ""
        if LOGIC.C_TYPE_IS_ARRAY(c_type):
            c_type, sizes = LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
            dims = "".join(f"[{d}]" for d in sizes)
        info = self._info(c_type)
        if info is None:
            return None
        suffix = ""
        if info.kind not in _HALF_ROLES and info.symbol.endswith("_plain"):
            # interface_func._plain_shape_of's copy is the class <half class>_plain,
            # and the half's C name starts with the half's class name
            cls = info.symbol[: -len("_plain")]
            halves = [h for _r, h in self._halves_like(c_type) if h.startswith(cls)]
            if len(halves) == 1:
                info, suffix = self._info(halves[0]), "_plain"
        if info.user_name:
            return info.user_name, "", dims

        def short(v):
            return getattr(v, "user_name", "") or getattr(v, "symbol", None) or str(v)

        # Factory arguments tell same-named types apart, or else their fields
        args = [short(v) for _k, v in info.params] or [
            short(v) for _k, v in info.fields
        ]
        return info.symbol + suffix, "<" + ", ".join(args) + ">" if args else "", dims

    def _names(self, c_types):
        """{C type: readable name} of the types in c_types that have one: the
        Python name, with its factory arguments' names when another type in
        c_types has the same Python name."""
        parts = {}
        clash = {}
        for c_type in c_types:
            p = self._name_parts(c_type)
            if p is not None:
                parts[c_type] = p
                key = p[0] + p[2]
                clash[key] = clash.get(key, 0) + 1
        names = {}
        for c_type, (name, args, dims) in parts.items():
            names[c_type] = name + (args if clash[name + dims] > 1 else "") + dims
        return names

    def resolve(self, data):
        """data with the type table added and every _TypeRef replaced by its
        index into it."""
        order = sorted(self.used)
        index = {c_type: i for i, c_type in enumerate(order)}
        names = self._names(order)
        table = []
        for c_type in order:
            row = {"c": c_type, "bits": self.bits(c_type)}
            role = self.role(c_type)
            if role != "plain":
                row["role"] = role
            if names.get(c_type, c_type) != c_type:
                row["name"] = names[c_type]
            table.append(row)

        def walk(obj):
            if isinstance(obj, _TypeRef):
                return index[obj.c_type]
            if isinstance(obj, dict):
                return {k: walk(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [walk(v) for v in obj]
            return obj

        resolved = walk(data)
        resolved["types"] = table
        return resolved


def _clock_id(mhz, group):
    """The page's name of a clock identity (mhz, name)."""
    if mhz is None:
        return "no clock"
    return f"{mhz:g} MHz" + (f" {group}" if group else "")


def _clocks(ps):
    """Each MAIN clock: its rate, group, Python name and the goal timing uses."""
    clocks = {}
    for main in sorted(ps.main_mhz):
        mhz, group = ps.main_mhz[main], ps.main_clk_group.get(main)
        cid = _clock_id(mhz, group)
        if cid in clocks:
            continue
        clocks[cid] = {
            "mhz": mhz,
            "group": group,
            "name": getattr(ps, "pypeline_clock_names", {}).get((mhz, group)),
            "goal_mhz": SYN.GET_TARGET_MHZ(main, ps, allow_no_syn_tool=True),
        }
    return clocks


def _src_loc(logic):
    meta = logic.ast_meta if logic is not None else None
    if meta is None:
        return None, None
    return meta.src_file, meta.line


def _mains(ps, lookup):
    """Each MAIN: its function, file, line, clock, latency, kind (main, or the
    global instance or FIFO it implements) and whether it is only wiring."""
    decl_of = {}
    for key, decl in getattr(ps, "pypeline_global_insts", {}).items():
        for name in decl.main_names:
            decl_of[name] = decl
    mains = {}
    for main in sorted(ps.main_mhz):
        logic = ps.FuncLogicLookupTable[main]
        src, line = _src_loc(logic)
        entry = {
            "clock": _clock_id(ps.main_mhz[main], ps.main_clk_group.get(main)),
            "latency": lookup[main].GET_TOTAL_LATENCY(ps, lookup),
            "kind": "main",
            "file": src,
            "line": line,
            "wiring": _wiring_reason(logic, ps),
        }
        reset = getattr(ps, "main_resets", {}).get(main)
        if reset is not None:
            entry["reset"] = reset.source
        decl = decl_of.get(main)
        if decl is not None:
            is_fifo = isinstance(decl, PY_TO_LOGIC.GlobalFifoDecl)
            entry["kind"] = "fifo" if is_fifo else "global_inst"
            entry["wiring"] = None  # its hardware is the instance or FIFO
            entry["name"] = decl.bare_name
            entry["file"] = decl.src_file
            entry["line"] = decl.line
            entry["decl"] = decl.describe()
            if len(decl.main_names) > 1:
                # An async FIFO's write and read sides draw as one node
                entry["group"] = decl.key
        mains[main] = entry
    return mains


def _wiring_reason(logic, ps):
    """Why a MAIN or an operator does nothing but connect wires (the viewer's
    wiring filter hides it), or None. Uses the compiler's own zero-delay rule
    (SYN.LOGIC_IS_ZERO_DELAY); something with registers anywhere in its
    hierarchy (LOGIC.LOGIC_NEEDS_CLOCK_ENABLE), raw VHDL, a clock crossing or
    a black box is never only wiring."""
    if logic.func_name in ps.func_marked_wires:
        return "@wires"
    if logic.is_clock_crossing or logic.func_name in ps.func_marked_blackbox:
        return None
    if LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(logic, ps):
        return None
    if logic.vhdl_module_text is not None:
        return None
    if SYN.LOGIC_IS_ZERO_DELAY(logic, ps, allow_none_delay=True):
        return "no logic"
    return None


def _pins(ps, types):
    """Top-level Input and Output pins."""
    pins = {}
    decls = getattr(ps, "pypeline_wire_decls", {})
    for name in sorted(ps.input_wires | ps.output_wires):
        info = ps.global_vars.get(name)
        decl = decls.get(name)
        pins[name] = {
            "dir": "in" if name in ps.input_wires else "out",
            "t": types.ref(info.type_name if info is not None else None),
            "name": decl.bare_name if decl is not None else name,
            "loc": decl.loc if decl is not None else None,
            "clock_pin": decl is not None and decl.binding is not None,
        }
    return pins


def _wires(ps, types):
    """Each global wire: its Python name, where it is declared, its type and
    whether it is ASYNC."""
    wires = {}
    for var in sorted(ps.global_vars):
        decl = getattr(ps, "pypeline_wire_decls", {}).get(var)
        wires[var] = {
            "name": decl.bare_name if decl is not None else var,
            "loc": decl.loc if decl is not None else None,
            "t": types.ref(ps.global_vars[var].type_name),
            "async": var in ps.async_wires,
        }
    return wires


def _path_str(path):
    return "".join(f"[{t}]" if isinstance(t, int) else f".{t}" for t in path)


def _links(ps, types):
    """Writer -> reader links of every global wire, one per field leaf a reader
    reads (whole wires for C), and one per clock crossing (write MAIN -> read
    MAIN). Endpoints are instance names, or "pin:<name>" for a top-level pin.

    Writers and readers follow VHDL.WRITE_MULTIMAIN_TOP's "Directly connected
    global wires": a writer has the wire in write_only_global_wires (or as a
    state reg) and drives global_wire_driven_paths; a reader has it in
    read_only_global_wires, or reads it back through readback_global_wires,
    at its global_wire_read_paths. A reader path links to each writer whose
    driven paths overlap it."""
    decls = getattr(ps, "pypeline_wire_decls", {})
    links = set()
    for var in sorted(ps.global_vars):
        info = ps.global_vars[var]
        writers = {}  # instance -> driven paths
        readers = {}  # instance -> read paths
        for func in sorted(info.used_in_funcs):
            logic = ps.FuncLogicLookupTable.get(func)
            insts = ps.FuncToInstances.get(func)
            if logic is None or not insts:
                continue
            reads = getattr(logic, "global_wire_read_paths", {}).get(var) or {(): None}
            if var in logic.write_only_global_wires or var in logic.state_regs:
                driven = getattr(logic, "global_wire_driven_paths", {}).get(var) or {()}
                for inst in insts:
                    writers[inst] = driven
                if var in getattr(logic, "readback_global_wires", {}):
                    for inst in insts:
                        readers[inst] = set(reads)
            elif var in logic.read_only_global_wires:
                for inst in insts:
                    readers[inst] = set(reads)
        if var in ps.input_wires and not writers:
            writers["pin:" + var] = {()}
        if var in ps.output_wires:
            readers["pin:" + var] = {()}
        is_async = var in ps.async_wires
        for reader in sorted(readers):
            for read_path in sorted(readers[reader], key=repr):
                for writer in sorted(writers):
                    if writer == reader:
                        continue
                    for driven_path in sorted(writers[writer], key=repr):
                        if not PY_TO_LOGIC._path_overlaps(read_path, driven_path):
                            continue
                        path = max(read_path, driven_path, key=len)
                        links.add(
                            (
                                writer,
                                reader,
                                var,
                                _path_str(path),
                                types.field_type(info.type_name, path),
                                is_async,
                                False,
                            )
                        )
    for var in sorted(ps.clk_cross_var_info):
        cross = ps.clk_cross_var_info[var]
        write_mains, read_mains = cross.write_read_main_funcs
        for writer in sorted(write_mains):
            for reader in sorted(read_mains):
                links.add((writer, reader, var, "", None, True, True))
    rows = []
    for writer, reader, var, path, c_type, is_async, crossing in sorted(
        links, key=lambda t: tuple("" if v is None else str(v) for v in t)
    ):
        decl = decls.get(var)
        rows.append(
            {
                "src": writer,
                "dst": reader,
                "wire": var,
                "name": (decl.bare_name if decl is not None else var) + path,
                "t": types.ref(c_type),
                "async": is_async,
                "crossing": crossing,
            }
        )
    return rows


def _func_kind(logic, ps):
    """op (operators and other built-ins, never drawn as a hierarchy level),
    vhdl (raw HDL leaf), wires (@wires), generated, library or user."""
    if logic.vhdl_module_text is not None:
        return "vhdl"
    if (
        logic.is_c_built_in
        or logic.is_vhdl_func
        or logic.is_vhdl_expr
        or LOGIC.IS_BIT_MANIP(logic)
        or logic.ast_meta is None
    ):
        return "op"
    if logic.func_name in ps.func_marked_wires:
        return "wires"
    src = logic.ast_meta.src_file
    if not src or not os.path.isfile(src):
        return "generated"
    if _is_library_file(src):
        return "library"
    return "user"


def _is_library_file(path):
    """A file shipped with the compiler: under include/, or in src/ itself
    (pypeline.py), not a design under src/tests."""
    path = os.path.abspath(path)
    return path.startswith(_INCLUDE_DIR) or os.path.dirname(path) == _SRC_DIR


def _def_name(logic):
    raw = logic.ast_meta.raw if logic.ast_meta is not None else None
    name = getattr(raw, "name", None)
    if name is None:
        decl = getattr(raw, "decl", None)  # pycparser FuncDef
        name = getattr(decl, "name", None)
    return name if isinstance(name, str) else None


def _funcs(ps, lookup, types):
    """Each function reachable from a MAIN, with its graph unless it is an
    operator, and the latency of every instance on the way that has one:
    pipelining puts its registers into operators (and raw VHDL), so an
    operator's latency is where they are. The walk does not enter an AUTO_FSM
    call site: the FSM it generates is not the user's hierarchy."""
    funcs = {}
    inst_latency = {}
    seen = set()
    stack = [(main, main) for main in sorted(ps.main_mhz, reverse=True)]
    while stack:
        inst, func = stack.pop()
        logic = ps.FuncLogicLookupTable[func]
        kind = _func_kind(logic, ps)
        if inst in lookup:
            latency = lookup[inst].GET_TOTAL_LATENCY(ps, lookup)
            if latency:
                inst_latency[inst] = latency
        if func not in seen:
            seen.add(func)
            funcs[func] = _func_entry(logic, kind, ps, types)
        if kind == "op" or kind == "vhdl":
            continue
        for local in sorted(logic.submodule_instances, reverse=True):
            if local in getattr(logic, "sub_inst_to_auto_fsm_key", {}):
                callee = logic.submodule_instances[local]
                child = inst + LOGIC.SUBMODULE_MARKER + local
                if callee not in funcs:
                    seen.add(callee)
                    funcs[callee] = _func_entry(
                        ps.FuncLogicLookupTable[callee], "fsm", ps, types
                    )
                if child in lookup:
                    latency = lookup[child].GET_TOTAL_LATENCY(ps, lookup)
                    if latency:
                        inst_latency[child] = latency
                continue
            stack.append(
                (
                    inst + LOGIC.SUBMODULE_MARKER + local,
                    logic.submodule_instances[local],
                )
            )
    return funcs, inst_latency


def _func_entry(logic, kind, ps, types):
    entry = {"kind": kind}
    if logic.delay is not None:
        entry["delay_ns"] = round(logic.delay / SYN.DELAY_UNIT_MULT, 4)
        if getattr(logic, "delay_is_estimated", False):
            entry["delay_estimated"] = True
    # Wiring call sites: @wires functions (casts among them) and operators that
    # are only wiring. A user's own function with no logic stays a block of its
    # hierarchy (one that only routes fields, say).
    if kind == "wires":
        entry["wiring"] = "@wires"
    elif kind == "op":
        wiring = _wiring_reason(logic, ps)
        if wiring is not None:
            entry["wiring"] = wiring
        return entry
    src, line = _src_loc(logic)
    entry["file"] = src
    entry["line"] = line
    entry["def"] = _def_name(logic)
    entry["inputs"] = [
        [p, types.ref(logic.wire_to_c_type.get(p))] for p in logic.inputs
    ]
    entry["outputs"] = [
        [p, types.ref(logic.wire_to_c_type.get(p))] for p in logic.outputs
    ]
    if logic.mcp_tuples:
        entry["mcp"] = True
    if logic.state_regs:
        entry["regs"] = sorted(logic.state_regs)
    if kind in ("vhdl", "fsm"):
        return entry
    entry["graph"] = _graph(logic, ps, types)
    offsets = _offsets(logic, ps)
    if offsets is not None:
        entry["offsets"] = offsets
    return entry


def _offsets(logic, ps):
    """{local instance: [start_ns, end_ns]} of a stateless function with every
    submodule delay known, from the compiler's own zero-added-clocks pipeline
    map -- the functions SYN.ADD_PATH_DELAY_TO_LOOKUP can pipeline -- else None."""
    if logic.state_regs or logic.feedback_vars:
        return None
    if not logic.submodule_instances or logic.vhdl_module_text is not None:
        return None
    if logic.delay is None or logic.delay <= 0:
        return None
    if logic.func_name not in ps.FuncToInstances:
        return None
    if not AUTO_PIPELINE.FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL(
        logic.func_name, ps
    ):
        return None
    for sub_func in logic.submodule_instances.values():
        if ps.FuncLogicLookupTable[sub_func].delay is None:
            return None
    inst = sorted(ps.FuncToInstances[logic.func_name])[0]
    pmap = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_PIPELINE_MAP(inst, logic, ps)
    offsets = {}
    for sub_inst, start in pmap.zero_clk_submodule_start_offset.items():
        local = LOGIC.LEAF_NAME(sub_inst)
        end = pmap.zero_clk_submodule_end_offset.get(sub_inst, start)
        offsets[local] = [
            round(start / SYN.DELAY_UNIT_MULT, 4),
            round(end / SYN.DELAY_UNIT_MULT, 4),
        ]
    return offsets


def _display_local(local):
    """A call site's local instance name without its source-origin suffix:
    add1[top_py_l14_c17_ec24] -> add1."""
    i = local.find("[")
    return local[:i] if i > 0 else local


def _graph(logic, ps, types):
    """The function as nodes (inputs, outputs, submodule call sites, register
    current/next values, global wire read/write stubs, constants, the clock
    enable) and edges [source node index, its port, driven node index, its
    port, type, names, fb] between their ports. An edge follows wire_drives
    through plain wires (variables and their aliases) from a driving endpoint
    to a driven one, as PipelineMap.write_png did; it carries the driving
    wire's type, the variables on the way (the driving one first) and fb when
    it passes through a Feedback variable."""
    subs = logic.submodule_instances
    inputs = set(logic.inputs)
    outputs = set(logic.outputs)
    regs = logic.state_regs
    reads = logic.read_only_global_wires
    writes = logic.write_only_global_wires
    readback_of = {
        rb: var for var, rb in getattr(logic, "readback_global_wires", {}).items()
    }
    drives = logic.wire_drives
    marker = LOGIC.SUBMODULE_MARKER

    def sub_port(wire):
        i = wire.find(marker)
        while i > 0:
            if wire[:i] in subs:
                return "s:" + wire[:i], wire[i + len(marker) :]
            i = wire.find(marker, i + 1)
        return None

    def source(wire):
        if wire in inputs:
            return "i:" + wire, ""
        if wire in regs:
            return "rq:" + wire, ""
        if wire in readback_of:
            return "gr:" + readback_of[wire], ""
        if wire in reads:
            return "gr:" + wire, ""
        if wire == LOGIC.CLOCK_ENABLE_NAME:
            return "ce", ""
        if LOGIC.WIRE_IS_CONSTANT(wire):
            return "c:" + wire, ""
        return sub_port(wire)

    def sink(wire):
        if wire in outputs:
            return "o:" + wire, ""
        if wire in regs:
            return "rd:" + wire, ""
        if wire in writes:
            return "gw:" + wire, ""
        return sub_port(wire)

    def var_of(wire):
        orig = logic.alias_to_orig_var_name.get(wire, wire)
        return orig if orig in logic.variable_names else None

    # wire -> ((sink id, sink port), names, fb) reached through plain wires;
    # names are the variables after the wire itself on the way
    memo = {}

    def reach(start):
        stack = [(start, False)]
        active = set()
        while stack:
            wire, expanded = stack.pop()
            if wire in memo:
                continue
            kids = sorted(drives.get(wire, ()))
            if not expanded:
                if wire in active:
                    continue
                active.add(wire)
                stack.append((wire, True))
                for kid in kids:
                    if sink(kid) is None and kid not in memo and kid not in active:
                        stack.append((kid, False))
                continue
            own = var_of(wire) if wire != start else None
            fb = wire in logic.feedback_vars or (
                logic.alias_to_orig_var_name.get(wire) in logic.feedback_vars
            )
            found = {}
            for kid in kids:
                end = sink(kid)
                items = [(end, (), False)] if end is not None else memo.get(kid, ())
                for item_end, item_names, item_fb in items:
                    if item_end not in found:
                        names = item_names
                        if own is not None and own not in names:
                            names = (own,) + names
                        found[item_end] = (names, fb or item_fb)
            memo[wire] = tuple(
                (end, names, f) for end, (names, f) in sorted(found.items())
            )
            active.discard(wire)
        return memo[start]

    nodes = {}

    def add_node(node_id, **info):
        if node_id not in nodes:
            nodes[node_id] = info

    for p in logic.inputs:
        add_node("i:" + p, kind="in", name=p, t=logic.wire_to_c_type.get(p))
    for p in logic.outputs:
        add_node("o:" + p, kind="out", name=p, t=logic.wire_to_c_type.get(p))
    origins = getattr(logic, "submodule_instance_to_source_origins", {})
    for local in sorted(subs):
        callee = subs[local]
        info = {"kind": "sub", "name": _display_local(local), "callee": callee}
        locs = origins.get(local)
        if locs:
            first = min(locs, key=lambda t: tuple(str(v) for v in t))
            info["src"] = [first[0], first[1]]
        ap_key = getattr(logic, "sub_inst_to_auto_pipeline_key", {}).get(local)
        if ap_key is not None:
            info["auto_pipeline"] = ap_key
        fsm_key = getattr(logic, "sub_inst_to_auto_fsm_key", {}).get(local)
        if fsm_key is not None:
            info["auto_fsm"] = fsm_key
        add_node("s:" + local, **info)

    edges = set()
    for wire in sorted(drives):
        start = source(wire)
        if start is None:
            continue
        c_type = logic.wire_to_c_type.get(wire)
        own = var_of(wire)
        for (end, end_port), names, fb in reach(wire):
            if own is not None and own not in names:
                names = (own,) + names
            edges.add((start[0], start[1], end, end_port, c_type, names, fb))

    for src_id, _sp, dst_id, _dp, _t, _n, _f in edges:
        for node_id in (src_id, dst_id):
            kind, _, name = node_id.partition(":")
            if node_id == "ce":
                add_node("ce", kind="ce", name=LOGIC.CLOCK_ENABLE_NAME)
            elif kind in ("rq", "rd"):
                add_node(
                    node_id,
                    kind="reg" if kind == "rq" else "reg_next",
                    name=name,
                    t=logic.wire_to_c_type.get(name),
                )
            elif kind == "gr":
                add_node(node_id, kind="wire_read", name=name)
            elif kind == "gw":
                add_node(node_id, kind="wire_write", name=name)
            elif kind == "c":
                add_node(
                    node_id,
                    kind="const",
                    name=LOGIC.GET_VAL_STR_FROM_CONST_WIRE(name, logic, ps),
                )
    for node in nodes.values():
        if "t" in node:
            node["t"] = types.ref(node["t"])
    # Edges name their nodes by index: operator call sites have long names
    order = sorted(nodes)
    index = {node_id: i for i, node_id in enumerate(order)}
    return {
        "nodes": [dict(nodes[node_id], id=node_id) for node_id in order],
        "edges": [
            [index[s], sp, index[d], dp, types.ref(c_type), list(names), 1 if f else 0]
            for s, sp, d, dp, c_type, names, f in sorted(
                edges, key=lambda t: tuple("" if v is None else str(v) for v in t)
            )
        ],
    }


def _files(ps, src_file, mains):
    """Each design file: library/generated/design, the files it imports and its
    MAINs. Pypeline files come from file_to_module_prefix and their import
    edges from pypeline_file_imports (an import through a file with no hardware
    of its own counts as importing what it imports); a C design is the files
    its MAINs are defined in."""
    top = os.path.abspath(src_file)
    paths = set(getattr(ps, "file_to_module_prefix", {}))
    paths.add(top)
    for entry in mains.values():
        if entry["file"]:
            paths.add(entry["file"])
    imports = {}
    for importer, imported in getattr(ps, "pypeline_file_imports", ()):
        imports.setdefault(importer, set()).add(imported)

    def reached(path):
        # Files with hardware imported by path, through hardware-less files
        out, stack, seen = set(), sorted(imports.get(path, ())), {path}
        while stack:
            nxt = stack.pop()
            if nxt in seen:
                continue
            seen.add(nxt)
            if nxt in paths:
                out.add(nxt)
            else:
                stack.extend(sorted(imports.get(nxt, ())))
        return out

    files = {}
    for path in sorted(paths):
        if not os.path.isfile(path):
            kind = "generated"
        elif _is_library_file(path):
            kind = "library"
        else:
            kind = "design"
        files[path] = {
            "kind": kind,
            "top": path == top,
            "imports": sorted(reached(path)),
            "mains": sorted(m for m, e in mains.items() if e["file"] == path),
        }
    return files
