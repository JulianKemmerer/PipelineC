# pyright: reportInvalidTypeForm=none
"""`interface_func` -- write the feedforward direction, get the reverse wired.

A function whose annotations use whole `@interface` types is an *interface
function*: its body wires only the feedforward direction between submodule calls,
and `make_hw_func_from_interface_func` generates the ordinary `(hw_func,
struct_t)` pair that threads the reverse direction through `Feedback[T]`.

No decorator is needed -- a whole interface is not a valid hardware type, so
annotating with one is unambiguous. Instantiation stays explicit, so the boundary
where real hardware enters a design is always visible.

Port shape of the generated function (identical to what a hand-written module
declares, which is why the two compose):

    args   = each param (its feedforward half, or a plain non-interface value)
             + one feedback half per *output* port, named by that port
    return = one feedforward half per *output* port, named by that port
             + one feedback half per *input* port, named by that param

Wiring rule (the whole of it): calls are emitted in source order, and an edge
needs a `Feedback[T]` iff the value's source is emitted *after* the destination
that consumes it. That is direction-agnostic -- it inserts a feedback on a
reverse edge (ordinary backpressure) and equally on a feedforward edge (a loop
where a later call feeds an earlier one).

Call sites bind like ordinary Python (`_bind_call_args`): positional args fill
the callee's caller-visible (feedforward) params left-to-right, keyword args bind
by name, the two may be mixed. The reverse halves of the callee's output ports
are synthesized here and are never passed by hand, so naming one is an error --
as are an unknown name, a name given twice, or a missing feedforward arg.

Mechanism: the pass analyzes the AST and *generates real source*, exec'd into a
synthetic module registered in `sys.modules` + `linecache`, so native simulation
and PY_TO_LOGIC elaboration consume one artifact and cannot disagree. Python 3.8
compatible (no `ast.unparse`).
"""

import ast
import hashlib
import inspect
import linecache
import sys
import textwrap
import types
import warnings as _warnings

from pypeline import (
    Feedback,
    NamedTuple,
    _array_elem_ctype,
    _array_len,
    _enclosing_factory_param_suffix,
    hw_func,
    struct,
)

from interface.interface import (
    FB,
    FWD,
    InterfaceError,
    interface_of,
    interface_role,
    is_interface,
)

IN = "in"
OUT = "out"
_DEFAULT_OUT = "out_port_if"  # port name given to a bare (unbundled) interface return
# NOTE: must be a legal VHDL identifier -- "out" is a VHDL reserved word.
_MAX_SUFFIX_LEN = 48  # beyond this a factory-parameter suffix is hashed, see _factory_suffix


class InterfaceFuncError(InterfaceError):
    """Raised for an interface function body the pass cannot wire."""


# ─────────────────────────────────────────────────────────────────────────────
# Port introspection -- structural, no name conventions
# ─────────────────────────────────────────────────────────────────────────────
class _Port:
    """One port: an interface, a direction, and (for an array port) a length.

    `elem_*_t` are the per-element halves; `fwd_t`/`fb_t` are what the port
    actually declares -- the same types for a scalar port, arrays of them for an
    array port.
    """

    __slots__ = ("name", "iface", "direction", "n", "elem_fwd_t", "elem_fb_t",
                 "fwd_t", "fb_t")

    def __init__(self, name, iface, direction, n=None):
        self.name = name
        self.iface = iface
        self.direction = direction
        self.n = n
        self.elem_fwd_t = iface.fwd_t
        self.elem_fb_t = iface.fb_t
        self.fwd_t = self.elem_fwd_t
        self.fb_t = self.elem_fb_t
        if n is not None:
            if self.fwd_t is not None:
                self.fwd_t = self.fwd_t[n]
            if self.fb_t is not None:
                self.fb_t = self.fb_t[n]

    def indices(self):
        """The element indices to wire: `[None]` for a scalar port."""
        return [None] if self.n is None else list(range(self.n))

    def __repr__(self):
        arr = "" if self.n is None else f"[{self.n}]"
        return f"<port {self.name}{arr} {self.direction}>"


_plain_shape_cache = {}


def _plain_shape_of(paired_t):
    """A plain struct with the identical fields as an @interface's derived
    `.fwd_t`/`.fb_t` (or an element thereof), but without the
    `_pypeline_interface_role` marker that makes the paired type -- safe to
    use as `Feedback[T]`/`Wire[T]`/a plain local's type, since none of
    `paired_t`'s own fields can themselves be an interface or `Feedback[...]`
    (interface.py's `_reject_nested` already guarantees that when `.fwd_t`/
    `.fb_t` were derived). Memoized per paired type so repeated calls reuse
    the same class object (canonical-name determinism)."""
    if paired_t is None:
        return None
    cached = _plain_shape_cache.get(paired_t)
    if cached is not None:
        return cached
    fields = [(n, paired_t.__annotations__[n]) for n in paired_t._fields]
    plain_t = struct(NamedTuple(f"{paired_t.__name__}_plain", fields))
    _plain_shape_cache[paired_t] = plain_t
    return plain_t


def is_interface_func(f):
    """True if any annotation of `f` is a whole `@interface`."""
    fn = inspect.unwrap(f) if callable(f) else f
    anns = getattr(fn, "__annotations__", {}) or {}
    return any(is_interface(t) for t in anns.values())


def _qn(fn):
    return getattr(fn, "__qualname__", repr(fn))


def _half_of(ann):
    """`(interface, role, n)` for an annotation that is one half of a port --
    a derived struct, or an array of one. `(None, None, None)` otherwise."""
    iface, role = interface_of(ann), interface_role(ann)
    if iface is not None:
        return iface, role, None
    elem = _array_elem_ctype(ann)
    if elem is not None:
        iface, role = interface_of(elem), interface_role(elem)
        if iface is not None:
            return iface, role, _array_len(ann)
    return None, None, None


def _legacy_hint(name, candidates):
    """Diagnostic only -- never consulted for wiring. Names a leftover scalar
    handshake signal so a half-migrated module says what to fix."""
    for guess in (f"{name}_ready", f"ready_for_{name}", f"{name}_rdy"):
        if guess in candidates:
            return (
                f" (found {guess!r} -- legacy scalar handshake ports are not "
                "supported; both halves of a port share the port's name)"
            )
    return ""


def callee_ports(fn):
    """Port map of an *instanced* module: {name: _Port}.

    A port's two halves share a name across args and return fields; whichever
    side holds the feedforward half sets the direction. Purely structural -- no
    prefix/suffix convention is consulted.
    """
    fn = inspect.unwrap(fn)
    anns = getattr(fn, "__annotations__", {}) or {}
    params = list(inspect.signature(fn).parameters)
    ret_t = anns.get("return")
    ret_fields = (
        list(ret_t._fields) if (ret_t is not None and hasattr(ret_t, "_fields")) else []
    )
    ret_anns = getattr(ret_t, "__annotations__", {}) if ret_fields else {}

    sides = {}
    for p in params:
        iface, role, n = _half_of(anns.get(p))
        if iface is not None:
            sides.setdefault(p, {})["arg"] = (iface, role, n)
    for f in ret_fields:
        iface, role, n = _half_of(ret_anns.get(f))
        if iface is not None:
            sides.setdefault(f, {})["ret"] = (iface, role, n)

    ports = {}
    for name, halves in sides.items():
        arg_iface, arg_role, arg_n = halves.get("arg", (None, None, None))
        ret_iface, ret_role, ret_n = halves.get("ret", (None, None, None))
        if arg_role == FWD and ret_role == FWD:
            raise InterfaceFuncError(
                f"port {name!r} of {_qn(fn)!r} has a feedforward half on both the "
                "argument and the return side; its direction is ambiguous"
            )
        if arg_iface is not None and ret_iface is not None and arg_iface is not ret_iface:
            raise InterfaceFuncError(
                f"port {name!r} of {_qn(fn)!r} mixes two different interfaces"
            )
        if arg_n is not None and ret_n is not None and arg_n != ret_n:
            raise InterfaceFuncError(
                f"port {name!r} of {_qn(fn)!r} declares {arg_n} elements on the "
                f"argument side but {ret_n} on the return side"
            )
        iface = arg_iface if arg_iface is not None else ret_iface
        n = arg_n if arg_n is not None else ret_n
        direction = IN if arg_role == FWD else OUT if ret_role == FWD else (
            IN if ret_role == FB else OUT
        )

        # Both halves must be declared, or the missing one has nothing driving
        # it. Catching it here names the port; letting it through produces an
        # unrecognizable error much later (or, worse, a silent misconnection).
        port = _Port(name, iface, direction, n)
        have_arg, have_ret = "arg" in halves, "ret" in halves
        fwd_side, fb_side = ("arg", "ret") if direction == IN else ("ret", "arg")
        for role_name, side, needed in (
            ("feedforward", fwd_side, port.elem_fwd_t),
            ("reverse", fb_side, port.elem_fb_t),
        ):
            if needed is None:
                continue  # this interface has no fields in that direction
            if (side == "arg" and have_arg) or (side == "ret" and have_ret):
                continue
            where = "argument" if side == "arg" else "return field"
            others = set(ret_fields) if side == "ret" else set(params)
            raise InterfaceFuncError(
                f"port {name!r} of {_qn(fn)!r} declares only its "
                f"{'reverse' if role_name == 'feedforward' else 'feedforward'} "
                f"half; add a {where} named {name!r} carrying its {role_name} "
                f"half{_legacy_hint(name, others)}"
            )
        if direction == IN and n is not None:
            raise InterfaceFuncError(
                f"input port {name!r} of {_qn(fn)!r} is an array of interfaces; "
                "array ports are supported on outputs (fan-out) only"
            )
        if not name.endswith("_if"):
            _warnings.warn(
                f"port {name!r} of {_qn(fn)!r} does not end in '_if' -- by "
                "convention, an arg/return-field name that pairs a port's two "
                "halves should (e.g. 'stream_in_if')",
                stacklevel=2,
            )
        ports[name] = port
    return ports, params, ret_fields


# ─────────────────────────────────────────────────────────────────────────────
# Source-generation substrate
# ─────────────────────────────────────────────────────────────────────────────
class _Emitter:
    """Names everything the generated module introduces.

    Every name carries a `tag` that is a pure function of the interface
    function's identity. Without it, two generated modules would both define
    `if_t1`, `if_t2`, ... -- and since a callee's own module globals rank *below*
    the calling module's during elaboration, a generated module calling another
    generated module would resolve the caller's same-numbered type instead of its
    own (silently, as a wrong port type). Interface functions nest in real
    designs, so the names have to be globally distinct.
    """

    def __init__(self, base_ns, tag):
        self.ns = dict(base_ns)
        self.ns.update(
            {
                "hw_func": hw_func,
                "struct": struct,
                "NamedTuple": NamedTuple,
                "Feedback": Feedback,
            }
        )
        self.tag = tag
        self._inj_by_id = {}
        self._n = 0

    def inj(self, obj, hint="T"):
        key = id(obj)
        if key in self._inj_by_id:
            return self._inj_by_id[key]
        self._inj_by_id[key] = name = self.gensym(hint)
        self.ns[name] = obj
        return name

    def gensym(self, hint):
        self._n += 1
        return f"if{self.tag}_{hint}{self._n}"


def _func_eval_ns(orig):
    ns = dict(getattr(orig, "__globals__", {}))
    if orig.__closure__:
        for name, cell in zip(orig.__code__.co_freevars, orig.__closure__):
            try:
                ns[name] = cell.cell_contents
            except ValueError:
                pass
    return ns


def _parse(orig):
    src = textwrap.dedent(inspect.getsource(orig))
    tree = ast.parse(src)
    fdef = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)), None)
    if fdef is None:
        raise InterfaceFuncError("could not parse interface function source")
    return src, fdef


def _reject_control_flow(fdef):
    for stmt in fdef.body:
        if isinstance(stmt, (ast.If, ast.For, ast.While, ast.With)):
            raise InterfaceFuncError(
                "conditional/loop control flow is not allowed in an interface "
                "function; route interfaces through an explicit mux/demux/select "
                f"module instead (at line {stmt.lineno})"
            )
    for node in ast.walk(fdef):
        if isinstance(node, ast.IfExp):
            raise InterfaceFuncError(
                "conditional expression (a if c else b) is not allowed in an "
                f"interface function (at line {node.lineno})"
            )


def _norm(text):
    return "".join(text.split())


def _resolve(node, ns):
    if isinstance(node, ast.Name):
        if node.id not in ns:
            raise InterfaceFuncError(f"unknown callee {node.id!r}")
        return ns[node.id]
    if isinstance(node, ast.Attribute):
        return getattr(_resolve(node.value, ns), node.attr)
    raise InterfaceFuncError("unsupported callee expression")


def _return_leaf_map(expr, src):
    """Map the return value's top-level field names -> source text.

    Only the outermost bundle constructor is destructured: a `return
    ports(a=..., b=...)` yields one entry per keyword. Anything deeper is that
    field's value, opaque -- which is what lets a plain field be an arbitrary
    expression (including a struct constructor of its own)."""
    if isinstance(expr, ast.Call) and expr.keywords:
        return {
            (kw.arg,): _norm(ast.get_source_segment(src, kw.value))
            for kw in expr.keywords
        }
    return {(): _norm(ast.get_source_segment(src, expr))}


def _iface_uses(stmt, iface_vals, iface_attrs):
    """Interface values a plain statement touches (must be empty for it to be
    copied through). Reading a *non-interface* field off a call result -- a
    status flag, a count -- is fine; the interface ports themselves are not."""
    ok_bases = set()
    bad = set()
    for node in ast.walk(stmt):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            v = node.value.id
            if v in iface_vals:
                attrs = iface_attrs.get(v)
                if attrs is None or node.attr in attrs:
                    bad.add(f"{v}.{node.attr}")
                else:
                    ok_bases.add(id(node.value))
    for node in ast.walk(stmt):
        if isinstance(node, ast.Name) and node.id in iface_vals:
            if id(node) not in ok_bases:
                bad.add(node.id)
    return bad


# ─────────────────────────────────────────────────────────────────────────────
# The pass
# ─────────────────────────────────────────────────────────────────────────────
_MEMO = {}


def _factory_suffix(orig):
    """Canonical-name suffix for an interface function defined inside a factory,
    built from that factory's own parameters -- the same rule `@struct` uses.

    Without it, `make_core(a)` and `make_core(b)` generate two different modules
    under one canonical name. The frame walk skips this module's own frames so a
    nested interface function still sees its real factory, not the pass.
    """
    frame = sys._getframe(1)
    while frame is not None and frame.f_code.co_filename == __file__:
        frame = frame.f_back
    if frame is None:
        return ""
    suffix = _enclosing_factory_param_suffix(orig, frame)
    # The generated module's name becomes a directory name during synthesis, so
    # a factory with many parameters (dsp/fir_interp: coeffs, widths, rounding,
    # symmetry, ...) would overflow the filesystem's limit. Hash it -- still a
    # pure function of the factory's inputs, so names stay deterministic.
    if len(suffix) > _MAX_SUFFIX_LEN:
        suffix = "_" + hashlib.sha256(suffix.encode()).hexdigest()[:16]
    return suffix


def _own_output_ports(ret_type):
    """Output ports declared by an interface function's return annotation.

    A return interface whose fields include at least one interface is a *bundle*
    (one port per interface field, plain fields ride along as feedforward); one
    with no interface fields is a single port named `out`.
    """
    if not is_interface(ret_type):
        raise InterfaceFuncError(
            "an interface function must return an @interface (a single port, or a "
            "bundle whose fields are interfaces)"
        )
    iface_fields = [
        f for f in ret_type._fields if is_interface(ret_type.__annotations__[f])
    ]
    if not iface_fields:
        return {_DEFAULT_OUT: _Port(_DEFAULT_OUT, ret_type, OUT)}, False
    plain_fb = [
        f
        for f in ret_type._fields
        if f not in iface_fields
        and interface_of(ret_type.__annotations__[f]) is None
        and getattr(ret_type.__annotations__[f], "__class__", None).__name__
        == "_FeedbackType"
    ]
    if plain_fb:
        raise InterfaceFuncError(
            f"return bundle {ret_type.__name__!r} has both interface fields and "
            f"direct Feedback fields ({plain_fb}); put reverse signals inside an "
            "interface field instead"
        )
    ports = {
        f: _Port(f, ret_type.__annotations__[f], OUT) for f in iface_fields
    }
    return ports, True


def _classify_callee(ports, params, ret_fields):
    """Split a callee's ports into the roles the generated call needs."""
    fwd_params = [p for p in params if not (p in ports and ports[p].direction == OUT)]
    fb_params = [p for p in params if p in ports and ports[p].direction == OUT]
    out_fields = [f for f in ret_fields if f in ports and ports[f].direction == OUT]
    return fwd_params, fb_params, out_fields


def _bind_call_args(call, fwd_params, fb_params, ref, src, lineno):
    """Bind a callee call's positional + keyword args to the callee's
    feedforward parameter names, mirroring Python's own call semantics.

    Only `fwd_params` are caller-suppliable: the reverse (feedback) halves of a
    callee's output ports (`fb_params`) are synthesized by this pass, so naming
    one is an error. Returns `{param_name: normalized_source_text}` covering
    every `fwd_param` exactly once -- which is all the rest of the pass needs,
    since it re-emits the call positionally in callee-declaration order, keyed by
    name (so the caller's arg order and positional/keyword mix are immaterial
    downstream).
    """

    def err(msg):
        raise InterfaceFuncError(f"call to {ref} {msg} (at line {lineno})")

    pos = call.args
    if any(isinstance(n, ast.Starred) for n in pos):
        err("uses *args unpacking, unsupported for an interface-function call")
    if len(pos) > len(fwd_params):
        err(
            f"passes {len(pos)} positional feedforward args but the module takes "
            f"{len(fwd_params)}"
        )
    bound = {p: _norm(ast.get_source_segment(src, n)) for p, n in zip(fwd_params, pos)}
    filled_positionally = set(fwd_params[: len(pos)])
    fb = set(fb_params)
    for kw in call.keywords:
        name = kw.arg
        if name is None:
            err("uses **kwargs unpacking, unsupported for an interface-function call")
        if name in filled_positionally:
            err(f"got multiple values for argument {name!r}")
        if name not in fwd_params:
            if name in fb:
                err(
                    f"passes {name!r} by keyword, but it is a reverse (feedback) "
                    "port supplied automatically -- drop it"
                )
            err(f"got an unexpected keyword argument {name!r}")
        bound[name] = _norm(ast.get_source_segment(src, kw.value))
    missing = [p for p in fwd_params if p not in bound]
    if missing:
        err(f"is missing feedforward argument(s) {missing}")
    return bound


def make_hw_func_from_interface_func(f):
    """Compile an interface function into an ordinary `(hw_func, struct_t)` pair.

    Memoized on the function so repeated instantiation yields one identical
    definition (one hardware definition, many call-site instances).
    """
    orig = inspect.unwrap(f)
    if not is_interface_func(orig):
        raise InterfaceFuncError(
            f"{_qn(orig)!r} is not an interface function (no @interface annotations)"
        )
    if orig in _MEMO:
        return _MEMO[orig]
    suffix = _factory_suffix(orig)

    eval_ns = _func_eval_ns(orig)
    src, fdef = _parse(orig)
    _reject_control_flow(fdef)
    anns = orig.__annotations__
    param_names = [a.arg for a in fdef.args.args]
    if "return" not in anns:
        raise InterfaceFuncError(f"interface function {_qn(orig)!r} needs a return annotation")

    # ── our own ports ──
    in_ports, plain_params = {}, []
    for p in param_names:
        t = anns.get(p)
        if is_interface(t):
            in_ports[p] = _Port(p, t, IN)
        else:
            plain_params.append(p)
    out_ports, ret_is_bundle = _own_output_ports(anns["return"])
    for name in out_ports:
        if name in in_ports or name in plain_params:
            raise InterfaceFuncError(
                f"output port {name!r} collides with a parameter of the same name"
            )

    # Deterministic per-function tag: identity only, never an address or a
    # counter, so re-running a design produces byte-identical generated source.
    tag = hashlib.sha256(
        f"{getattr(orig, '__module__', '')}.{_qn(orig)}{suffix}".encode()
    ).hexdigest()[:8]
    em = _Emitter(eval_ns, tag)
    iface_vals = set(in_ports)  # names holding interface values
    # per interface value, which of its attributes are interface ports; None
    # means the value is wholly an interface (a parameter)
    iface_attrs = {p: None for p in in_ports}

    # ── walk the body: calls, plain statements, the return ──
    if not (fdef.body and isinstance(fdef.body[-1], ast.Return)):
        raise InterfaceFuncError(f"interface function {_qn(orig)!r} must end in a return")
    ret_node = fdef.body[-1]

    calls, body_plan = [], []
    for stmt in fdef.body[:-1]:
        is_call_assign = (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Call)
        )
        callobj = None
        if is_call_assign:
            try:
                callobj = _resolve(stmt.value.func, eval_ns)
            except InterfaceFuncError:
                callobj = None
        # A nested interface function is compiled to its instance; that instance
        # is a different object from the name written in the source, so it must be
        # injected rather than referenced by name.
        was_iface_func = callobj is not None and is_interface_func(callobj)
        if was_iface_func:
            callobj, _ = make_hw_func_from_interface_func(callobj)
        cports = {}
        if callobj is not None:
            try:
                cports, cparams, cret = callee_ports(callobj)
            except InterfaceFuncError:
                raise
            except Exception:
                cports = {}
        if is_call_assign and cports:
            var = stmt.targets[0].id
            ref = (
                em.inj(callobj, "callee")
                if was_iface_func
                else ast.get_source_segment(src, stmt.value.func)
            )
            fwd_params, fb_params, out_fields = _classify_callee(cports, cparams, cret)
            calls.append(
                {
                    "var": var,
                    "ref": ref,
                    "ports": cports,
                    "params": cparams,
                    "fwd_params": fwd_params,
                    "fb_params": fb_params,
                    "out_fields": out_fields,
                    "args": _bind_call_args(
                        stmt.value, fwd_params, fb_params, ref, src, stmt.lineno
                    ),
                    "lineno": stmt.lineno,
                }
            )
            iface_vals.add(var)
            iface_attrs[var] = set(cports)
            body_plan.append(("call", len(calls) - 1))
        else:
            # a plain statement: legal as long as it touches no interface value
            clash = _iface_uses(stmt, iface_vals, iface_attrs)
            if clash:
                raise InterfaceFuncError(
                    f"statement at line {stmt.lineno} uses interface value(s) "
                    f"{sorted(clash)} outside of a module call; interface values may "
                    "only be produced by calls and consumed as call arguments"
                )
            body_plan.append(("plain", _norm_stmt(src, stmt)))

    # ── dataflow: producers and consumers of each feedforward value ──
    # An array output port contributes one entry per element, so each fork of a
    # fan-out is wired (and back-pressured) independently.
    def _elem_text(var, field, k):
        return _norm(f"{var}.{field}" if k is None else f"{var}.{field}[{k}]")

    producer = {}  # text -> ("call", i, portname, index) | ("param", name)
    for name in in_ports:
        producer[name] = ("param", name)
    for i, c in enumerate(calls):
        for f in c["out_fields"]:
            for k in c["ports"][f].indices():
                producer[_elem_text(c["var"], f, k)] = ("call", i, f, k)

    consumer = {}  # text -> ("call", i, portname) | ("return", outport)
    for i, c in enumerate(calls):
        for p, text in c["args"].items():
            if p in c["ports"] and c["ports"][p].direction == IN:
                if text in consumer:
                    raise InterfaceFuncError(
                        f"interface value `{text}` is consumed more than once; each "
                        "interface is point-to-point (fan-out needs an explicit "
                        "duplicator module)"
                    )
                consumer[text] = ("call", i, p)

    ret_leaves = _return_leaf_map(ret_node.value, src)
    plain_ret_fields = (
        [f for f in anns["return"]._fields if f not in out_ports] if ret_is_bundle else []
    )
    out_text = {}  # out port -> producing text
    plain_text = {}  # plain (non-interface) return field -> producing text
    for path, text in ret_leaves.items():
        name = path[0] if path else _DEFAULT_OUT
        if name in plain_ret_fields:
            plain_text[name] = text
            continue
        if name not in out_ports:
            continue
        out_text[name] = text
        if text in consumer:
            raise InterfaceFuncError(
                f"interface value `{text}` is consumed more than once"
            )
        consumer[text] = ("return", name)
    missing = set(out_ports) - set(out_text)
    if missing:
        raise InterfaceFuncError(
            f"output port(s) {sorted(missing)} are never assigned in the return"
        )
    missing_plain = set(plain_ret_fields) - set(plain_text)
    if missing_plain:
        raise InterfaceFuncError(
            f"plain return field(s) {sorted(missing_plain)} are never assigned in "
            "the return"
        )

    for i, c in enumerate(calls):
        for f in c["out_fields"]:
            for k in c["ports"][f].indices():
                t = _elem_text(c["var"], f, k)
                if t not in consumer:
                    raise InterfaceFuncError(
                        f"interface produced by `{t}` is never consumed (its reverse "
                        "direction would be undriven)"
                    )
    for name in in_ports:
        cons = consumer.get(name)
        if cons is None or cons[0] != "call":
            raise InterfaceFuncError(
                f"input port {name!r} is not consumed by any call; passing an input "
                "straight through to an output is not supported"
            )

    # ── allocate Feedback for every backward edge (either direction) ──
    fb_fwd, fb_rev = {}, {}
    for text, cons in consumer.items():
        prod = producer.get(text)
        if prod is None or prod[0] != "call":
            continue
        j = prod[1]
        if cons[0] == "call":
            i = cons[1]
            if j > i:  # feedforward source emitted later -> loop
                fb_fwd[text] = em.gensym("fwd")
            else:  # reverse value produced later than its consumer
                fb_rev[text] = em.gensym("rev")

    # ── emit ──
    out_struct = em.gensym(f"{orig.__name__}{suffix}_t")
    fields = []
    for name, port in out_ports.items():
        if port.fwd_t is not None:
            fields.append((name, em.inj(port.fwd_t, "t")))
    if ret_is_bundle:
        rt = anns["return"]
        for fname in rt._fields:
            if not is_interface(rt.__annotations__[fname]):
                fields.append((fname, em.inj(rt.__annotations__[fname], "t")))
    for name, port in in_ports.items():
        if port.fb_t is not None:
            fields.append((name, em.inj(port.fb_t, "t")))

    sig = []
    for p in param_names:
        if p in in_ports:
            if in_ports[p].fwd_t is not None:
                sig.append(f"{p}: {em.inj(in_ports[p].fwd_t, 't')}")
        else:
            sig.append(f"{p}: {em.inj(anns[p], 't')}")
    for name, port in out_ports.items():
        if port.fb_t is not None:
            sig.append(f"{name}: {em.inj(port.fb_t, 't')}")

    fname_ = em.gensym(f"{orig.__name__}{suffix}_inst")
    L = ["@struct", f"class {out_struct}(NamedTuple):"]
    for n, t in fields:
        L.append(f"    {n}: {t}")
    L.append("")
    L.append("@hw_func")
    L.append(f"def {fname_}({', '.join(sig)}) -> {out_struct}:")

    def _ctor(paired_t_name, fields, value_expr):
        """Construct the real paired type inline, field by field, from a
        plain-shape value -- the paired type itself is never a Feedback[T]'s
        (or any other local's) declared type, only ever this inline expression
        at the point it meets a real port (PY_TO_LOGIC.py's _elab_ann_assign/
        _discover_global_wires checks)."""
        args = ", ".join(f"{fn}={value_expr}.{fn}" for fn in fields)
        return f"{paired_t_name}({args})"

    body = []
    fb_fwd_paired = {}  # text -> (paired_t injected name, paired_t fields)
    for text, v in fb_fwd.items():
        i = consumer[text][1]
        p = consumer[text][2]
        port = calls[i]["ports"][p]
        if port.n is not None:
            raise InterfaceFuncError(
                f"a feedforward loop through an array port ({p!r}) is not "
                "supported -- array ports are only wired for reverse (fan-out) "
                "feedback today"
            )
        paired_t = port.fwd_t
        plain_name = em.inj(_plain_shape_of(paired_t), "t")
        fb_fwd_paired[text] = (em.inj(paired_t, "t"), paired_t._fields)
        body.append(f"{v}: Feedback[{plain_name}]")
    fb_rev_paired = {}  # text -> (paired_t injected name, paired_t fields)
    for text, v in fb_rev.items():
        _, j, f_, k = producer[text]
        # one element of an array port carries the element's half, not the array's
        port = calls[j]["ports"][f_]
        plain_name = em.inj(_plain_shape_of(port.elem_fb_t), "t")
        fb_rev_paired[text] = (em.inj(port.elem_fb_t, "t"), port.elem_fb_t._fields)
        body.append(f"{v}: Feedback[{plain_name}]")

    def fwd_value(text):
        if text in fb_fwd:
            paired_name, fields = fb_fwd_paired[text]
            return _ctor(paired_name, fields, fb_fwd[text])
        return text

    def fb_elem_value(call_idx, portname, k):
        """The reverse value driving one element of call `call_idx`'s output
        port `portname`."""
        text = _elem_text(calls[call_idx]["var"], portname, k)
        cons = consumer[text]
        if cons[0] == "return":
            return cons[1]  # our own feedback arg, available at entry
        if text in fb_rev:
            paired_name, fields = fb_rev_paired[text]
            return _ctor(paired_name, fields, fb_rev[text])
        return _norm(f"{calls[cons[1]]['var']}.{cons[2]}")

    for kind, payload in body_plan:
        if kind == "plain":
            body.append(payload)
            continue
        c = calls[payload]
        pos = []
        for p in c["params"]:
            if p not in c["fb_params"]:
                pos.append(fwd_value(c["args"][p]))
                continue
            port = c["ports"][p]
            if port.n is None:
                pos.append(fb_elem_value(payload, p, None))
                continue
            # an array port's reverse half is assembled element-by-element,
            # since each fork is back-pressured by a different module -- built
            # as an inline list literal directly in the call argument (no local
            # variable of the array-of-.fb_t type is ever declared, since a
            # plain local may never be declared with an @interface's .fwd_t/
            # .fb_t type -- see PY_TO_LOGIC.py's _elab_ann_assign check).
            elems = [fb_elem_value(payload, p, k) for k in range(port.n)]
            pos.append(f"[{', '.join(elems)}]")
        body.append(f"{c['var']} = {c['ref']}({', '.join(pos)})")

    # Drive each Feedback var from the plain-shape fields of the real paired
    # value that produced it (field-by-field -- the two are structurally
    # identical but distinct ctypes, so a whole-value assignment would not
    # type-check).
    for text, v in fb_fwd.items():
        _, fields = fb_fwd_paired[text]
        for fn in fields:
            body.append(f"{v}.{fn} = {text}.{fn}")
    for text, v in fb_rev.items():
        i, p = consumer[text][1], consumer[text][2]
        _, fields = fb_rev_paired[text]
        for fn in fields:
            body.append(f"{v}.{fn} = {calls[i]['var']}.{p}.{fn}")

    ovar = em.gensym("o")
    body.append(f"{ovar}: {out_struct}")
    for name, port in out_ports.items():
        if port.fwd_t is not None:
            body.append(f"{ovar}.{name} = {out_text[name]}")
    for name, text in plain_text.items():
        body.append(f"{ovar}.{name} = {text}")
    for name in in_ports:
        if in_ports[name].fb_t is None:
            continue
        cons = consumer[name]
        body.append(f"{ovar}.{name} = {calls[cons[1]]['var']}.{cons[2]}")
    body.append(f"return {ovar}")
    for line in body:
        L.append("    " + line)
    L.append("")

    source = "\n".join(L) + "\n"

    modname = f"pypeline_interface_func_gen_{fname_}"
    modfile = f"{modname}.py"
    linecache.cache[modfile] = (len(source), None, source.splitlines(True), modfile)
    mod = types.ModuleType(modname)
    mod.__file__ = modfile
    mod.__dict__.update(em.ns)
    sys.modules[modname] = mod
    try:
        exec(compile(source, modfile, "exec"), mod.__dict__)
    except Exception as e:
        raise InterfaceFuncError(
            f"failed to build interface function {_qn(orig)!r}: {e}\n"
            f"--- generated source ---\n{source}"
        ) from e

    inst = mod.__dict__[fname_]
    inst_t = mod.__dict__[out_struct]
    inst._pypeline_iface_generated = True
    inst.generated_source = source
    _MEMO[orig] = (inst, inst_t)
    return inst, inst_t


def _norm_stmt(src, stmt):
    return ast.get_source_segment(src, stmt)
