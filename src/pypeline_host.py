"""Generate a standalone, stdlib-only Python module that packs and unpacks a
design's wire-format structs -- for a host that has no Pypeline checkout.

WHY THIS EXISTS. `pypeline.type_to_bytes` / `type_from_bytes` already give
in-repo software the exact byte layout the hardware uses. That covers a
testbench; it does not cover the machine on the other end of the wire. Copying
`pypeline.py` there does not work either: it imports standalone, but a design's
TYPES do not -- a struct defined next to its hardware pulls in the factory
library that defines it (`axi.type_axis`, `fifo`, `dsp.fir_common`, ...), i.e.
the whole checkout. So host programs end up hand-transcribing the layout as a
`struct` format string, and a drifted copy is the worst kind of bug: a
well-formed frame of the right length that loads the wrong values into the
wrong registers.

So `pypelinec` generates the host's copy instead. Old C-based PipelineC did the
same thing for C hosts -- `SW_LIB.py`'s
GEN_POST_PREPROCESS_WITH_NONFUNCDEFS_TYPE_BYTES_HEADERS emitted `<T>_to_bytes` /
`bytes_to_<T>` headers into the output directory. This is that, in Python.

WHY IT CANNOT DRIFT. Nothing here re-derives the layout. The leaf walk
(`_enumerate_leaves`), the leaf sizing (`_leaf_bit_width`), the total
(`byte_length`) and the mask/sign rule (`_sim_cast_params`) are the very
functions `type_to_bytes` and the hardware generator `make_type_to_bytes` use.
One walk, three consumers. Since `type_to_bytes` is in turn asserted equal to
simulated hardware (`inst/type_bytes_sw_test.py::test_sw_matches_hw`) and the
generated module is asserted equal to `type_to_bytes`
(`inst/host_types_test.py`), the chain is: generated host module == in-repo
software == native-sim hardware == VHDL hardware.

WHAT LANDS WHERE. One file, `<out_dir>/host/pypeline_host_types.py`, written by
`write_host_types()` from `src/pipelinec` after parsing a `.py` design. Nothing
is written when a design serializes no struct.
"""

import os

from pypeline import (
    _array_elem_ctype,
    _array_len,
    _bytes_type_key,
    _enumerate_leaves,
    _leaf_bit_width,
    _sim_cast_params,
    byte_length,
    host_exports,
)

MODULE_NAME = "pypeline_host_types"
HOST_SUBDIR = "host"

# struct-module format characters for the leaf widths that have one. A type
# whose every leaf is one of these (and which is otherwise flat) gets a
# `struct` fast path; everything else uses the generic shape walk.
_FMT_CHAR = {8: "b", 16: "h", 32: "i", 64: "q"}

# Exactly the attributes _register() assigns onto a generated @struct -- and
# nothing more. `count`/`index` are deliberately NOT here: a namedtuple field
# by those names merely shadows tuple.count/tuple.index, which breaks nothing
# about packing, and rejecting them would fail designs that pack fine today.
_RESERVED_ATTRS = frozenset(("BYTE_LENGTH", "FORMAT", "to_bytes", "from_bytes", "zero"))

_PY_KEYWORDS = frozenset(
    """False None True and as assert async await break class continue def del
    elif else except finally for from global if import in is lambda nonlocal not
    or pass raise return try while with yield""".split()
)


# ─────────────────────────────────────────────
# Type introspection (all layout facts come from pypeline's own helpers)
# ─────────────────────────────────────────────


def _kind(t):
    if getattr(t, "_pypeline_is_enum", False):
        return "enum"
    if _array_elem_ctype(t) is not None:
        return "array"
    if hasattr(t, "_fields"):
        return "struct"
    return "scalar"


def _is_char_array(t):
    elem = _array_elem_ctype(t)
    return elem is not None and getattr(elem, "_ctype_name", None) == "char"


def _leaf_signed(t):
    """Signed-ness of a scalar leaf, from the same helper _sim_cast uses -- so
    an int16_t comes back negative on the host exactly as it does in sim."""
    return _sim_cast_params(t)[2]


def _deps(t, out=None):
    """Every struct/enum type `t` contains, so emission can put a nested type
    before the type that holds it."""
    if out is None:
        out = []
    k = _kind(t)
    if k == "enum":
        out.append(t)
    elif k == "array":
        _deps(_array_elem_ctype(t), out)
    elif k == "struct":
        for f in t._fields:
            _deps(t.__annotations__[f], out)
        out.append(t)
    return out


def _host_name(t, names):
    """The identifier this type gets in the generated module."""
    return names[_bytes_type_key(t)]


def _assign_host_names(types):
    """canonical name -> host identifier, over every type being emitted.

    A design's own source name (`cfg_t`) rather than the canonical hashed one
    (`cfg_t_a_uint32_t_m_mode_t_OFF_ACTIVE`), because the whole point is code a
    person writes by hand. Two types wanting the same short name is the one
    case where that is not safe, and there BOTH fall back to the canonical name
    -- deterministic, and never an arbitrary winner that silently changes which
    type a host's `cfg_t` refers to.
    """
    wanted = {}
    for t in types:
        canon = _bytes_type_key(t)
        short = getattr(t, "__name__", None)
        if _kind(t) in ("array", "scalar") or not _is_identifier(short):
            short = canon
        wanted.setdefault(short, []).append(canon)
    names = {}
    for short, canons in wanted.items():
        for canon in canons:
            names[canon] = short if len(canons) == 1 else canon
    return names


def _is_identifier(s):
    return bool(s) and isinstance(s, str) and s.isidentifier() and s not in _PY_KEYWORDS


def _check_emittable(t, host_name):
    """Reject, loudly and at generation time, the two shapes that would produce
    a broken or booby-trapped host module."""
    if _kind(t) != "struct":
        return
    for f in t._fields:
        if f in _PY_KEYWORDS:
            raise ValueError(
                f"pypeline_host: @struct {host_name!r} has a field named {f!r}, "
                f"a Python keyword, so it cannot become a namedtuple field; "
                f"rename the field"
            )
        if f in _RESERVED_ATTRS:
            raise ValueError(
                f"pypeline_host: @struct {host_name!r} has a field named {f!r}, "
                f"which collides with a generated attribute of the same name; "
                f"rename the field"
            )


# ─────────────────────────────────────────────
# Shape trees -- what the generated module walks to pack/unpack
#
#   ("u", bits)                       unsigned scalar leaf
#   ("i", bits)                       signed scalar leaf
#   ("e", bits, enum_cls)             @enum leaf (always unsigned)
#   ("a", n, elem_shape, is_char)     array
#   ("t", nt_cls, ((name, shape),..)) @struct
# ─────────────────────────────────────────────


def _shape_expr(t, names):
    k = _kind(t)
    if k == "enum":
        return f'("e", {_leaf_bit_width(t)}, {_host_name(t, names)})'
    if k == "array":
        elem = _array_elem_ctype(t)
        return (
            f'("a", {_array_len(t)}, {_shape_expr(elem, names)}, '
            f"{_is_char_array(t)})"
        )
    if k == "struct":
        fields = ", ".join(
            f'("{f}", {_shape_expr(t.__annotations__[f], names)})' for f in t._fields
        )
        return f'("t", {_host_name(t, names)}, ({fields},))'
    return f'("{"i" if _leaf_signed(t) else "u"}", {_leaf_bit_width(t)})'


def _struct_format(t):
    """The `struct`-module format string for `t`, or None if it has no fast
    path. Deliberately narrow: a flat @struct of standard-width, non-enum
    scalars. That covers the shapes a host actually parses in bulk (it
    reproduces, character for character, the format strings hosts have been
    writing by hand) without a second code path that could disagree with the
    generic walk about enums or nesting.
    """
    if _kind(t) != "struct":
        return None
    chars = []
    for f in t._fields:
        ft = t.__annotations__[f]
        if _kind(ft) != "scalar":
            return None
        bits = _leaf_bit_width(ft)
        c = _FMT_CHAR.get(bits)
        if c is None:
            return None
        chars.append(c if _leaf_signed(ft) else c.upper())
    return "".join(chars) if chars else None


# ─────────────────────────────────────────────
# Constant values
# ─────────────────────────────────────────────


def _value_literal(value, names):
    """Source text reconstructing an exported constant in the generated module."""
    if isinstance(value, type) or getattr(value, "_pypeline_is_enum", False):
        return _host_name(value, names)  # a type exported under an alias
    cls = type(value)
    if getattr(cls, "_pypeline_is_enum", False):
        return f"{_host_name(cls, names)}.{value.name}"
    if hasattr(cls, "_fields") and hasattr(cls, "_pypeline_ctype_name"):
        args = ", ".join(
            f"{f}={_value_literal_of(getattr(value, f), cls.__annotations__[f], names)}"
            for f in cls._fields
        )
        return f"{_host_name(cls, names)}({args})"
    if isinstance(value, bool):
        return repr(bool(value))
    if isinstance(value, int):
        return repr(int(value))
    if isinstance(value, (float, str, bytes)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_value_literal(v, names) for v in value) + "]"
    raise TypeError(f"pypeline_host: cannot export value of type {cls!r}: {value!r}")


def _value_literal_of(value, t, names):
    """Like _value_literal but with the declared type in hand, so an enum-typed
    field holding a plain SimVal still emits as the enum member, and a char
    array keeps its CharArray wrapper."""
    k = _kind(t)
    if k == "enum":
        try:
            return f"{_host_name(t, names)}.{t(int(value)).name}"
        except ValueError:
            return repr(int(value))
    if k == "array":
        elem = _array_elem_ctype(t)
        inner = ", ".join(_value_literal_of(v, elem, names) for v in value)
        return f"CharArray([{inner}])" if _is_char_array(t) else f"[{inner}]"
    if k == "struct":
        args = ", ".join(
            f"{f}={_value_literal_of(getattr(value, f), t.__annotations__[f], names)}"
            for f in t._fields
        )
        return f"{_host_name(t, names)}({args})"
    return repr(int(value))


# ─────────────────────────────────────────────
# The generated module's own runtime (emitted verbatim into every host file)
# ─────────────────────────────────────────────

_RUNTIME = '''
import struct as _struct


class CharArray(list):
    """A char_t[N] value: a list of ints that also behaves like the string it
    represents, stopping at the first NUL -- the host-side twin of pypeline's
    own CharArray, so `str(v.name)` reads the same on both sides."""

    def __str__(self):
        chars = []
        for v in self:
            if int(v) == 0:
                break
            chars.append(chr(int(v)))
        return "".join(chars)

    def __repr__(self):
        return "CharArray(%r)" % (str(self),)

    def __eq__(self, other):
        if isinstance(other, str):
            return str(self) == other
        return list.__eq__(self, other)

    def __ne__(self, other):
        return not self.__eq__(other)

    __hash__ = None


# Layout tables, keyed by the type objects defined below. Side tables rather
# than attributes because an @enum class must NOT gain a `to_bytes` attribute:
# it would shadow int.to_bytes on every member.
_SHAPES = {}
_LENS = {}
_ENDIANS = {}
_FORMATS = {}
_MASKS = {}


class _Type(object):
    """Stand-in type object for an export that is not an @struct -- a bare
    scalar or an array. Carries the same surface as a generated struct
    (BYTE_LENGTH / zero / to_bytes / from_bytes) so every entry in TYPES can be
    used the same way."""

    def __init__(self, name):
        self._name = name

    def __repr__(self):
        return self._name

    @property
    def BYTE_LENGTH(self):
        return _LENS[self]

    def zero(self):
        return _zero(_SHAPES[self])

    def to_bytes(self, value, endian=None):
        return type_to_bytes(self, value, endian)

    def from_bytes(self, data, endian=None):
        return type_from_bytes(self, data, endian)


def _zero(shape):
    kind = shape[0]
    if kind == "t":
        return shape[1](*[_zero(s) for _, s in shape[2]])
    if kind == "a":
        vals = [_zero(shape[2]) for _ in range(shape[1])]
        return CharArray(vals) if shape[3] else vals
    if kind == "e":
        try:
            return shape[2](0)
        except ValueError:
            return 0
    return 0


def _pack_into(shape, value, endian, out):
    kind = shape[0]
    if kind == "t":
        for name, sub in shape[2]:
            _pack_into(sub, getattr(value, name), endian, out)
        return
    if kind == "a":
        for i in range(shape[1]):
            _pack_into(shape[2], value[i], endian, out)
        return
    bits = shape[1]
    v = int(value) & ((1 << bits) - 1)
    out += v.to_bytes((bits + 7) // 8, endian)


def _unpack_from(shape, buf, pos, endian):
    kind = shape[0]
    if kind == "t":
        vals = []
        for _name, sub in shape[2]:
            v, pos = _unpack_from(sub, buf, pos, endian)
            vals.append(v)
        return shape[1](*vals), pos
    if kind == "a":
        vals = []
        for _ in range(shape[1]):
            v, pos = _unpack_from(shape[2], buf, pos, endian)
            vals.append(v)
        return (CharArray(vals) if shape[3] else vals), pos
    bits = shape[1]
    nbytes = (bits + 7) // 8
    v = int.from_bytes(buf[pos : pos + nbytes], endian) & ((1 << bits) - 1)
    pos += nbytes
    if kind == "i" and (v >> (bits - 1)):
        v -= 1 << bits
    elif kind == "e":
        try:
            v = shape[2](v)
        except ValueError:
            pass  # a value that names no member stays a plain int
    return v, pos


def _shape_of(t, func_name):
    try:
        return _SHAPES[t]
    except (KeyError, TypeError):
        raise TypeError(
            "%s: %r is not a type from this generated module" % (func_name, t)
        )


def byte_length(t):
    """Packed byte size of `t` -- the same number pypeline.byte_length(t) gives."""
    _shape_of(t, "byte_length")
    return _LENS[t]


def type_to_bytes(t, value, endian=None):
    """Pack `value` into byte_length(t) bytes. `endian` defaults to the one the
    hardware itself uses for this type."""
    shape = _shape_of(t, "type_to_bytes")
    endian = endian or _ENDIANS[t]
    fmt = _FORMATS.get(t)
    if fmt is not None:
        vals = []
        for v, (mask, sign_bit, signed) in zip(value, _MASKS[t]):
            v = int(v) & mask
            if signed and (v & sign_bit):
                v -= mask + 1
            vals.append(v)
        return _struct.pack(("<" if endian == "little" else ">") + fmt, *vals)
    out = bytearray()
    _pack_into(shape, value, endian, out)
    return bytes(out)


def type_from_bytes(t, data, endian=None):
    """Unpack exactly byte_length(t) bytes into a value of `t`."""
    shape = _shape_of(t, "type_from_bytes")
    endian = endian or _ENDIANS[t]
    buf = bytes(bytearray(data))
    n = _LENS[t]
    if len(buf) != n:
        raise ValueError(
            "type_from_bytes(%r): expected %d bytes (byte_length), got %d"
            % (t, n, len(buf))
        )
    fmt = _FORMATS.get(t)
    if fmt is not None:
        return t(*_struct.unpack_from(("<" if endian == "little" else ">") + fmt, buf))
    value, _pos = _unpack_from(shape, buf, 0, endian)
    return value


def _register(t, shape, n, endian, fmt=None, masks=None):
    _SHAPES[t] = shape
    _LENS[t] = n
    _ENDIANS[t] = endian
    if fmt is not None:
        # Cheap guard that the fast path and the layout agree; the generator
        # derives both from one leaf walk, so a mismatch means a bad edit.
        assert _struct.calcsize("<" + fmt) == n, (t, fmt, n)
        _FORMATS[t] = fmt
        _MASKS[t] = masks
    if hasattr(t, "_fields"):
        # Conveniences on generated @struct types only -- never on an @enum,
        # where a `to_bytes` attribute would shadow int.to_bytes on members.
        t.BYTE_LENGTH = n
        t.FORMAT = fmt
        t.zero = classmethod(lambda c: _zero(_SHAPES[c]))
        t.to_bytes = classmethod(
            lambda c, value, endian=None: type_to_bytes(c, value, endian)
        )
        t.from_bytes = classmethod(
            lambda c, data, endian=None: type_from_bytes(c, data, endian)
        )
'''


# ─────────────────────────────────────────────
# Generation
# ─────────────────────────────────────────────


def _emit_order(exports):
    """Every type the module must define, nested types before the types that
    hold them. Exports are visited in canonical-name order, not registration
    order, so the output is a pure function of the design rather than of import
    sequence (see docs/pypeline_DESIGN.md on canonical-name determinism)."""
    order, seen = [], set()
    for canon in sorted(exports):
        t = exports[canon]["type"]
        for d in _deps(t) + [t]:
            key = _bytes_type_key(d)
            if key not in seen:
                seen.add(key)
                order.append(d)
    return order


def _resolve_endians(exports, order):
    """Type -> the endian its generated to_bytes/from_bytes default to.

    An export that the design serialized exactly one way defaults to that way.
    One serialized BOTH ways (a testbench checking both) has no single right
    answer, so it defaults to pypeline's own default and says so in the file. A
    nested type that is never serialized on its own inherits from the first
    export that reaches it.
    """
    resolved, ambiguous = {}, set()
    for canon in sorted(exports):
        entry = exports[canon]
        endians = entry["endians"]
        e = next(iter(endians)) if len(endians) == 1 else "little"
        if len(endians) > 1:
            ambiguous.add(canon)
        resolved[canon] = e
    for canon in sorted(exports):
        for d in _deps(exports[canon]["type"]):
            resolved.setdefault(_bytes_type_key(d), resolved[canon])
    for t in order:
        resolved.setdefault(_bytes_type_key(t), "little")
    return resolved, ambiguous


def _byte_map(t, names):
    """The on-wire layout as comment lines: byte offset, name, and width of
    every leaf. Emitted above each type because it is what a person reading the
    host file actually needs -- the same thing hand-written host modules put in
    a comment next to their format string."""
    rows = []
    off = 0
    for path, leaf_t in _enumerate_leaves(t):
        bits = _leaf_bit_width(leaf_t)
        nbytes = (bits + 7) // 8
        where = f"[{off}]" if nbytes == 1 else f"[{off}:{off + nbytes}]"
        name = ".".join(str(tok) for tok in path) or "value"
        if getattr(leaf_t, "_pypeline_is_enum", False):
            desc = f"{_host_name(leaf_t, names)} ({bits} bits)"
        else:
            desc = str(leaf_t)
            if bits % 8:
                desc += f" ({bits} bits)"
        rows.append((where, name, desc))
        off += nbytes
    w_off = max((len(r[0]) for r in rows), default=0)
    w_name = max((len(r[1]) for r in rows), default=0)
    return [
        f"#   {where:<{w_off}}  {name:<{w_name}}  {desc}" for where, name, desc in rows
    ]


def _emit_type(t, names, endian, lines):
    host = _host_name(t, names)
    canon = _bytes_type_key(t)
    _check_emittable(t, host)
    kind = _kind(t)
    lines.append("")
    lines.append("")
    n = byte_length(t)
    lines.append(f"# {host} -- {n} byte{'' if n == 1 else 's'}, {endian}-endian")
    if host != canon:
        lines.append(f"# Canonical hardware type: {canon}")
    if kind != "enum":
        lines += _byte_map(t, names)
    if kind == "enum":
        lines.append(f"class {host}(_IntEnum):")
        for member in t:
            lines.append(f"    {member.name} = {int(member)}")
    elif kind == "struct":
        lines.append(f"{host} = _namedtuple(")
        lines.append(f'    "{host}",')
        lines.append("    (")
        for f in t._fields:
            lines.append(f'        "{f}",')
        lines.append("    ),")
        lines.append(")")
    else:
        lines.append(f'{host} = _Type("{host}")  # {t}')
    fmt = _struct_format(t)
    lines.append("")
    lines.append("_register(")
    lines.append(f"    {host},")
    lines.append(f"    {_shape_expr(t, names)},")
    lines.append(f"    {byte_length(t)},")
    lines.append(f"    {endian!r},")
    if fmt is not None:
        masks = ", ".join(
            repr(_sim_cast_params(t.__annotations__[f])) for f in t._fields
        )
        lines.append(f"    {fmt!r},")
        lines.append(f"    ({masks},),")
    lines.append(")")


def generate(exports, values, src_file):
    """Source text of the standalone host module for one build. Pure: same
    inputs in, byte-identical text out."""
    order = _emit_order(exports)
    names = _assign_host_names(order)
    endians, ambiguous = _resolve_endians(exports, order)

    src_name = os.path.basename(src_file) if src_file else "a Pypeline design"
    head = [
        '"""Wire-format types for %s -- GENERATED by pypelinec, do not edit.'
        % src_name,
        "",
        "Standalone: the Python standard library only, no Pypeline checkout needed.",
        "Copy this one file next to a host program that talks to this design.",
        "",
        "Every layout here comes from the same leaf walk the hardware itself was",
        "built from, so it cannot drift from the bytes on the wire. Regenerate this",
        "file rather than editing it.",
        "",
        "    frame = some_t.to_bytes(some_t(field=1, ...))   # -> bytes",
        "    value = some_t.from_bytes(frame)                # -> some_t",
        "    some_t.BYTE_LENGTH                              # frame size",
        "    some_t.zero()                                   # all-zero value",
        "",
        "@struct types are namedtuples (so `_replace` and `_asdict` work, and every",
        "field must be given -- exactly as in Pypeline). @enum types are IntEnums;",
        "convert those with the module-level type_to_bytes/type_from_bytes, which",
        "also accept every type in TYPES.",
    ]
    if ambiguous:
        head += [
            "",
            "NOTE: this design serialized the following both little- and big-endian,",
            "so they default to little here -- pass endian= explicitly if you need the",
            "other: " + ", ".join(sorted(names[c] for c in ambiguous)),
        ]
    head += [
        '"""',
        "",
        "from collections import namedtuple as _namedtuple",
        "from enum import IntEnum as _IntEnum",
    ]

    lines = list(head)
    lines.append(_RUNTIME)
    for t in order:
        _emit_type(t, names, endians[_bytes_type_key(t)], lines)

    lines.append("")
    lines.append("")
    lines.append("# Every generated type, by name.")
    lines.append("TYPES = {")
    for t in order:
        host = _host_name(t, names)
        lines.append(f'    "{host}": {host},')
    lines.append("}")

    if values:
        lines.append("")
        lines.append("")
        lines.append("# Constants exported by the design via host_export().")
        for name in values:
            lines.append(f"{name} = {_value_literal(values[name], names)}")

    lines.append("")
    return "\n".join(lines)


def write_host_types(out_dir, src_file, exports=None, values=None):
    """Write `<out_dir>/host/pypeline_host_types.py` for the current build.

    Returns the path written, or None when the design registered no type --
    a design that never puts a struct on a wire gets no host file, rather than
    an empty one.
    """
    if exports is None or values is None:
        reg_exports, reg_values = host_exports()
        exports = reg_exports if exports is None else exports
        values = reg_values if values is None else values
    if not exports:
        return None
    text = generate(exports, values, src_file)
    host_dir = os.path.join(out_dir, HOST_SUBDIR)
    os.makedirs(host_dir, exist_ok=True)
    path = os.path.join(host_dir, MODULE_NAME + ".py")
    with open(path, "w") as f:
        f.write(text)
    return path
