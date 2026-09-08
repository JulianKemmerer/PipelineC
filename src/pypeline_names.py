"""Pypeline naming metadata and VHDL presentation, independent of the compiler.

Logical type/operator keys are not VHDL presentation. Keep source descriptions
alongside those keys and translate identifiers only at the emission boundary.
See docs/PY_TO_LOGIC_DESIGN.md#generated-vhdl-names.
"""

from dataclasses import dataclass, replace
from enum import IntEnum
import functools
import hashlib
import inspect
import json
import os
import re

BASE_LIMIT = 192
IDENTIFIER_LIMIT = 240
_ADDRESS = re.compile(r" at 0x[0-9a-fA-F]+")
_WORDS = re.compile(r"[^A-Za-z0-9]+")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def safe(text):
    text = _WORDS.sub("_", str(text)).strip("_") or "v"
    return text if text[0].isalpha() else "v_" + text


def shorten(text, limit=IDENTIFIER_LIMIT, identity=None):
    """Keep whole tokens, with an explicit hash of everything omitted."""
    if len(text) <= limit:
        return text
    role = re.search(
        r"(_[0-9]+CLK_[0-9a-f]+(?:_top)?|_global_to_module_t|_module_to_global_t|_to_slv|_NULL|_top)$",
        text,
    )
    suffix = "_h" + digest(identity or text) + (role[0] if role else "")
    budget = limit - len(suffix)
    prefix = text[: budget + 1].rsplit("_", 1)[0]
    if len(prefix) > budget or not prefix:
        prefix = "generated"
    return prefix + suffix


def stable_key(value, seen=frozenset()):
    """Typed, address-free specialization snapshot (never a readable name).

    Lists and tuples, strings and numbers, and punctuation-bearing strings
    must not alias after identifier sanitization. Recursive graphs are bounded
    by their defining type/symbol, never by the object address used as a guard.
    """
    cls = type(value)
    typename = cls.__module__ + "." + cls.__qualname__
    if id(value) in seen:
        return ("cycle", typename, getattr(value, "__qualname__", ""))
    seen = seen | {id(value)}
    if isinstance(value, IntEnum):
        return ("enum", stable_key(cls, seen), value.name, int(value))
    if value is None or isinstance(value, (bool, int, str)):
        return (typename, value)
    if isinstance(value, float):
        return ("float", value.hex())
    if isinstance(value, type):
        info = getattr(value, "_pypeline_name_info", None)
        if info is not None:
            return ("type", hashlib.sha256(info.identity.encode()).hexdigest())
        elem = getattr(value, "_elem_ctype", None)
        if elem is not None:
            return ("array", value._arr_len, stable_key(elem, seen))
        return (
            "type",
            getattr(value, "_pypeline_ctype_canonical", None)
            or getattr(value, "_ctype_name", None)
            or (value.__module__, value.__qualname__),
        )
    if isinstance(value, (list, tuple)):
        return (typename, tuple(stable_key(v, seen) for v in value))
    if isinstance(value, (dict, set, frozenset)):
        items = (
            [(stable_key(k, seen), stable_key(v, seen)) for k, v in value.items()]
            if isinstance(value, dict)
            else [stable_key(v, seen) for v in value]
        )
        return (typename, tuple(sorted(items, key=repr)))
    if hasattr(value, "inner_ctype"):
        return (typename, stable_key(value.inner_ctype, seen))
    if isinstance(value, functools.partial):
        return (
            "partial",
            stable_key(value.func, seen),
            stable_key(value.args, seen),
            stable_key(value.keywords, seen),
        )
    if callable(value):
        for attr in ("_is_autopipeline_pragma", "_is_autofsm_pragma"):
            if getattr(value, attr, False):
                # Pinned AP depth is deliberately not identity: it changes
                # during the compiler's pin-and-confirm elaboration loop.
                config = (
                    ()
                    if attr == "_is_autopipeline_pragma"
                    else (
                        getattr(value, "max_latency", None),
                        getattr(value, "register_output", True),
                    )
                )
                return (attr, stable_key(value.func, seen), config)
        value = inspect.unwrap(value)
        code = getattr(value, "__code__", None)
        if code is not None:
            cells = []
            for name, cell in zip(code.co_freevars, value.__closure__ or ()):
                try:
                    cells.append((name, stable_key(cell.cell_contents, seen)))
                except ValueError:
                    cells.append((name, "empty_cell"))
            # co_code and constants distinguish same-qualname lambdas/defs;
            # repr(code objects) would introduce addresses and absolute paths.
            return (
                "callable",
                value.__module__,
                value.__qualname__,
                code.co_code.hex(),
                _code_constants(code),
                tuple(cells),
                stable_key(value.__defaults__, seen),
                stable_key(value.__kwdefaults__, seen),
            )
    state = getattr(value, "__dict__", None)
    if state is not None:
        return (typename, stable_key(state, seen))
    return (typename, _ADDRESS.sub("", repr(value)))


def _code_constants(code):
    return tuple(
        ("code", c.co_code.hex(), _code_constants(c))
        if inspect.iscode(c)
        else stable_key(c)
        for c in code.co_consts
    )


def identity(value):
    return json.dumps(stable_key(value), ensure_ascii=True, separators=(",", ":"))


@dataclass(frozen=True)
class NameInfo:
    kind: str
    symbol: str
    module: str = ""
    qualname: str = ""
    source: str = ""
    line: int = 0
    params: tuple = ()
    fields: tuple = ()
    identity: str = ""

    def render(self, limit=None, context=True):
        base = safe(self.symbol)
        if context and self.module:
            base += "_from_" + safe(self.module)
            scopes = self.qualname.split(".<locals>.")[:-1]
            # make_kept_data_bus_t / kept_data_bus_t repeats the symbol.
            scopes = [
                s
                for s in scopes
                if (s[5:] if s.startswith("make_") else s)
                not in (
                    self.symbol,
                    self.symbol[:-2] if self.symbol.endswith("_t") else self.symbol,
                )
            ]
            if scopes:
                base += "_" + "_".join(safe(s) for s in scopes)
        values = self.params or self.fields
        # Scalar settings precede nested types so e.g. n=4 survives deep
        # composition. Ties retain Python declaration order.
        values = sorted(
            values,
            key=lambda p: (1 if p[1].kind == "scalar_type" else 2)
            if isinstance(p[1], NameInfo)
            else 0,
        )
        rendered = [
            v.render(context=False) if isinstance(v, NameInfo) else v for _, v in values
        ]

        def compose():
            return base + "".join(
                "_" + safe(k) + "_" + v for (k, _), v in zip(values, rendered)
            )

        full = compose()
        if limit is None or len(full) <= limit:
            return full
        # Reduce the largest nested descriptions first; each child keeps
        # its own scalar parameters and a hash of its complete identity.
        for _ in range(len(values) * 2):
            candidates = [
                i
                for i, (_, v) in enumerate(values)
                if isinstance(v, NameInfo) and len(rendered[i]) > 48
            ]
            if not candidates or len(compose()) <= limit:
                break
            i = max(candidates, key=lambda j: len(rendered[j]))
            target = max(48, len(rendered[i]) - (len(compose()) - limit) - 14)
            rendered[i] = values[i][1].render(target, context=False)
        result = compose()
        # One parent digest also covers structure omitted from its nested
        # presentation; no composition relies on a child's readable prefix.
        return shorten(
            result + "_h" + digest(self.identity or full), limit, self.identity or full
        )


def value_description(value, seen=frozenset()):
    if id(value) in seen:
        return (
            safe(getattr(value, "__name__", type(value).__name__))
            + "_h"
            + digest(identity(value))
        )
    seen = seen | {id(value)}
    if isinstance(value, type):
        info = getattr(value, "_pypeline_name_info", None)
        if info is not None:
            return info
        elem = getattr(value, "_elem_ctype", None)
        if elem is not None:
            return NameInfo(
                "array",
                "array",
                params=(
                    ("n", str(value._arr_len)),
                    ("of", value_description(elem, seen)),
                ),
                identity=identity(value),
            )
        return NameInfo(
            "scalar_type",
            safe(getattr(value, "_ctype_name", value.__name__)),
            identity=identity(value),
        )
    if hasattr(value, "inner_ctype"):
        return NameInfo(
            "direction",
            type(value).__name__,
            params=(("of", value_description(value.inner_ctype, seen)),),
            identity=identity(value),
        )
    if callable(value):
        if getattr(value, "_is_autopipeline_pragma", False) or getattr(
            value, "_is_autofsm_pragma", False
        ):
            return NameInfo(
                "wrapper",
                type(value).__name__,
                params=(("func", value_description(value.func, seen)),),
                identity=identity(value),
            )
        if isinstance(value, functools.partial):
            return NameInfo(
                "partial",
                "partial",
                params=(
                    ("func", value_description(value.func, seen)),
                    ("args", value_description(value.args, seen)),
                    ("kwargs", value_description(value.keywords, seen)),
                ),
                identity=identity(value),
            )
        value = inspect.unwrap(value)
        info = getattr(value, "_pypeline_name_info", None)
        if info is not None:
            return info
        code = getattr(value, "__code__", None)
        if code is not None:
            params = dict(getattr(value, "_pypeline_factory_args", {}) or {})
            if not params:
                for k, cell in zip(code.co_freevars, value.__closure__ or ()):
                    try:
                        params[k] = cell.cell_contents
                    except ValueError:
                        pass
            return NameInfo(
                "function",
                value.__name__,
                value.__module__ or "",
                value.__qualname__,
                code.co_filename,
                code.co_firstlineno,
                tuple((k, value_description(v, seen)) for k, v in params.items()),
                identity=identity(value),
            )
        return safe(
            getattr(value, "__qualname__", type(value).__name__).replace(
                ".<locals>.", "_"
            )
        )
    if isinstance(value, (list, tuple)):
        return (
            "_".join(
                str(v.render(context=False) if isinstance(v, NameInfo) else v)
                for v in (value_description(x, seen) for x in value)
            )
            or "empty"
        )
    if isinstance(value, dict):

        def fragment(v):
            desc = value_description(v, seen)
            return desc.render(context=False) if isinstance(desc, NameInfo) else desc

        return (
            "_".join(
                fragment(k) + "_" + fragment(v)
                for k, v in sorted(
                    value.items(), key=lambda kv: repr(stable_key(kv[0]))
                )
            )
            or "empty"
        )
    if isinstance(value, int):
        return "neg" + str(-value) if value < 0 else str(value)
    if isinstance(value, float):
        return safe(repr(value).replace("-", "neg").replace(".", "p"))
    if value is None or isinstance(value, str):
        return safe(value)
    return safe(type(value).__name__) + "_h" + digest(identity(value))


def describe(obj, kind, params=None, frame=None):
    """Snapshot a declaration while its factory parameters are available."""
    obj = inspect.unwrap(obj)
    params = params or {}
    if kind == "function" and not params:
        for name, cell in zip(
            getattr(obj, "__code__", None).co_freevars
            if hasattr(obj, "__code__")
            else (),
            getattr(obj, "__closure__", None) or (),
        ):
            try:
                params[name] = cell.cell_contents
            except ValueError:
                pass
    source, line = "", 0
    try:
        source = inspect.getsourcefile(obj) or ""
        line = inspect.getsourcelines(obj)[1]
    except (OSError, TypeError):
        if frame is not None:
            source, line = frame.f_code.co_filename, frame.f_lineno
    fields = getattr(obj, "__annotations__", {}) if kind != "function" else {}
    # Snapshot before stamping the object, avoiding a self-reference.
    semantic = identity((kind, obj.__name__, params, fields))
    module = getattr(obj, "__module__", "") or ""
    if module == "pypeline_design" and source:
        module = os.path.splitext(os.path.basename(source))[0]
    return NameInfo(
        kind,
        obj.__name__,
        module,
        getattr(obj, "__qualname__", obj.__name__),
        source,
        line,
        tuple((k, value_description(v)) for k, v in params.items()),
        tuple((k, value_description(v)) for k, v in fields.items()),
        semantic,
    )


def derived_type(iface, role, fields):
    info = iface._pypeline_name_info
    return replace(
        info,
        kind="interface_" + role,
        symbol=info.symbol + "_" + role + "_t",
        fields=tuple((k, value_description(v)) for k, v in fields),
        identity=identity((info.identity, role, dict(fields))),
    )


# VHDL strings (including doubled quotes), comments, extended identifiers,
# character literals, and basic identifiers. Only the last alternative is
# rewritten: diagnostics/string payloads and user comments stay verbatim.
_VHDL_TOKEN = re.compile(
    r'"(?:[^"\n]|"")*"|--[^\n]*|\\[^\\\n]*\\|\'[^\n]\'|[A-Za-z][A-Za-z0-9_]*'
)


class EmissionNames:
    """One immutable base mapping and an emission memo per elaborated build."""

    def __init__(self, descriptions, protected=(), reserved=()):
        self.descriptions = descriptions
        self.protected = set(protected)
        protected_lower = {name.lower() for name in self.protected | set(reserved)}
        candidates = {}
        self.bases = {}
        for raw, infos in sorted(descriptions.items()):
            info = min(infos, key=lambda n: (n.module, n.qualname, n.source, n.line))
            name = info.render(BASE_LIMIT)
            candidates.setdefault(name.lower(), []).append((raw, name, info))
        for group in candidates.values():
            for raw, name, info in group:
                if len(group) > 1 or name.lower() in protected_lower:
                    name = shorten(name + "_h" + digest(raw), BASE_LIMIT, raw)
                self.bases[raw] = name
        self.memo = {}
        self.full = {}
        self.outputs = set(self.bases.values()) | self.protected
        # A composed helper name can embed a type and/or a function name.
        # Include emitted bases as protected matches to make rendering
        # idempotent when GET_ENTITY_NAME already formatted a reference.
        keys = set(self.bases) | self.outputs
        self.pattern = (
            re.compile(
                r"(?<![A-Za-z0-9])(?:"
                + "|".join(
                    re.escape(k) for k in sorted(keys, key=lambda k: (-len(k), k))
                )
                + r")(?![A-Za-z0-9])"
            )
            if keys
            else None
        )

    def identifier(self, raw):
        if raw in self.protected or raw in self.outputs:
            return raw
        if raw in self.memo:
            return self.memo[raw]
        full = (
            self.pattern.sub(
                lambda m: m[0] if m[0] in self.outputs else self.bases[m[0]], raw
            )
            if self.pattern
            else raw
        )
        result = shorten(full)
        self.memo[raw] = result
        self.outputs.add(result)
        if result != raw or re.search(r"_[0-9]+CLK_[0-9a-f]+", raw):
            self.full[result] = (raw, full)
        return result

    def text(self, text):
        return _VHDL_TOKEN.sub(
            lambda m: self.identifier(m[0]) if m[0][0].isalpha() else m[0], text
        )

    def source_comment(self, raw):
        infos = self.descriptions.get(raw, ())
        lines = []
        for info in sorted(infos, key=lambda n: (n.source, n.line, n.qualname)):
            source = display_source(info.source)
            lines.append(
                f"-- Python: {info.module}.{info.qualname} ({source}:{info.line})"
            )
            lines.append(f"-- Specialization: {info.render()}")
        return "\n".join(lines) + ("\n" if lines else "")


def display_source(source):
    """Portable source paths in generated HDL; absolute paths remain in index."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if source.startswith(root + os.sep):
        return os.path.relpath(source, root)
    # Synthetic sources and external designs do not embed the scratch root.
    return os.path.basename(source)
