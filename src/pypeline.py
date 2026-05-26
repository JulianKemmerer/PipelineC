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


# ── unsigned integer types ────────────────────
uint1_t = _make_ctype("uint1_t")
uint2_t = _make_ctype("uint2_t")
uint3_t = _make_ctype("uint3_t")
uint4_t = _make_ctype("uint4_t")
uint5_t = _make_ctype("uint5_t")
uint6_t = _make_ctype("uint6_t")
uint7_t = _make_ctype("uint7_t")
uint8_t = _make_ctype("uint8_t")
uint9_t = _make_ctype("uint9_t")
uint10_t = _make_ctype("uint10_t")
uint11_t = _make_ctype("uint11_t")
uint12_t = _make_ctype("uint12_t")
uint13_t = _make_ctype("uint13_t")
uint14_t = _make_ctype("uint14_t")
uint15_t = _make_ctype("uint15_t")
uint16_t = _make_ctype("uint16_t")
uint24_t = _make_ctype("uint24_t")
uint32_t = _make_ctype("uint32_t")
uint33_t = _make_ctype("uint33_t")
uint34_t = _make_ctype("uint34_t")
uint48_t = _make_ctype("uint48_t")
uint64_t = _make_ctype("uint64_t")

# ── signed integer types ──────────────────────
int1_t = _make_ctype("int1_t")
int2_t = _make_ctype("int2_t")
int4_t = _make_ctype("int4_t")
int8_t = _make_ctype("int8_t")
int16_t = _make_ctype("int16_t")
int32_t = _make_ctype("int32_t")
int64_t = _make_ctype("int64_t")

# ── float types ───────────────────────────────
float16_t = _make_ctype("float16_t")
float32_t = _make_ctype("float32_t")
float64_t = _make_ctype("float64_t")


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
