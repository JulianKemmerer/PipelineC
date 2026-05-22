"""
pypeline.py — runtime support for Pypeline hardware design files.

Imported by user design files. Provides:
  - Hardware type objects (_CType): uint1_t, uint32_t, etc.
    Subscriptable to produce array types: uint32_t[4] -> _CType("uint32_t[4]")
    str() gives the C type string the elaborator expects.
  - MAIN decorator + _main_registry for entry point discovery.
"""

from typing import NamedTuple  # re-exported for user convenience


# ─────────────────────────────────────────────
# Elaboration-time C type objects
# ─────────────────────────────────────────────


class _CType:
    """Represents a C type at elaboration time.
    Supports subscript for array dimensions and str() for C type string.
    """

    def __init__(self, name: str):
        self._name = name

    def __getitem__(self, dim):
        if not isinstance(dim, int):
            raise TypeError(f"Array dimension must be int, got {type(dim)}: {dim!r}")
        return _CType(f"{self._name}[{dim}]")

    def __str__(self):
        return self._name

    def __repr__(self):
        return self._name

    def __eq__(self, other):
        if isinstance(other, _CType):
            return self._name == other._name
        if isinstance(other, str):
            return self._name == other
        return NotImplemented

    def __hash__(self):
        return hash(self._name)

    @property
    def width(self) -> int:
        """Bit width of scalar types. e.g. uint32_t.width == 32"""
        import re

        m = re.match(r"(?:u?int)(\d+)_t", self._name)
        if m:
            return int(m.group(1))
        raise NotImplementedError(f"width not defined for '{self._name}'")


# ── unsigned integer types ────────────────────
uint1_t = _CType("uint1_t")
uint2_t = _CType("uint2_t")
uint3_t = _CType("uint3_t")
uint4_t = _CType("uint4_t")
uint5_t = _CType("uint5_t")
uint6_t = _CType("uint6_t")
uint7_t = _CType("uint7_t")
uint8_t = _CType("uint8_t")
uint9_t = _CType("uint9_t")
uint10_t = _CType("uint10_t")
uint11_t = _CType("uint11_t")
uint12_t = _CType("uint12_t")
uint13_t = _CType("uint13_t")
uint14_t = _CType("uint14_t")
uint15_t = _CType("uint15_t")
uint16_t = _CType("uint16_t")
uint24_t = _CType("uint24_t")
uint32_t = _CType("uint32_t")
uint48_t = _CType("uint48_t")
uint64_t = _CType("uint64_t")

# ── signed integer types ──────────────────────
int1_t = _CType("int1_t")
int2_t = _CType("int2_t")
int4_t = _CType("int4_t")
int8_t = _CType("int8_t")
int16_t = _CType("int16_t")
int32_t = _CType("int32_t")
int64_t = _CType("int64_t")

# ── float types ───────────────────────────────
float16_t = _CType("float16_t")
float32_t = _CType("float32_t")
float64_t = _CType("float64_t")


# ─────────────────────────────────────────────
# MAIN decorator
# ─────────────────────────────────────────────

_main_registry: list = []


def MAIN(func):
    """Marks a function as a top-level hardware process (clock-domain entry point).
    Appends to _main_registry so the compiler can discover all entry points.
    Returns the function unchanged so it can still be called as Python for simulation.
    """
    _main_registry.append(func)
    return func
