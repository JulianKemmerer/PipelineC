# pyright: reportInvalidTypeForm=none
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
import functools as _functools


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
        arr = _make_ctype(f"{cls._ctype_name}[{dim}]")
        arr._elem_ctype = cls
        return arr

    @property
    def width(cls):
        import re

        m = re.match(r"(?:u?int)(\d+)_t", cls._ctype_name)
        if m:
            return int(m.group(1))
        raise NotImplementedError(f"width not defined for '{cls._ctype_name}'")

    def __len__(cls):
        import re

        m = re.search(r"\[(\d+)\]", cls._ctype_name)
        if m:
            return int(m.group(1))
        return cls.width


def _make_ctype(name: str):
    """Create a C type as a real Python class.
    Passes isinstance(t, type) so NamedTuple accepts it as a field annotation.
    str(uint32_t) == 'uint32_t',  uint32_t[2] -> _make_ctype('uint32_t[2]').
    """
    return _CTypeMeta(name, (object,), {"_ctype_name": name})


def make_uint_t(width: int):
    """Return the C unsigned integer type for the given bit width, e.g. make_uint_t(3) -> uint3_t."""
    return _make_ctype(f"uint{width}_t")


def make_int_t(width: int):
    """Return the C signed integer type for the given bit width, e.g. make_int_t(8) -> int8_t."""
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
    exp_t = make_uint_t(exponent_width)
    man_t = make_uint_t(mantissa_width)

    @struct
    class float_t(NamedTuple):
        sign: uint1_t
        exp: exp_t
        man: man_t

    float_t.as_const = staticmethod(
        lambda value: float_t(**_float_to_fields(value, exponent_width, mantissa_width))
    )
    return float_t


# ── unsigned integer types ────────────────────
uint1_t = make_uint_t(1)
uint2_t = make_uint_t(2)
uint3_t = make_uint_t(3)
uint4_t = make_uint_t(4)
uint5_t = make_uint_t(5)
uint6_t = make_uint_t(6)
uint7_t = make_uint_t(7)
uint8_t = make_uint_t(8)
uint9_t = make_uint_t(9)
uint10_t = make_uint_t(10)
uint11_t = make_uint_t(11)
uint12_t = make_uint_t(12)
uint13_t = make_uint_t(13)
uint14_t = make_uint_t(14)
uint15_t = make_uint_t(15)
uint16_t = make_uint_t(16)
uint17_t = make_uint_t(17)
uint18_t = make_uint_t(18)
uint24_t = make_uint_t(24)
uint32_t = make_uint_t(32)
uint33_t = make_uint_t(33)
uint34_t = make_uint_t(34)
uint48_t = make_uint_t(48)
uint64_t = make_uint_t(64)

# ── signed integer types ──────────────────────
int2_t = make_int_t(2)
int3_t = make_int_t(3)
int4_t = make_int_t(4)
int5_t = make_int_t(5)
int6_t = make_int_t(6)
int7_t = make_int_t(7)
int8_t = make_int_t(8)
int9_t = make_int_t(9)
int10_t = make_int_t(10)
int11_t = make_int_t(11)
int12_t = make_int_t(12)
int13_t = make_int_t(13)
int14_t = make_int_t(14)
int15_t = make_int_t(15)
int16_t = make_int_t(16)
int32_t = make_int_t(32)
int33_t = make_int_t(33)
int64_t = make_int_t(64)

# ─────────────────────────────────────────────
# C-type-string helpers (shared with PY_TO_LOGIC)
# ─────────────────────────────────────────────
import re as _re_ctype

_INT_CTYPE_RE = _re_ctype.compile(r"(u?)int(\d+)_t$")


@_functools.lru_cache(maxsize=None)
def _ctype_is_int(c_type: str) -> bool:
    """True if c_type is a plain integer type (uint/int)."""
    return bool(_INT_CTYPE_RE.match(c_type))


@_functools.lru_cache(maxsize=None)
def _infer_literal_ctype(val: int):
    """Minimum C type string for a plain Python int, matching PY_TO_LOGIC._infer_const_ctype.

    Used by SimVal arithmetic to infer the hardware type of integer literals that carry
    no SimVal ctype, so that mixed SimVal/literal operations apply the same unsigned
    wrapping that PY_TO_LOGIC produces in hardware.
    Returns None for non-integers or booleans (handled separately by hardware elaborator).
    """
    if not isinstance(val, int) or isinstance(val, bool):
        return None
    if val in (0, 1):
        return "uint1_t"
    if val > 1:
        return f"uint{val.bit_length()}_t"
    bits = max(1, (-val - 1).bit_length() + 1)
    return f"int{bits}_t"


@_functools.lru_cache(maxsize=None)
def _ctype_info(c_type: str):
    """Parse integer C type string. Returns (is_signed, width).
    e.g. 'uint32_t' -> (False, 32),  'int16_t' -> (True, 16)
    """
    m = _INT_CTYPE_RE.match(c_type)
    if not m:
        raise NotImplementedError(f"Cannot get integer type info from: {c_type!r}")
    return (m.group(1) != "u", int(m.group(2)))


def _int_ctype(is_signed: bool, width: int) -> str:
    """Build integer C type string. e.g. (True, 32) -> 'int32_t'"""
    return f"{'int' if is_signed else 'uint'}{width}_t"


@_functools.lru_cache(maxsize=None)
def _arith_promote(l_type: str, r_type: str):
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
    return _int_ctype(True, l_w + 1), r_type, True  # promote l to signed


@_functools.lru_cache(maxsize=None)
def _arith_output_ctype(op: str, eff_l_type: str, eff_r_type: str, result_signed: bool):
    """Full-precision output ctype OBJECT for an arithmetic op (after sign promotion).

    op: "add" | "sub" | "mul" | "div" | "mod"
    Returns a _CTypeMeta ctype object (e.g. make_int_t(17)).
    Width rules:
      add  -> max(lw, rw) + 1
      sub  -> max+1 (signed), max (unsigned)
      mul  -> lw + rw
      div/mod -> max(lw, rw)
    """
    _, l_w = _ctype_info(eff_l_type)
    _, r_w = _ctype_info(eff_r_type)
    max_w = max(l_w, r_w)
    if op == "add":
        out_w = max_w + 1
    elif op == "sub":
        out_w = (max_w + 1) if result_signed else max_w
    elif op == "mul":
        out_w = l_w + r_w
    else:
        out_w = max_w
    return make_int_t(out_w) if result_signed else make_uint_t(out_w)


# ─────────────────────────────────────────────
# NamedTuple with automatic subscript support
# ─────────────────────────────────────────────


def _mangle_type(s):
    """Remove array brackets for VHDL-compatible name mangling: uint32_t[2] -> uint32_t_2."""
    return s.replace("[", "_").replace("]", "")


def _struct_class_getitem(cls, dim):
    """Enables point_t[10] -> _make_ctype('point_t[10]') using the canonical C type name."""
    name = getattr(cls, "_pypeline_ctype_name", cls.__name__)
    arr = _make_ctype(f"{name}[{dim}]")
    arr._elem_ctype = cls
    return arr


@_functools.lru_cache(maxsize=None)
def _is_scalar_pypeline_int(ctype):
    """True for scalar uint/int types; False for array types (uint32_t[N]) and structs."""
    if not hasattr(ctype, "_ctype_name"):
        return False
    try:
        _ = (
            ctype.width
        )  # raises NotImplementedError for arrays, AttributeError for structs
        return True
    except (NotImplementedError, AttributeError):
        return False


# ─────────────────────────────────────────────
# SimVal — simulation-mode integer
# Defined here (before @struct) so _typed_new can reference it.
# Method bodies reference _unary_operator_registry etc. which are defined
# later in this module; that is fine because methods are only called at runtime.
# ─────────────────────────────────────────────


class SimVal(int):
    """Thin int subclass that carries a pypeline ctype and supports bit-slicing.

    Used in simulation mode: struct constructors produce SimVal fields, and
    arithmetic / operator-dispatch propagates type information through the call graph.
    SimVal is a subclass of int, so it is transparent to the hardware elaborator.

    PERF NOTE: All type-checks use `type(x) is SimVal` rather than isinstance —
    subclassing SimVal is prohibited as a performance constraint.
    """

    def __new__(cls, value=0, ctype=None):
        obj = _int_new(cls, int(value))
        _obj_setattr(obj, "_ctype", ctype)
        return obj

    def __getitem__(self, key):
        """Bit slice: x[bit] → uint1 value, x[hi:lo] → (hi-lo+1)-bit value."""
        if isinstance(key, int):
            return SimVal((int(self) >> key) & 1)
        hi, lo = key.start, key.stop  # hardware convention: x[hi:lo]
        return SimVal((int(self) >> lo) & ((1 << (hi - lo + 1)) - 1))

    def _dispatch_unary(self, op_name, fallback):
        if self._ctype is not None:
            fn = _unary_operator_registry.get((op_name, _ctype_str(self._ctype)))
            if callable(fn):
                result = fn(self)
                if type(result) is not SimVal or result._ctype is None:
                    ret_t = getattr(
                        getattr(fn, "__wrapped__", fn), "__annotations__", {}
                    ).get("return")
                    if ret_t is not None:
                        return _sim_cast(result, ret_t)
                return result
        return SimVal(fallback)

    def __neg__(self):
        v = -int(self)
        if self._ctype is None or "NEGATE" in _registered_unary_op_names:
            return self._dispatch_unary("NEGATE", v)
        if SIM_STRICT_ARITH:
            try:
                mask, sign_bit, is_signed = _sim_cast_param_cache[self._ctype]
            except KeyError:
                mask, sign_bit, is_signed = _sim_type_init(self._ctype)
            v = v & mask
            if is_signed and v >= sign_bit:
                v -= mask + 1
        return _sim_val_make(v, self._ctype)

    def __invert__(self):
        v = ~int(self)
        if self._ctype is None or "NOT" in _registered_unary_op_names:
            return self._dispatch_unary("NOT", v)
        if SIM_STRICT_ARITH:
            try:
                mask, sign_bit, is_signed = _sim_cast_param_cache[self._ctype]
            except KeyError:
                mask, sign_bit, is_signed = _sim_type_init(self._ctype)
            v = v & mask
            if is_signed and v >= sign_bit:
                v -= mask + 1
        return _sim_val_make(v, self._ctype)

    def _dispatch_binary(self, op_name, other, fallback_int, preserve_ctype=False):
        if self._ctype is not None:
            l_str = _ctype_str(self._ctype)
            rc = other._ctype if type(other) is SimVal else None
            fn = rc and _operator_registry.get((op_name, l_str, _ctype_str(rc)))
            fn = fn or _left_operator_registry.get((op_name, l_str))
            if callable(fn):
                result = fn(self, other)
                if type(result) is not SimVal or result._ctype is None:
                    ret_t = getattr(
                        getattr(fn, "__wrapped__", fn), "__annotations__", {}
                    ).get("return")
                    if ret_t is not None:
                        return _sim_cast(result, ret_t)
                return result
            # No registered operator. For shifts: PY_TO_LOGIC output type = left operand
            # type (constant-shift built-in keeps l_type). Preserve ctype so downstream
            # arithmetic can apply the correct unsigned/signed wrapping.
            if preserve_ctype:
                return _sim_cast(fallback_int, self._ctype)
        return SimVal(fallback_int)

    def __rshift__(self, o):
        v = int(self) >> int(o)
        if SIM_RAW_INTS:
            return v
        if self._ctype is None or "SR" in _registered_binary_op_names:
            return self._dispatch_binary("SR", o, v, preserve_ctype=True)
        return _sim_val_make(v, self._ctype)

    def __lshift__(self, o):
        v = int(self) << int(o)
        if SIM_RAW_INTS:
            return v
        if self._ctype is None or "SL" in _registered_binary_op_names:
            return self._dispatch_binary("SL", o, v, preserve_ctype=True)
        if SIM_STRICT_ARITH:
            try:
                mask, sign_bit, is_signed = _sim_cast_param_cache[self._ctype]
            except KeyError:
                mask, sign_bit, is_signed = _sim_type_init(self._ctype)
            v = v & mask
            if is_signed and v >= sign_bit:
                v -= mask + 1
        return _sim_val_make(v, self._ctype)

    # Arithmetic with hardware type-promotion when both operands have known ctypes.
    # SIM_STRICT_ARITH (default True) applies masking to the result so that
    # intermediate values wrap identically to hardware. Set False for faster sim.
    #
    # When the other operand is a plain Python int (no _ctype), its hardware type is
    # inferred via _infer_literal_ctype — the same minimum-bit-width rule that
    # PY_TO_LOGIC uses for integer literals.  This ensures that, e.g.,
    #   uint12_t_val - 641   →  uint12_t result (unsigned wrap, not signed Python int)
    # matching what hardware produces for the expression `signal - CONSTANT`.
    def __add__(self, o):
        ov = int(o)
        if SIM_RAW_INTS:
            return int(self) + ov
        result = int(self) + ov
        if SIM_STRICT_ARITH and self._ctype is not None:
            rc = o._ctype if type(o) is SimVal else _infer_literal_ctype(ov)
            if rc is not None:
                l_name = self._ctype._ctype_name
                r_name = rc if isinstance(rc, str) else rc._ctype_name
                eff_l, eff_r, rsig = _arith_promote(l_name, r_name)
                if rsig is not None:
                    out_ctype = _arith_output_ctype("add", eff_l, eff_r, rsig)
                    try:
                        mask, sign_bit, is_signed = _sim_cast_param_cache[out_ctype]
                    except KeyError:
                        mask, sign_bit, is_signed = _sim_type_init(out_ctype)
                    v = result & mask
                    if is_signed and v >= sign_bit:
                        v -= mask + 1
                    return _sim_val_make(v, out_ctype)
        return SimVal(result)

    def __sub__(self, o):
        ov = int(o)
        if SIM_RAW_INTS:
            return int(self) - ov
        result = int(self) - ov
        if SIM_STRICT_ARITH and self._ctype is not None:
            rc = o._ctype if type(o) is SimVal else _infer_literal_ctype(ov)
            if rc is not None:
                l_name = self._ctype._ctype_name
                r_name = rc if isinstance(rc, str) else rc._ctype_name
                eff_l, eff_r, rsig = _arith_promote(l_name, r_name)
                if rsig is not None:
                    out_ctype = _arith_output_ctype("sub", eff_l, eff_r, rsig)
                    try:
                        mask, sign_bit, is_signed = _sim_cast_param_cache[out_ctype]
                    except KeyError:
                        mask, sign_bit, is_signed = _sim_type_init(out_ctype)
                    v = result & mask
                    if is_signed and v >= sign_bit:
                        v -= mask + 1
                    return _sim_val_make(v, out_ctype)
        return SimVal(result)

    def __mul__(self, o):
        ov = int(o)
        if SIM_RAW_INTS:
            return int(self) * ov
        result = int(self) * ov
        if SIM_STRICT_ARITH and self._ctype is not None:
            rc = o._ctype if type(o) is SimVal else _infer_literal_ctype(ov)
            if rc is not None:
                l_name = self._ctype._ctype_name
                r_name = rc if isinstance(rc, str) else rc._ctype_name
                eff_l, eff_r, rsig = _arith_promote(l_name, r_name)
                if rsig is not None:
                    out_ctype = _arith_output_ctype("mul", eff_l, eff_r, rsig)
                    try:
                        mask, sign_bit, is_signed = _sim_cast_param_cache[out_ctype]
                    except KeyError:
                        mask, sign_bit, is_signed = _sim_type_init(out_ctype)
                    v = result & mask
                    if is_signed and v >= sign_bit:
                        v -= mask + 1
                    return _sim_val_make(v, out_ctype)
        return SimVal(result)

    def __and__(self, o):
        if SIM_RAW_INTS:
            return int(self) & int(o)
        return SimVal(int(self) & int(o))

    def __or__(self, o):
        if SIM_RAW_INTS:
            return int(self) | int(o)
        return SimVal(int(self) | int(o))

    def __xor__(self, o):
        if SIM_RAW_INTS:
            return int(self) ^ int(o)
        return SimVal(int(self) ^ int(o))

    # Reflected arithmetic: plain-int op SimVal. Apply full SIM_STRICT_ARITH so that
    # `CONSTANT - typed_signal` wraps the same way hardware does (e.g. 481 - uint12_t).
    # `o` is always a non-SimVal here (Python only calls __radd__ when the left operand
    # didn't handle it), so int(o) is fine.
    def __radd__(self, o):
        if SIM_RAW_INTS:
            return int(o) + int(self)
        result = int(o) + int(self)
        if SIM_STRICT_ARITH and self._ctype is not None:
            lc = _infer_literal_ctype(int(o))
            if lc is not None:
                eff_l, eff_r, rsig = _arith_promote(lc, self._ctype._ctype_name)
                if rsig is not None:
                    return _sim_cast(
                        result, _arith_output_ctype("add", eff_l, eff_r, rsig)
                    )
        return SimVal(result)

    def __rsub__(self, o):
        if SIM_RAW_INTS:
            return int(o) - int(self)
        result = int(o) - int(self)
        if SIM_STRICT_ARITH and self._ctype is not None:
            lc = _infer_literal_ctype(int(o))
            if lc is not None:
                eff_l, eff_r, rsig = _arith_promote(lc, self._ctype._ctype_name)
                if rsig is not None:
                    return _sim_cast(
                        result, _arith_output_ctype("sub", eff_l, eff_r, rsig)
                    )
        return SimVal(result)

    def __rlshift__(self, o):
        if SIM_RAW_INTS:
            return int(o) << int(self)
        return SimVal(int(o) << int(self))

    def __rrshift__(self, o):
        if SIM_RAW_INTS:
            return int(o) >> int(self)
        return SimVal(int(o) >> int(self))


class _RawField(int):
    """Bare int subclass used for struct fields in SIM_RAW_INTS mode.

    Inherits all arithmetic from int (C-level, no Python dispatch overhead).
    Only adds __getitem__ so struct.field[bit] still works in raw mode.
    Arithmetic results are plain Python ints — the SimVal type system is not entered.
    """

    __slots__ = ()

    def __getitem__(self, key):
        v = int(self)
        if isinstance(key, int):
            return (v >> key) & 1
        hi, lo = key.start, key.stop  # hardware convention: x[hi:lo]
        return (v >> lo) & ((1 << (hi - lo + 1)) - 1)


# Pre-bind low-level constructors so _sim_cast and arithmetic ops can create SimVals
# without going through SimVal.__new__ (a Python function call = ~0.1µs overhead).
_int_new = int.__new__
_obj_setattr = object.__setattr__

# Flyweight cache: (int_value, ctype) → SimVal for values 0..15 per ctype.
# Mirrors CPython's own small-int cache. Populated lazily via _sim_type_init.
_SIM_CONST_CACHE: dict = {}
_SIM_CONST_MAX = 15


def _sim_val_make(v, ctype):
    """Create a typed SimVal, returning a cached flyweight for small non-negative values."""
    if 0 <= v <= _SIM_CONST_MAX:
        cached = _SIM_CONST_CACHE.get((v, ctype))
        if cached is not None:
            return cached
    obj = _int_new(SimVal, v)
    _obj_setattr(obj, "_ctype", ctype)
    return obj


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

    def _typeof(cls, field_name):
        return cls.__annotations__[field_name]

    cls.typeof = classmethod(_typeof)
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

    # Override __new__ so that scalar integer fields are auto-wrapped in SimVals.
    # This makes float32_t(sign=0, exp=127, man=0) produce typed SimVal fields for
    # simulation without requiring a separate constructor. SimVal subclasses int, so
    # the hardware elaborator sees plain integers and is unaffected.
    _orig_new = cls.__new__

    def _typed_new(klass, *args, **kwargs):
        if args and not kwargs:
            kwargs = dict(zip(klass._fields, args))
        typed = {}
        if SIM_RAW_INTS:
            for fname, v in kwargs.items():
                ftype = klass.__annotations__.get(fname)
                if (
                    ftype is not None
                    and (type(v) is int or type(v) is SimVal)
                    and _is_scalar_pypeline_int(ftype)
                ):
                    v = _RawField(int(v))
                elif ftype is not None and type(v) is list:
                    elem_ftype = _array_elem_ctype(ftype)
                    if elem_ftype is not None and _is_scalar_pypeline_int(elem_ftype):
                        v = [
                            _RawField(int(e)) if type(e) in (int, SimVal) else e
                            for e in v
                        ]
                typed[fname] = v
        else:
            for fname, v in kwargs.items():
                ftype = klass.__annotations__.get(fname)
                if (
                    ftype is not None
                    and (type(v) is int or type(v) is SimVal)
                    and _is_scalar_pypeline_int(ftype)
                ):
                    if type(v) is not SimVal or v._ctype is None:
                        # Inline allocation: bypass SimVal.__new__ Python call frame.
                        obj = _int_new(SimVal, int(v))
                        _obj_setattr(obj, "_ctype", ftype)
                        v = obj
                elif ftype is not None and type(v) is list:
                    # Array-of-scalar field passed a raw Python list (e.g. a list
                    # literal): cast each element so it carries the field's bit width,
                    # matching the per-field scalar wrap above. Struct/array elements
                    # are left untouched -- they self-type via their own constructor.
                    elem_ftype = _array_elem_ctype(ftype)
                    if elem_ftype is not None and _is_scalar_pypeline_int(elem_ftype):
                        v = [_sim_cast(e, elem_ftype) for e in v]
                typed[fname] = v
        return _orig_new(klass, **typed)

    cls.__new__ = staticmethod(_typed_new)
    return cls


# ─────────────────────────────────────────────
# MAIN decorator and pragma registries
# ─────────────────────────────────────────────

_main_registry: list = []
_main_mhz_registry: dict = {}  # func.__name__ → float mhz
_part_registry: "str | None" = None


def PART(part_string: str):
    """Set the global FPGA target part (equivalent to #pragma PART "...").

    Call once at module level, e.g.::

        PART("xc7a35ticsg324-1l")
    """
    global _part_registry
    _part_registry = part_string


def _register_main(func, mhz):
    if mhz is not None:
        _main_mhz_registry[func.__name__] = float(mhz)
    wrapped = _sim_type_wrap(func)
    _main_registry.append(wrapped)
    return wrapped


def MAIN(func_or_mhz=None, *, mhz=None):
    """Marks a function as a top-level hardware process.

    Supports three forms::

        @MAIN                  # no clock constraint
        @MAIN(100.0)           # positional MHz
        @MAIN(mhz=100.0)       # keyword MHz

    Implies @hw_func: inputs/outputs are type-cast for simulation and
    the function can be passed to sim_call().
    """
    if callable(func_or_mhz):
        # Used as bare @MAIN with no arguments
        return _register_main(func_or_mhz, mhz=None)
    else:
        # Used as @MAIN(100.0) or @MAIN(mhz=100.0)
        if func_or_mhz is not None:
            mhz = float(func_or_mhz)

        def decorator(func):
            return _register_main(func, mhz=mhz)

        return decorator


def sim_output(fn):
    """Mark a function as simulation output-only.

    Calls to @sim_output functions are skipped (return SimVal(0)) during
    delta-cycle convergence passes and execute normally in the final
    post-convergence pass each clock cycle. Use this for side effects such
    as print, file writes, or live display updates that should fire exactly
    once per cycle with the correct converged wire values.
    """

    @_functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if _sim_converging:
            return SimVal(0)
        return fn(*args, **kwargs)

    wrapper._is_sim_output = True
    return wrapper


def autopipeline(call_result, depth: int = -1):
    """Force pipelining through the wrapped function call (equivalent to
    PipelineC's `#pragma AUTOPIPELINE <depth>`).

    Wrap a single direct function call::

        rv = autopipeline(some_func(x))        # auto depth
        rv = autopipeline(some_func(x), 2)      # explicit depth
        rv = autopipeline(some_func(x), depth=2)

    Identity passthrough in proto-simulation. The elaborator unwraps this to
    elaborate `some_func(x)` as the real submodule instance and tags it with
    the given depth; `autopipeline(...)` itself produces no hardware. If the
    wrapped call's *arguments* themselves contain function calls, those
    nested calls are tagged first (same "next instantiation" semantics as
    the underlying PipelineC C pragma).
    """
    return call_result


autopipeline._is_autopipeline_pragma = True


# ─────────────────────────────────────────────
# Operator overloading registry
# ─────────────────────────────────────────────


@_functools.lru_cache(maxsize=None)
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
# Set of op_name strings that have at least one global (non-scoped) registration.
# Used by __rshift__/__lshift__ to skip _dispatch_binary when no operators are registered.
_registered_binary_op_names: set = set()

# Parallel set for unary ops — used by __neg__/__invert__ to skip _dispatch_unary.
_registered_unary_op_names: set = set()

# Scoped registrations: active only while elaborating the keyed function.
# id(func) -> {registry_key: name_or_callable}
_scoped_operator_registry: dict = {}
_scoped_left_operator_registry: dict = {}
_scoped_unary_operator_registry: dict = {}
# Fast-lookup set: id(func) for any func that has at least one scoped registration.
# Allows _push_scoped_registrations to short-circuit with a single O(1) check.
_scoped_funcs: set = set()


def register_operator(op: str, left_type, right_type, func, scope=None) -> None:
    """Register a hardware function as the implementation of a variable binary operator.
    Matches on both left and right operand types (exact match).

    op:         "SL" (<<) or "SR" (>>)
    left_type:  C type of the left operand (e.g. uint32_t)
    right_type: C type of the right operand / shift amount (e.g. uint6_t)
    func:       callable hardware function object.
    scope:      if provided, registration is active only while elaborating that callable.
    """
    key = (op, _ctype_str(left_type), _ctype_str(right_type))
    if scope is None:
        _operator_registry[key] = func
        _registered_binary_op_names.add(op)
    else:
        _scoped_funcs.add(id(scope))
        _scoped_operator_registry.setdefault(id(scope), {})[key] = func


def register_left_operator(op: str, left_type, func, scope=None) -> None:
    """Register a hardware function as the implementation of a binary operator,
    matching only on the left operand type. The right operand type is derived
    from the registered function (e.g. shift amount derived from value width).

    op:        "SL" (<<) or "SR" (>>)
    left_type: C type of the left operand (e.g. uint32_t)
    func:      callable hardware function object.
    scope:     if provided, registration is active only while elaborating that callable.
    """
    key = (op, _ctype_str(left_type))
    if scope is None:
        _left_operator_registry[key] = func
        _registered_binary_op_names.add(op)
    else:
        _scoped_funcs.add(id(scope))
        _scoped_left_operator_registry.setdefault(id(scope), {})[key] = func


def register_unary_operator(op: str, operand_type, func, scope=None) -> None:
    """Register a hardware function as the implementation of a unary operator.

    op:           "NEGATE" (-) or "NOT" (~)
    operand_type: C type of the operand (e.g. uint32_t)
    func:         callable hardware function object.
    scope:        if provided, registration is active only while elaborating that callable.
    """
    key = (op, _ctype_str(operand_type))
    if scope is None:
        _unary_operator_registry[key] = func
        _registered_unary_op_names.add(op)
    else:
        _scoped_funcs.add(id(scope))
        _scoped_unary_operator_registry.setdefault(id(scope), {})[key] = func


def _push_scoped_registrations(func):
    """Merge scoped operator registrations for *func* into the active global registries.
    Returns a list of (registry, key, old_value) triples for restoring afterward.
    Scoped entries from outer elaboration frames are already present in the global
    registries, so inner callees automatically inherit them.
    """
    func_id = id(func)
    if func_id not in _scoped_funcs:
        return _EMPTY_SAVED
    saved = []
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


_SCOPED_MISSING = object()  # sentinel for _pop_scoped_registrations; created once
_EMPTY_SAVED = []  # returned by _push_scoped_registrations when nothing to push


def _pop_scoped_registrations(saved):
    """Restore registry entries to their pre-push state."""
    for registry, key, old_val in saved:
        if old_val is None:
            registry.pop(key, _SCOPED_MISSING)
        else:
            registry[key] = old_val


# ─────────────────────────────────────────────
# Reg[T] — hardware state register annotation
# ─────────────────────────────────────────────


class _MultiCycleRole:
    """One endpoint (.start or .end) of a MULTI_CYCLE[...] tag. Produced by
    MULTI_CYCLE[ncycles].start / .end, consumed by Reg[T, role] to mark that
    register declaration as one end of a multi-cycle timing path."""

    def __init__(self, tag, is_start):
        self.tag = tag
        self.is_start = is_start


class _MultiCycleTag:
    """Returned by MULTI_CYCLE[ncycles]. Tag exactly two Reg[T] declarations
    with .start / .end (equivalent of PipelineC's
    `#pragma MULTI_CYCLE <ncycles> <start_reg> <end_reg>`):

        MC = MULTI_CYCLE[32]
        data0: Reg[my_struct_t, MC.start]
        data1: Reg[my_struct_t, MC.end]
    """

    def __init__(self, ncycles):
        self.ncycles = ncycles
        self.start = _MultiCycleRole(self, is_start=True)
        self.end = _MultiCycleRole(self, is_start=False)


class _MultiCycleMeta(type):
    def __getitem__(cls, ncycles):
        if not isinstance(ncycles, int):
            raise TypeError(f"MULTI_CYCLE[ncycles] expects an int, got {ncycles!r}")
        return _MultiCycleTag(ncycles)


class MULTI_CYCLE(metaclass=_MultiCycleMeta):
    """MULTI_CYCLE[ncycles] — tag for two Reg[T] declarations forming a
    multi-cycle timing path (equivalent of PipelineC's
    `#pragma MULTI_CYCLE <ncycles> <start_reg> <end_reg>`).

    Usage:
        MC = MULTI_CYCLE[32]
        data0: Reg[my_struct_t, MC.start]
        data1: Reg[my_struct_t, MC.end]
    """

    pass


class _RegType:
    """Produced by Reg[T] or Reg[T, MULTI_CYCLE[...].start/.end].
    Marks a variable as a hardware register (flip-flop)."""

    def __init__(self, inner_ctype, multi_cycle_role=None):
        self.inner_ctype = inner_ctype  # a _CTypeMeta class or array ctype
        self.multi_cycle_role = multi_cycle_role  # _MultiCycleRole or None

    def __str__(self):
        return f"Reg[{self.inner_ctype}]"

    def __repr__(self):
        return str(self)


class _RegMeta(type):
    def __getitem__(cls, inner_type):
        if isinstance(inner_type, tuple):
            if len(inner_type) != 2 or not isinstance(inner_type[1], _MultiCycleRole):
                raise TypeError(
                    "Reg[T, tag] second argument must be a MULTI_CYCLE[...].start "
                    "or .end role"
                )
            base_type, role = inner_type
            return _RegType(base_type, multi_cycle_role=role)
        return _RegType(inner_type)


class Reg(metaclass=_RegMeta):
    """Marks a local variable as a hardware state register (persistent between cycles).

    Usage in hardware functions:
        acc: Reg[uint32_t]      # register, initialized to 0 at power-on
        acc = acc + data_in     # read current value; write sets next-cycle value

    A register may also be tagged as one end of a multi-cycle timing path:
        MC = MULTI_CYCLE[32]
        data0: Reg[my_struct_t, MC.start]
        data1: Reg[my_struct_t, MC.end]
    """

    pass


# Feedback[T] — combinatorial feedback wire annotation
# ──────────────────────────────────────────────────────


class _FeedbackType:
    """Produced by Feedback[T]. Marks a variable as a combinatorial feedback wire."""

    def __init__(self, inner_ctype):
        self.inner_ctype = inner_ctype

    def __str__(self):
        return f"Feedback[{self.inner_ctype}]"

    def __repr__(self):
        return str(self)


class _FeedbackMeta(type):
    def __getitem__(cls, inner_type):
        return _FeedbackType(inner_type)


class Feedback(metaclass=_FeedbackMeta):
    """Marks a local variable as a combinatorial feedback wire.

    Usage in hardware functions:
        f: Feedback[uint1_t]   # declare feedback — NOT zero-initialised
        rv = f | a             # use f before its driver is known
        f = ~b                 # driver resolved; back-patched at end of elaboration
    """

    pass


# Wire[T] — global combinatorial wire annotation
# ───────────────────────────────────────────────


class _WireType:
    """Produced by Wire[T]. Marks a module-level variable as a global combinatorial wire."""

    def __init__(self, inner_ctype):
        self.inner_ctype = inner_ctype

    def __str__(self):
        return f"Wire[{self.inner_ctype}]"

    def __repr__(self):
        return str(self)


class _WireMeta(type):
    def __getitem__(cls, inner_type):
        return _WireType(inner_type)


class Wire(metaclass=_WireMeta):
    """Marks a module-level variable as a global combinatorial wire.

    Usage at module level only:
        my_sig: Wire[uint1_t]   # global combinatorial wire

    Exactly one function may write to it; any number of functions may read from it.
    Wire[T] inside a function body is an ElaborationError.
    """

    pass


# Input[T] / Output[T] — top-level module I/O port annotations
# ──────────────────────────────────────────────────────────────


class _InputType:
    """Produced by Input[T]. Marks a module-level variable as a top-level design input."""

    def __init__(self, inner_ctype):
        self.inner_ctype = inner_ctype

    def __str__(self):
        return f"Input[{self.inner_ctype}]"

    def __repr__(self):
        return str(self)


class _InputMeta(type):
    def __getitem__(cls, inner_type):
        return _InputType(inner_type)


class Input(metaclass=_InputMeta):
    """Marks a module-level variable as a top-level design input port.

    Usage at module level only:
        my_in: Input[uint1_t]

    Any number of functions may read it; no function may write it.
    Input[T] inside a function body is an ElaborationError.
    """

    pass


class _OutputType:
    """Produced by Output[T]. Marks a module-level variable as a top-level design output."""

    def __init__(self, inner_ctype):
        self.inner_ctype = inner_ctype

    def __str__(self):
        return f"Output[{self.inner_ctype}]"

    def __repr__(self):
        return str(self)


class _OutputMeta(type):
    def __getitem__(cls, inner_type):
        return _OutputType(inner_type)


class Output(metaclass=_OutputMeta):
    """Marks a module-level variable as a top-level design output port.

    Usage at module level only:
        my_out: Output[uint1_t]

    Exactly one function (with exactly one hierarchy instance) may write it.
    Output[T] inside a function body is an ElaborationError.
    """

    pass


# ─────────────────────────────────────────────
# Bit manipulation primitives
# (intercepted by PY_TO_LOGIC elaborator; not callable at Python runtime)
# ─────────────────────────────────────────────
# Bit slice / select: use subscript syntax on integer wires
#   y = x[15]       # single bit  → uint1_t
#   z = x[15:0]     # range       → uint16_t


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


def concat(*args):
    """Bit concatenation for simulation: first arg = MSBits, last = LSBits.

    Width of each argument is inferred from its SimVal ctype (via len(ctype)) or,
    for plain Python ints, from max(1, val.bit_length()). The result is a SimVal
    with ctype = make_uint_t(total_bits).

    In hardware (PY_TO_LOGIC elaboration) this function is intercepted and treated
    as variadic tuple concat — see the 'concat' branch in _elab_bit_manip_call.
    """
    widths = []
    for a in args:
        if type(a) is SimVal and a._ctype is not None:
            widths.append(len(a._ctype))
        elif type(a) is int or type(a) is SimVal:
            widths.append(max(1, int(a).bit_length()))
        else:
            raise TypeError(f"concat: cannot infer bit width for {a!r}")
    total = sum(widths)
    result = 0
    for a, w in zip(args, widths):
        result = (result << w) | (int(a) & ((1 << w) - 1))
    return SimVal(result, ctype=make_uint_t(total))


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
        "concat",
    }
)


# ─────────────────────────────────────────────
# Raw VHDL passthrough
# (intercepted by PY_TO_LOGIC elaborator; not callable at Python runtime)
# ─────────────────────────────────────────────


def vhdl(vhdl_text):
    """Raw VHDL passthrough: replaces the entire calling function's body with
    literal VHDL text spliced into the generated entity's architecture. Must be
    the only statement in the function body. Equivalent to C's __vhdl__("...").

    Unlike the bit manipulation primitives above, there is no general way to
    simulate arbitrary user-supplied VHDL text in Python, so this function has
    no dual-mode simulation behavior: it always raises when actually called
    (i.e. outside hardware elaboration, which recognizes vhdl(...) structurally
    by AST and never executes this body).
    """
    raise NotImplementedError(
        "vhdl(...) has no simulation model yet. It can only be used inside "
        "hardware-elaborated functions — calling it directly, via sim_call(), or "
        "via pypeline_sim.py is not yet supported. (A future hook will let you "
        "attach a Python simulation model to a specific vhdl(...) block.)"
    )


# ─────────────────────────────────────────────
# Sim infrastructure: _sim_cast, _sim_type_wrap / hw_func, sim_call
# ─────────────────────────────────────────────

import functools as _functools
import inspect as _inspect
import sys as _sys
import dis as _dis
import ast as _ast
import textwrap as _textwrap
import types as _types


# ─────────────────────────────────────────────
# Sim register state: instance path tracking and per-instance register storage
# ─────────────────────────────────────────────

# Stack of (func_qualname, call_loc) entries tracking the current simulation
# instance path. call_loc = (filename, lineno, col_offset, end_col_offset),
# mirroring the hardware elaborator's _loc_str(src_file, node) convention.
_sim_inst_stack = []

# Register state keyed by instance path tuple.
# _sim_reg_state[inst_path][reg_name] = current integer value (0 = reset default).
_sim_reg_state = {}

# Maximum convergence iterations for Feedback[T] simulation.
# Combinatorial feedback must reach a fixed point in far fewer iterations than this.
_SIM_FEEDBACK_MAX_ITER = 1000

# Simulation accuracy mode flags.
# These are normally set together by pypeline_sim.py --sim-mode before the
# design is imported (decorators read them at decoration time).
#
# strict (default): SIM_STRICT_ARITH=True,  SIM_RAW_INTS=False
#   Full hardware accuracy. Every arithmetic op masks to declared bit width.
#   Slowest, but results match hardware exactly.
#
# loose:            SIM_STRICT_ARITH=False, SIM_RAW_INTS=False
#   Values stay as typed SimVal objects so bit-indexing (x[n], x[hi:lo])
#   works everywhere, but arithmetic uses Python-precision (no masking).
#
# raw:              SIM_STRICT_ARITH=False, SIM_RAW_INTS=True
#   Maximum speed. Arithmetic returns plain Python ints; function boundaries
#   do no casting. Bit-indexing on arithmetic results will not work
#   (struct field access x.field[n] still works).

# When True, SimVal arithmetic applies hardware type-promotion and _sim_cast,
# matching hardware wrap-on-overflow. Set False for faster Python-precision sim.
SIM_STRICT_ARITH: bool = True

# When True, bypass ALL SimVal wrapping, type casting, and bit-width masking.
# SIM_RAW_INTS=True implies SIM_STRICT_ARITH is irrelevant (casting is skipped).
# Read at @hw_func decoration time — must be set before importing the design.
SIM_RAW_INTS: bool = False

# When True, @hw_func wrappers capture exact call-site column numbers via
# co_positions() for uniquely naming multi-instance register hierarchies.
# False (default) uses only filename+lineno, skipping the O(instructions) co_positions
# scan and bypassing frame capture entirely for pure-combinatorial functions.
# Enable when simulating designs where the same Reg[T] function is instantiated
# at multiple call sites (i.e. multi-instance register hierarchies).
SIM_TRACE_LOCATIONS: bool = False

# Global wire simulation state.
_sim_wire_state: dict = {}  # wire name → current int value
_sim_converging: bool = False  # True during delta-cycle convergence passes
_sim_reg_write_buffer = None  # None = direct commit; dict = buffered mode
_sim_current_main = None  # MAIN fn currently executing (for reader tracking)
_sim_wire_readers: dict = {}  # wire name → set of MAINs that have read it
_sim_active: bool = False  # True only while pypeline_sim.py is driving a simulation run


def _sim_current_inst_path():
    """Return the current simulation instance path as an immutable tuple."""
    return tuple(_sim_inst_stack)


def _is_compound_pypeline_type(ctype):
    """True for struct (NamedTuple) or array ctypes; False for scalars and the
    Reg/Feedback/Wire/Input/Output descriptor objects (none of which carry
    _fields or _ctype_name)."""
    if hasattr(ctype, "_fields"):
        return True
    if hasattr(ctype, "_ctype_name") and "[" in ctype._ctype_name:
        return True
    return False


def _array_elem_ctype(ctype):
    """Return the element ctype of an array ctype (preferring _elem_ctype, falling back
    to stripping the trailing [N] from _ctype_name), or None if ctype is not an array."""
    if not hasattr(ctype, "_ctype_name"):
        return None
    m = _re_ctype.search(r"\[(\d+)\]$", ctype._ctype_name)
    if not m:
        return None
    return getattr(ctype, "_elem_ctype", None) or _make_ctype(
        ctype._ctype_name[: m.start()]
    )


def _array_len(ctype):
    """Return the trailing [N] dimension of an array ctype, or None if not an array."""
    if not hasattr(ctype, "_ctype_name"):
        return None
    m = _re_ctype.search(r"\[(\d+)\]$", ctype._ctype_name)
    return int(m.group(1)) if m else None


def _make_sim_zero(ctype):
    """Return a zero-initialized simulation value for the given pypeline ctype."""
    if hasattr(ctype, "_fields"):
        return ctype(*(_make_sim_zero(ctype.__annotations__[f]) for f in ctype._fields))
    elem_ctype = _array_elem_ctype(ctype)
    if elem_ctype is not None:
        n = _array_len(ctype)
        return [_make_sim_zero(elem_ctype) for _ in range(n)]
    return _sim_cast(0, ctype)


def _sim_cast_deep(value, ctype):
    """Cast value to ctype, recursing through arrays so every scalar leaf becomes a
    typed SimVal -- mirrors hardware where an array's elements all share one declared
    bit width. Structs are left as-is: struct construction already types scalar (and,
    via _typed_new, array-of-scalar) fields at construction time."""
    if hasattr(ctype, "_fields"):
        return value
    elem_ctype = _array_elem_ctype(ctype)
    if elem_ctype is not None:
        return [_sim_cast_deep(v, elem_ctype) for v in value]
    return _sim_cast(value, ctype)


def _sim_lens_set(obj, path, value):
    """Return a copy of obj with the nested element at path replaced by value.

    Handles NamedTuple structs (immutable -> _replace) and lists (copy + index set).
    path is a list of field-name strings (struct attribute) or ints (array index),
    root-to-leaf order.
    """
    if not path:
        return value
    head, rest = path[0], path[1:]
    if isinstance(head, str):
        child = getattr(obj, head)
        return obj._replace(**{head: _sim_lens_set(child, rest, value)})
    new_list = list(obj)
    idx = int(head)
    new_list[idx] = _sim_lens_set(new_list[idx], rest, value)
    return new_list


def _sim_reg_read(inst_path, reg_name, default=0):
    """Return the current register value for this instance (default if never written)."""
    return _sim_reg_state.get(inst_path, {}).get(reg_name, default)


def _sim_reg_write(inst_path, reg_name, value):
    """Update the register value, routing to buffer if buffering is active."""
    if _sim_reg_write_buffer is not None:
        _sim_reg_write_buffer.setdefault(inst_path, {})[reg_name] = value
    else:
        _sim_reg_state.setdefault(inst_path, {})[reg_name] = value


def _sim_wire_read(name: str):
    """Return the current global wire value (0 if not yet driven).
    Records the calling MAIN as a reader of this wire for dependency tracking.
    """
    if _sim_current_main is not None:
        _sim_wire_readers.setdefault(name, set()).add(_sim_current_main)
    return _sim_wire_state.get(name, 0)


def _sim_wire_write(name: str, value) -> None:
    """Set the current global wire value (struct types preserved, not converted to int)."""
    _sim_wire_state[name] = value


def sim_reset():
    """Clear all simulated register and wire state."""
    _sim_reg_state.clear()
    _sim_wire_state.clear()


def _sim_reg_begin_buffer():
    """Switch register writes into buffered mode; writes accumulate until flush."""
    global _sim_reg_write_buffer
    _sim_reg_write_buffer = {}


def _sim_reg_flush_buffer():
    """Commit buffered register writes to _sim_reg_state and exit buffer mode."""
    global _sim_reg_write_buffer
    if _sim_reg_write_buffer:
        for inst_path, regs in _sim_reg_write_buffer.items():
            _sim_reg_state.setdefault(inst_path, {}).update(regs)
    _sim_reg_write_buffer = None


def sim_wire_reset():
    """Clear all global wire simulation state."""
    _sim_wire_state.clear()


class _GlobalWireRewriter(_ast.NodeTransformer):
    """AST transformer that rewrites global wire reads/writes in hw_func bodies.

    Replaces:
      - Name(id='wire', ctx=Load)      →  _sim_wire_read('wire')
      - wire = expr                    →  _sim_wire_write('wire', expr)   (Expr stmt)
      - wire: T = expr                 →  _sim_wire_write('wire', expr)   (AnnAssign with value)
      - module.wire  (Load)            →  _sim_wire_read('wire')          (cross-module read)
      - module.wire = expr             →  _sim_wire_write('wire', expr)   (cross-module write)

    module_wire_attrs: {(alias_name, attr_name): sim_key} for wires in imported modules.
    """

    def __init__(self, wire_names, module_wire_attrs=None):
        self._wire_names = frozenset(wire_names)
        self._module_wire_attrs = module_wire_attrs or {}

    def visit_Name(self, node):
        if node.id in self._wire_names and isinstance(node.ctx, _ast.Load):
            return _ast.copy_location(
                _ast.Call(
                    func=_ast.Name(id="_sim_wire_read", ctx=_ast.Load()),
                    args=[_ast.Constant(value=node.id)],
                    keywords=[],
                ),
                node,
            )
        return node

    def visit_Attribute(self, node):
        if (
            isinstance(node.value, _ast.Name)
            and isinstance(node.ctx, _ast.Load)
            and (node.value.id, node.attr) in self._module_wire_attrs
        ):
            wire_name = self._module_wire_attrs[(node.value.id, node.attr)]
            return _ast.copy_location(
                _ast.Call(
                    func=_ast.Name(id="_sim_wire_read", ctx=_ast.Load()),
                    args=[_ast.Constant(value=wire_name)],
                    keywords=[],
                ),
                node,
            )
        return self.generic_visit(node)

    def visit_Assign(self, node):
        node = self.generic_visit(node)  # transform RHS and any non-wire targets
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], _ast.Name)
            and node.targets[0].id in self._wire_names
        ):
            wire_name = node.targets[0].id
            return _ast.copy_location(
                _ast.Expr(
                    value=_ast.Call(
                        func=_ast.Name(id="_sim_wire_write", ctx=_ast.Load()),
                        args=[_ast.Constant(value=wire_name), node.value],
                        keywords=[],
                    )
                ),
                node,
            )
        # Cross-module write: module_alias.wire_name = expr
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], _ast.Attribute)
            and isinstance(node.targets[0].value, _ast.Name)
        ):
            target = node.targets[0]
            key = (target.value.id, target.attr)
            if key in self._module_wire_attrs:
                wire_name = self._module_wire_attrs[key]
                return _ast.copy_location(
                    _ast.Expr(
                        value=_ast.Call(
                            func=_ast.Name(id="_sim_wire_write", ctx=_ast.Load()),
                            args=[_ast.Constant(value=wire_name), node.value],
                            keywords=[],
                        )
                    ),
                    node,
                )
        return node

    def visit_AnnAssign(self, node):
        # Annotated assignment with a value inside a function body, e.g. x: T = expr.
        # Module-level wire declarations (no value) are untouched.
        node = self.generic_visit(node)
        if (
            isinstance(node.target, _ast.Name)
            and node.target.id in self._wire_names
            and node.value is not None
        ):
            wire_name = node.target.id
            return _ast.copy_location(
                _ast.Expr(
                    value=_ast.Call(
                        func=_ast.Name(id="_sim_wire_write", ctx=_ast.Load()),
                        args=[_ast.Constant(value=wire_name), node.value],
                        keywords=[],
                    )
                ),
                node,
            )
        return node


class _TypedAnnAssignRewriter(_ast.NodeTransformer):
    """Rewrites typed assignments to call _sim_cast, mirroring hardware truncation.

    Two rewrite rules:
    1. `var: scalar_int_type = expr`  →  `var = _sim_cast(expr, T)` (AnnAssign with value)
    2. `var = expr` (plain Assign) where `var` was previously declared with a scalar
       integer annotation  →  `var = _sim_cast(expr, T)` using the declared type

    Rule 2 matches hardware semantics: a signal's type is declared once and every
    subsequent write to it truncates, even bare re-assignments (`t = t + d` in a loop
    behaves identically to `t: int16_t = t + d` when `t: int16_t` was declared earlier).

    Must be applied AFTER _GlobalWireRewriter: wire AnnAssigns have already been
    converted to Expr(Call) nodes by that pass, so this rewriter only sees non-wire
    annotations.

    A third rule handles bare struct/array locals (the canonical `rv: T` then
    `rv.field = ...` / `rv[i] = ...` idiom carried over from C PipelineC):
    3. `var: struct_or_array_type` (no value)  →  `var = _make_sim_zero(T)`, so the
       name is bound to a zero-valued instance instead of raising UnboundLocalError.
    4. `var.field = expr` / `var[i] = expr` (and nested chains thereof) where `var` was
       declared via rule 3 (or via `var: T = ...`)  →  `var = _sim_lens_set(var,
       [path...], expr)`, since struct instances are immutable NamedTuples and can't
       be mutated with plain attribute assignment.

    Reg[T]/Feedback[T] descriptor objects carry neither `_fields` nor `_ctype_name`
    themselves, but when their `inner_ctype` is a struct/array, the variable is
    tracked in `_compound_declared` (rule 4) exactly like a bare compound local —
    `_build_reg_sim_func` handles their read/zero-init separately, but nested
    `.field=`/`[i]=` writes on them go through the same `_sim_lens_set` rewrite.
    Wire[T]/Input[T]/Output[T] still fall through both checks untouched.
    """

    def __init__(self, eval_ns, ann_ctypes_out):
        self._eval_ns = eval_ns
        self._ann_ctypes_out = ann_ctypes_out  # filled in-place: key → ctype_obj
        self._declared_types = {}  # var_name → ctype, populated by AnnAssign visits
        self._compound_declared = {}  # var_name → ctype, bare/typed struct or array locals
        self.modified = False  # True if any compound zero-init/lens rewrite happened

    def _make_cast(self, value_node, ctype, ref_node):
        """Return a _sim_cast(value_node, __sim_ann_L_C__) Call node."""
        key = f"__sim_ann_{ref_node.lineno}_{ref_node.col_offset}__"
        self._ann_ctypes_out[key] = ctype
        return _ast.Call(
            func=_ast.Name(id="_sim_cast", ctx=_ast.Load()),
            args=[value_node, _ast.Name(id=key, ctx=_ast.Load())],
            keywords=[],
        )

    def _make_zero_call(self, ctype, ref_node):
        """Return a _make_sim_zero(__sim_ann_L_C__) Call node."""
        key = f"__sim_ann_{ref_node.lineno}_{ref_node.col_offset}__"
        self._ann_ctypes_out[key] = ctype
        return _ast.Call(
            func=_ast.Name(id="_make_sim_zero", ctx=_ast.Load()),
            args=[_ast.Name(id=key, ctx=_ast.Load())],
            keywords=[],
        )

    def _make_deep_cast(self, value_node, ctype, ref_node):
        """Return a _sim_cast_deep(value_node, __sim_ann_L_C__) Call node -- casts a
        Rule-4 partial-write value (scalar or array-of-scalar) to the statically-resolved
        leaf ctype before it's threaded through _sim_lens_set."""
        key = f"__sim_ann_{ref_node.lineno}_{ref_node.col_offset}__deep__"
        self._ann_ctypes_out[key] = ctype
        return _ast.Call(
            func=_ast.Name(id="_sim_cast_deep", ctx=_ast.Load()),
            args=[value_node, _ast.Name(id=key, ctx=_ast.Load())],
            keywords=[],
        )

    def _chain_to_path(self, target):
        """Walk an Attribute/Subscript chain to (root_name, [path_node, ...], [kind, ...]),
        root-to-leaf order. path nodes are ast.Constant(field_name) for attribute
        access or the raw slice node for subscript access -- used to build the runtime
        _sim_lens_set path list. kinds is a parallel list of ('attr', field_name_str) or
        ('idx', None), used at rewrite time (not runtime) to statically resolve the leaf
        ctype, since an array's elements all share one declared ctype regardless of the
        (possibly dynamic) index expression. Returns (None, None, None) if the chain
        doesn't bottom out in a plain Name."""
        path = []
        kinds = []
        node = target
        while isinstance(node, (_ast.Attribute, _ast.Subscript)):
            if isinstance(node, _ast.Attribute):
                path.append(_ast.Constant(value=node.attr))
                kinds.append(("attr", node.attr))
                node = node.value
            else:
                slc = node.slice
                if isinstance(slc, _ast.Index):  # py3.8 compat
                    slc = slc.value
                path.append(slc)
                kinds.append(("idx", None))
                node = node.value
        path.reverse()
        kinds.reverse()
        if isinstance(node, _ast.Name):
            return node.id, path, kinds
        return None, None, None

    def _resolve_leaf_ctype(self, root_ctype, kinds):
        """Walk root_ctype through a _chain_to_path 'kinds' list to the statically-known
        leaf ctype, or None if it can't be resolved (defensive -- callers fall back to
        today's uncast behavior rather than erroring)."""
        ctype = root_ctype
        for kind, field_name in kinds:
            if kind == "attr":
                if not hasattr(ctype, "_fields"):
                    return None
                ann = ctype.__annotations__.get(field_name)
                if ann is None:
                    return None
                ctype = ann
            else:
                elem_ctype = _array_elem_ctype(ctype)
                if elem_ctype is None:
                    return None
                ctype = elem_ctype
        return ctype

    def visit_AnnAssign(self, node):
        self.generic_visit(node)
        if not isinstance(node.target, _ast.Name):
            return node  # tuple-unpack or subscript target, skip
        try:
            ann_val = eval(
                compile(_ast.Expression(body=node.annotation), "<ann>", "eval"),
                self._eval_ns,
            )
        except Exception:
            return node
        if _is_compound_pypeline_type(ann_val):
            # Bare struct/array local: track it (with its ctype, so later .field=/[i]=
            # writes can resolve the leaf ctype for casting) so subsequent writes get
            # lens-rewritten, and zero-init it if declared without a value.
            self._compound_declared[node.target.id] = ann_val
            if node.value is None:
                self.modified = True
                new_node = _ast.Assign(
                    targets=[node.target],
                    value=self._make_zero_call(ann_val, node),
                )
                return _ast.copy_location(new_node, node)
            return node  # `var: T = value` already binds the name via plain Python
        if isinstance(
            ann_val, (_RegType, _FeedbackType)
        ) and _is_compound_pypeline_type(ann_val.inner_ctype):
            # Reg[T]/Feedback[T] where T is a struct/array: the read-back value is
            # an immutable NamedTuple (or plain list), exactly like a bare compound
            # local, so nested .field=/[i]= writes need the same lens-rewrite. The
            # AnnAssign itself is left untouched — _build_reg_sim_func handles
            # Reg/Feedback read/zero-init separately.
            self._compound_declared[node.target.id] = ann_val.inner_ctype
            return node
        if not _is_scalar_pypeline_int(ann_val):
            return node  # Wire, Input, Output — skip
        # Always record: bare `var: T` declarations also type subsequent plain assigns.
        self._declared_types[node.target.id] = ann_val
        if node.value is None:
            return node  # declaration-only: type recorded, nothing to rewrite
        new_node = _ast.Assign(
            targets=[node.target],
            value=self._make_cast(node.value, ann_val, node),
        )
        return _ast.copy_location(new_node, node)

    def visit_Assign(self, node):
        self.generic_visit(node)
        if len(node.targets) != 1:
            return node  # tuple-unpack target, skip
        target = node.targets[0]
        if isinstance(target, _ast.Name):
            ctype = self._declared_types.get(target.id)
            if ctype is None:
                return node  # not a previously-declared scalar-typed variable
            new_node = _ast.Assign(
                targets=node.targets,
                value=self._make_cast(node.value, ctype, node),
            )
            return _ast.copy_location(new_node, node)
        if isinstance(target, (_ast.Attribute, _ast.Subscript)):
            root, path, kinds = self._chain_to_path(target)
            if root is not None and root in self._compound_declared:
                self.modified = True
                leaf_ctype = self._resolve_leaf_ctype(
                    self._compound_declared[root], kinds
                )
                value_node = node.value
                if leaf_ctype is not None:
                    value_node = self._make_deep_cast(value_node, leaf_ctype, node)
                path_list = _ast.List(elts=path, ctx=_ast.Load())
                lens_call = _ast.Call(
                    func=_ast.Name(id="_sim_lens_set", ctx=_ast.Load()),
                    args=[
                        _ast.Name(id=root, ctx=_ast.Load()),
                        path_list,
                        value_node,
                    ],
                    keywords=[],
                )
                new_node = _ast.Assign(
                    targets=[_ast.Name(id=root, ctx=_ast.Store())],
                    value=lens_call,
                )
                return _ast.copy_location(new_node, node)
        return node


def _build_reg_sim_func(fn):
    """Build a simulation-mode function body for fn that manages Reg[T] and Feedback[T].

    Scans the function body's AST for `var: Reg[T]` and `var: Feedback[T]`
    annotation-only statements. Returns None if neither are found or if source
    extraction fails.

    Unified transformation — each section is emitted only when the corresponding
    collection is non-empty:

        # only when reg_names non-empty:
        __ip__ = _sim_current_inst_path()
        <reg> = _sim_reg_read(__ip__, "<reg>")   # per register
        <__reg_init_reg> = <reg>                 # snapshot for convergence reset

        # only when feedback_names non-empty:
        <fb> = 0                                 # per feedback var, zero-init
        __fb_iters = 0

        # try/finally wraps the while when reg_names non-empty; bare while otherwise:
        [try:]
            while True:
                # only when feedback_names non-empty:
                __fb_iters += 1
                if __fb_iters > _SIM_FEEDBACK_MAX_ITER: raise RuntimeError(...)
                # only when BOTH reg and feedback non-empty:
                <reg> = <__reg_init_reg>         # reset reg to initial each pass
                # only when feedback_names non-empty:
                <__fb_snap_fb> = <fb>            # snapshot per feedback var
                <original body minus stripped AnnAssigns>
                # when feedback_names non-empty — convergence check:
                if <fb> == <__fb_snap_fb> [and ...]: break
                # when feedback_names IS empty — always run body once:
                break
        [finally:]
            # only when reg_names non-empty:
            _sim_reg_write(__ip__, "<reg>", <reg>)  # per register

    When feedback_names is empty the while degenerates to a single pass
    (unconditional break) — equivalent to the former plain try/finally.
    Registers held at their initial read values across all convergence
    iterations so that feedback resolves combinatorially before any state commit.

    Note: local variable annotations (var: T inside a function body) are NOT
    stored in fn.__annotations__ by Python, so annotations must be discovered
    by evaluating the AnnAssign nodes against the function's globals.
    """
    orig_fn = _inspect.unwrap(fn)
    try:
        _src_lines, _first_lineno = _inspect.getsourcelines(orig_fn)
        src = _textwrap.dedent("".join(_src_lines))
    except (OSError, TypeError):
        return None, False
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return None, False
    # getsourcelines numbers the snippet from 1, but `src_file` below is the real file
    # on disk — shift every node's lineno to match its true position there so
    # tracebacks raised from the exec'd body point at the actual failing line instead
    # of whatever happens to sit at that line number near the top of the real file.
    _ast.increment_lineno(tree, _first_lineno - 1)

    func_def = next((n for n in tree.body if isinstance(n, _ast.FunctionDef)), None)
    if func_def is None:
        return None, False

    # Build eval namespace: globals + closure variables (for closures like make_vga_timing).
    # Closure variables (e.g. h_uint, V_MAX) appear in Reg[T] annotations and body
    # expressions but are not in fn.__globals__ — they live in fn.__closure__.
    _eval_ns = dict(fn.__globals__)
    if fn.__code__.co_freevars and fn.__closure__:
        for _cv, _cell in zip(fn.__code__.co_freevars, fn.__closure__):
            try:
                _eval_ns[_cv] = _cell.cell_contents
            except ValueError:
                pass

    # Discover global wire names from the function's defining module and rewrite
    # all reads/writes in the function body to go through _sim_wire_read/write.
    global_wire_names = {
        name
        for name, ann in fn.__globals__.get("__annotations__", {}).items()
        if isinstance(ann, (_WireType, _InputType, _OutputType))
    }
    # Also build a map for cross-module wire access (module_alias.wire_name).
    # Scans all module objects in fn.__globals__ for wire annotations.
    module_wire_attrs = {}
    for _alias, _obj in fn.__globals__.items():
        if not isinstance(_obj, _types.ModuleType):
            continue
        for _wname, _ann in getattr(_obj, "__annotations__", {}).items():
            if isinstance(_ann, (_WireType, _InputType, _OutputType)):
                module_wire_attrs[(_alias, _wname)] = _wname
    if global_wire_names or module_wire_attrs:
        _GlobalWireRewriter(global_wire_names, module_wire_attrs).visit(func_def)
        _ast.fix_missing_locations(func_def)

    # Rewrite typed local annotations AFTER _GlobalWireRewriter (wire AnnAssigns are
    # already converted to Expr nodes) and BEFORE orig_body is sliced, so orig_body
    # picks up the rewritten Assign nodes.
    # Skipped in SIM_RAW_INTS mode: no _sim_cast calls injected, plain Python
    # arithmetic flows through unchanged.
    ann_ctypes_out: dict = {}
    _typed_rewriter_modified = False
    if not SIM_RAW_INTS:
        _typed_rewriter = _TypedAnnAssignRewriter(_eval_ns, ann_ctypes_out)
        _typed_rewriter.visit(func_def)
        _ast.fix_missing_locations(func_def)
        _typed_rewriter_modified = _typed_rewriter.modified

    # Discover register and feedback variable names by evaluating each AnnAssign
    # annotation against the function's eval namespace.
    # Typed local AnnAssigns (e.g. x: int16_t = 512) were already rewritten to plain
    # Assign nodes by _TypedAnnAssignRewriter above, so only Reg[T]/Feedback[T] remain.
    reg_names = []
    reg_zeros = {}  # name → power-on default value, computed once at decoration time
    feedback_names = []
    # Locals assigned via plain `name = expr` earlier in the body (e.g.
    # `MC = MULTI_CYCLE[32]`) aren't in _eval_ns (built before the function ran), but
    # Reg[T, MC.start] annotations reference them. Accumulate pure-Python-evaluable
    # locals here, in source order, mirroring the elaborator's const_env.
    _local_const_ns = {}
    for stmt in func_def.body:
        if (
            isinstance(stmt, _ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], _ast.Name)
        ):
            try:
                _local_const_ns[stmt.targets[0].id] = eval(
                    compile(_ast.Expression(body=stmt.value), "<local_const>", "eval"),
                    {**_eval_ns, **_local_const_ns},
                )
            except Exception:
                pass
            continue
        if not (
            isinstance(stmt, _ast.AnnAssign) and isinstance(stmt.target, _ast.Name)
        ):
            continue
        _merged_ns = {**_eval_ns, **_local_const_ns}
        try:
            ann_val = eval(
                compile(_ast.Expression(body=stmt.annotation), "<ann>", "eval"),
                _merged_ns,
            )
        except Exception:
            continue
        if isinstance(ann_val, _RegType):
            reg_names.append(stmt.target.id)
            if stmt.value is not None:
                # Reg[T] = val: evaluate the init expression for the power-on default.
                try:
                    init_val = eval(
                        compile(_ast.Expression(body=stmt.value), "<reg_init>", "eval"),
                        _merged_ns,
                    )
                    # Dict-style struct init {"field": val} → convert to NamedTuple
                    # so that field access (pt.x) works in the simulated body.
                    if isinstance(init_val, dict) and hasattr(
                        ann_val.inner_ctype, "_fields"
                    ):
                        init_val = ann_val.inner_ctype(**init_val)
                    reg_zeros[stmt.target.id] = init_val
                except Exception:
                    reg_zeros[stmt.target.id] = _make_sim_zero(ann_val.inner_ctype)
            else:
                reg_zeros[stmt.target.id] = _make_sim_zero(ann_val.inner_ctype)
        elif isinstance(ann_val, _FeedbackType) and stmt.value is None:
            feedback_names.append(stmt.target.id)

    if (
        not reg_names
        and not feedback_names
        and not global_wire_names
        and not module_wire_attrs
        and not ann_ctypes_out
        and not _typed_rewriter_modified
    ):
        return None, False

    # Strip Reg[T] annotations (with or without init value) and Feedback[T]
    # annotation-only stmts from the body — init values are handled via
    # __reg_zero_<name>__ injected into new_globals; the AnnAssign itself must not
    # remain or it would overwrite the _sim_reg_read result.
    _reg_set = set(reg_names)
    _fb_set = set(feedback_names)
    orig_body = [
        stmt
        for stmt in func_def.body
        if not (
            isinstance(stmt, _ast.AnnAssign)
            and isinstance(stmt.target, _ast.Name)
            and (
                stmt.target.id in _reg_set
                or (stmt.target.id in _fb_set and stmt.value is None)
            )
        )
    ]

    # --- Build transformed function body ---

    new_stmts = []

    # Register reads and initial-value snapshots (only when reg_names non-empty).
    if reg_names:
        new_stmts.append(_ast.parse("__ip__ = _sim_current_inst_path()").body[0])
        for name in reg_names:
            new_stmts.append(
                _ast.parse(
                    f'{name} = _sim_reg_read(__ip__, "{name}", __reg_zero_{name}__)'
                ).body[0]
            )
            new_stmts.append(_ast.parse(f"__reg_init_{name} = {name}").body[0])

    # Feedback zero-init and iteration counter (only when feedback_names non-empty).
    if feedback_names:
        for name in feedback_names:
            new_stmts.append(_ast.parse(f"{name} = 0").body[0])
        new_stmts.append(_ast.parse("__fb_iters = 0").body[0])

    # When feedback is present, the return statement must live OUTSIDE the
    # convergence loop so that the loop can iterate to a fixed point before
    # returning.  Hardware functions have exactly one return (the final
    # top-level statement); extract it here.
    if feedback_names and orig_body and isinstance(orig_body[-1], _ast.Return):
        loop_stmts = orig_body[:-1]
        trailing_return = orig_body[-1]
    else:
        loop_stmts = orig_body
        trailing_return = None

    # Build the while loop body.
    loop_body = []

    if feedback_names:
        # Safety iteration limit check.
        loop_body.append(_ast.parse("__fb_iters += 1").body[0])
        fn_name = orig_fn.__name__
        loop_body.append(
            _ast.parse(
                f"if __fb_iters > _SIM_FEEDBACK_MAX_ITER: "
                f"raise RuntimeError(\"Feedback[T] sim: convergence failed in '{fn_name}'\")"
            ).body[0]
        )
        # Reset registers to their initial values at the start of each iteration
        # so they act as constant inputs throughout combinatorial convergence.
        if reg_names:
            for name in reg_names:
                loop_body.append(_ast.parse(f"{name} = __reg_init_{name}").body[0])
        # Snapshot all feedback variables before running the body this pass.
        for name in feedback_names:
            loop_body.append(_ast.parse(f"__fb_snap_{name} = {name}").body[0])

    # Original function body (both Reg[T] and Feedback[T] AnnAssigns removed;
    # trailing return extracted above when feedback is present).
    loop_body.extend(loop_stmts)

    # Convergence check (feedback present) or unconditional single-pass break.
    if feedback_names:
        conditions = " and ".join(
            f"{name} == __fb_snap_{name}" for name in feedback_names
        )
        loop_body.append(_ast.parse(f"if {conditions}: break").body[0])
    else:
        loop_body.append(_ast.parse("break").body[0])

    while_loop = _ast.While(
        test=_ast.Constant(value=True),
        body=loop_body,
        orelse=[],
    )

    # Wrap in try/finally for register commits (only when reg_names non-empty).
    if reg_names:
        finally_stmts = [
            _ast.parse(f'_sim_reg_write(__ip__, "{name}", {name})').body[0]
            for name in reg_names
        ]
        new_stmts.append(
            _ast.Try(body=[while_loop], handlers=[], orelse=[], finalbody=finally_stmts)
        )
    else:
        new_stmts.append(while_loop)

    # Emit the trailing return after the loop/try block (feedback case only).
    if trailing_return is not None:
        new_stmts.append(trailing_return)

    func_def.body = new_stmts
    func_def.decorator_list = []  # strip decorators to avoid re-wrapping on exec

    _ast.fix_missing_locations(tree)

    src_file = getattr(getattr(orig_fn, "__code__", None), "co_filename", "<sim_reg>")
    try:
        code = compile(tree, src_file, "exec")
    except Exception:
        return None, bool(reg_names or feedback_names)

    new_globals = _eval_ns.copy()  # includes globals + closure vars
    new_globals.update(
        _sim_cast=_sim_cast,
        _sim_cast_deep=_sim_cast_deep,
        _make_sim_zero=_make_sim_zero,
        _sim_lens_set=_sim_lens_set,
        _sim_current_inst_path=_sim_current_inst_path,
        _sim_reg_read=_sim_reg_read,
        _sim_reg_write=_sim_reg_write,
        _SIM_FEEDBACK_MAX_ITER=_SIM_FEEDBACK_MAX_ITER,
        _sim_wire_read=_sim_wire_read,
        _sim_wire_write=_sim_wire_write,
    )
    for _name, _zero in reg_zeros.items():
        new_globals[f"__reg_zero_{_name}__"] = _zero
    for _key, _ctype_obj in ann_ctypes_out.items():
        new_globals[_key] = _ctype_obj
    # Inject function signature annotation type names that only appear in annotations
    # (not the body), so Python doesn't capture them in co_freevars — but exec still
    # needs them when it re-evaluates the def statement's annotation expressions.
    _sig_anns = getattr(orig_fn, "__annotations__", {})
    for _arg in func_def.args.args:
        if _arg.annotation and isinstance(_arg.annotation, _ast.Name):
            _type_name = _arg.annotation.id
            if _type_name not in new_globals and _arg.arg in _sig_anns:
                new_globals[_type_name] = _sig_anns[_arg.arg]
    if func_def.returns and isinstance(func_def.returns, _ast.Name):
        _ret_name = func_def.returns.id
        if _ret_name not in new_globals and "return" in _sig_anns:
            new_globals[_ret_name] = _sig_anns["return"]
    exec(code, new_globals)  # noqa: S102
    return new_globals.get(orig_fn.__name__), bool(reg_names or feedback_names)


@_functools.lru_cache(maxsize=None)
def _sim_cast_params(ctype):
    """Pre-compute mask, sign_bit, and is_signed for a ctype (cached per unique type object)."""
    n = len(ctype)
    mask = (1 << n) - 1
    is_signed = str(ctype).startswith("int")
    return mask, 1 << (n - 1), is_signed


# Direct dict replacing the lru_cache function call in the _sim_cast hot path.
# Avoids Python function call overhead (~0.1µs) for each of the 4M+ casts per 1K cycles.
_sim_cast_param_cache: dict = {}


def _sim_type_init(ctype):
    """Initialize both caches for a ctype on first use. Returns (mask, sign_bit, is_signed).

    Called only in the cold `except KeyError` path — never the hot path.
    Populates _sim_cast_param_cache and pre-builds the flyweight constants 0..15.
    """
    mask, sign_bit, is_signed = _sim_cast_params(ctype)
    _sim_cast_param_cache[ctype] = (mask, sign_bit, is_signed)
    limit = min(16, mask + 1)
    for const_v in range(limit):
        obj = _int_new(SimVal, const_v)
        _obj_setattr(obj, "_ctype", ctype)
        _SIM_CONST_CACHE[(const_v, ctype)] = obj
    return mask, sign_bit, is_signed


def _sim_cast(val, ctype):
    """Cast a Python int/SimVal to a pypeline ctype: mask to n bits, handle signedness.

    This is the sim equivalent of a hardware type assignment. It implements unsigned
    wrap-on-overflow and signed two's complement masking.
    """
    if SIM_RAW_INTS:
        return val
    if type(val) is SimVal and val._ctype is ctype:
        return val
    try:
        mask, sign_bit, is_signed = _sim_cast_param_cache[ctype]
    except KeyError:
        mask, sign_bit, is_signed = _sim_type_init(ctype)
    v = int(val) & mask
    if is_signed and v >= sign_bit:
        v -= mask + 1  # sign-extend to Python negative
    return _sim_val_make(v, ctype)


def _sim_type_wrap(fn):
    """Wrap a pypeline hardware function for bit-accurate simulation.

    On each call: records the call-site location for register instance identity,
    casts positional arguments to their annotated input types, pushes any scoped
    operator registrations, calls the original function (or a register-aware
    simulation body for Reg[T] functions), pops registrations, then casts the
    return value to the annotated return type.

    Transparent to the hardware elaborator: _elaborate_live_func uses
    inspect.unwrap() to recover the original function for source analysis.
    functools.wraps copies __annotations__ and merges __dict__ (preserving
    custom attributes like .out_t and .amount_t set by factory functions).
    """
    ann = fn.__annotations__
    try:
        params = list(_inspect.signature(fn).parameters.keys())
    except (ValueError, TypeError):
        params = []
    ret_t = ann.get("return")

    # Scan source for Reg[T]/Feedback[T] annotations and build register-aware sim body.
    # Returns (fn_or_None, has_state) where has_state=True means the body calls
    # _sim_current_inst_path() so the instance stack must be maintained.
    sim_body_fn, has_state = _build_reg_sim_func(fn)

    # Helper: cast args and kwargs to their annotated types, run the body, cast result.
    # Extracted so both wrapper variants share the same arg-casting logic.
    def _run_body(new_args, kwargs):
        new_kwargs = dict(kwargs)
        for k, v in kwargs.items():
            pt = ann.get(k)
            if (
                pt is not None
                and (type(v) is int or type(v) is SimVal)
                and _is_scalar_pypeline_int(pt)
            ):
                new_kwargs[k] = _sim_cast(v, pt)
        saved = _push_scoped_registrations(fn)
        try:
            if sim_body_fn is not None:
                result = sim_body_fn(*new_args, **new_kwargs)
            else:
                result = fn(*new_args, **new_kwargs)
        finally:
            _pop_scoped_registrations(saved)
        if (
            ret_t is not None
            and (type(result) is int or type(result) is SimVal)
            and _is_scalar_pypeline_int(ret_t)
        ):
            result = _sim_cast(result, ret_t)
        return result

    if SIM_RAW_INTS:
        # ── Raw-int mode: zero casting, zero SimVal creation ─────────────────
        # No arg/result casting. Values are plain Python ints throughout.
        # Decoration-time check means zero per-call overhead for the mode branch.
        if not has_state:

            @_functools.wraps(fn)
            def wrapper(*args, **kwargs):
                if not _sim_active:
                    return fn(*args, **kwargs)
                saved = _push_scoped_registrations(fn)
                try:
                    return (
                        sim_body_fn(*args, **kwargs)
                        if sim_body_fn is not None
                        else fn(*args, **kwargs)
                    )
                finally:
                    _pop_scoped_registrations(saved)
        else:

            @_functools.wraps(fn)
            def wrapper(*args, **kwargs):
                if not _sim_active:
                    # State-bearing hw_funcs must be called via sim_call() so the
                    # register state dict is active.  Raising here prevents the
                    # elaborator's _try_eval_const from accidentally treating a
                    # Reg[T]=init_val function as a compile-time constant.
                    raise TypeError(
                        f"{fn.__qualname__!r} has Reg[T]/Feedback[T] state and "
                        f"cannot be called outside sim_call()"
                    )
                caller_f = _sys._getframe(1)
                call_loc = (caller_f.f_code.co_filename, caller_f.f_lineno, None, None)
                _sim_inst_stack.append((fn.__qualname__, call_loc))
                saved = _push_scoped_registrations(fn)
                try:
                    return (
                        sim_body_fn(*args, **kwargs)
                        if sim_body_fn is not None
                        else fn(*args, **kwargs)
                    )
                finally:
                    _pop_scoped_registrations(saved)
                    _sim_inst_stack.pop()

        return wrapper

    if not has_state:
        # ── Fast path: no Reg[T] / Feedback[T] in this function ─────────────
        # _sim_current_inst_path() is never called inside this body, so the
        # instance stack and _getframe capture are pure overhead. Skip both.
        # Functions with typed locals but no registers take this path.
        # Multi-instance register designs should set SIM_TRACE_LOCATIONS=True
        # to restore full ancestor-path tracking.
        @_functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not _sim_active:
                return fn(*args, **kwargs)
            new_args = list(args)
            for i, a in enumerate(args):
                if i < len(params):
                    pt = ann.get(params[i])
                    if (
                        pt is not None
                        and (type(a) is int or type(a) is SimVal)
                        and _is_scalar_pypeline_int(pt)
                    ):
                        new_args[i] = _sim_cast(a, pt)
            return _run_body(new_args, kwargs)
    else:
        # ── Register-aware path (has Reg[T] / Feedback[T]) ───────────────────
        # Must push to _sim_inst_stack so _sim_current_inst_path() returns a
        # unique path for each hardware instance.
        # SIM_TRACE_LOCATIONS=False (default): filename+lineno only (fast).
        # SIM_TRACE_LOCATIONS=True: also captures column via co_positions() for
        # designs with multiple hardware instances of the same Reg[T] function.
        @_functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not _sim_active:
                # State-bearing hw_funcs must be called via sim_call() so the
                # register state dict is active.  Raising here prevents the
                # elaborator's _try_eval_const from accidentally treating a
                # Reg[T]=init_val function as a compile-time constant.
                raise TypeError(
                    f"{fn.__qualname__!r} has Reg[T]/Feedback[T] state and "
                    f"cannot be called outside sim_call()"
                )
            caller_f = _sys._getframe(1)
            if SIM_TRACE_LOCATIONS:
                filename = caller_f.f_code.co_filename
                lineno = caller_f.f_lineno
                col, end_col = None, None
                if hasattr(caller_f.f_code, "co_positions"):
                    lasti = caller_f.f_lasti
                    instr_idx = lasti // 2
                    positions = list(caller_f.f_code.co_positions())
                    if 0 <= instr_idx < len(positions):
                        pos = positions[instr_idx]
                        if pos[2] is not None:
                            col, end_col = pos[2], pos[3]
                call_loc = (
                    caller_f.f_code.co_filename,
                    caller_f.f_lineno,
                    col,
                    end_col,
                )
            else:
                call_loc = (caller_f.f_code.co_filename, caller_f.f_lineno, None, None)
            _sim_inst_stack.append((fn.__qualname__, call_loc))
            try:
                new_args = list(args)
                for i, a in enumerate(args):
                    if i < len(params):
                        pt = ann.get(params[i])
                        if (
                            pt is not None
                            and (type(a) is int or type(a) is SimVal)
                            and _is_scalar_pypeline_int(pt)
                        ):
                            new_args[i] = _sim_cast(a, pt)
                return _run_body(new_args, kwargs)
            finally:
                _sim_inst_stack.pop()

    return wrapper


hw_func = _sim_type_wrap
"""Decorator that marks an inner pypeline hardware function for bit-accurate simulation.
Apply to inner function definitions inside make_* factory functions:

    def make_negate(value_t, out_t):
        @hw_func
        def negate(a: value_t) -> out_t:
            ...
        return negate

Transparent to the hardware elaborator (inspect.unwrap recovers the original).
"""


def wires(func):
    """Mark a function as "just wires" (equivalent to PipelineC's
    `#pragma FUNC_WIRES <func_name>`): pure rewiring/bit-casting logic with no
    real combinational delay, so the synthesizer skips timing estimation for
    its whole hierarchy.

    Implies @hw_func: inputs/outputs are type-cast for simulation and the
    function can be passed to sim_call() directly — no separate @hw_func
    needed. Stacks with @MAIN in either order.
    """
    wrapped = _sim_type_wrap(func)
    wrapped._is_func_wires_pragma = True
    return wrapped


def sim_call(func, *args, **kwargs):
    """Call a pypeline function in simulation mode with scoped operators active.

    Pushes scoped operator registrations keyed on func's id before calling.
    When @hw_func is applied to the function, scoped ops are registered under
    id(wrapped_func), so func must be passed as-is (not unwrapped).
    The @hw_func wrapper itself calls _push_scoped_registrations(original),
    which is a no-op for the original, so there is no double-push conflict.

    Also activates _sim_active for the duration of the call so that @hw_func
    wrappers run their sim bodies (Reg[T] handling) rather than falling through
    to the raw function. The raw-function fallback exists only for the elaborator's
    _try_eval_const probe, which calls functions directly without sim_call.
    """
    global _sim_active
    prev_active = _sim_active
    _sim_active = True
    saved = _push_scoped_registrations(func)
    try:
        return func(*args, **kwargs)
    finally:
        _pop_scoped_registrations(saved)
        _sim_active = prev_active
