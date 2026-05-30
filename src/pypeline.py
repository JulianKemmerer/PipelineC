"""
pypeline.py — runtime support for Pypeline hardware design files.

Usage in user design files:
    from pypeline import MAIN, NamedTuple, uint32_t, uint1_t, ...

    class point_t(NamedTuple):
        x: uint32_t
        y: uint32_t

    # point_t[10] works as a type annotation after the class definition
"""

import typing


# ─────────────────────────────────────────────
# Elaboration-time C type objects
# ─────────────────────────────────────────────


class _CTypeMeta(type):
    """Metaclass for C type objects.
    str/repr return the C type name. Subscript produces array types.
    """

    def __repr__(cls):
        return cls._ctype_name

    def __str__(cls):
        return cls._ctype_name

    def __getitem__(cls, dim):
        if not isinstance(dim, int):
            raise TypeError(f"Array dimension must be int, got {type(dim)}: {dim!r}")
        return _make_ctype(f"{cls._ctype_name}[{dim}]")

    @property
    def width(cls):
        import re

        m = re.match(r"(?:u?int)(\d+)_t", cls._ctype_name)
        if m:
            return int(m.group(1))
        raise NotImplementedError(f"width not defined for '{cls._ctype_name}'")

    def __len__(cls):
        return cls.width


def _make_ctype(name: str):
    """Create a C type as a real Python class.
    Passes isinstance(t, type) so NamedTuple accepts it as a field annotation.
    str(uint32_t) == 'uint32_t',  uint32_t[2] -> _make_ctype('uint32_t[2]').
    """
    return _CTypeMeta(name, (object,), {"_ctype_name": name})


def make_uint(width: int):
    """Return the C unsigned integer type for the given bit width, e.g. make_uint(3) -> uint3_t."""
    return _make_ctype(f"uint{width}_t")


def make_int(width: int):
    """Return the C signed integer type for the given bit width, e.g. make_int(8) -> int8_t."""
    return _make_ctype(f"int{width}_t")


def _float_to_fields(value, exponent_width, mantissa_width):
    """Convert a Python float to an IEEE 754-like sign/exp/man dict at elaboration time."""
    import struct as _struct

    f = float(value)
    if exponent_width == 8 and mantissa_width == 23:
        bits = _struct.unpack(">I", _struct.pack(">f", f))[0]
    elif exponent_width == 11 and mantissa_width == 52:
        bits = _struct.unpack(">Q", _struct.pack(">d", f))[0]
    else:
        # General: rebase from FP64 representation
        bits64 = _struct.unpack(">Q", _struct.pack(">d", f))[0]
        sign = (bits64 >> 63) & 1
        exp64 = (bits64 >> 52) & 0x7FF
        man64 = bits64 & ((1 << 52) - 1)
        bias64 = 1023
        bias_t = (1 << (exponent_width - 1)) - 1
        exp_max = (1 << exponent_width) - 1
        if exp64 == 0x7FF:  # inf / nan
            biased_exp = exp_max
            man = man64 >> (52 - mantissa_width) if man64 else 0
        elif exp64 == 0 and man64 == 0:  # zero
            biased_exp = 0
            man = 0
        else:  # normal
            true_exp = exp64 - bias64
            biased_exp = true_exp + bias_t
            biased_exp = max(1, min(exp_max - 1, biased_exp))
            man = man64 >> (52 - mantissa_width)
        return {"sign": sign, "exp": biased_exp, "man": man}
    sign = (bits >> (exponent_width + mantissa_width)) & 1
    exp = (bits >> mantissa_width) & ((1 << exponent_width) - 1)
    man = bits & ((1 << mantissa_width) - 1)
    return {"sign": sign, "exp": exp, "man": man}


def make_float_t(exponent_width, mantissa_width):
    """Create an IEEE 754-like floating-point struct type with variable field widths.

    Fields: sign (uint1_t), exp (uintE_t), man (uintM_t).
    The returned type has an .as_const(value) method for elaboration-time conversion
    of a Python float into the dict initializer form.

    Usage:
        float32_t = make_float_t(8, 23)   # standard FP32
        x: float32_t = float32_t.as_const(1.23)
    """
    exp_t = make_uint(exponent_width)
    man_t = make_uint(mantissa_width)

    @struct
    class float_t(NamedTuple):
        sign: uint1_t
        exp: exp_t
        man: man_t

    float_t.as_const = staticmethod(
        lambda value: _float_to_fields(value, exponent_width, mantissa_width)
    )
    float_t.exponent_width = exponent_width
    float_t.mantissa_width = mantissa_width
    return float_t


# ── unsigned integer types ────────────────────
uint1_t = make_uint(1)
uint2_t = make_uint(2)
uint3_t = make_uint(3)
uint4_t = make_uint(4)
uint5_t = make_uint(5)
uint6_t = make_uint(6)
uint7_t = make_uint(7)
uint8_t = make_uint(8)
uint9_t = make_uint(9)
uint10_t = make_uint(10)
uint11_t = make_uint(11)
uint12_t = make_uint(12)
uint13_t = make_uint(13)
uint14_t = make_uint(14)
uint15_t = make_uint(15)
uint16_t = make_uint(16)
uint17_t = make_uint(17)
uint18_t = make_uint(18)
uint24_t = make_uint(24)
uint32_t = make_uint(32)
uint33_t = make_uint(33)
uint34_t = make_uint(34)
uint48_t = make_uint(48)
uint64_t = make_uint(64)

# ── signed integer types ──────────────────────
int1_t = make_int(1)
int2_t = make_int(2)
int4_t = make_int(4)
int8_t = make_int(8)
int16_t = make_int(16)
int32_t = make_int(32)
int33_t = make_int(33)
int64_t = make_int(64)

# ─────────────────────────────────────────────
# NamedTuple with automatic subscript support
# ─────────────────────────────────────────────


def _mangle_type(s):
    """Remove array brackets for VHDL-compatible name mangling: uint32_t[2] -> uint32_t_2."""
    return s.replace("[", "_").replace("]", "")


def _struct_class_getitem(cls, dim):
    """Enables point_t[10] -> _make_ctype('point_t[10]') using the canonical C type name."""
    name = getattr(cls, "_pypeline_ctype_name", cls.__name__)
    return _make_ctype(f"{name}[{dim}]")


class _NamedTupleBase:
    """Internal sentinel base used by the NamedTuple() function below."""

    pass


def NamedTuple(cls=None, **kwargs):
    """Used as a base class to create hardware struct types.
    Automatically adds array subscript support so point_t[10] works.

    Usage:
        class point_t(NamedTuple):
            x: uint32_t
            y: uint32_t
    """
    # When used as a base class Python calls this as NamedTuple() to get
    # the base object, then builds the subclass. We return a special sentinel.
    # The actual class is built via __init_subclass__ on _NamedTupleBase...
    # but that's complex. Instead we use __class_getitem__ on the returned object.
    #
    # Simplest approach that works: return typing.NamedTuple and rely on
    # a module-level __init__ hook. But that's not available.
    #
    # The actual working approach: NamedTuple is a function that,
    # when used as `class Foo(NamedTuple):`, Python will call it with no args
    # to get the base. We return typing.NamedTuple so the class is built
    # correctly, then we cannot patch it at that point.
    #
    # THE REAL FIX: use typing.NamedTuple directly and provide a
    # 'struct' decorator that patches __class_getitem__.
    pass


# Use typing.NamedTuple directly — it works fine for field annotations.
# For subscript support on the resulting class, use the @struct decorator.
NamedTuple = typing.NamedTuple


def struct(cls):
    """Decorator that adds array subscript support and stamps a canonical C type name.
    The canonical name is derived from the class name and field types, making it
    deterministic regardless of the Python variable name used at the call site.
    This allows factory-produced structs nested inside other factories to get
    unique, stable names without being visible at module level.

    Usage:
        @struct
        class point_t(NamedTuple):
            x: uint32_t
            y: uint32_t

        # Now point_t[10] works as an annotation, and point_t._pypeline_ctype_name
        # is set to "point_t_x_uint32_t_y_uint32_t"
    """
    cls.__class_getitem__ = classmethod(_struct_class_getitem)
    parts = []
    for field, ann in cls.__annotations__.items():
        if isinstance(ann, type):
            # Use canonical name for struct-typed fields if already computed
            ann_str = getattr(ann, "_pypeline_ctype_name", ann.__name__)
        else:
            ann_str = str(ann)
        parts.append(f"{field}_{_mangle_type(ann_str)}")
    canonical = cls.__name__ + ("_" + "_".join(parts) if parts else "")
    cls._pypeline_ctype_canonical = canonical
    cls._pypeline_ctype_name = canonical
    return cls


# ─────────────────────────────────────────────
# MAIN decorator
# ─────────────────────────────────────────────

_main_registry: list = []


def MAIN(func):
    """Marks a function as a top-level hardware process."""
    _main_registry.append(func)
    return func


# ─────────────────────────────────────────────
# Operator overloading registry
# ─────────────────────────────────────────────


def _ctype_str(t) -> str:
    """Return the canonical C type name for a type object.
    Works for _CTypeMeta integer types (uint32_t) and @struct NamedTuple types.
    """
    if hasattr(t, "_pypeline_ctype_name"):
        return t._pypeline_ctype_name
    return str(t)


_operator_registry: dict = {}  # (op_str, l_type_str, r_type_str) -> name_or_callable
_left_operator_registry: dict = {}  # (op_str, l_type_str) -> name_or_callable
_unary_operator_registry: dict = {}  # (op_str, type_str) -> name_or_callable

# Scoped registrations: active only while elaborating the keyed function.
# id(func) -> {registry_key: name_or_callable}
_scoped_operator_registry: dict = {}
_scoped_left_operator_registry: dict = {}
_scoped_unary_operator_registry: dict = {}


def register_operator(op: str, left_type, right_type, func_name, scope=None) -> None:
    """Register a hardware function as the implementation of a variable binary operator.
    Matches on both left and right operand types (exact match).

    op:        "SL" (<<) or "SR" (>>)
    left_type: C type of the left operand (e.g. uint32_t)
    right_type: C type of the right operand / shift amount (e.g. uint6_t)
    func_name: string name of a module-level callable, or a callable directly.
    scope:     if provided, registration is active only while elaborating that callable.
    """
    key = (op, _ctype_str(left_type), _ctype_str(right_type))
    if scope is None:
        _operator_registry[key] = func_name
    else:
        _scoped_operator_registry.setdefault(id(scope), {})[key] = func_name


def register_left_operator(op: str, left_type, func_name, scope=None) -> None:
    """Register a hardware function as the implementation of a binary operator,
    matching only on the left operand type. The right operand type is derived
    from the registered function (e.g. shift amount derived from value width).

    op:        "SL" (<<) or "SR" (>>)
    left_type: C type of the left operand (e.g. uint32_t)
    func_name: string name of a module-level callable, or a callable directly.
    scope:     if provided, registration is active only while elaborating that callable.
    """
    key = (op, _ctype_str(left_type))
    if scope is None:
        _left_operator_registry[key] = func_name
    else:
        _scoped_left_operator_registry.setdefault(id(scope), {})[key] = func_name


def register_unary_operator(op: str, operand_type, func_name, scope=None) -> None:
    """Register a hardware function as the implementation of a unary operator.

    op:           "NEGATE" (-) or "NOT" (~)
    operand_type: C type of the operand (e.g. uint32_t)
    func_name:    string name of a module-level callable, or a callable directly.
    scope:        if provided, registration is active only while elaborating that callable.
    """
    key = (op, _ctype_str(operand_type))
    if scope is None:
        _unary_operator_registry[key] = func_name
    else:
        _scoped_unary_operator_registry.setdefault(id(scope), {})[key] = func_name


def _push_scoped_registrations(func):
    """Merge scoped operator registrations for *func* into the active global registries.
    Returns a list of (registry, key, old_value) triples for restoring afterward.
    Scoped entries from outer elaboration frames are already present in the global
    registries, so inner callees automatically inherit them.
    """
    saved = []
    func_id = id(func)
    for key, val in _scoped_operator_registry.get(func_id, {}).items():
        saved.append((_operator_registry, key, _operator_registry.get(key)))
        _operator_registry[key] = val
    for key, val in _scoped_left_operator_registry.get(func_id, {}).items():
        saved.append((_left_operator_registry, key, _left_operator_registry.get(key)))
        _left_operator_registry[key] = val
    for key, val in _scoped_unary_operator_registry.get(func_id, {}).items():
        saved.append((_unary_operator_registry, key, _unary_operator_registry.get(key)))
        _unary_operator_registry[key] = val
    return saved


def _pop_scoped_registrations(saved):
    """Restore registry entries to their pre-push state."""
    _MISSING = object()
    for registry, key, old_val in saved:
        if old_val is None:
            registry.pop(key, _MISSING)
        else:
            registry[key] = old_val


# ─────────────────────────────────────────────
# Reg[T] — hardware state register annotation
# ─────────────────────────────────────────────


class _RegType:
    """Produced by Reg[T]. Marks a variable as a hardware register (flip-flop)."""

    def __init__(self, inner_ctype):
        self.inner_ctype = inner_ctype  # a _CTypeMeta class or array ctype

    def __str__(self):
        return f"Reg[{self.inner_ctype}]"

    def __repr__(self):
        return str(self)


class _RegMeta(type):
    def __getitem__(cls, inner_type):
        return _RegType(inner_type)


class Reg(metaclass=_RegMeta):
    """Marks a local variable as a hardware state register (persistent between cycles).

    Usage in hardware functions:
        acc: Reg[uint32_t]      # register, initialized to 0 at power-on
        acc = acc + data_in     # read current value; write sets next-cycle value
    """

    pass


# ─────────────────────────────────────────────
# Bit manipulation primitives
# (intercepted by PY_TO_LOGIC elaborator; not callable at Python runtime)
# ─────────────────────────────────────────────
# Bit slice / select: use subscript syntax on integer wires
#   y = x[15]       # single bit  → uint1_t
#   z = x[15:0]     # range       → uint16_t
# Bit concat: use tuple syntax on unsigned integer wires
#   z = (a, b)      # a=upper, b=lower; chains for >2 elements


def bit_dup(x, n):
    """Replicate x n times: bit_dup(uint4_t, 4) → uint16_t."""
    raise NotImplementedError("bit_dup is a PipelineC hardware primitive")


def rotl(x, amount):
    """Rotate x left by amount bits (constant)."""
    raise NotImplementedError("rotl is a PipelineC hardware primitive")


def rotr(x, amount):
    """Rotate x right by amount bits (constant)."""
    raise NotImplementedError("rotr is a PipelineC hardware primitive")


def bswap(x):
    """Reverse byte order of x."""
    raise NotImplementedError("bswap is a PipelineC hardware primitive")


def bit_assign(base, x, pos):
    """Assign x into base at bit position pos (constant): base[pos+width-1:pos] = x."""
    raise NotImplementedError("bit_assign is a PipelineC hardware primitive")


def array_to_uint_be(arr):
    """Pack array elements into a single uint, big-endian (element[0] at MSB)."""
    raise NotImplementedError("array_to_uint_be is a PipelineC hardware primitive")


def array_to_uint_le(arr):
    """Pack array elements into a single uint, little-endian (element[0] at LSB)."""
    raise NotImplementedError("array_to_uint_le is a PipelineC hardware primitive")


def uint_to_array_be(x, elem_w):
    """Split uint x into array of elem_w-bit elements, big-endian (MSB → element[0])."""
    raise NotImplementedError("uint_to_array_be is a PipelineC hardware primitive")


def uint_to_array_le(x, elem_w):
    """Split uint x into array of elem_w-bit elements, little-endian (LSB → element[0])."""
    raise NotImplementedError("uint_to_array_le is a PipelineC hardware primitive")


BIT_MANIP_FUNC_NAMES = frozenset(
    {
        "bit_dup",
        "rotl",
        "rotr",
        "bswap",
        "bit_assign",
        "array_to_uint_be",
        "array_to_uint_le",
        "uint_to_array_be",
        "uint_to_array_le",
    }
)
