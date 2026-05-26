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
int64_t = make_int(64)

# ─────────────────────────────────────────────
# NamedTuple with automatic subscript support
# ─────────────────────────────────────────────


def _struct_class_getitem(cls, dim):
    """Enables point_t[10] -> _make_ctype('point_t[10]')."""
    return _make_ctype(f"{cls.__name__}[{dim}]")


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
    """Decorator that adds array subscript support to a NamedTuple class.
    Enables: point_t[10] as a type annotation elsewhere.

    Usage:
        @struct
        class point_t(NamedTuple):
            x: uint32_t
            y: uint32_t

        # Now point_t[10] works as an annotation
    """
    cls.__class_getitem__ = classmethod(_struct_class_getitem)
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

_operator_registry: dict = {}  # (op_str, l_type_str, r_type_str) -> module_level_name_str


def register_operator(op: str, left_type, right_type, func_name: str) -> None:
    """Register a hardware function as the implementation of a variable operator.

    op:        "SL" (<<) or "SR" (>>)
    left_type: C type of the left operand (e.g. uint32_t)
    right_type: C type of the right operand / shift amount (e.g. uint6_t)
    func_name: string name of a module-level callable in the design file
               (the closure-factory result assigned to that name)
    """
    _operator_registry[(op, str(left_type), str(right_type))] = func_name


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
