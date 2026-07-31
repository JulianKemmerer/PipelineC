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

import hashlib as _hashlib
import typing
import functools as _functools
import warnings as _warnings
from enum import IntEnum as _IntEnum, auto as _auto

# If a fully-expanded struct canonical name exceeds this length it is replaced
# with "{class_name}_{sha256[:8]}" to keep VHDL type identifiers manageable.
_MAX_MANGLE_NAME_LEN = 64


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
        name = f"{cls._ctype_name}[{dim}]"
        inner_elem = getattr(cls, "_elem_ctype", None)
        if inner_elem is not None:
            # cls is itself an array type (from an earlier bracket, e.g. T[A]). A
            # further bracket T[A][dim] declares `dim` as a MORE DEEPLY NESTED
            # dimension -- matching C, where in `T x[A][dim]` A is the outer/first
            # dimension and dim is inner -- so push the new dim onto the leaf
            # element type instead of wrapping outside, keeping this array's own
            # outer length (A) unchanged.
            arr = _make_ctype(name)
            arr._elem_ctype = inner_elem[dim]
            arr._arr_len = cls._arr_len
            return arr
        arr = _make_ctype(name)
        arr._elem_ctype = cls
        arr._arr_len = dim
        return arr

    @property
    def width(cls):
        import re

        if cls._ctype_name == "char":
            return 8
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


def _enum_bit_width(enum_cls) -> int:
    """Compute the minimum uint bit width needed to represent all values of a pypeline enum type."""
    max_val = max((m.value for m in enum_cls), default=0)
    return max(1, max_val.bit_length()) if max_val > 0 else 1


def enum_bit_width(enum_cls) -> int:
    """Return the minimum uint bit width for a pypeline @enum type (inspects member values)."""
    return _enum_bit_width(enum_cls)


def enum_uint_type(enum_cls):
    """Return the underlying uint pypeline type for a pypeline @enum type.
    e.g. enum_uint_type(state_t) -> uint2_t  for a 3-state enum with values 0,1,2
    """
    return make_uint_t(_enum_bit_width(enum_cls))


class PypelineEnum(_IntEnum):
    """IntEnum base class for pypeline enum types with 0-based auto() numbering.

    Unlike plain IntEnum (where auto() starts at 1), PypelineEnum makes
    auto() start at 0, matching PipelineC's C enum convention.

    Usage:
        from enum import auto
        from pypeline import enum, PypelineEnum

        @enum
        class state_t(PypelineEnum):
            IDLE    = auto()   # 0
            RUNNING = auto()   # 1
            DONE    = auto()   # 2
    """

    @staticmethod
    def _generate_next_value_(name, start, count, last_values):
        return count  # 0, 1, 2, …


# ── unsigned integer types (every width 1-64) ─
for _w in range(1, 65):
    globals()[f"uint{_w}_t"] = make_uint_t(_w)
del _w

# ── signed integer types (every width 1-64) ───
for _w in range(1, 65):
    globals()[f"int{_w}_t"] = make_int_t(_w)
del _w

# ── char type (8-bit; distinct C-type-string "char", not "uint8_t") ──────────
char_t = _make_ctype("char")

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


_ARITH_RESULT_TYPE_OP_ALIAS = {
    "PLUS": "add",
    "MINUS": "sub",
    "INFERRED_MULT": "mul",
    "MULT": "mul",
    "DIV": "div",
    "MOD": "mod",
}


def arith_result_type(op: str, l_type, r_type):
    """Public wrapper over the same sign-promotion/full-precision-width rules
    the built-in inferred path uses, for library operator implementations that
    must produce a result identically shaped to what the built-in path would
    have produced (so switching an op's implementation never changes an
    existing design's wire widths).

    op:      "PLUS" | "MINUS" | "INFERRED_MULT" | "DIV" | "MOD" (or the short
             aliases "add" | "sub" | "mul" | "div" | "mod")
    l_type:  C type of the left operand (e.g. uint32_t)
    r_type:  C type of the right operand

    Returns (eff_l_type, eff_r_type, out_type): the effective (sign-promoted)
    input types and the full-precision output ctype OBJECT.
    """
    short_op = _ARITH_RESULT_TYPE_OP_ALIAS.get(op, op)
    eff_l, eff_r, result_signed = _arith_promote(_ctype_str(l_type), _ctype_str(r_type))
    out_t = _arith_output_ctype(short_op, eff_l, eff_r, result_signed)
    return _reconstruct_int_ctype(eff_l), _reconstruct_int_ctype(eff_r), out_t


# ─────────────────────────────────────────────
# NamedTuple with automatic subscript support
# ─────────────────────────────────────────────


def _mangle_type(s):
    """Remove array brackets for VHDL-compatible name mangling: uint32_t[2] -> uint32_t_2."""
    return s.replace("[", "_").replace("]", "")


def _struct_class_getitem(cls, dim):
    """Enables point_t[10] -> _make_ctype('point_t[10]') using the canonical C type name.
    Always a base case (cls is the scalar struct type, never itself an array -- a
    further bracket on the result goes through _CTypeMeta.__getitem__ instead)."""
    name = getattr(cls, "_pypeline_ctype_name", cls.__name__)
    arr = _make_ctype(f"{name}[{dim}]")
    arr._elem_ctype = cls
    arr._arr_len = dim
    return arr


@_functools.lru_cache(maxsize=None)
def _is_scalar_pypeline_int(ctype):
    """True for scalar uint/int types and @enum types; False for arrays and structs."""
    if getattr(ctype, "_pypeline_is_enum", False):
        return True
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
        """Bit slice: x[bit] → uint1 value, x[hi:lo] → (hi-lo+1)-bit value.

        The slice result carries a uintN_t ctype sized to the slice width (not the
        original operand's ctype) -- this is what lets hex(x[hi:lo]) know how many
        hex digits to zero-pad to, matching VHDL's %X rendering of the same slice.
        """
        if isinstance(key, int):
            return SimVal((int(self) >> key) & 1, make_uint_t(1))
        hi, lo = key.start, key.stop  # hardware convention: x[hi:lo]
        width = hi - lo + 1
        return SimVal((int(self) >> lo) & ((1 << width) - 1), make_uint_t(width))

    def _dispatch_unary(self, op_name, fallback):
        if self._ctype is not None:
            l_str = _ctype_str(self._ctype)
            fn = _unary_operator_registry.get((op_name, l_str))
            if fn is None:
                fn = _resolve_generic_unary_operator(op_name, l_str)
            if fn is INFERRED:
                fn = None
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
            r_str = _ctype_str(rc) if rc else None
            fn = None
            if r_str:
                fn = _operator_registry.get((op_name, l_str, r_str))
                if fn is None:
                    fn = _resolve_generic_operator(op_name, l_str, r_str)
            if fn is None or fn is INFERRED:
                fn = _left_operator_registry.get((op_name, l_str))
                if fn is None:
                    fn = _resolve_generic_left_operator(op_name, l_str)
            if fn is INFERRED:
                fn = None
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

    # Bitwise ops: hardware requires matching-width operands and the result keeps
    # that width/type (no arithmetic promotion like +/-). Losing the ctype here
    # (falling back to a bare, untyped SimVal) previously made downstream width
    # inference (_bit_manip_width, e.g. inside rotl()) fall back to
    # int(v).bit_length() -- silently *narrower* than the real declared width
    # whenever the result happens to have leading zero bits, corrupting any
    # rotl()/rotr()/bswap() applied to a bitwise-op result (e.g. chacha20's
    # `rotl(state[d] ^ a1, 16)`).
    def _bitwise_ctype(self, o):
        if self._ctype is not None:
            return self._ctype
        if type(o) is SimVal:
            return o._ctype
        return None

    def __and__(self, o):
        v = int(self) & int(o)
        if SIM_RAW_INTS:
            return v
        ctype = self._bitwise_ctype(o)
        if ctype is None:
            return SimVal(v)
        if SIM_STRICT_ARITH:
            try:
                mask, sign_bit, is_signed = _sim_cast_param_cache[ctype]
            except KeyError:
                mask, sign_bit, is_signed = _sim_type_init(ctype)
            v = v & mask
            if is_signed and v >= sign_bit:
                v -= mask + 1
        return _sim_val_make(v, ctype)

    def __or__(self, o):
        v = int(self) | int(o)
        if SIM_RAW_INTS:
            return v
        ctype = self._bitwise_ctype(o)
        if ctype is None:
            return SimVal(v)
        if SIM_STRICT_ARITH:
            try:
                mask, sign_bit, is_signed = _sim_cast_param_cache[ctype]
            except KeyError:
                mask, sign_bit, is_signed = _sim_type_init(ctype)
            v = v & mask
            if is_signed and v >= sign_bit:
                v -= mask + 1
        return _sim_val_make(v, ctype)

    def __xor__(self, o):
        v = int(self) ^ int(o)
        if SIM_RAW_INTS:
            return v
        ctype = self._bitwise_ctype(o)
        if ctype is None:
            return SimVal(v)
        if SIM_STRICT_ARITH:
            try:
                mask, sign_bit, is_signed = _sim_cast_param_cache[ctype]
            except KeyError:
                mask, sign_bit, is_signed = _sim_type_init(ctype)
            v = v & mask
            if is_signed and v >= sign_bit:
                v -= mask + 1
        return _sim_val_make(v, ctype)

    # Reflected bitwise ops: plain-int op SimVal (`o` is always a non-SimVal here,
    # same reasoning as __radd__ below). AND/OR/XOR are commutative, so just reuse
    # self's ctype -- no promotion needed, unlike +/-.
    def __rand__(self, o):
        v = int(o) & int(self)
        if SIM_RAW_INTS:
            return v
        if self._ctype is None:
            return SimVal(v)
        if SIM_STRICT_ARITH:
            try:
                mask, sign_bit, is_signed = _sim_cast_param_cache[self._ctype]
            except KeyError:
                mask, sign_bit, is_signed = _sim_type_init(self._ctype)
            v = v & mask
            if is_signed and v >= sign_bit:
                v -= mask + 1
        return _sim_val_make(v, self._ctype)

    def __ror__(self, o):
        v = int(o) | int(self)
        if SIM_RAW_INTS:
            return v
        if self._ctype is None:
            return SimVal(v)
        if SIM_STRICT_ARITH:
            try:
                mask, sign_bit, is_signed = _sim_cast_param_cache[self._ctype]
            except KeyError:
                mask, sign_bit, is_signed = _sim_type_init(self._ctype)
            v = v & mask
            if is_signed and v >= sign_bit:
                v -= mask + 1
        return _sim_val_make(v, self._ctype)

    def __rxor__(self, o):
        v = int(o) ^ int(self)
        if SIM_RAW_INTS:
            return v
        if self._ctype is None:
            return SimVal(v)
        if SIM_STRICT_ARITH:
            try:
                mask, sign_bit, is_signed = _sim_cast_param_cache[self._ctype]
            except KeyError:
                mask, sign_bit, is_signed = _sim_type_init(self._ctype)
            v = v & mask
            if is_signed and v >= sign_bit:
                v -= mask + 1
        return _sim_val_make(v, self._ctype)

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

    # Comparisons, DIV and MOD: no built-in fast path exists for these (unlike
    # +/-/* which always have an inferred lowering) -- when nothing is
    # registered they simply fall back to plain int comparison/division, same
    # result as before this dispatch existed. When a soft impl IS registered
    # (default-flip library, or a user's own), route through it so sim agrees
    # structurally with the generated hardware. Gated by
    # _registered_binary_op_names so an unregistered design pays one set
    # lookup, same pattern as __rshift__/__lshift__.
    def __lt__(self, o):
        v = int(self) < int(o)
        if SIM_RAW_INTS:
            return v
        if self._ctype is not None and "LT" in _registered_binary_op_names:
            return self._dispatch_binary("LT", o, v)
        return v

    def __le__(self, o):
        v = int(self) <= int(o)
        if SIM_RAW_INTS:
            return v
        if self._ctype is not None and "LTE" in _registered_binary_op_names:
            return self._dispatch_binary("LTE", o, v)
        return v

    def __gt__(self, o):
        v = int(self) > int(o)
        if SIM_RAW_INTS:
            return v
        if self._ctype is not None and "GT" in _registered_binary_op_names:
            return self._dispatch_binary("GT", o, v)
        return v

    def __ge__(self, o):
        v = int(self) >= int(o)
        if SIM_RAW_INTS:
            return v
        if self._ctype is not None and "GTE" in _registered_binary_op_names:
            return self._dispatch_binary("GTE", o, v)
        return v

    def __truediv__(self, o):
        ov = int(o)
        v = int(self) // ov if (int(self) < 0) == (ov < 0) else -(-int(self) // ov)
        if SIM_RAW_INTS:
            return v
        if self._ctype is not None and "DIV" in _registered_binary_op_names:
            return self._dispatch_binary("DIV", o, v, preserve_ctype=True)
        return _sim_val_make(v, self._ctype) if self._ctype is not None else SimVal(v)

    def __mod__(self, o):
        ov = int(o)
        d = int(self) // ov if (int(self) < 0) == (ov < 0) else -(-int(self) // ov)
        v = int(self) - d * ov
        if SIM_RAW_INTS:
            return v
        if self._ctype is not None and "MOD" in _registered_binary_op_names:
            return self._dispatch_binary("MOD", o, v, preserve_ctype=True)
        return _sim_val_make(v, self._ctype) if self._ctype is not None else SimVal(v)


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


def _format_struct_param_value(val):
    """Format one enclosing-factory parameter value for embedding in a struct's
    canonical name. Mirrors the convention _canonical_func_name uses for
    hw_func closure params in PY_TO_LOGIC.py (not imported -- pypeline.py has
    zero dependency on the compiler and must stay that way): a pypeline C
    type contributes its own canonical name, int/bool contributes its value
    string, None contributes "None". Negative ints use a 'neg' prefix rather
    than a bare '-', which is not legal inside a VHDL identifier. Anything
    else falls back to a short hash of its repr so struct() never raises on
    an unusual factory parameter type -- it just won't distinguish on it.
    """
    if isinstance(val, type):
        return _mangle_type(getattr(val, "_pypeline_ctype_name", val.__name__))
    if isinstance(val, bool) or isinstance(val, int):
        return str(val) if val >= 0 else f"neg{-val}"
    if val is None:
        return "None"
    if callable(val):
        # Deterministic (no memory address): a function's default repr embeds
        # its address, which would rename the struct on every design
        # re-execution -- and the AUTOPIPELINE .latency pin-and-confirm loop
        # re-executes designs in-process, matching entities across passes by
        # name. module+qualname is enough identity for this suffix; the
        # struct's structural distinctness is already carried by its field
        # types in the canonical name.
        import inspect

        if getattr(val, "_is_autopipeline_pragma", False):
            return "AUTOPIPELINE_" + _format_struct_param_value(val.func)
        unwrapped = inspect.unwrap(val)
        qual = getattr(unwrapped, "__qualname__", None)
        if qual:
            mod = getattr(unwrapped, "__module__", "") or ""
            dotted = (f"{mod}.{qual}" if mod else qual).replace(".<locals>.", "_")
            return _mangle_type(
                dotted.replace(".", "_").replace("<", "_").replace(">", "_")
            )
    return _hashlib.sha256(repr(val).encode()).hexdigest()[:8]


def _enclosing_factory_param_suffix(cls, frame):
    """If `cls` was defined directly inside a factory function (its
    __qualname__ contains '.<locals>.'), return a canonical-name suffix built
    from that function's own declared parameters -- unconditionally, as a
    pure function of the call's own inputs, so the result never depends on
    what else has been elaborated before it (mirrors _canonical_func_name's
    closure-param handling for @hw_func factories). Returns "" if there's no
    enclosing function, it has no declared parameters, or (safety bail-out)
    the live frame's function name doesn't match what the qualname lexically
    implies -- e.g. a struct defined two factory levels deep, which no
    current factory in this codebase does; degrading to "no suffix" here is
    safe (same as the module-level case), not incorrect.
    """
    qualname = getattr(cls, "__qualname__", "")
    if ".<locals>." not in qualname:
        return ""
    expected_name = qualname.split(".<locals>.")[-2]
    if frame.f_code.co_name != expected_name:
        return ""
    code = frame.f_code
    n = code.co_argcount + code.co_kwonlyargcount
    param_names = code.co_varnames[:n]
    parts = [
        f"{name}_{_format_struct_param_value(frame.f_locals[name])}"
        for name in sorted(param_names)
        if name in frame.f_locals
    ]
    return ("_" + "_".join(parts)) if parts else ""


def struct(cls):
    """Decorator that adds array subscript support and stamps a canonical C type name.
    The canonical name is derived from the class name, field types, and (for a
    struct defined directly inside a factory function) that factory's own
    parameters -- making it deterministic regardless of the Python variable
    name used at the call site, and collision-free even when two different
    parameter combinations would otherwise produce identical field types (e.g.
    a fixed-point factory where int_bits+frac_bits alone sizes the only
    field). This allows factory-produced structs nested inside other
    factories to get unique, stable names without being visible at module
    level, and without requiring any change at the @struct call site itself.

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
        # A plain struct has one direction, so a reverse (Feedback) field or a
        # whole interface has no meaning inside it -- reject at declaration
        # rather than emitting a nonsense C type name that fails much later in
        # VHDL writing. (Duck-typed so pypeline needn't import the interface lib.)
        if isinstance(ann, _FeedbackType):
            raise TypeError(
                f"@struct {cls.__name__!r} field {field!r} is Feedback[...]; a "
                "reverse-direction field is only meaningful in an @interface"
            )
        if getattr(ann, "_pypeline_is_interface", False):
            raise TypeError(
                f"@struct {cls.__name__!r} field {field!r} is an @interface; use "
                "@interface for bundles that contain interfaces, or a derived "
                "make_interface_type()/make_interface_feedback_type() struct here"
            )
        if isinstance(ann, type):
            # Use canonical name for struct-typed fields if already computed
            ann_str = getattr(ann, "_pypeline_ctype_name", ann.__name__)
        else:
            ann_str = str(ann)
        parts.append(f"{field}_{_mangle_type(ann_str)}")
    canonical = cls.__name__ + ("_" + "_".join(parts) if parts else "")
    canonical += _enclosing_factory_param_suffix(cls, _sys._getframe(1))
    cls._pypeline_ctype_canonical = canonical  # full name retained for debugging
    if len(canonical) > _MAX_MANGLE_NAME_LEN:
        h = _hashlib.sha256(canonical.encode()).hexdigest()[:8]
        cls._pypeline_ctype_name = f"{cls.__name__}_{h}"
    else:
        cls._pypeline_ctype_name = canonical

    # Override __new__ so that scalar integer fields are auto-wrapped in SimVals.
    # This makes float32_t(sign=0, exp=127, man=0) produce typed SimVal fields for
    # simulation without requiring a separate constructor. SimVal subclasses int, so
    # the hardware elaborator sees plain integers and is unaffected.
    _orig_new = cls.__new__

    def _typed_new(klass, *args, **kwargs):
        if args:
            positional = dict(zip(klass._fields, args))
            positional.update(kwargs)
            kwargs = positional
        typed = {}
        if SIM_RAW_INTS:
            for fname, v in kwargs.items():
                ftype = klass.__annotations__.get(fname)
                if (
                    ftype is not None
                    and isinstance(v, int)  # covers int, SimVal, IntEnum members
                    and _is_scalar_pypeline_int(ftype)
                ):
                    v = _RawField(int(v))
                elif ftype is not None and type(v) is list:
                    elem_ftype = _array_elem_ctype(ftype)
                    if elem_ftype is not None and _is_scalar_pypeline_int(elem_ftype):
                        v = [_RawField(int(e)) if isinstance(e, int) else e for e in v]
                typed[fname] = v
        else:
            for fname, v in kwargs.items():
                ftype = klass.__annotations__.get(fname)
                if (
                    ftype is not None
                    and isinstance(v, int)  # covers int, SimVal, IntEnum members
                    and _is_scalar_pypeline_int(ftype)
                ):
                    # Always mask/sign-extend to the field's declared bit width,
                    # same as a hardware-typed assignment (`_sim_cast`), so e.g.
                    # p_t(c=a.c+1) wraps identically to `o.c = a.c+1`. A value
                    # already carrying *some* ctype (e.g. arithmetic promoting
                    # uint4_t+int to uint5_t) must still be recast down to
                    # ftype -- `_sim_cast` itself short-circuits the no-op case
                    # where the ctype already matches ftype exactly.
                    v = _sim_cast(v, ftype)
                elif ftype is not None and (type(v) is list or isinstance(v, str)):
                    # Array-of-scalar field passed a raw Python list (e.g. a list
                    # literal) or, for a char/uint8_t array field, a bare Python str:
                    # cast/convert via _sim_cast_deep so it carries the field's bit
                    # width (and, for char_t[N], becomes a CharArray). Struct/array
                    # elements are left untouched -- they self-type via their own
                    # constructor.
                    if _array_elem_ctype(ftype) is not None:
                        v = _sim_cast_deep(v, ftype)
                typed[fname] = v
        return _orig_new(klass, **typed)

    cls.__new__ = staticmethod(_typed_new)

    # Operator overloading for registered struct types (e.g. floating-point
    # add/sub/mul/div): consult the same registries the hardware elaborator
    # uses, so `a + b` also works during plain Python/native simulation, not
    # just hardware elaboration. No registration -> clear TypeError, rather
    # than the tuple/NamedTuple default (concatenation for +, repeat for *).
    cls.__add__ = lambda self, other: _struct_dispatch_binary_op("PLUS", self, other)
    cls.__sub__ = lambda self, other: _struct_dispatch_binary_op("MINUS", self, other)
    cls.__mul__ = lambda self, other: _struct_dispatch_binary_op(
        "INFERRED_MULT", self, other
    )
    cls.__truediv__ = lambda self, other: _struct_dispatch_binary_op("DIV", self, other)
    cls.__neg__ = lambda self: _struct_dispatch_unary_op("NEGATE", self)
    # Comparisons: no built-in fallback exists for structs (NamedTuple's default
    # lexicographic tuple ordering is not a meaningful hardware comparison), so
    # these are TypeErrors unless registered -- matching _elab_compare, which
    # now also consults the operator registry (see PY_TO_LOGIC._elab_compare).
    cls.__lt__ = lambda self, other: _struct_dispatch_binary_op("LT", self, other)
    cls.__le__ = lambda self, other: _struct_dispatch_binary_op("LTE", self, other)
    cls.__gt__ = lambda self, other: _struct_dispatch_binary_op("GT", self, other)
    cls.__ge__ = lambda self, other: _struct_dispatch_binary_op("GTE", self, other)

    return cls


def enum(cls):
    """Decorator for pypeline enum types. Stamps canonical _pypeline_ctype_name and
    pypeline metadata onto an IntEnum subclass (or plain class, which is auto-converted).

    Integer-encoded: each variant is an unsigned integer value. The underlying uint width
    is computed from the maximum member value at decoration time.

    Usage:
        from enum import IntEnum
        from pypeline import enum

        @enum
        class state_t(IntEnum):
            IDLE    = 0
            RUNNING = 1
            DONE    = 2

        # Parameterizable factory (user-written):
        def make_my_enum_t(include_err=True):
            members = {"IDLE": 0, "RUN": 1}
            if include_err:
                members["ERR"] = 2
            return enum(IntEnum("my_enum_t", members))
    """
    if not isinstance(cls, type) or not issubclass(cls, _IntEnum):
        # Plain class body: extract members in definition order, supporting both
        # explicit int values and auto() (which assigns 0-based sequential values).
        members = {}
        counter = 0
        for k, v in vars(cls).items():
            if k.startswith("_"):
                continue
            if isinstance(v, _auto):
                members[k] = counter
                counter += 1
            elif isinstance(v, int):
                members[k] = v
                counter = v + 1
        cls = _IntEnum(cls.__name__, members)

    # Canonical name: name_MEMBER1_val1_MEMBER2_val2 sorted by value
    parts = [f"{m.name}_{m.value}" for m in sorted(cls, key=lambda m: m.value)]
    canonical = cls.__name__ + ("_" + "_".join(parts) if parts else "")
    if len(canonical) > _MAX_MANGLE_NAME_LEN:
        h = _hashlib.sha256(canonical.encode()).hexdigest()[:8]
        ctype_name = f"{cls.__name__}_{h}"
    else:
        ctype_name = canonical

    n_bits = _enum_bit_width(cls)
    cls._pypeline_ctype_name = ctype_name
    cls._pypeline_ctype_canonical = canonical
    cls._pypeline_is_enum = True
    cls._pypeline_enum_int_ctype = f"uint{n_bits}_t"
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

    The function body may also read (or write) a module-level Wire[T]/Input[T]/
    Output[T] directly by bare name (or module.attr for a cross-module wire) --
    the same AST rewriting @hw_func/@MAIN bodies get is applied here too, via
    _sim_type_wrap, so e.g. `print(out0)` inside a @sim_output body works without
    out0 being passed in as an argument. This works no matter where the function
    is called from in the design -- a top-level @MAIN body, or a nested
    non-MAIN helper -- not just one fixed location.

    Known limitation: a @sim_output function that both references a wire
    directly AND uses `global x; x = ...` to mutate an unrelated plain Python
    module-level variable will only see that mutation in its own subsequent
    calls (it runs against a rebuilt, detached copy of the module's globals
    dict), not from other code reading the true module attribute externally.
    """
    hw_fn = _sim_type_wrap(fn)

    @_functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if _sim_converging:
            return SimVal(0)
        return hw_fn(*args, **kwargs)

    wrapper._is_sim_output = True
    return wrapper


def sim_input(fn):
    """Mark a function as simulation input-only -- the temporal/directional mirror
    of @sim_output.

    Two supported call forms, usable interchangeably or together:
      - direct-write form: the function's own body assigns directly to a
        module-level Wire[T]/Input[T]/Output[T] name (bare name, or module.attr
        for a cross-module wire) -- e.g. `in0 = python_stuff()`. Called as a
        bare statement: `in_global()`.
      - return-value form: the function's own body has no wire reference; its
        return value is captured by the calling @MAIN/@hw_func's own (already
        AST-rewritten) assignment: `in1 = in_return()`.

    Both forms may be called from anywhere in the design -- a top-level @MAIN
    body or a nested plain-Python helper -- any number of times, not just once
    at a fixed point in simulation setup.

    Runs the real body at most once per simulated clock cycle: the first call
    (wherever in the design it happens to occur -- during delta-cycle
    convergence or the unconditional final pass) computes for real and caches
    the result; every later call the same cycle is a pure cache hit. This is
    the temporal mirror of @sim_output's convergence gating: @sim_output defers
    real execution to the final pass; @sim_input executes once, as early as it
    is first reached, so a fresh value is available to every reader throughout
    that cycle's convergence, not just after it. It also keeps convergence
    stable: if the underlying value came from something non-idempotent (a
    counter, a queue pop), calling it more than once per cycle would make its
    wire look like it keeps changing.

    The cache is reset once per cycle -- see pypeline_sim.py's _run_clock_cycle
    (Layer 2) and this module's sim_call() (Layer 1, where each top-level
    sim_call() invocation is itself one cycle).

    Known limitation: the cache key is the function identity only (no args/
    kwargs awareness) -- fine for zero-arg usage, but a @sim_input function
    called with different arguments within the same cycle returns the first
    call's cached result regardless of the later call's own arguments.
    """
    hw_fn = _sim_type_wrap(fn)

    @_functools.wraps(fn)
    def wrapper(*args, **kwargs):
        key = id(wrapper)
        if key in _sim_input_cache:
            return _sim_input_cache[key]
        result = hw_fn(*args, **kwargs)
        _sim_input_cache[key] = result
        return result

    wrapper._is_sim_input = True
    return wrapper


# ─────────────────────────────────────────────
# AUTOPIPELINE: tool-pipelined regions with .latency feedback
# ─────────────────────────────────────────────

# canonical_key -> discovered pipeline stage count, harvested from the
# previous elaborate+sweep pass. Installed only by the pipelinec driver:
# between pin-and-confirm passes (SET_AUTOPIPELINE_LATENCY_CACHE), and again
# before a non---comb `--sim` run's native-sim design import so both
# .latency reads and the AUTOPIPELINE delay-line emulation see the built
# stage counts. Always empty in plain native Pypeline sim (pypeline_sim.py
# run directly) and in --comb/--no_synth/--yosys_json builds, so .latency
# reads 0 there.
_autopipeline_latency_cache: dict = {}
# True once any AUTOPIPELINE .latency was read during the current design-file
# execution. The pipelinec driver uses this to skip the pin-and-confirm pass
# entirely: if no Python code consumed a latency value, the cache cannot have
# influenced the elaborated design, so the bootstrap pass's result is final.
_autopipeline_latency_was_read: bool = False


def SET_AUTOPIPELINE_LATENCY_CACHE(cache: dict) -> None:
    """pipelinec-driver hook: install the previous pass's harvested
    AUTOPIPELINE latencies (canonical_key -> stage count) so the next
    design-file execution's AUTOPIPELINE(...) constructions resolve
    .latency to real values."""
    global _autopipeline_latency_cache
    _autopipeline_latency_cache = dict(cache)


def CLEAR_AUTOPIPELINE_LATENCY_READ_FLAG() -> None:
    global _autopipeline_latency_was_read
    _autopipeline_latency_was_read = False


def AUTOPIPELINE_LATENCY_WAS_READ() -> bool:
    return _autopipeline_latency_was_read


class AUTOPIPELINE:
    """AUTOPIPELINE(func, depth=-1): let the synthesis tool insert pipeline
    registers inside calls to `func` (equivalent to PipelineC's
    `#pragma AUTOPIPELINE`), and expose the discovered stage count as
    `.latency`::

        MY_AP = AUTOPIPELINE(some_func)           # tool picks the depth
        MY_AP = AUTOPIPELINE(some_func, depth=2)  # force exactly 2 stages

        @hw_func
        def my_pipeline(i: my_struct_t) -> my_struct_t:
            return MY_AP(i)        # some_func(i), autopipelined

        MY_AP.latency              # int: pipeline depth; 0 until known

    `func` must already be @hw_func-decorated. Calls through the instance are
    an identity passthrough in proto-simulation (`MY_AP(x)` just runs
    `func(x)`); in elaboration the call becomes a submodule instance of
    `func` tagged for autopipelining, and AUTOPIPELINE itself produces no
    hardware. Under a pipelinec non---comb `--sim` build's native simulation
    the call site instead emulates the built pipeline: an N-deep output delay
    line (N = .latency, installed from the final harvest) makes
    out(t) = func(in(t-N)), cycle-accurate against the generated VHDL (see
    _sim_delay_line below).

    .latency reads 0:
      - always in plain native Pypeline sim (pypeline_sim.py run directly --
        no synthesis ever runs),
      - always in --comb / --no_synth / --yosys_json builds (no throughput
        sweep ever runs),
      - during the bootstrap elaboration pass of a real synthesizing build.
    On a real build the pipelinec driver re-executes the design after the
    throughput sweep with the discovered stage counts installed, so .latency
    then resolves to the real value (see the pin-and-confirm loop in
    docs/SYN_DESIGN.md) -- including in the native simulation a non---comb
    `--sim` build launches at the end.

    CONSTRUCTION TIMING MATTERS: construct AUTOPIPELINE(...) once, eagerly,
    as plain Python (typically at a factory function's own top level) and
    capture the object by closure into whatever @hw_func body calls it —
    that is what makes `.latency` visible to surrounding Python code (e.g.
    FIFO sizing). Constructing it inline inside a @hw_func body still
    pipelines correctly, but nothing outside that body can read `.latency`.
    """

    # Duck-type marker probed by the elaborator (PY_TO_LOGIC._elab_call).
    _is_autopipeline_pragma = True

    def __init__(self, func, depth: int = -1):
        if not is_hw_func(func):
            raise TypeError(
                f"AUTOPIPELINE(func, ...): "
                f"{getattr(func, '__qualname__', func)!r} must be "
                f"@hw_func-decorated before being passed in"
            )
        if not isinstance(depth, int):
            raise TypeError(f"AUTOPIPELINE depth must be an int, got {depth!r}")
        self.func = func
        self.depth = depth
        self._canonical_key = None
        # Skip key computation entirely when the cache is empty (native sim,
        # comb builds, bootstrap pass): keeps pure-sim runs from importing
        # the compiler (see canonical_key).
        if _autopipeline_latency_cache:
            self._latency = _autopipeline_latency_cache.get(self.canonical_key, 0)
        else:
            self._latency = 0

    @property
    def latency(self) -> int:
        global _autopipeline_latency_was_read
        _autopipeline_latency_was_read = True
        return self._latency

    @property
    def canonical_key(self) -> str:
        if self._canonical_key is None:
            # Lazy so pure native-sim runs never import the compiler; any
            # context that needs the key (elaboration, non-empty cache) has
            # PY_TO_LOGIC loaded already.
            import PY_TO_LOGIC

            self._canonical_key = PY_TO_LOGIC.CANONICAL_CALLABLE_KEY(self.func)
        return self._canonical_key

    def __call__(self, *args, **kwargs):
        if _sim_active and self._latency > 0:
            # Native sim with a pinned latency (pipelinec non---comb --sim
            # builds install the harvested stage counts before the sim's
            # design import): emulate the N-stage pipeline with a per-call-site
            # output delay line instead of the zero-latency identity.
            # canonical_key is already computed (cache was non-empty at
            # __init__) and distinguishes two different AUTOPIPELINE objects
            # called from the same source line (e.g. a loop over
            # factory-produced APs whose funcs share a __qualname__).
            _sim_inst_stack.append(
                (
                    "AUTOPIPELINE:" + self.canonical_key,
                    _sim_capture_call_loc(_sys._getframe(1)),
                )
            )
            try:
                return self._sim_delay_line(args, kwargs)
            finally:
                _sim_inst_stack.pop()
        return self.func(*args, **kwargs)

    def _sim_delay_line(self, args, kwargs):
        """Native-sim emulation of this call site as an N-stage pipeline:
        out(t) = func(in(t - N)), N = self._latency.

        Follows _call_sim_model's commit discipline: read the delay line
        committed at the last clock edge, buffered-write the shifted copy, so
        under convergence every re-evaluation this cycle reads the same
        committed line (output is input-independent -- no convergence churn)
        and only the final pass's buffered write lands at
        _sim_reg_flush_buffer. Warm-up matches hardware's empty pipeline:
        the first N outputs are typed zeros of func's return type.

        Deepcopies guard aliasing: the pushed result may alias caller objects
        (e.g. func returning an input), and committed[0] is returned to every
        re-evaluation in the cycle -- caller mutation of either must not
        corrupt the committed line.
        """
        inst_path = _sim_current_inst_path()
        committed = _sim_reg_read(inst_path, _SIM_AP_DELAY_KEY, None)
        if committed is None:
            out_t = hw_return_type(self.func)
            committed = [sim_zero(out_t) for _ in range(self._latency)]
        now = self.func(*args, **kwargs)
        _sim_reg_write(
            inst_path, _SIM_AP_DELAY_KEY, committed[1:] + [_copy.deepcopy(now)]
        )
        return _copy.deepcopy(committed[0])

    def __repr__(self):
        # AUTOPIPELINE objects get captured in factory closures (e.g.
        # _autopipeline_with_io_regs), and closure cell reprs feed the
        # canonical entity-name hashing in PY_TO_LOGIC. That makes two
        # properties load-bearing here:
        #   - deterministic (no memory address): an address-bearing default
        #     repr would rename entities on every design re-execution,
        #     breaking the pin-and-confirm pass's cross-pass matching;
        #   - fully distinguishing: two AUTOPIPELINE objects wrapping
        #     different factory-produced funcs must repr differently even
        #     when the funcs share a qualname (the funcs' own closure values
        #     included -- e.g. five make_stream_pipeline invocations all wrap
        #     a 'func_stream' closure, each over a different user core), or
        #     their wrapper entities collide into one FuncLogicLookupTable
        #     entry and mis-wire.
        # canonical_key (PY_TO_LOGIC.CANONICAL_CALLABLE_KEY) provides both;
        # in pure native-sim runs the compiler isn't loaded (and nothing
        # hashes reprs there), so fall back to a readable module.qualname.
        import sys

        if "PY_TO_LOGIC" in sys.modules:
            inner = self.canonical_key
        else:
            import inspect

            func = inspect.unwrap(self.func)
            qual = getattr(func, "__qualname__", "?")
            mod = getattr(func, "__module__", "?")
            inner = f"{mod}.{qual}"
        return f"AUTOPIPELINE({inner}, depth={self.depth})"


def _autopipeline_with_io_regs(func, has_input_reg: bool, has_output_reg: bool):
    """Internal helper: AUTOPIPELINE(func) plus optional unconditional
    every-cycle Reg[T] input/output boundary registers around the call
    (the registered-input/registered-output idiom).

    Returns (wrapped_func, autopipeline_call): wrapped_func has func's own
    (in_type) -> out_type signature; autopipeline_call is the AUTOPIPELINE
    instance so callers can read .latency. Note .latency is func's own core
    pipeline depth only — the boundary registers added here are NOT included
    (callers account for them, e.g. total = has_input_reg + .latency +
    has_output_reg).
    """
    ap = AUTOPIPELINE(func)
    (in_type,) = hw_arg_types(func)
    out_type = hw_return_type(func)

    if has_input_reg and has_output_reg:

        @hw_func
        def autopipelined(x: in_type) -> out_type:
            in_reg: Reg[in_type]
            out_reg: Reg[out_type]
            rv: out_type = out_reg
            out_reg = ap(in_reg)
            in_reg = x
            return rv

    elif has_input_reg:

        @hw_func
        def autopipelined(x: in_type) -> out_type:
            in_reg: Reg[in_type]
            rv: out_type = ap(in_reg)
            in_reg = x
            return rv

    elif has_output_reg:

        @hw_func
        def autopipelined(x: in_type) -> out_type:
            out_reg: Reg[out_type]
            rv: out_type = out_reg
            out_reg = ap(x)
            return rv

    else:

        @hw_func
        def autopipelined(x: in_type) -> out_type:
            return ap(x)

    return autopipelined, ap


# ─────────────────────────────────────────────
# AUTOFSM: tool-scheduled resource-shared FSM regions
# ─────────────────────────────────────────────

# canonical_key -> schedule dict, harvested from the previous elaborate pass by
# AUTOFSM.HARVEST_AUTOFSM_SCHEDULES and installed by the pipelinec driver
# (SET_AUTOFSM_SCHEDULE_CACHE) before the design file is re-executed, and again
# before a non---comb `--sim` run's native-sim design import so both .latency
# reads and the FSM's native-sim emulation see the built state count. Always
# empty in plain native Pypeline sim (pypeline_sim.py run directly) and in
# --comb/--no_synth/--yosys_json builds, so .latency reads 0 and the call site
# stays a zero-latency combinational passthrough there.
#
# Schedule dict shape (plain picklable data; see docs/AUTOFSM_DESIGN.md):
#   {"version", "key", "entity", "n_states", "latency", "budget_scale",
#    "at_floor", "floor_ns", "node_to_state", "fu_of_node", "fus",
#    "fu_order", "descended", "entity_delays_snapshot", ...}
_autofsm_schedule_cache: dict = {}


def SET_AUTOFSM_SCHEDULE_CACHE(cache: dict) -> None:
    """pipelinec-driver hook: install the previous pass's harvested AUTOFSM
    schedules (canonical_key -> schedule dict) so the next design-file
    execution's AUTOFSM(...) constructions resolve .latency to real values and
    their call sites elaborate to the generated FSM instead of a passthrough."""
    global _autofsm_schedule_cache
    _autofsm_schedule_cache = dict(cache)


def AUTOFSM_SCHEDULE_CACHE() -> dict:
    return _autofsm_schedule_cache


# Native-sim state key for an AUTOFSM call site's emulated FSM registers,
# mirroring _SIM_AP_DELAY_KEY's role for AUTOPIPELINE delay lines.
_SIM_AUTOFSM_STATE_KEY = "__sim_autofsm_state__"


def _make_autofsm_stream_t(data_t):
    """Build the plain `{data, valid}` struct AUTOFSM uses at its call-site
    boundary. Deliberately a pypeline.py-local twin of
    include/pypeline/stream/stream.py's make_stream_t rather than an import of
    it: pypeline.py is the base module every design imports and must keep zero
    dependency on the include/pypeline library (which designs put on sys.path
    themselves). The two produce structurally identical, duck-type-compatible
    types -- a make_stream_t(T) value can be passed straight into an AUTOFSM
    call site and vice versa -- they just carry different canonical type names.
    """

    @struct
    class autofsm_stream_t(NamedTuple):
        data: data_t
        valid: uint1_t

    return autofsm_stream_t


class AUTOFSM:
    """AUTOFSM(func): implement a pure combinational function as a
    resource-shared finite state machine -- the resource-minimizing dual of
    AUTOPIPELINE.

    Where AUTOPIPELINE(func) builds an initiation-interval-1 pipeline (one full
    copy of func's hardware, cut into N register stages), AUTOFSM(func) builds
    an ~N-state FSM holding ONE shared copy of each distinct operation, executed
    over N clock cycles::

        MY_FSM = AUTOFSM(some_pure_func)      # tool picks the state count

        @MAIN(100.0)
        def top():
            s: MY_FSM.in_stream_t             # {data, valid}
            s.data = x
            s.valid = start_pulse
            o = MY_FSM(s)                     # o: {data, valid}
            if o.valid:
                result_reg = o.data
            ...
        MY_FSM.latency                        # int: fixed in->out cycle count; 0 until known

    Twelve identical adders in `func` (whether written as a Python loop that
    elaborates unrolled, or as twelve separate lines) become ONE adder used in
    twelve different states. The cost is latency and operand multiplexers; the
    win is area. The tool picks the state count so that the chain of operations
    executed in any single state fits the design's clock period -- if a timing
    report blames the FSM, the driver shrinks the per-state delay budget and
    reschedules into more states, the same way the throughput sweep adds
    pipeline stages for AUTOPIPELINE.

    Contract at the call site (fixed latency, one computation in flight):
      - `func` must be @hw_func-decorated, pure (no Reg/Feedback/global wires
        anywhere in its call subtree), and take exactly ONE annotated argument
        (bundle multiple inputs in an @struct) with an annotated return type.
      - The argument is a `{data, valid}` struct -- use `MY_FSM.in_stream_t`,
        or any structurally identical type (e.g. make_stream_t(in_t)).
      - An input is accepted only when the FSM is idle; `valid` pulses asserted
        while it is busy are IGNORED (no backpressure signal in this version --
        space inputs at least .latency cycles apart, which .latency itself lets
        surrounding Python compute).
      - The result appears with a one-cycle `valid` pulse exactly .latency
        cycles after the accepted input cycle; `.data` holds the last result
        between pulses. Initiation interval == .latency.

    .latency reads 0 (and the call site is a zero-latency combinational
    passthrough, `o.data = func(s.data)`, `o.valid = s.valid`):
      - always in plain native Pypeline sim (pypeline_sim.py run directly),
      - always in --comb / --no_synth / --yosys_json builds,
      - during the bootstrap elaboration pass of a real synthesizing build.
    On a real build the pipelinec driver measures the function's operation
    delays, schedules it, and re-executes the design with the schedule
    installed, so .latency then resolves to the real value -- including in the
    native simulation a non---comb `--sim` build launches at the end, where the
    call site emulates the built FSM cycle-accurately.

    CONSTRUCTION TIMING MATTERS, exactly as for AUTOPIPELINE: construct
    AUTOFSM(...) once, eagerly, as plain Python (typically at module or factory
    top level) and capture it by closure into the @hw_func body that calls it --
    that is what makes .latency visible to the surrounding Python.

    See docs/AUTOFSM_DESIGN.md for the scheduler, the generated FSM's shape,
    and the driver's schedule-and-confirm loop.
    """

    # Duck-type marker probed by the elaborator (PY_TO_LOGIC._elab_call).
    _is_autofsm_pragma = True

    def __init__(self, func, max_latency=None):
        if not is_hw_func(func):
            raise TypeError(
                f"AUTOFSM(func): {getattr(func, '__qualname__', func)!r} must be "
                f"@hw_func-decorated before being passed in"
            )
        if max_latency is not None:
            # Reserved for the planned "don't always trade all the latency for
            # area" knob; rejected rather than silently ignored (the AUTOPIPELINE
            # depth= parameter's fate -- accepted, stored, never consumed -- is
            # exactly the trap being avoided here).
            raise NotImplementedError(
                "AUTOFSM(func, max_latency=...): capping the FSM latency is not "
                "implemented yet; omit max_latency to let the tool minimize "
                "resources"
            )
        arg_types = hw_arg_types(func)
        if len(arg_types) != 1:
            raise TypeError(
                f"AUTOFSM(func): {getattr(func, '__qualname__', func)!r} must take "
                f"exactly one annotated argument (got {len(arg_types)}); bundle "
                f"multiple inputs into a single @struct type"
            )
        self.func = func
        self.in_type = arg_types[0]
        self.out_type = hw_return_type(func)
        if self.out_type is None:
            raise TypeError(
                f"AUTOFSM(func): {getattr(func, '__qualname__', func)!r} must have "
                f"an annotated return type"
            )
        self.in_stream_t = _make_autofsm_stream_t(self.in_type)
        self.out_stream_t = _make_autofsm_stream_t(self.out_type)
        self._canonical_key = None
        self._generated = None  # memoized generated hw_func for this pass
        # Snapshot the installed schedule at construction time, mirroring
        # AUTOPIPELINE's latency snapshot: the driver installs the cache before
        # re-executing the design, so every construction in one pass sees one
        # consistent view. Skip key computation entirely when the cache is empty
        # (native sim, comb builds, bootstrap pass) so pure-sim runs never import
        # the compiler.
        if _autofsm_schedule_cache:
            self._schedule = _autofsm_schedule_cache.get(self.canonical_key)
        else:
            self._schedule = None
        self._latency = self._schedule["latency"] if self._schedule else 0

    @property
    def latency(self) -> int:
        return self._latency

    @property
    def schedule(self):
        """The installed schedule dict for this call site, or None before one
        has been computed. Read by the elaborator; designs use .latency."""
        return self._schedule

    @property
    def canonical_key(self) -> str:
        if self._canonical_key is None:
            # Lazy so pure native-sim runs never import the compiler; any
            # context that needs the key (elaboration, non-empty cache) has
            # PY_TO_LOGIC loaded already.
            import PY_TO_LOGIC

            self._canonical_key = PY_TO_LOGIC.CANONICAL_CALLABLE_KEY(self.func)
        return self._canonical_key

    def __call__(self, s):
        data = getattr(s, "data", None)
        valid = getattr(s, "valid", None)
        if data is None or valid is None:
            raise TypeError(
                f"AUTOFSM call argument must be a {{data, valid}} struct (e.g. "
                f"MY_FSM.in_stream_t), got {type(s).__name__}"
            )
        if _sim_active and self._latency > 1:
            # Native sim with a pinned schedule (pipelinec non---comb --sim builds
            # install the harvested schedules before the sim's design import):
            # emulate the built FSM's registers instead of the zero-latency
            # passthrough. canonical_key is already computed (cache was non-empty
            # at __init__) and distinguishes two different AUTOFSM objects called
            # from the same source line.
            _sim_inst_stack.append(
                (
                    "AUTOFSM:" + self.canonical_key,
                    _sim_capture_call_loc(_sys._getframe(1)),
                )
            )
            try:
                return self._sim_fsm(data, valid)
            finally:
                _sim_inst_stack.pop()
        return self.out_stream_t(data=self.func(data), valid=valid)

    def _sim_fsm(self, data, valid):
        """Native-sim emulation of this call site as the generated FSM: a
        register-level model of exactly the state/output registers the generated
        hardware declares (see AUTOFSM.GENERATE_FSM_SOURCE), so the two are
        cycle-accurate against each other by construction rather than by a
        separate timing argument.

        Follows _call_sim_model's / _sim_delay_line's commit discipline: the
        returned value is computed only from state committed at the last clock
        edge (so every re-evaluation during this cycle's convergence returns the
        same thing -- no convergence churn), and the next state is written into
        the buffer, where last-write-wins and only the final pass's write lands
        at _sim_reg_flush_buffer.
        """
        n_states = self._latency - 1
        inst_path = _sim_current_inst_path()
        st = _sim_reg_read(inst_path, _SIM_AUTOFSM_STATE_KEY, None)
        if st is None:
            # Warm-up matches hardware reset: idle, no result yet, typed zeros.
            st = {
                "st": 0,
                "in": sim_zero(self.in_type),
                "out_data": sim_zero(self.out_type),
                "out_valid": 0,
            }
        # Outputs are the committed registers (registered outputs in hardware).
        out = self.out_stream_t(data=st["out_data"], valid=st["out_valid"])
        # Next-state, mirroring the generated body's write order.
        nxt = {
            "st": st["st"],
            "in": st["in"],
            "out_data": st["out_data"],
            "out_valid": 0,
        }
        if st["st"] == 0:
            if valid:
                nxt["in"] = _copy.deepcopy(data)
                nxt["st"] = 1
        elif st["st"] >= n_states:
            # Last execution state: the whole function's result lands in the
            # output registers. (The native model computes func() in one go
            # rather than per-state; the FSM's per-state decomposition is a
            # hardware implementation detail with identical cycle-level
            # behavior at the boundary.)
            nxt["out_data"] = _copy.deepcopy(self.func(st["in"]))
            nxt["out_valid"] = 1
            nxt["st"] = 0
        else:
            nxt["st"] = st["st"] + 1
        _sim_reg_write(inst_path, _SIM_AUTOFSM_STATE_KEY, nxt)
        return out

    def __repr__(self):
        # Same determinism requirement as AUTOPIPELINE.__repr__ (see the long
        # comment there): these objects get captured in factory closures whose
        # cell reprs feed canonical entity-name hashing, so the repr must be
        # address-free and fully distinguishing.
        import sys

        if "PY_TO_LOGIC" in sys.modules:
            inner = self.canonical_key
        else:
            import inspect

            func = inspect.unwrap(self.func)
            qual = getattr(func, "__qualname__", "?")
            mod = getattr(func, "__module__", "?")
            inner = f"{mod}.{qual}"
        return f"AUTOFSM({inner})"


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


def ctype_name(t) -> str:
    """Return the canonical C/VHDL hardware type name for a pypeline type
    (e.g. uint32_t -> "uint32_t", an @struct NamedTuple -> its mangled name).
    Useful when writing raw vhdl(...) text that needs to reference the
    compiler's auto-generated {type}_SLV_LEN constant or {type}_to_slv /
    slv_to_{type} conversion functions for a given pypeline type.
    """
    return _ctype_str(t)


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


# ─────────────────────────────────────────────
# Generic (matcher-based) operator registrations
#
# Exact registrations (register_operator(op, uint32_t, uint32_t, impl)) require
# one call per concrete type pair. A library implementation (e.g. a soft adder)
# needs to cover every width a design happens to promote to, so register_* also
# accept a *type matcher* in place of a concrete type -- and, in that case, a
# *factory* (called lazily with the concrete type objects) in place of a
# finished hw_func. Matches are resolved on miss and memoized back into the
# ordinary exact dicts, so the hot path stays a single dict lookup.
# ─────────────────────────────────────────────


class _IntTypeMatcher:
    """Matches integer ctypes by signedness/max-width predicate.
    Deterministic repr (no object id) -- these can end up embedded in factory
    closures, and canonical entity-name hashing must stay a pure function of
    source (see docs: project_canonical_name_determinism)."""

    __slots__ = ("_name", "_signed", "_max_width")

    def __init__(self, name, signed, max_width=None):
        self._name = name
        self._signed = signed  # True / False / None (None = either signedness)
        self._max_width = max_width

    def matches(self, ctype_str) -> bool:
        if not _ctype_is_int(ctype_str):
            return False
        is_signed, width = _ctype_info(ctype_str)
        if self._signed is not None and is_signed != self._signed:
            return False
        if self._max_width is not None and width > self._max_width:
            return False
        return True

    def __repr__(self):
        return self._name


any_uint_t = _IntTypeMatcher("any_uint_t", signed=False)
any_int_t = _IntTypeMatcher("any_int_t", signed=True)
any_integer_t = _IntTypeMatcher("any_integer_t", signed=None)


def uint_upto(n: int):
    """Matcher: any uintW_t with W <= n."""
    return _IntTypeMatcher(f"uint_upto_{n}", signed=False, max_width=n)


def int_upto(n: int):
    """Matcher: any intW_t with W <= n."""
    return _IntTypeMatcher(f"int_upto_{n}", signed=True, max_width=n)


class _ExactTypeMatcher:
    """Wraps a concrete type as a matcher, so register_operator can mix one
    matcher side with one exact side (e.g. any_uint_t on the left, a fixed
    shift-amount type on the right)."""

    __slots__ = ("_s",)

    def __init__(self, t):
        self._s = _ctype_str(t)

    def matches(self, ctype_str) -> bool:
        return ctype_str == self._s

    def __repr__(self):
        return self._s


def _is_type_matcher(x) -> bool:
    return isinstance(x, _IntTypeMatcher)


def _as_matcher(x):
    return x if _is_type_matcher(x) else _ExactTypeMatcher(x)


def _reconstruct_int_ctype(ctype_str: str):
    """Rebuild a ctype OBJECT (make_uint_t/make_int_t) from its canonical
    string. Only used to hand a generic-registration factory concrete type
    objects -- exact (non-matcher) registrations never need this."""
    is_signed, width = _ctype_info(ctype_str)
    return make_int_t(width) if is_signed else make_uint_t(width)


class _InferredSentinel:
    """Registered as an operator impl to mean "fall through to the built-in
    inferred path" -- the escape hatch for overriding one narrower case out of
    a broader generic registration (e.g. keep one hot function's multiply on
    a DSP while everything else in the design is soft), and the mechanism a
    soft library implementation uses to pin down its own internal recursion
    (e.g. a soft adder's carry chain must not recursively call itself)."""

    def __repr__(self):
        return "INFERRED"


INFERRED = _InferredSentinel()

# Generic (matcher-based) registrations. Lists, most-recently-registered last;
# resolution scans in reverse so a later registration overrides an earlier,
# broader one for overlapping matchers (e.g. register_soft_mult() then
# register_soft_mult_karatsuba() -- the karatsuba registration wins).
_generic_operator_registry: list = []  # [(op, l_matcher, r_matcher, factory_or_INFERRED)]
_generic_left_operator_registry: list = []  # [(op, l_matcher, factory_or_INFERRED)]
_generic_unary_operator_registry: list = []  # [(op, matcher, factory_or_INFERRED)]
# Memoization of resolved generic lookups, keyed on the concrete type string(s).
_generic_operator_cache: dict = {}
_generic_left_operator_cache: dict = {}
_generic_unary_operator_cache: dict = {}
# Scoped counterparts, mirroring _scoped_operator_registry etc.
_scoped_generic_operator_registry: dict = {}  # id(scope) -> [(op, lm, rm, factory)]
_scoped_generic_left_operator_registry: dict = {}
_scoped_generic_unary_operator_registry: dict = {}


def _resolve_generic_operator(op, l_str, r_str):
    """Consult the generic binary registry. Returns a callable, INFERRED, or
    None (no generic registration matches)."""
    key = (op, l_str, r_str)
    if key in _generic_operator_cache:
        return _generic_operator_cache[key]
    impl = None
    for entry_op, lm, rm, factory in reversed(_generic_operator_registry):
        if entry_op == op and lm.matches(l_str) and rm.matches(r_str):
            impl = (
                factory
                if factory is INFERRED
                else factory(_reconstruct_int_ctype(l_str), _reconstruct_int_ctype(r_str))
            )
            break
    _generic_operator_cache[key] = impl
    if impl is not None and impl is not INFERRED:
        _operator_registry[key] = impl
        _registered_binary_op_names.add(op)
    return impl


def _resolve_generic_left_operator(op, l_str):
    key = (op, l_str)
    if key in _generic_left_operator_cache:
        return _generic_left_operator_cache[key]
    impl = None
    for entry_op, lm, factory in reversed(_generic_left_operator_registry):
        if entry_op == op and lm.matches(l_str):
            impl = factory if factory is INFERRED else factory(_reconstruct_int_ctype(l_str))
            break
    _generic_left_operator_cache[key] = impl
    if impl is not None and impl is not INFERRED:
        _left_operator_registry[key] = impl
        _registered_binary_op_names.add(op)
    return impl


def _resolve_generic_unary_operator(op, t_str):
    key = (op, t_str)
    if key in _generic_unary_operator_cache:
        return _generic_unary_operator_cache[key]
    impl = None
    for entry_op, m, factory in reversed(_generic_unary_operator_registry):
        if entry_op == op and m.matches(t_str):
            impl = factory if factory is INFERRED else factory(_reconstruct_int_ctype(t_str))
            break
    _generic_unary_operator_cache[key] = impl
    if impl is not None and impl is not INFERRED:
        _unary_operator_registry[key] = impl
        _registered_unary_op_names.add(op)
    return impl


def register_operator(op: str, left_type, right_type, func, scope=None) -> None:
    """Register a hardware function (or factory) as the implementation of a
    binary operator.

    op:         operator name string, e.g. "PLUS" (+), "GT" (>), "SL" (<<).
    left_type:  C type of the left operand (e.g. uint32_t), OR a type matcher
                (any_uint_t / any_int_t / any_integer_t / uint_upto(n) /
                int_upto(n)) to cover many concrete types with one call.
    right_type: C type of the right operand, or a type matcher (as above).
    func:       callable hardware function object for an exact (concrete-type)
                registration; a factory func(left_type, right_type) -> hw_func
                for a matcher-based (generic) registration; or INFERRED to
                explicitly fall through to the built-in inferred path (an
                escape hatch for overriding one case out of a broader generic
                registration).
    scope:      if provided, registration is active only while elaborating that
                callable (and its callees).
    """
    if _is_type_matcher(left_type) or _is_type_matcher(right_type):
        entry = (op, _as_matcher(left_type), _as_matcher(right_type), func)
        if scope is None:
            _generic_operator_registry.append(entry)
            _generic_operator_cache.clear()
        else:
            _scoped_funcs.add(id(scope))
            _scoped_generic_operator_registry.setdefault(id(scope), []).append(entry)
        return
    key = (op, _ctype_str(left_type), _ctype_str(right_type))
    if scope is None:
        _operator_registry[key] = func
        _registered_binary_op_names.add(op)
    else:
        _scoped_funcs.add(id(scope))
        _scoped_operator_registry.setdefault(id(scope), {})[key] = func


def register_left_operator(op: str, left_type, func, scope=None) -> None:
    """Register a hardware function (or factory) as the implementation of a
    binary operator, matching only on the left operand type. The right
    operand type is derived from the registered function (e.g. shift amount
    derived from value width).

    op:        operator name string, e.g. "SL" (<<) or "SR" (>>).
    left_type: C type of the left operand (e.g. uint32_t), or a type matcher.
    func:      callable hardware function object (exact registration), a
               factory func(left_type) -> hw_func (matcher registration), or
               INFERRED.
    scope:     if provided, registration is active only while elaborating that
               callable (and its callees).
    """
    if _is_type_matcher(left_type):
        entry = (op, left_type, func)
        if scope is None:
            _generic_left_operator_registry.append(entry)
            _generic_left_operator_cache.clear()
        else:
            _scoped_funcs.add(id(scope))
            _scoped_generic_left_operator_registry.setdefault(id(scope), []).append(entry)
        return
    key = (op, _ctype_str(left_type))
    if scope is None:
        _left_operator_registry[key] = func
        _registered_binary_op_names.add(op)
    else:
        _scoped_funcs.add(id(scope))
        _scoped_left_operator_registry.setdefault(id(scope), {})[key] = func


def register_unary_operator(op: str, operand_type, func, scope=None) -> None:
    """Register a hardware function (or factory) as the implementation of a
    unary operator.

    op:           operator name string, e.g. "NEGATE" (-) or "NOT" (~).
    operand_type: C type of the operand (e.g. uint32_t), or a type matcher.
    func:         callable hardware function object (exact registration), a
                  factory func(operand_type) -> hw_func (matcher registration),
                  or INFERRED.
    scope:        if provided, registration is active only while elaborating
                  that callable (and its callees).
    """
    if _is_type_matcher(operand_type):
        entry = (op, operand_type, func)
        if scope is None:
            _generic_unary_operator_registry.append(entry)
            _generic_unary_operator_cache.clear()
        else:
            _scoped_funcs.add(id(scope))
            _scoped_generic_unary_operator_registry.setdefault(id(scope), []).append(entry)
        return
    key = (op, _ctype_str(operand_type))
    if scope is None:
        _unary_operator_registry[key] = func
        _registered_unary_op_names.add(op)
    else:
        _scoped_funcs.add(id(scope))
        _scoped_unary_operator_registry.setdefault(id(scope), {})[key] = func


def _struct_dispatch_call(fn, args):
    """Call a registered struct-operator impl with simulation properly active.

    Mirrors sim_call(): activates _sim_active and pushes fn's own scoped
    registrations for the duration of the call. Without this, a registered
    impl invoked from a bare `a + b` (outside any enclosing sim_call) would
    take _sim_type_wrap's raw-passthrough branch -- skipping both its own
    scoped sub-registrations (e.g. a float adder's internal NEGATE/SR
    helpers) and its own arg/return casting -- silently computing wrong
    results rather than raising, since ints tolerate ctype mismatches
    numerically in a way structs don't surface as errors.
    """
    global _sim_active
    prev_active = _sim_active
    _sim_active = True
    saved = _push_scoped_registrations(fn)
    try:
        return fn(*args)
    finally:
        _pop_scoped_registrations(saved)
        _sim_active = prev_active


def _struct_dispatch_binary_op(op_name, left, right):
    """Look up and call a registered operator for a @struct-typed binary op.
    Mirrors SimVal._dispatch_binary, but structs have no meaningful raw
    fallback (unlike ints), so an unregistered pair raises TypeError instead
    of silently falling through to e.g. tuple concatenation/repeat.
    """
    l_str = left._pypeline_ctype_name
    r_str = getattr(right, "_pypeline_ctype_name", None)
    fn = None
    if r_str:
        fn = _operator_registry.get((op_name, l_str, r_str))
        if fn is None:
            fn = _resolve_generic_operator(op_name, l_str, r_str)
    if fn is None or fn is INFERRED:
        fn = _left_operator_registry.get((op_name, l_str))
        if fn is None:
            fn = _resolve_generic_left_operator(op_name, l_str)
    if fn is INFERRED:
        fn = None
    if not callable(fn):
        raise TypeError(
            f"No {op_name!r} operator registered for {l_str!r} and "
            f"{r_str or type(right).__name__!r} -- use register_operator(...)"
        )
    return _struct_dispatch_call(fn, (left, right))


def _struct_dispatch_unary_op(op_name, operand):
    """Look up and call a registered operator for a @struct-typed unary op."""
    l_str = operand._pypeline_ctype_name
    fn = _unary_operator_registry.get((op_name, l_str))
    if fn is None:
        fn = _resolve_generic_unary_operator(op_name, l_str)
    if fn is INFERRED:
        fn = None
    if not callable(fn):
        raise TypeError(f"No {op_name!r} operator registered for {l_str!r}")
    return _struct_dispatch_call(fn, (operand,))


def _push_scoped_registrations(func):
    """Merge scoped operator registrations for *func* into the active global registries.
    Returns a list of (registry, key, old_value) triples for restoring afterward.
    Scoped entries from outer elaboration frames are already present in the global
    registries, so inner callees automatically inherit them.

    Also provisionally adds the op name to _registered_binary_op_names /
    _registered_unary_op_names (the fast-path sets SimVal's __neg__/__invert__/
    __rshift__/__lshift__ check before bothering to look in the precise
    per-type registries at all) if not already present, so a scoped-only
    registration dispatches correctly even when no unrelated global
    registration for that op name happens to already exist. Without this, a
    scoped NEGATE/SR/SL registration would silently never be consulted --
    SimVal would take its default int-arithmetic fallback instead -- unless
    some other, unrelated module happened to have also globally registered
    that same op name (for any type), which is not something a self-contained
    factory function should have to depend on.
    """
    func_id = id(func)
    if func_id not in _scoped_funcs:
        return _EMPTY_SAVED
    saved = []
    for key, val in _scoped_operator_registry.get(func_id, {}).items():
        saved.append((_operator_registry, key, _operator_registry.get(key)))
        _operator_registry[key] = val
        if key[0] not in _registered_binary_op_names:
            _registered_binary_op_names.add(key[0])
            saved.append((_registered_binary_op_names, key[0], _SCOPED_SET_ADD))
    for key, val in _scoped_left_operator_registry.get(func_id, {}).items():
        saved.append((_left_operator_registry, key, _left_operator_registry.get(key)))
        _left_operator_registry[key] = val
        if key[0] not in _registered_binary_op_names:
            _registered_binary_op_names.add(key[0])
            saved.append((_registered_binary_op_names, key[0], _SCOPED_SET_ADD))
    for key, val in _scoped_unary_operator_registry.get(func_id, {}).items():
        saved.append((_unary_operator_registry, key, _unary_operator_registry.get(key)))
        _unary_operator_registry[key] = val
        if key[0] not in _registered_unary_op_names:
            _registered_unary_op_names.add(key[0])
            saved.append((_registered_unary_op_names, key[0], _SCOPED_SET_ADD))
    # Generic (matcher-based) scoped entries: appended to the live list (stack
    # discipline -- nested push/pop always fully completes before this pop
    # runs, so popping the last N entries is always correct), and the
    # memoization cache is cleared since availability just changed.
    generic_entries = _scoped_generic_operator_registry.get(func_id, [])
    if generic_entries:
        _generic_operator_registry.extend(generic_entries)
        _generic_operator_cache.clear()
        saved.append((_generic_operator_registry, len(generic_entries), _SCOPED_GENERIC_POP))
    generic_left_entries = _scoped_generic_left_operator_registry.get(func_id, [])
    if generic_left_entries:
        _generic_left_operator_registry.extend(generic_left_entries)
        _generic_left_operator_cache.clear()
        saved.append(
            (_generic_left_operator_registry, len(generic_left_entries), _SCOPED_GENERIC_POP)
        )
    generic_unary_entries = _scoped_generic_unary_operator_registry.get(func_id, [])
    if generic_unary_entries:
        _generic_unary_operator_registry.extend(generic_unary_entries)
        _generic_unary_operator_cache.clear()
        saved.append(
            (_generic_unary_operator_registry, len(generic_unary_entries), _SCOPED_GENERIC_POP)
        )
    return saved


_SCOPED_MISSING = object()  # sentinel for _pop_scoped_registrations; created once
_SCOPED_SET_ADD = object()  # sentinel: this saved entry is a set .add() to undo
_SCOPED_GENERIC_POP = object()  # sentinel: this saved entry is N generic-list entries to pop
_EMPTY_SAVED = []  # returned by _push_scoped_registrations when nothing to push


def _pop_scoped_registrations(saved):
    """Restore registry entries (and fast-path set membership) to their pre-push state."""
    for registry, key, old_val in saved:
        if old_val is _SCOPED_SET_ADD:
            registry.discard(key)
        elif old_val is _SCOPED_GENERIC_POP:
            n = key  # here `key` holds the count of entries appended by push
            del registry[len(registry) - n :]
            if registry is _generic_operator_registry:
                _generic_operator_cache.clear()
            elif registry is _generic_left_operator_registry:
                _generic_left_operator_cache.clear()
            else:
                _generic_unary_operator_cache.clear()
        elif old_val is None:
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

    def __call__(self, *args, **kwargs):
        # Never meant to be constructed -- defined only so that typing's
        # _type_check (which merely requires callable()) accepts Feedback[T] as a
        # NamedTuple field annotation, which is how @interface marks a reverse
        # field. Local-variable use (`f: Feedback[T]`) never goes through typing.
        raise TypeError("Feedback[T] is a direction annotation, not a constructible type")


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


def _wire_ann_inner_ctype(ann):
    """The ctype a Wire/Input/Output annotation's `.inner_ctype` actually
    denotes: for `Wire[SomeInterface]` (the bare @interface class, not
    .fwd_t/.fb_t/.stream_t), that's sugar for `Wire[SomeInterface.wire_t]` --
    a flat, non-directional struct (Feedback[T] fields unwrapped to plain T)
    that's a real, flattenable, multi-writer struct ctype. Only Wire gets
    this sugar -- Input/Output are chip-boundary signals, a different use
    case that hasn't come up. Every native-sim/sim_call code path that reads
    a Wire/Input/Output annotation's ctype must go through this, not
    `ann.inner_ctype` directly, so it agrees with PY_TO_LOGIC's real-VHDL
    path (PY_TO_LOGIC._discover_global_wires does the same substitution)."""
    inner_ctype = ann.inner_ctype
    if isinstance(ann, _WireType) and getattr(
        inner_ctype, "_pypeline_is_interface", False
    ):
        return inner_ctype.wire_t
    return inner_ctype


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


def _bit_manip_width(v):
    """Infer the bit width of a sim value for the bit-manipulation prims below."""
    if type(v) is SimVal and v._ctype is not None:
        return len(v._ctype)
    if type(v) is int or type(v) is SimVal:
        return max(1, int(v).bit_length())
    raise TypeError(f"cannot infer bit width for {v!r}")


def _bit_manip_result_ctype(v, width):
    """Preserve v's own ctype when typed, else synthesize a plain uint<width>_t."""
    if type(v) is SimVal and v._ctype is not None:
        return v._ctype
    return make_uint_t(width)


def bit_dup(x, n):
    """Replicate x n times: bit_dup(uint4_t, 4) → uint16_t."""
    w = _bit_manip_width(x)
    xv = int(x) & ((1 << w) - 1)
    result = 0
    for _ in range(n):
        result = (result << w) | xv
    return SimVal(result, ctype=make_uint_t(w * n))


def rotl(x, amount):
    """Rotate x left by amount bits (constant). Matches VHDL's `x rol amount`."""
    w = _bit_manip_width(x)
    xv = int(x) & ((1 << w) - 1)
    amount %= w
    result = (
        xv if amount == 0 else ((xv << amount) | (xv >> (w - amount))) & ((1 << w) - 1)
    )
    return SimVal(result, ctype=_bit_manip_result_ctype(x, w))


def rotr(x, amount):
    """Rotate x right by amount bits (constant). Matches VHDL's `x ror amount`."""
    w = _bit_manip_width(x)
    xv = int(x) & ((1 << w) - 1)
    amount %= w
    result = (
        xv if amount == 0 else ((xv >> amount) | (xv << (w - amount))) & ((1 << w) - 1)
    )
    return SimVal(result, ctype=_bit_manip_result_ctype(x, w))


def bswap(x):
    """Reverse byte order of x."""
    w = _bit_manip_width(x)
    if w % 8 != 0:
        raise ValueError(f"bswap: width {w} is not a multiple of 8")
    xv = int(x) & ((1 << w) - 1)
    nbytes = w // 8
    result = 0
    for i in range(nbytes):
        byte = (xv >> (i * 8)) & 0xFF
        result |= byte << ((nbytes - 1 - i) * 8)
    return SimVal(result, ctype=_bit_manip_result_ctype(x, w))


def bit_assign(base, x, pos):
    """Assign x into base at bit position pos (constant): base[pos+width-1:pos] = x."""
    base_w = _bit_manip_width(base)
    x_w = _bit_manip_width(x)
    mask = ((1 << x_w) - 1) << pos
    result = (int(base) & ~mask) | ((int(x) << pos) & mask)
    result &= (1 << base_w) - 1
    return SimVal(result, ctype=_bit_manip_result_ctype(base, base_w))


def array_to_uint_be(arr):
    """Pack array elements into a single uint, big-endian (element[0] at MSB)."""
    result = 0
    total_w = 0
    for e in arr:
        w = _bit_manip_width(e)
        result = (result << w) | (int(e) & ((1 << w) - 1))
        total_w += w
    return SimVal(result, ctype=make_uint_t(total_w))


def array_to_uint_le(arr):
    """Pack array elements into a single uint, little-endian (element[0] at LSB)."""
    result = 0
    total_w = 0
    for e in reversed(list(arr)):
        w = _bit_manip_width(e)
        result = (result << w) | (int(e) & ((1 << w) - 1))
        total_w += w
    return SimVal(result, ctype=make_uint_t(total_w))


def uint_to_array_be(x, elem_w):
    """Split uint x into array of elem_w-bit elements, big-endian (MSB → element[0])."""
    w = _bit_manip_width(x)
    if w % elem_w != 0:
        raise ValueError(
            f"uint_to_array_be: width {w} not a multiple of elem_w {elem_w}"
        )
    n = w // elem_w
    xv = int(x) & ((1 << w) - 1)
    elem_mask = (1 << elem_w) - 1
    elem_ctype = make_uint_t(elem_w)
    return [
        SimVal((xv >> ((n - 1 - i) * elem_w)) & elem_mask, ctype=elem_ctype)
        for i in range(n)
    ]


def uint_to_array_le(x, elem_w):
    """Split uint x into array of elem_w-bit elements, little-endian (LSB → element[0])."""
    w = _bit_manip_width(x)
    if w % elem_w != 0:
        raise ValueError(
            f"uint_to_array_le: width {w} not a multiple of elem_w {elem_w}"
        )
    n = w // elem_w
    xv = int(x) & ((1 << w) - 1)
    elem_mask = (1 << elem_w) - 1
    elem_ctype = make_uint_t(elem_w)
    return [
        SimVal((xv >> (i * elem_w)) & elem_mask, ctype=elem_ctype) for i in range(n)
    ]


def concat(*args):
    """Bit concatenation for simulation: first arg = MSBits, last = LSBits.

    Width of each argument is inferred from its SimVal ctype (via len(ctype)) or,
    for plain Python ints, from max(1, val.bit_length()). The result is a SimVal
    with ctype = make_uint_t(total_bits).

    In hardware (PY_TO_LOGIC elaboration) this function is intercepted and treated
    as variadic tuple concat — see the 'concat' branch in _elab_bit_manip_call.
    """
    widths = [_bit_manip_width(a) for a in args]
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
# Type <-> bytes conversion (packed, unpadded layout)
# ─────────────────────────────────────────────

import linecache as _linecache

_ENDIAN_BYTE_SUFFIX = {"little": "le", "big": "be"}


def _check_endian(endian: str, func_name: str) -> None:
    if endian not in _ENDIAN_BYTE_SUFFIX:
        raise ValueError(
            f"{func_name}: endian must be 'little' or 'big', got {endian!r}"
        )


def _check_bytes_type(t, func_name: str) -> None:
    if not (_is_compound_pypeline_type(t) or _is_scalar_pypeline_int(t)):
        raise TypeError(f"{func_name}: not a pypeline type: {t!r}")


def byte_length(t) -> int:
    """Byte size of a pypeline type t, as a packed-unpadded struct: each leaf
    scalar field rounds up to a whole byte (ceil(width / 8)); fields/elements
    are packed back-to-back in declaration order with no further padding
    (this is NOT C natural alignment). Works for scalars, arrays (any
    nesting), and @struct types.

    Enum types are not supported in this version -- raises NotImplementedError,
    including when an enum appears nested inside a struct or array.

    Pure Python; no hardware elaboration required (analogous to enum_bit_width()).
    """
    if getattr(t, "_pypeline_is_enum", False):
        raise NotImplementedError(
            f"byte_length: enum type {t!r} is not supported by "
            "byte_length/make_type_to_bytes/make_type_from_bytes in this version"
        )
    elem = _array_elem_ctype(t)
    if elem is not None:
        return byte_length(elem) * _array_len(t)
    if hasattr(t, "_fields"):
        return sum(byte_length(t.__annotations__[f]) for f in t._fields)
    return (t.width + 7) // 8


def _enumerate_leaves(t, path=()):
    """Yield (access_path, leaf_ctype) for every scalar leaf of t, in
    declaration order. access_path tokens are int (array index) or str
    (struct field name); () for a bare scalar t. Raises NotImplementedError
    if an enum is encountered anywhere (leaf, nested struct field, or array
    element)."""
    if getattr(t, "_pypeline_is_enum", False):
        raise NotImplementedError(
            f"enum type {t!r} is not supported by "
            "byte_length/make_type_to_bytes/make_type_from_bytes in this version"
        )
    elem = _array_elem_ctype(t)
    if elem is not None:
        for i in range(_array_len(t)):
            yield from _enumerate_leaves(elem, path + (i,))
        return
    if hasattr(t, "_fields"):
        for f in t._fields:
            yield from _enumerate_leaves(t.__annotations__[f], path + (f,))
        return
    yield (path, t)


def _access_expr(root: str, path) -> str:
    """('a', 3, 'b') -> 'root.a[3].b' ; () -> 'root'"""
    s = root
    for tok in path:
        s += f"[{tok}]" if isinstance(tok, int) else f".{tok}"
    return s


def _bytes_type_key(t) -> str:
    """Raw (not yet length-limited) canonical identifier for a pypeline type,
    used as the basis for generated to_bytes/from_bytes function names and as
    the factory memoization cache key. Reuses @struct's own canonical name for
    structs (already deterministic/hash-collapsed); mangles the C type string
    for scalars/arrays, e.g. uint32_t[3] -> uint32_t_3."""
    return getattr(t, "_pypeline_ctype_name", None) or _mangle_type(str(t))


def _finalize_hw_name(name: str) -> str:
    """Collapse a generated hardware function name to fit _MAX_MANGLE_NAME_LEN,
    using the same truncated-prefix + sha256[:8] fallback convention as
    @struct/@enum."""
    if len(name) > _MAX_MANGLE_NAME_LEN:
        h = _hashlib.sha256(name.encode()).hexdigest()[:8]
        name = f"{name[: _MAX_MANGLE_NAME_LEN - 9]}_{h}"
    return name


def _collect_struct_types(t, out=None):
    """Recursively collect every distinct @struct type reachable from t
    (including t itself and any nested struct fields/array elements), keyed by
    canonical name. Used to seed the exec() globals of a generated to_bytes/
    from_bytes function so PY_TO_LOGIC's live-closure struct auto-registration
    (which only scans that function's own __globals__ values, not transitively
    through struct field types) sees every struct shape it needs regardless of
    whether the caller's design module already registered them."""
    if out is None:
        out = {}
    elem = _array_elem_ctype(t)
    if elem is not None:
        _collect_struct_types(elem, out)
        return out
    if hasattr(t, "_fields"):
        name = getattr(t, "_pypeline_ctype_name", None)
        if name is not None and name not in out:
            out[name] = t
            for f in t._fields:
                _collect_struct_types(t.__annotations__[f], out)
    return out


def _exec_generated_func(func_name: str, src: str, extra_globals: dict):
    """exec() a single-function source string (a flat, non-nested `def`, so
    its __qualname__ has no '.<locals>.' and PY_TO_LOGIC's elaborator treats it
    as an ordinary top-level function rather than a factory closure), patching
    linecache so inspect.getsource()/getsourcelines() -- used both by the
    elaborator and by hw_func's own simulation-body analysis -- can recover it.

    The synthetic filename avoids '<', '>', ':' (unlike the common '<string>'-style
    convention) because PY_TO_LOGIC._loc_str embeds os.path.basename(src_file)
    verbatim (aside from '.' -> '_') into generated VHDL identifiers for
    uniqueness -- those characters are legal in a Python/linecache "filename"
    but not in a VHDL identifier, and only fail once the output actually reaches
    a VHDL compiler (e.g. via --sim --ghdl), not under plain --no_synth
    elaboration, which never compiles the generated text.
    """
    fake_file = f"/pypeline_generated_bytes/{func_name}.py"
    _linecache.cache[fake_file] = (len(src), None, src.splitlines(True), fake_file)
    code = compile(src, fake_file, "exec")
    ns = dict(extra_globals)
    exec(code, ns)
    return ns[func_name]


_TYPE_TO_BYTES_CACHE: dict = {}
_TYPE_FROM_BYTES_CACHE: dict = {}


def make_type_to_bytes(t, endian: str = "little"):
    """Factory: returns a hardware function packing a value of type t into a
    fixed uint8_t[byte_length(t)] array, matching a packed/unpadded C struct's
    field order (sub-byte fields round up to 1 byte; no other padding).
    endian in {"little", "big"} controls per-multi-byte-field byte order
    (little = least-significant byte first). The returned function is tagged
    @wires (pure bit rewiring, zero synthesis delay).

    Enum types (including nested in structs/arrays) are not supported in this
    version -- raises NotImplementedError at factory-call time.

    Usage:
        my_struct_to_bytes = make_type_to_bytes(my_struct_t)
        raw: uint8_t[byte_length(my_struct_t)] = my_struct_to_bytes(x)
    """
    _check_endian(endian, "make_type_to_bytes")
    _check_bytes_type(t, "make_type_to_bytes")
    raw_name = _bytes_type_key(t)
    cache_key = (raw_name, endian)
    cached = _TYPE_TO_BYTES_CACHE.get(cache_key)
    if cached is not None:
        return cached

    n = byte_length(t)
    out_t = uint8_t[n]
    func_name = _finalize_hw_name(f"{raw_name}_to_bytes_{_ENDIAN_BYTE_SUFFIX[endian]}")

    leaf_type_names: dict = {}  # ctype-name str -> synthetic global var name
    extra_globals = {"t": t, "out_t": out_t, "wires": wires}

    def _leaf_type_name(leaf_t) -> str:
        key = str(leaf_t)
        varname = leaf_type_names.get(key)
        if varname is None:
            varname = f"_leaf_t{len(leaf_type_names)}"
            leaf_type_names[key] = varname
            extra_globals[varname] = leaf_t
        return varname

    lines = ["@wires", f"def {func_name}(x: t) -> out_t:", "    rv: out_t"]
    base = 0
    for path, leaf_t in _enumerate_leaves(t):
        w = leaf_t.width
        k = (w + 7) // 8
        access = _access_expr("x", path)
        if k == 1:
            lines.append(f"    rv[{base}] = {access}")
        else:
            # Bit-slicing is only elaborator-supported on a bare Name or a
            # single struct-attribute chain (PY_TO_LOGIC._try_elab_bit_slice),
            # not on an array-indexed base -- so any leaf reached via an array
            # index (a bare array element, or an array-typed struct field)
            # must first be materialized into a plain local, mirroring the
            # existing hand-written idiom (e.g. wireguard-fpga's
            # `word: uint32_t = block.state[i]` before slicing `word`).
            tmp = f"tmp{base}"
            lines.append(f"    {tmp}: {_leaf_type_name(leaf_t)} = {access}")
            for j in range(k):
                hi = min(w - 1, j * 8 + 7)
                lo = j * 8
                dst = base + j if endian == "little" else base + (k - 1 - j)
                sel = f"{tmp}[{hi}]" if hi == lo else f"{tmp}[{hi}:{lo}]"
                lines.append(f"    rv[{dst}] = {sel}")
        base += k
    lines.append("    return rv")
    src = "\n".join(lines) + "\n"

    extra_globals.update(_collect_struct_types(t))
    fn = _exec_generated_func(func_name, src, extra_globals)
    _TYPE_TO_BYTES_CACHE[cache_key] = fn
    return fn


def make_type_from_bytes(t, endian: str = "little"):
    """Factory: returns a hardware function unpacking a uint8_t[byte_length(t)]
    array into a value of type t. Exact inverse of make_type_to_bytes(t, endian)
    for the same t/endian. The returned function is tagged @wires (pure bit
    rewiring, zero synthesis delay).

    Enum types (including nested in structs/arrays) are not supported in this
    version -- raises NotImplementedError at factory-call time.

    Usage:
        my_struct_from_bytes = make_type_from_bytes(my_struct_t)
        x: my_struct_t = my_struct_from_bytes(raw)
    """
    _check_endian(endian, "make_type_from_bytes")
    _check_bytes_type(t, "make_type_from_bytes")
    raw_name = _bytes_type_key(t)
    cache_key = (raw_name, endian)
    cached = _TYPE_FROM_BYTES_CACHE.get(cache_key)
    if cached is not None:
        return cached

    n = byte_length(t)
    in_t = uint8_t[n]
    func_name = _finalize_hw_name(
        f"{raw_name}_from_bytes_{_ENDIAN_BYTE_SUFFIX[endian]}"
    )

    lines = ["@wires", f"def {func_name}(src: in_t) -> t:", "    rv: t"]
    base = 0
    for path, leaf_t in _enumerate_leaves(t):
        w = leaf_t.width
        k = (w + 7) // 8
        access = _access_expr("rv", path)
        if k == 1:
            lines.append(f"    {access} = src[{base}]")
        else:
            chunks = []
            for j in range(k - 1, -1, -1):
                dst = base + j if endian == "little" else base + (k - 1 - j)
                chunks.append(f"src[{dst}]")
            lines.append(f"    {access} = concat({', '.join(chunks)})")
        base += k
    lines.append("    return rv")
    src = "\n".join(lines) + "\n"

    extra_globals = {"t": t, "in_t": in_t, "concat": concat, "wires": wires}
    extra_globals.update(_collect_struct_types(t))
    fn = _exec_generated_func(func_name, src, extra_globals)
    _TYPE_FROM_BYTES_CACHE[cache_key] = fn
    return fn


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
    by AST and never executes this body). To simulate a vhdl(...)-bodied
    function, attach a Python simulation model to it with @sim_model (below).
    """
    raise NotImplementedError(
        "vhdl(...) has no attached simulation model. It can only be used inside "
        "hardware-elaborated functions — to call a vhdl(...)-bodied function via "
        "sim_call() or pypeline_sim.py, attach a Python simulation model to it "
        "with @sim_model(target)."
    )


def sim_model(target, copy_state=True):
    """Attach a Python simulation model to a hardware function.

    Returns a decorator that registers the model as the native-simulation
    implementation of `target` (an @hw_func/@MAIN-decorated function). Whenever
    target is called during simulation, the model runs instead of target's own
    body; hardware elaboration is completely unaffected (models are invisible
    to the elaborator). This is how vhdl(...)-bodied functions become
    simulable, and it can equally override an ordinary hardware function with
    a faster or higher-level model.

    Exactly one model per target, of either form (a second attachment raises
    ValueError):

    Form 1 -- an @hw_func delegate (synthesizable Pypeline, same signature)::

        @sim_model(accum)
        @hw_func
        def accum_model(din: uint32_t) -> uint32_t:
            total: Reg[uint32_t]
            total = total + din
            return total

    Form 2 -- an arbitrary Python class (sim-only; any state in __init__)::

        @sim_model(accum)
        class AccumModel:
            def __init__(self):
                self.samples = np.array([], dtype=np.uint64)
            def __call__(self, din):
                self.samples = np.append(self.samples, int(din))
                return int(self.samples.sum())

    One class instance is created lazily per hardware instance (per call site,
    the same keying as Reg[T] state), so two call sites of target hold
    independent model state. A pre-constructed callable instance may also be
    attached; with copy_state=True it serves as the per-instance power-on
    template.

    State timing for class/callable models is Reg-like: each evaluation runs
    on a copy.deepcopy of the instance committed at the last clock edge and
    commits through the buffered register-write path, so outputs are a pure
    function of (cycle-start state, current inputs) and pypeline_sim.py
    wire-convergence re-evaluation cannot double-step state. Model __call__
    bodies may run several times per cycle during convergence -- keep them
    side-effect-free, or gate side effects on `not pypeline._sim_converging`
    (the same rule @sim_output exists to solve).

    copy_state=False skips the deepcopy: the instance is created once and
    mutated in place -- faster for heavy state, but NOT convergence-safe (only
    sound when the model's inputs are already final the first time it runs
    each cycle, e.g. plain single-call sim_call() use). Ignored for hw_func
    delegates, whose Reg[T] state already commits through the register path.

    Model outputs are cast to target's declared return type at the call
    boundary, exactly like any hw_func result.
    """
    cell = getattr(target, "_sim_model_cell", None)
    if cell is None:
        raise TypeError(
            f"sim_model target {getattr(target, '__name__', target)!r} is not a "
            f"hardware function — apply @hw_func (or @MAIN) to it first"
        )

    def _attach(model):
        if cell[0] is not None:
            raise ValueError(
                f"{target.__name__!r} already has a sim model attached "
                f"({cell[0][0]!r}); exactly one model (of either form) per "
                f"hardware function"
            )
        if is_hw_func(model):
            kind = "hw_func"
            model_ret = _inspect.unwrap(model).__annotations__.get("return")
            target_ret = _inspect.unwrap(target).__annotations__.get("return")
            if hw_arg_types(model) != hw_arg_types(target) or model_ret != target_ret:
                raise TypeError(
                    f"sim model {model.__name__!r} signature does not match "
                    f"target {target.__name__!r}: an @hw_func delegate must "
                    f"take and return the same hardware types"
                )
        elif isinstance(model, type):
            kind = "class"
            if not any("__call__" in vars(c) for c in model.__mro__):
                raise TypeError(
                    f"sim model class {model.__name__!r} must define __call__"
                )
        elif callable(model):
            kind = "callable"
        else:
            raise TypeError(
                f"sim model must be an @hw_func delegate, a class, or a "
                f"callable instance, not {type(model).__name__}"
            )
        cell[0] = (model, kind, copy_state)
        return model

    return _attach


# ─────────────────────────────────────────────
# hex -- printf-style hex formatting for sim_print/sim_assert f-strings
# (intercepted structurally by PY_TO_LOGIC as a %X marker; this is the real
# callable used when the surrounding code actually runs in native simulation)
# ─────────────────────────────────────────────

_builtin_hex = hex


def hex(value):
    """hex(x) for use inside sim_print/sim_assert f-strings: renders zero-padded
    hex digits with no "0x" prefix, matching VHDL's %X rendering of the same
    value -- e.g. hex(uint8_t value 7) -> "07", not Python's default "0x7".

    Width is taken from the value's ctype (SimVal instances, including bit-slice
    results like x[hi:lo] -- see SimVal.__getitem__) when known; otherwise (a
    plain Python int with no ctype) falls back to Python's own hex(), matching
    the pre-existing behavior for non-hardware values.
    """
    ctype = getattr(value, "_ctype", None)
    if ctype is None:
        return _builtin_hex(value)
    try:
        width = ctype.width
    except (AttributeError, NotImplementedError):
        return _builtin_hex(value)
    nibbles = (width + 3) // 4
    return f"{int(value):0{nibbles}X}"


# ─────────────────────────────────────────────
# sim_print -- printf-style console output
# (intercepted by PY_TO_LOGIC elaborator; also a real callable for simulation)
# ─────────────────────────────────────────────


def sim_print(s, debug=False):
    """printf-style console output: prints during simulation (once per cycle, using
    converged wire values -- same @sim_output-style semantics) and elaborates to a real
    VHDL write(output, ...) statement in hardware.

    Takes exactly one positional argument, matching how it's normally written -- an
    f-string or a plain string literal, e.g.::

        sim_print(f"n={n} hex={hex(n)} ch={chr(n)}")
        sim_print("starting up")

    A trailing newline is appended automatically, like real print(). Unlike PipelineC's C
    printf(fmt, ...), there is no separate %-style multi-argument form -- ordinary Python
    interpolation is used instead; the elaborator reconstructs an equivalent internal
    format string from the f-string's AST (see PY_TO_LOGIC.py's _elab_sim_print_stmt).
    Since Python evaluates the f-string before this function is ever called, the
    simulation side is just a plain print() of the already-formatted text.

    debug=True (must be a compile-time-constant literal True/False) prefixes the message
    with a "[SIM DEBUG PRINT: <abs file path>:<N>]" tag identifying the call site, for use
    with pypeline_sim_debug.py (a tool that diffs sim_print(debug=True) output cycle-by-cycle
    between native and VHDL sim -- ordinary sim_print(...) output, debug=False, is not
    compared by that tool). The tag uses an absolute path + ":<line>" (not just a basename)
    so terminals/editors that recognize "path:line" text can turn it into a clickable jump
    to the call site. The tag is deliberately just file+line, no type info: the format
    string is already shared between native and VHDL rendering (see hex() above and
    PY_TO_LOGIC.py's _build_sim_fmt_string), so the two sims' output for identical source is
    guaranteed to render identically -- no per-type normalization is needed downstream.
    """
    if _sim_converging:
        return SimVal(0)
    if debug:
        import os as _os
        import sys as _sys2

        frame = _sys2._getframe(1)
        tag = f"[SIM DEBUG PRINT: {_os.path.abspath(frame.f_code.co_filename)}:{frame.f_lineno}]"
        # A debug=True print exists only to be cycle-compared against VHDL by
        # pypeline_sim_debug.py. If it fires from inside pipelined combinational
        # logic -- a naturally-pipelined pure MAIN, or an AUTOPIPELINE core --
        # its cycle CANNOT match: native sim runs that comb at stage-0 timing
        # while the VHDL fires it at whatever pipeline stage retiming placed it.
        # Fail loudly rather than emit a print that will silently mis-compare
        # (see pypeline_sim_DESIGN.md's Limitations). Only triggers under a
        # pipelined build; plain native/--comb sim has no pipelined context.
        _sim_check_debug_probe_not_in_pipeline(
            f"{frame.f_code.co_filename}:{frame.f_lineno}"
        )
        s = f"{tag}: {s}"
    print(s)
    return SimVal(0)


def _sim_check_debug_probe_not_in_pipeline(loc: str) -> None:
    """Raise if a sim_print(debug=True) is executing inside pipelined comb
    (a pipelined pure MAIN, or an AUTOPIPELINE core's func evaluation)."""
    in_pipelined_main = (
        _sim_current_main is not None and _sim_current_main in _sim_pipelined_main_info
    )
    in_autopipeline_core = any(
        isinstance(entry[0], str) and entry[0].startswith("AUTOPIPELINE:")
        for entry in _sim_inst_stack
    )
    if in_pipelined_main or in_autopipeline_core:
        where = "a pipelined pure MAIN" if in_pipelined_main else "an AUTOPIPELINE core"
        raise RuntimeError(
            f"sim_print(debug=True) at {loc} executed inside {where}. Its cycle "
            f"cannot be compared against VHDL: native sim runs pipelined comb at "
            f"stage-0 timing while the VHDL fires it at its retimed pipeline "
            f"stage. Move debug=True probes into a stateful (0-latency) MAIN "
            f"that reads the pipeline's output wires (plain sim_print(...) "
            f"without debug=True is fine anywhere -- it is not cycle-compared)."
        )


sim_print._is_sim_print = True


# ─────────────────────────────────────────────
# sim_assert -- simulation-only condition check
# (intercepted by PY_TO_LOGIC elaborator; also a real callable for simulation)
# ─────────────────────────────────────────────


def sim_assert(cond, msg=None):
    """Simulation-only assertion: checks `cond` during simulation (once per cycle, using
    converged wire values -- same semantics as sim_print) and elaborates to a real VHDL
    `assert ... report ... severity failure;` statement in hardware, which halts GHDL
    simulation immediately on failure.

    `msg` is optional, an f-string or plain string literal like sim_print's argument.
    """
    if _sim_converging:
        return SimVal(0)
    assert cond, msg if msg is not None else "sim_assert failed"
    return SimVal(0)


sim_assert._is_sim_assert = True


# ─────────────────────────────────────────────
# sim_finish -- simulation-only stop signal
# (intercepted by PY_TO_LOGIC elaborator; also a real callable for simulation)
# ─────────────────────────────────────────────


class SimFinish(Exception):
    """Raised by sim_finish() to signal that simulation should stop now."""


def sim_finish():
    """Simulation-only stop signal: raises SimFinish during simulation (caught by the
    native-sim run loop to end the run cleanly) and elaborates to a real VHDL
    `std.env.finish;` statement in hardware, halting GHDL simulation.
    """
    if _sim_converging:
        return SimVal(0)
    raise SimFinish()


sim_finish._is_sim_finish = True


# ─────────────────────────────────────────────
# Sim infrastructure: _sim_cast, _sim_type_wrap / hw_func, sim_call
# ─────────────────────────────────────────────

import copy as _copy
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
_sim_wire_state: dict = {}  # wire name → current value (int or struct/array instance)
_sim_wire_ctype: dict = {}  # wire name → inner ctype (for zero defaults / leaf casting)
# claim_key (writer function's qualified name) → {wire name → set of concrete
# written path tuples} -- runtime-recorded driven leaves, reset to zero at the
# top of each of that function's invocations (see _sim_wire_reset_claims).
_sim_wire_claims: dict = {}
_sim_converging: bool = False  # True during delta-cycle convergence passes


def _sim_set_converging(value: bool) -> bool:
    """Set _sim_converging, returning its previous value -- a save/restore helper
    used by _build_reg_sim_func's generated Feedback[T] convergence loop (which
    execs into its own separate globals dict, so a bare assignment there would
    not reach this module's real flag) to suppress sim_print/sim_assert/
    sim_finish/@sim_output during the loop's non-final internal iterations,
    matching the top-level per-cycle driver's own convergence-then-final-pass
    behavior one level deeper.
    """
    global _sim_converging
    old = _sim_converging
    _sim_converging = value
    return old


_sim_reg_write_buffer = None  # None = direct commit; dict = buffered mode
_sim_current_main = None  # MAIN fn currently executing (for reader tracking)
# Naturally-pipelined pure MAINs (sliced by the sweep without AUTOPIPELINE)
# under pipelinec non---comb --sim: main_fn -> {"latency": int, "queue":
# deque of per-cycle write-set lists, "collector": this cycle's list of
# (wire_name, lens_path_tuple, value) entries}. Populated only by
# pypeline_sim.run_sim when the driver hands it a nonzero main latency;
# empty dict = feature off (one truthiness test on the wire-write hot paths).
# Such a MAIN's global-wire writes are diverted into "collector" and applied
# to _sim_wire_state N cycles later (write-side latency emulation: the wire
# values other MAINs read at cycle t are what the MAIN computed at t-N,
# matching hardware where its outputs cross N pipeline register stages).
_sim_pipelined_main_info: dict = {}
_sim_wire_readers: dict = {}  # wire name → set of MAINs that have read it
_sim_active: bool = False  # True only while pypeline_sim.py is driving a simulation run
_sim_input_cache: dict = {}  # id(@sim_input wrapper) → cached result for the current cycle


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
    to stripping the leading [N] from _ctype_name -- the array's own/outer dimension is
    always the *first* bracket, matching C's `T x[A][B]` and PY_TO_LOGIC.py's
    _array_elem_type), or None if ctype is not an array."""
    if not hasattr(ctype, "_ctype_name") or "[" not in ctype._ctype_name:
        return None
    elem_ctype = getattr(ctype, "_elem_ctype", None)
    if elem_ctype is not None:
        return elem_ctype
    m = _re_ctype.search(r"\[(\d+)\]", ctype._ctype_name)
    return _make_ctype(ctype._ctype_name[: m.start()] + ctype._ctype_name[m.end() :])


def _array_len(ctype):
    """Return an array ctype's own (outer/first, leftmost-bracket) dimension, or None if
    not an array."""
    if not hasattr(ctype, "_ctype_name"):
        return None
    arr_len = getattr(ctype, "_arr_len", None)
    if arr_len is not None:
        return arr_len
    m = _re_ctype.search(r"\[(\d+)\]", ctype._ctype_name)
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


def sim_zero(ctype):
    """Return a zero-initialized simulation value for a pypeline ctype (scalar,
    struct, or array) -- the same "power-on" value Reg[T] uses for its reset
    default. For sim_model authors who need a correctly-typed placeholder for
    an arbitrary caller-supplied type before any real data exists yet (e.g. an
    empty queue/buffer's output slot).
    """
    return _make_sim_zero(ctype)


class CharArray(list):
    """Sim-mode representation of a char_t[N] value: a list of SimVal(char_t) that also
    behaves like the Python str it represents, mirroring hardware's %s/strlen display
    convention (stops at the first NUL byte). This is what lets sim_call args/kwargs,
    sim_call return values, and sim_print interpolation all accept/produce plain Python
    str transparently, with no user-facing conversion helpers required."""

    def __str__(self):
        chars = []
        for v in self:
            iv = int(v)
            if iv == 0:
                break
            chars.append(chr(iv))
        return "".join(chars)

    def __repr__(self):
        return f"CharArray({str(self)!r})"

    def __eq__(self, other):
        if isinstance(other, str):
            return str(self) == other
        return list.__eq__(self, other)

    def __ne__(self, other):
        return not self.__eq__(other)

    __hash__ = None


def _sim_cast_deep(value, ctype):
    """Cast value to ctype, recursing through arrays so every scalar leaf becomes a
    typed SimVal -- mirrors hardware where an array's elements all share one declared
    bit width. Structs are left as-is: struct construction already types scalar (and,
    via _typed_new, array-of-scalar) fields at construction time.

    A char_t[N] (or nested char_t[..][N]) target also accepts a bare Python str here,
    zero-padded/length-checked and wrapped in CharArray -- this is the single mechanism
    behind every sim-side string-literal boundary (sim_call args/kwargs/return, Reg[T]
    init, struct-field construction, local var/field assignment inside a simulated
    function body). uint8_t[N] targets accept a str too (matching the elaboration side's
    parity between char/uint8_t string-literal targets) but are not wrapped in CharArray,
    since raw byte arrays aren't meant to behave like display strings."""
    if hasattr(ctype, "_fields"):
        return value
    elem_ctype = _array_elem_ctype(ctype)
    if elem_ctype is None:
        return _sim_cast(value, ctype)
    elem_name = getattr(elem_ctype, "_ctype_name", None)
    if isinstance(value, str):
        if elem_name not in ("char", "uint8_t"):
            raise TypeError(f"string value not valid for array type {ctype!r}")
        n = _array_len(ctype)
        if len(value) > n:
            raise ValueError(
                f"string {value!r} (len {len(value)}) exceeds array size {n}"
            )
        codes = [ord(c) for c in value] + [0] * (n - len(value))
        elems = [_sim_cast(c, elem_ctype) for c in codes]
        return CharArray(elems) if elem_name == "char" else elems
    elems = [_sim_cast_deep(v, elem_ctype) for v in value]
    return CharArray(elems) if elem_name == "char" else elems


def _is_char_like_array(ctype):
    """True if ctype is an array (at any nesting depth) whose ultimate scalar element
    is char or uint8_t -- used to narrowly gate sim_call arg/kwarg/return casting to
    char-array-shaped values, leaving other array types (e.g. uint32_t[N]) passing
    through sim_call untouched, exactly as they do today."""
    elem = _array_elem_ctype(ctype)
    while elem is not None and _array_elem_ctype(elem) is not None:
        elem = _array_elem_ctype(elem)
    return elem is not None and getattr(elem, "_ctype_name", None) in (
        "char",
        "uint8_t",
    )


def strlen(arr) -> int:
    """Simulation-mode strlen(): returns the declared array length (element count) of
    arr, matching the hardware elaborator's constant-fold semantics -- NOT a runtime scan
    for a NUL terminator. This mirrors PipelineC's own strlen() exactly (see
    C_AST_STRLEN_FUNC_CALL_TO_LOGIC in C_TO_LOGIC.py), which is intentionally "declared
    capacity", not "content length". Use str(arr) for content-length string display
    instead."""
    return len(arr)


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
    """Return the current global wire value.
    Records the calling MAIN as a reader of this wire for dependency tracking.
    """
    if _sim_current_main is not None:
        _sim_wire_readers.setdefault(name, set()).add(_sim_current_main)
    if name not in _sim_wire_state:
        raise RuntimeError(
            f"Wire {name!r} was read but never discovered/initialized by "
            f"pypeline_sim's wire scan (_discover_wire_names) -- its declaring "
            f"module may not be reachable from the top design file's import graph."
        )
    return _sim_wire_state[name]


def _sim_wire_write(name: str, value, claim_key=None) -> None:
    """Set the current global wire value (struct types preserved, not converted to int).
    claim_key (the writing function's qualified name, baked in by
    _GlobalWireRewriter) records a whole-wire () claim for that function's
    per-invocation zero-reset (see _sim_wire_reset_claims).

    When the executing MAIN is a pipelined pure MAIN (see
    _sim_pipelined_main_info), the write is diverted into its per-cycle
    collector instead of _sim_wire_state -- pypeline_sim applies it N cycles
    later. Claim recording still happens: the diverted reset-claims path
    relies on _sim_wire_claims to know which leaves to zero."""
    if _sim_pipelined_main_info:
        info = _sim_pipelined_main_info.get(_sim_current_main)
        if info is not None:
            info["collector"].append((name, (), value))
            if claim_key is not None:
                _sim_wire_claims.setdefault(claim_key, {}).setdefault(name, set()).add(
                    ()
                )
            return
    _sim_wire_state[name] = value
    if claim_key is not None:
        _sim_wire_claims.setdefault(claim_key, {}).setdefault(name, set()).add(())


def _sim_wire_current_or_zero(name: str):
    """Return the wire's current value, or its typed zero if never written yet this
    run (e.g. a compound wire read/written leaf-by-leaf before any whole-wire write
    has occurred) -- mirrors hardware's implicit zero-init base wire."""
    if name in _sim_wire_state:
        return _sim_wire_state[name]
    ctype = _sim_wire_ctype.get(name)
    return _make_sim_zero(ctype) if ctype is not None else None


def _sim_wire_lens_read(name: str, path: list):
    """Read a nested field/index of a global wire's current value (or its zero
    default if unwritten so far), registering the calling MAIN as a reader exactly
    like _sim_wire_read (needed so convergence requeues on a foreign writer's
    leaf change)."""
    if _sim_current_main is not None:
        _sim_wire_readers.setdefault(name, set()).add(_sim_current_main)
    obj = _sim_wire_current_or_zero(name)
    for elem in path:
        obj = getattr(obj, elem) if isinstance(elem, str) else obj[int(elem)]
    return obj


def _sim_wire_lens_write(name: str, path: list, value, claim_key=None) -> None:
    """Write a nested field/index of a global wire's value, preserving every other
    leaf (own or another writer's) untouched -- the sim-side flattened-leaf model
    for compound-type Wire[T]/Output[T] partial/field writes.
    claim_key (the writing function's qualified name, baked in by
    _GlobalWireRewriter) records the concrete path written -- field names as
    strs, indices normalized to ints, so dynamic indices claim exactly the
    element(s) actually touched -- for that function's per-invocation
    zero-reset (see _sim_wire_reset_claims).

    Diverted into the executing pipelined MAIN's collector exactly like
    _sim_wire_write (lens path preserved so partial/field writes replay
    leaf-wise N cycles later without clobbering other writers' leaves)."""
    norm_path = tuple(p if isinstance(p, str) else int(p) for p in path)
    if _sim_pipelined_main_info:
        info = _sim_pipelined_main_info.get(_sim_current_main)
        if info is not None:
            info["collector"].append((name, norm_path, value))
            if claim_key is not None:
                _sim_wire_claims.setdefault(claim_key, {}).setdefault(name, set()).add(
                    norm_path
                )
            return
    base = _sim_wire_current_or_zero(name)
    _sim_wire_state[name] = _sim_lens_set(base, path, value)
    if claim_key is not None:
        _sim_wire_claims.setdefault(claim_key, {}).setdefault(name, set()).add(
            norm_path
        )


def _sim_ctype_at_path(ctype, path):
    """Walk a wire's ctype along a claim path (field strs / index ints); None if
    any step can't be resolved (unannotated field etc.)."""
    for p in path:
        if ctype is None:
            return None
        if isinstance(p, str):
            ctype = ctype.__annotations__.get(p) if hasattr(ctype, "_fields") else None
        else:
            ctype = _array_elem_ctype(ctype)
    return ctype


def _sim_wire_reset_claims(claim_key) -> None:
    """Zero every (wire, path) this function has ever written, at the start of
    each invocation -- the sim-side equivalent of elaboration's implicit
    zero-init first alias, scoped to exactly the leaves this function drives.

    Needed because _sim_wire_state is one persistent dict shared across
    repeated invocations of the same function within a cycle (the convergence
    pass, then the final @sim_output pass): without this, a "read own wire
    before this invocation's write" would see the *previous* invocation's
    already-written value instead of zero, and a conditionally-skipped write
    would leave last cycle's value latched instead of reading zero. Claims are
    recorded at runtime by _sim_wire_write/_sim_wire_lens_write with the
    concrete paths actually written (so unrolled loops, nested paths, and
    dynamic indices all reset exactly what they touched), and grow
    monotonically -- matching hardware, where the mux-to-zero structure exists
    for every leaf the function ever writes, every cycle. Resetting only this
    function's own claimed paths (never the whole wire) is essential so one
    writer's reset can't transiently clobber a different writer's
    already-committed leaves of the same wire within one cycle's convergence
    loop.

    When the executing MAIN is pipelined (_sim_pipelined_main_info), the
    zeroing diverts into its collector as zero-valued entries instead of
    touching _sim_wire_state -- otherwise each of that MAIN's invocations
    would wipe the N-cycles-old write-set pypeline_sim applied at the start
    of this cycle. Ordered replay of the collector (zeros first, then this
    invocation's writes; later invocations append again) reproduces the
    reset -> write -> final-pass-wins semantics inside the delayed view."""
    info = (
        _sim_pipelined_main_info.get(_sim_current_main)
        if _sim_pipelined_main_info
        else None
    )
    for wire_name, paths in _sim_wire_claims.get(claim_key, {}).items():
        ctype = _sim_wire_ctype.get(wire_name)
        if () in paths:
            if ctype is not None:
                if info is not None:
                    info["collector"].append((wire_name, (), _make_sim_zero(ctype)))
                else:
                    _sim_wire_state[wire_name] = _make_sim_zero(ctype)
            continue
        for path in paths:
            leaf_ctype = _sim_ctype_at_path(ctype, path)
            if leaf_ctype is None:
                continue
            if info is not None:
                info["collector"].append((wire_name, path, _make_sim_zero(leaf_ctype)))
                continue
            base = _sim_wire_current_or_zero(wire_name)
            _sim_wire_state[wire_name] = _sim_lens_set(
                base, list(path), _make_sim_zero(leaf_ctype)
            )


def _sim_apply_delayed_writes(entries) -> None:
    """Replay one popped pipelined-MAIN write-set (list of (wire_name,
    lens_path, value) entries, in recorded order) onto _sim_wire_state --
    called by pypeline_sim at the start of the cycle N cycles after the set
    was collected. Ordered replay reproduces the original invocation
    sequence (reset zeros, then writes; final pass last), so the net state
    equals what the MAIN would have written live."""
    for name, path, value in entries:
        if path == ():
            _sim_wire_state[name] = value
        else:
            base = _sim_wire_current_or_zero(name)
            _sim_wire_state[name] = _sim_lens_set(base, list(path), value)


def sim_reset():
    """Clear all simulated register and wire state."""
    _sim_reg_state.clear()
    _sim_wire_state.clear()
    _sim_wire_claims.clear()
    _sim_input_cache.clear()


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
    _sim_wire_claims.clear()


class _GlobalWireRewriter(_ast.NodeTransformer):
    """AST transformer that rewrites global wire reads/writes in hw_func bodies.

    Replaces:
      - Name(id='wire', ctx=Load)      →  _sim_wire_read('<mod>.wire')
      - wire = expr                    →  _sim_wire_write('<mod>.wire', expr)   (Expr stmt)
      - wire: T = expr                 →  _sim_wire_write('<mod>.wire', expr)   (AnnAssign with value)
      - module.wire  (Load)            →  _sim_wire_read('<mod>.wire')          (cross-module read)
      - module.wire = expr             →  _sim_wire_write('<mod>.wire', expr)   (cross-module write)

    Sim keys are module-qualified ('<declaring module name>.<wire name>'), not bare
    attribute names -- two different modules declaring a same-named Wire[T] (e.g. both
    calling it "key" for unrelated purposes) must not collide in _sim_wire_state.

    wire_names: {bare_name: qualified_sim_key} for wires declared in the function's own
    defining module. module_wire_attrs: {(alias_name, attr_name): qualified_sim_key} for
    wires in imported modules.

    `self.modified` tracks whether this specific function body actually referenced any
    wire (as opposed to `wire_names`/`module_wire_attrs` being non-empty merely because
    the defining *module* declares wires somewhere else) -- `_build_reg_sim_func` uses
    this to decide whether the function needs the detached-globals rebuilt-body path at
    all. Without a function-specific flag, any function living in a wire-bearing module
    would get rebuilt even if its own body never touches a wire.
    """

    def __init__(
        self,
        wire_names,
        module_wire_attrs=None,
        wire_ctypes=None,
        module_wire_ctypes=None,
        leaf_ctypes_out=None,
        claim_key=None,
    ):
        self._wire_names = dict(wire_names)
        self._module_wire_attrs = module_wire_attrs or {}
        self._wire_ctypes = wire_ctypes or {}  # bare_name -> inner_ctype
        self._module_wire_ctypes = (
            module_wire_ctypes or {}
        )  # (alias, attr) -> inner_ctype
        # leaf_ctypes_out: filled in-place, synthetic __wire_leaf_ctype_L_C__ name ->
        # ctype object -- ctype objects can't be embedded directly as ast.Constant
        # values (Python's compiler only accepts literal types there), so field/index
        # lens writes reference a synthetic global name instead, exactly like
        # _TypedAnnAssignRewriter's __sim_ann_L_C__ mechanism.
        self._leaf_ctypes_out = leaf_ctypes_out if leaf_ctypes_out is not None else {}
        # written_wire_names: qualified sim keys of every wire this function
        # writes anywhere in its body (whole-wire or any field/index lens write).
        # Non-empty => the decoration site injects a one-line
        # `_sim_wire_reset_claims(<claim_key>)` prologue at the top of the
        # rewritten body. The actual per-leaf reset bookkeeping happens at
        # RUNTIME: every rewritten write call carries claim_key (this function's
        # qualified name) and records the concrete path it wrote into
        # _sim_wire_claims, so the prologue zeros exactly the leaves this
        # function has driven -- static fields, nested paths, unrolled-loop or
        # dynamic indices alike -- never a whole compound wire another writer
        # partially owns (see _sim_wire_reset_claims for the full semantics).
        self.written_wire_names: set = set()
        self._claim_key = claim_key
        self.modified = False

    def _record_whole_write(self, wire_name, ctype):
        self.written_wire_names.add(wire_name)

    def _record_field_write(self, wire_name, path_nodes, leaf_ctype, root_ctype):
        self.written_wire_names.add(wire_name)

    def _claim_key_const(self):
        return _ast.Constant(value=self._claim_key)

    def _leaf_ctype_name(self, ctype, node):
        key = f"__wire_leaf_ctype_{node.lineno}_{node.col_offset}__"
        self._leaf_ctypes_out[key] = ctype
        return _ast.Name(id=key, ctx=_ast.Load())

    def visit_Name(self, node):
        if node.id in self._wire_names and isinstance(node.ctx, _ast.Load):
            self.modified = True
            return _ast.copy_location(
                _ast.Call(
                    func=_ast.Name(id="_sim_wire_read", ctx=_ast.Load()),
                    args=[_ast.Constant(value=self._wire_names[node.id])],
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
            self.modified = True
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

    def _wire_root(self, node):
        """If node is exactly a bare wire Name or a module.wire Attribute (the two
        whole-wire root shapes), return (qualified_sim_key, inner_ctype). Else None.
        """
        if isinstance(node, _ast.Name) and node.id in self._wire_names:
            return self._wire_names[node.id], self._wire_ctypes.get(node.id)
        if isinstance(node, _ast.Attribute) and isinstance(node.value, _ast.Name):
            key = (node.value.id, node.attr)
            if key in self._module_wire_attrs:
                return self._module_wire_attrs[key], self._module_wire_ctypes.get(key)
        return None

    def _wire_chain_to_path(self, target):
        """Walk a Store-context Attribute/Subscript chain down to its base and, if
        the base is a global wire (bare name or module.wire), return
        (qualified_sim_key, path_nodes, leaf_ctype, root_ctype). path_nodes are AST
        nodes (Constant(field_name) for attribute steps, the raw slice for subscript
        steps), root-to-leaf order, mirroring _TypedAnnAssignRewriter._chain_to_path.
        Returns (None, None, None, None) if the chain isn't rooted at a wire (e.g. a
        plain local compound variable -- left untouched for _TypedAnnAssignRewriter
        to handle in the pass that runs after this one).
        """
        path = []
        kinds = []
        node = target
        while isinstance(node, (_ast.Attribute, _ast.Subscript)):
            root = self._wire_root(node.value)
            if root is not None:
                if isinstance(node, _ast.Attribute):
                    path.append(_ast.Constant(value=node.attr))
                    kinds.append(("attr", node.attr))
                else:
                    slc = node.slice
                    if isinstance(slc, _ast.Index):  # py3.8 compat
                        slc = slc.value
                    path.append(slc)
                    kinds.append(("idx", None))
                path.reverse()
                kinds.reverse()
                leaf_ctype = root[1]
                for kind, field_name in kinds:
                    if leaf_ctype is None:
                        break
                    if kind == "attr":
                        leaf_ctype = (
                            leaf_ctype.__annotations__.get(field_name)
                            if hasattr(leaf_ctype, "_fields")
                            else None
                        )
                    else:
                        leaf_ctype = _array_elem_ctype(leaf_ctype)
                return root[0], path, leaf_ctype, root[1]
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
        return None, None, None, None

    def _build_lens_write(
        self, wire_name, path_nodes, leaf_ctype, value_node, ref_node
    ):
        """Build `_sim_wire_lens_write(wire_name, [path...], value)` (optionally
        _sim_cast_deep-wrapped), (re-)visiting path_nodes/value_node from scratch so
        nested wire reads are rewritten and no AST node is shared between call sites.
        """
        visited_path = [self.visit(_copy.deepcopy(p)) for p in path_nodes]
        visited_value = self.visit(value_node)
        if leaf_ctype is not None:
            visited_value = _ast.Call(
                func=_ast.Name(id="_sim_cast_deep", ctx=_ast.Load()),
                args=[visited_value, self._leaf_ctype_name(leaf_ctype, ref_node)],
                keywords=[],
            )
        return _ast.Expr(
            value=_ast.Call(
                func=_ast.Name(id="_sim_wire_lens_write", ctx=_ast.Load()),
                args=[
                    _ast.Constant(value=wire_name),
                    _ast.List(elts=visited_path, ctx=_ast.Load()),
                    visited_value,
                    self._claim_key_const(),
                ],
                keywords=[],
            )
        )

    def _build_lens_read(self, wire_name, path_nodes):
        visited_path = [self.visit(_copy.deepcopy(p)) for p in path_nodes]
        return _ast.Call(
            func=_ast.Name(id="_sim_wire_lens_read", ctx=_ast.Load()),
            args=[
                _ast.Constant(value=wire_name),
                _ast.List(elts=visited_path, ctx=_ast.Load()),
            ],
            keywords=[],
        )

    def visit_Assign(self, node):
        if len(node.targets) == 1:
            target = node.targets[0]
            root = self._wire_root(target)
            if root is not None:
                # Whole-wire write: wire = expr  /  module.wire = expr
                self.modified = True
                wire_name = root[0]
                self._record_whole_write(wire_name, root[1])
                new_node = _ast.Expr(
                    value=_ast.Call(
                        func=_ast.Name(id="_sim_wire_write", ctx=_ast.Load()),
                        args=[
                            _ast.Constant(value=wire_name),
                            self.visit(node.value),
                            self._claim_key_const(),
                        ],
                        keywords=[],
                    )
                )
                return _ast.copy_location(new_node, node)
            if isinstance(target, (_ast.Attribute, _ast.Subscript)):
                wire_name, path_nodes, leaf_ctype, root_ctype = (
                    self._wire_chain_to_path(target)
                )
                if wire_name is not None:
                    # Field/index write on a global wire: wire.x = expr, wire.arr[i] = expr,
                    # module.wire.field = expr, ... -- flattened-leaf lens write, preserving
                    # every other leaf (own earlier writes or another writer's leaves).
                    self.modified = True
                    self._record_field_write(
                        wire_name, path_nodes, leaf_ctype, root_ctype
                    )
                    return _ast.copy_location(
                        self._build_lens_write(
                            wire_name, path_nodes, leaf_ctype, node.value, node
                        ),
                        node,
                    )
        return self.generic_visit(node)

    def visit_AugAssign(self, node):
        target = node.target
        root = self._wire_root(target)
        if root is not None:
            # wire += expr  /  module.wire += expr
            self.modified = True
            wire_name = root[0]
            self._record_whole_write(wire_name, root[1])
            new_val = _ast.BinOp(
                left=_ast.Call(
                    func=_ast.Name(id="_sim_wire_read", ctx=_ast.Load()),
                    args=[_ast.Constant(value=wire_name)],
                    keywords=[],
                ),
                op=node.op,
                right=self.visit(node.value),
            )
            new_node = _ast.Expr(
                value=_ast.Call(
                    func=_ast.Name(id="_sim_wire_write", ctx=_ast.Load()),
                    args=[
                        _ast.Constant(value=wire_name),
                        new_val,
                        self._claim_key_const(),
                    ],
                    keywords=[],
                )
            )
            return _ast.copy_location(new_node, node)
        if isinstance(target, (_ast.Attribute, _ast.Subscript)):
            wire_name, path_nodes, leaf_ctype, root_ctype = self._wire_chain_to_path(
                target
            )
            if wire_name is not None:
                self.modified = True
                self._record_field_write(wire_name, path_nodes, leaf_ctype, root_ctype)
                read_call = self._build_lens_read(wire_name, path_nodes)
                new_val = _ast.BinOp(
                    left=read_call, op=node.op, right=self.visit(node.value)
                )
                # new_val already fully built (embeds a lens-read call, not a raw
                # source expr) -- build the write directly instead of routing through
                # _build_lens_write's self.visit(value_node), which is only meant for
                # unvisited source expressions.
                visited_path = [self.visit(_copy.deepcopy(p)) for p in path_nodes]
                cast_val = (
                    _ast.Call(
                        func=_ast.Name(id="_sim_cast_deep", ctx=_ast.Load()),
                        args=[new_val, self._leaf_ctype_name(leaf_ctype, node)],
                        keywords=[],
                    )
                    if leaf_ctype is not None
                    else new_val
                )
                new_node = _ast.Expr(
                    value=_ast.Call(
                        func=_ast.Name(id="_sim_wire_lens_write", ctx=_ast.Load()),
                        args=[
                            _ast.Constant(value=wire_name),
                            _ast.List(elts=visited_path, ctx=_ast.Load()),
                            cast_val,
                            self._claim_key_const(),
                        ],
                        keywords=[],
                    )
                )
                return _ast.copy_location(new_node, node)
        return self.generic_visit(node)

    def visit_AnnAssign(self, node):
        # Annotated assignment with a value inside a function body, e.g. x: T = expr.
        # Module-level wire declarations (no value) are untouched.
        node = self.generic_visit(node)
        if (
            isinstance(node.target, _ast.Name)
            and node.target.id in self._wire_names
            and node.value is not None
        ):
            self.modified = True
            wire_name = self._wire_names[node.target.id]
            self._record_whole_write(wire_name, self._wire_ctypes.get(node.target.id))
            return _ast.copy_location(
                _ast.Expr(
                    value=_ast.Call(
                        func=_ast.Name(id="_sim_wire_write", ctx=_ast.Load()),
                        args=[
                            _ast.Constant(value=wire_name),
                            node.value,
                            self._claim_key_const(),
                        ],
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
            # `var: T = value` -- always deep-cast so every scalar leaf (at any
            # array nesting depth) becomes a properly width-tagged SimVal. `value`
            # is not always already shaped that way: it may be a string literal, a
            # bare Name referencing an external plain-int list/tuple constant (e.g.
            # a testbench sourcing test vectors from another module), a list
            # literal/comprehension of raw ints, etc. Without this, per-element
            # width has to be *guessed* from each raw int's value wherever the
            # array is later consumed (e.g. array_to_uint_be/le's bit_length()
            # fallback) -- wrong for any element whose value doesn't happen to set
            # its type's MSB. _sim_cast_deep is idempotent on already-typed values
            # and passes structs through unchanged (its own `_fields` fast path),
            # so this is safe to apply unconditionally.
            self.modified = True
            new_node = _ast.Assign(
                targets=[node.target],
                value=self._make_deep_cast(node.value, ann_val, node),
            )
            return _ast.copy_location(new_node, node)
        if isinstance(ann_val, (_RegType, _FeedbackType)):
            if _is_compound_pypeline_type(ann_val.inner_ctype):
                # Reg[T]/Feedback[T] where T is a struct/array: the read-back value is
                # an immutable NamedTuple (or plain list), exactly like a bare compound
                # local, so nested .field=/[i]= writes need the same lens-rewrite. The
                # AnnAssign itself is left untouched — _build_reg_sim_func handles
                # Reg/Feedback read/zero-init separately.
                self._compound_declared[node.target.id] = ann_val.inner_ctype
            elif _is_scalar_pypeline_int(ann_val.inner_ctype):
                # Reg[T]/Feedback[T] where T is scalar: the read-back value is a
                # plain int/SimVal, exactly like a bare scalar local, so a later
                # plain `var = expr` reassignment in the same body needs the same
                # _sim_cast wrap. Without this, `var` can become an untyped/
                # unmasked raw Python int on a later cycle, which then poisons any
                # bitwise op combining it with a properly-typed sibling operand.
                # The AnnAssign itself is left untouched — _build_reg_sim_func
                # handles the actual read/zero-init separately.
                self._declared_types[node.target.id] = ann_val.inner_ctype
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
                    # _sim_cast_deep accepts a str RHS directly for a char/uint8_t
                    # array leaf type, so a string-literal write like `n.name = "id"`
                    # is handled by the same deep-cast call as every other write.
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
    # Sim keys are module-qualified ("<module>.<wire>") so two unrelated modules
    # declaring a same-named Wire[T] (e.g. both calling it "key") don't collide in
    # the single global _sim_wire_state dict.
    _own_mod_name = fn.__module__
    global_wire_names = {
        name: f"{_own_mod_name}.{name}"
        for name, ann in fn.__globals__.get("__annotations__", {}).items()
        if isinstance(ann, (_WireType, _InputType, _OutputType))
    }
    global_wire_ctypes = {
        name: _wire_ann_inner_ctype(ann)
        for name, ann in fn.__globals__.get("__annotations__", {}).items()
        if isinstance(ann, (_WireType, _InputType, _OutputType))
    }
    # Also build a map for cross-module wire access (module_alias.wire_name).
    # Scans all module objects in fn.__globals__ for wire annotations.
    module_wire_attrs = {}
    module_wire_ctypes = {}
    for _alias, _obj in fn.__globals__.items():
        if not isinstance(_obj, _types.ModuleType):
            continue
        for _wname, _ann in getattr(_obj, "__annotations__", {}).items():
            if isinstance(_ann, (_WireType, _InputType, _OutputType)):
                module_wire_attrs[(_alias, _wname)] = f"{_obj.__name__}.{_wname}"
                module_wire_ctypes[(_alias, _wname)] = _wire_ann_inner_ctype(_ann)
    # Register every discovered wire's ctype globally (keyed by qualified sim name)
    # so _sim_wire_lens_read/_sim_wire_lens_write can build a typed zero default for
    # a compound wire before any whole-wire write has ever landed in _sim_wire_state.
    for _bare_name, _qual_key in global_wire_names.items():
        _sim_wire_ctype[_qual_key] = global_wire_ctypes[_bare_name]
    for _mod_key, _qual_key in module_wire_attrs.items():
        _sim_wire_ctype[_qual_key] = module_wire_ctypes[_mod_key]
    wire_leaf_ctypes_out: dict = {}
    _wire_rewriter_modified = False
    if global_wire_names or module_wire_attrs:
        _wire_claim_key = f"{fn.__module__}.{fn.__qualname__}"
        _wire_rewriter = _GlobalWireRewriter(
            global_wire_names,
            module_wire_attrs,
            global_wire_ctypes,
            module_wire_ctypes,
            wire_leaf_ctypes_out,
            _wire_claim_key,
        )
        _wire_rewriter.visit(func_def)
        # If this function writes any wire, inject a one-line prologue that zeros
        # every (wire, path) this function has claimed so far
        # (_sim_wire_reset_claims) -- each invocation starts from the same
        # implicit zero-init elaboration gives it, scoped to exactly this
        # function's own driven leaves so the reset can never clobber a
        # different writer's already-committed leaves of a shared wire within
        # one cycle's convergence loop. The claimed-path bookkeeping itself is
        # runtime: every rewritten write call carries _wire_claim_key and
        # records the concrete path written (static fields, nested paths,
        # unrolled-loop and dynamic indices all land as the exact elements
        # touched).
        if _wire_rewriter.written_wire_names:
            func_def.body[0:0] = [
                _ast.Expr(
                    value=_ast.Call(
                        func=_ast.Name(id="_sim_wire_reset_claims", ctx=_ast.Load()),
                        args=[_ast.Constant(value=_wire_claim_key)],
                        keywords=[],
                    )
                )
            ]
        _ast.fix_missing_locations(func_def)
        _wire_rewriter_modified = _wire_rewriter.modified

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
    feedback_zeros = {}  # name → typed zero bootstrap value (struct/array-aware)
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
        except Exception as _ann_exc:
            if (
                isinstance(stmt.annotation, _ast.Subscript)
                and isinstance(stmt.annotation.value, _ast.Name)
                and stmt.annotation.value.id in ("Reg", "Feedback")
            ):
                raise NotImplementedError(
                    f"Could not resolve {stmt.annotation.value.id}[...] annotation type "
                    f"for '{stmt.target.id}': {_ast.dump(stmt.annotation)}"
                ) from _ann_exc
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
                    # so that field access (pt.x) works in the simulated body; this
                    # must happen before _sim_cast_deep below, whose struct fast path
                    # (`hasattr(ctype, "_fields")`) passes an already-NamedTuple value
                    # through unchanged.
                    if isinstance(init_val, dict) and hasattr(
                        ann_val.inner_ctype, "_fields"
                    ):
                        init_val = ann_val.inner_ctype(**init_val)
                    # Always deep-cast: turns a scalar/array-of-scalar literal init
                    # (e.g. `have: Reg[uint1_t] = 1`) into a properly width-masked,
                    # typed SimVal instead of leaving it as a bare Python int/list —
                    # otherwise it starts life on cycle 0 untyped and can poison a
                    # bitwise op combining it with a typed sibling operand. Also
                    # accepts a bare str for a char/uint8_t-array target (zero-padded),
                    # subsuming the previous str-only special case. Idempotent/safe
                    # for structs (passes through via the `_fields` fast path).
                    init_val = _sim_cast_deep(init_val, ann_val.inner_ctype)
                    reg_zeros[stmt.target.id] = init_val
                except Exception:
                    reg_zeros[stmt.target.id] = _make_sim_zero(ann_val.inner_ctype)
            else:
                reg_zeros[stmt.target.id] = _make_sim_zero(ann_val.inner_ctype)
        elif isinstance(ann_val, _FeedbackType) and stmt.value is None:
            feedback_names.append(stmt.target.id)
            feedback_zeros[stmt.target.id] = _make_sim_zero(ann_val.inner_ctype)

    if (
        not reg_names
        and not feedback_names
        and not _wire_rewriter_modified
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
            new_stmts.append(_ast.parse(f"{name} = __fb_zero_{name}__").body[0])
        new_stmts.append(_ast.parse("__fb_iters = 0").body[0])
        new_stmts.append(_ast.parse("__fb_final_pass = False").body[0])
        # Suppress sim_print/sim_assert/sim_finish/@sim_output (via the shared
        # _sim_converging flag) for every convergence iteration except the
        # final, already-settled one -- see _sim_set_converging's docstring.
        # __fb_entry_converging remembers what the flag actually was on entry
        # (may already be True if this call is itself nested inside an outer
        # suppressed pass), restored below before the real final iteration and
        # unconditionally on exit.
        new_stmts.append(
            _ast.parse("__fb_entry_converging = _sim_set_converging(True)").body[0]
        )

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
        # Only unsuppress (restore the caller's real flag) on the extra,
        # already-converged final iteration -- see comment at __fb_entry_converging.
        loop_body.append(
            _ast.parse(
                "if __fb_final_pass: _sim_set_converging(__fb_entry_converging)"
            ).body[0]
        )

    # Original function body (both Reg[T] and Feedback[T] AnnAssigns removed;
    # trailing return extracted above when feedback is present).
    loop_body.extend(loop_stmts)

    # Convergence check (feedback present) or unconditional single-pass break.
    if feedback_names:
        # Two-phase: once the snapshot matches (fixed point reached), don't
        # break immediately -- loop back for exactly one more, now-unsuppressed
        # iteration (numerically a no-op, since the feedback vars are already
        # settled) so side-effecting calls in the body see the real flag.
        loop_body.append(_ast.parse("if __fb_final_pass: break").body[0])
        conditions = " and ".join(
            f"{name} == __fb_snap_{name}" for name in feedback_names
        )
        loop_body.append(_ast.parse(f"if {conditions}: __fb_final_pass = True").body[0])
    else:
        loop_body.append(_ast.parse("break").body[0])

    while_loop = _ast.While(
        test=_ast.Constant(value=True),
        body=loop_body,
        orelse=[],
    )

    # Wrap in try/finally for register commits (reg_names non-empty) and/or to
    # unconditionally restore _sim_converging (feedback_names non-empty) --
    # e.g. on the _SIM_FEEDBACK_MAX_ITER RuntimeError path, which must not
    # leave the flag stuck suppressed for the rest of the simulation.
    finally_stmts = [
        _ast.parse(f'_sim_reg_write(__ip__, "{name}", {name})').body[0]
        for name in reg_names
    ]
    if feedback_names:
        finally_stmts.append(
            _ast.parse("_sim_set_converging(__fb_entry_converging)").body[0]
        )
    if finally_stmts:
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

    # Annotations are re-evaluated by the exec below, but a name that appears
    # *only* in an annotation is not a free variable, so a factory-local type
    # would not be in scope here (e.g. `x: some_fb_t[n]` -> NameError on some_fb_t).
    # Bind each already-resolved annotation object to a generated name and refer
    # to that, which works for every annotation form, not just bare names.
    _sig_anns = getattr(orig_fn, "__annotations__", {})
    _ann_objs = {}
    for _arg in func_def.args.args:
        if _arg.annotation is not None and _arg.arg in _sig_anns:
            _nm = f"__ann_arg_{_arg.arg}__"
            _ann_objs[_nm] = _sig_anns[_arg.arg]
            _arg.annotation = _ast.Name(id=_nm, ctx=_ast.Load())
    if func_def.returns is not None and "return" in _sig_anns:
        _ann_objs["__ann_return__"] = _sig_anns["return"]
        func_def.returns = _ast.Name(id="__ann_return__", ctx=_ast.Load())

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
        _sim_wire_lens_read=_sim_wire_lens_read,
        _sim_wire_lens_write=_sim_wire_lens_write,
        _sim_wire_reset_claims=_sim_wire_reset_claims,
        _sim_set_converging=_sim_set_converging,
    )
    for _name, _zero in reg_zeros.items():
        new_globals[f"__reg_zero_{_name}__"] = _zero
    for _name, _zero in feedback_zeros.items():
        new_globals[f"__fb_zero_{_name}__"] = _zero
    for _key, _ctype_obj in ann_ctypes_out.items():
        new_globals[_key] = _ctype_obj
    for _key, _ctype_obj in wire_leaf_ctypes_out.items():
        new_globals[_key] = _ctype_obj
    new_globals.update(_ann_objs)  # the pre-resolved signature annotations
    exec(code, new_globals)  # noqa: S102
    return new_globals.get(orig_fn.__name__), bool(reg_names or feedback_names)


@_functools.lru_cache(maxsize=None)
def _sim_cast_params(ctype):
    """Pre-compute mask, sign_bit, and is_signed for a ctype (cached per unique type object)."""
    if getattr(ctype, "_pypeline_is_enum", False):
        n = _enum_bit_width(ctype)
        return (1 << n) - 1, 1 << (n - 1), False  # enums are unsigned
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


def _sim_cast_call_arg(pt, v):
    """Cast a hw_func call argument to its declared parameter ctype pt, for
    simulation. Scalar int/SimVal args get bit-accurate truncation (existing
    behavior); a char/uint8_t-array-shaped param (at any nesting depth) is routed
    through _sim_cast_deep, which accepts either a bare Python str or a (possibly
    nested) list, mirroring the elaboration-side string-literal-argument handling
    in PY_TO_LOGIC._elab_call."""
    if pt is None:
        return v
    if (type(v) is int or type(v) is SimVal) and _is_scalar_pypeline_int(pt):
        return _sim_cast(v, pt)
    if _is_char_like_array(pt):
        return _sim_cast_deep(v, pt)
    return v


# ─────────────────────────────────────────────
# Simulation models (sim_model): per-instance storage and evaluation
# ─────────────────────────────────────────────

# Reserved _sim_reg_state key holding a hardware instance's committed
# class/callable model instance (a name no real register can have).
_SIM_MODEL_REG_KEY = "__sim_model__"

# Reserved _sim_reg_state key holding an AUTOPIPELINE call site's committed
# output delay line: a list of the last N results, oldest first (see
# AUTOPIPELINE._sim_delay_line).
_SIM_AP_DELAY_KEY = "__sim_autopipeline_delay__"


def _sim_capture_call_loc(caller_f):
    """Capture a call-site location tuple from a caller frame, honoring
    SIM_TRACE_LOCATIONS (same convention as the register-aware wrapper).
    Only used on model-attached paths, never the no-model hot path."""
    if SIM_TRACE_LOCATIONS and hasattr(caller_f.f_code, "co_positions"):
        instr_idx = caller_f.f_lasti // 2
        positions = list(caller_f.f_code.co_positions())
        if 0 <= instr_idx < len(positions):
            pos = positions[instr_idx]
            if pos[2] is not None:
                return (caller_f.f_code.co_filename, caller_f.f_lineno, pos[2], pos[3])
    return (caller_f.f_code.co_filename, caller_f.f_lineno, None, None)


def _call_sim_model(model_entry, args, kwargs):
    """Evaluate an attached simulation model for the current hardware instance.

    hw_func delegates are simply called: the delegate's own wrapper manages its
    Reg[T]/Feedback[T] state, pushing its own entry on top of the target's
    already-pushed instance-stack entry, so delegate state stays per-instance
    of the *target*.

    Class/callable models get Reg-like commit timing: every evaluation computes
    outputs from a deepcopy of the instance committed at the last clock edge,
    then commits the mutated copy through the buffered register-write path.
    Under pypeline_sim.py wire convergence the committed instance never moves
    mid-cycle, so re-evaluations with changing inputs are idempotent — a
    combinational input→output path through the model converges exactly like
    ordinary comb logic, and state advances exactly once per cycle (the final
    converged pass's buffered copy is what _sim_reg_flush_buffer commits).
    Under plain sim_call, the outermost call now also opens a register-write
    buffer for its whole duration (see sim_call's docstring), so a Feedback[T]
    convergence loop's re-invocations of a model (or a nested Reg[T] hw_func)
    are convergence-safe there too: every pass reads the state committed at
    the last real clock edge, and only the final pass's buffered write lands
    in _sim_reg_state once the outermost sim_call returns.
    """
    model, kind, copy_state = model_entry
    if kind == "hw_func":
        return model(*args, **kwargs)
    inst_path = _sim_current_inst_path()
    committed = _sim_reg_read(inst_path, _SIM_MODEL_REG_KEY, None)
    if committed is None:
        # First evaluation for this hardware instance: fresh power-on state
        # (sim_reset() clears _sim_reg_state, re-triggering this).
        committed = model() if kind == "class" else model
        if not copy_state:
            # In-place mode commits the instance itself directly, bypassing any
            # write buffer — otherwise re-evaluations within the creation cycle
            # would re-instantiate (and in-place mutation is not
            # convergence-safe regardless).
            _sim_reg_state.setdefault(inst_path, {})[_SIM_MODEL_REG_KEY] = committed
    if not copy_state:
        return committed(*args, **kwargs)
    working = _copy.deepcopy(committed)
    result = working(*args, **kwargs)
    _sim_reg_write(inst_path, _SIM_MODEL_REG_KEY, working)
    return result


class InterfacePortError(Exception):
    """A hw_func declares one half of an interface port but not its matching
    other half. The two halves of a port share the port's name -- the
    feedforward half on one side of the signature (an argument or a return
    field) and the reverse half on the other -- so a lone half is (almost)
    always an unfinished port, and this is a hard error.

    The one legitimate lone-half shape is an intentional valid-only /
    data-only signal (a stream with no backpressure). Build that with a
    genuinely one-directional type instead of a lone half of a with-ready
    interface -- e.g. `stream.make_stream_t(data_t)` / `axi.make_axis_t(n)`,
    which have no reverse half at all and so are exempt by construction.
    """


def _interface_half_of(t):
    """`(interface, role, is_array)` if `t` is a derived interface half (or an
    array of one), else `(None, None, False)`.

    getattr-only on the tags the interface library stamps on its derived structs
    (`_pypeline_interface_role` = "fwd"/"fb", `_pypeline_interface` = the source
    interface), so pypeline.py keeps its zero dependency on that library."""
    if t is None:
        return None, None, False
    role = getattr(t, "_pypeline_interface_role", None)
    if role is not None:
        return getattr(t, "_pypeline_interface", None), role, False
    elem = _array_elem_ctype(t)
    if elem is not None:
        role = getattr(elem, "_pypeline_interface_role", None)
        if role is not None:
            return getattr(elem, "_pypeline_interface", None), role, True
    return None, None, False


def _check_partial_interface_ports(fn, ann, params, ret_t):
    """Raise `InterfacePortError` for the first interface port that declares
    only one of its two halves.

    Presence-based and side-aware: an input port's feedforward half is an
    argument and its reverse half a return field (an output port is the
    reverse), so the missing half's side follows from where the present half
    sits. One-directional interfaces (no reverse fields at all, or no forward
    fields) are complete with a single half and never error -- checked via the
    interface's own `_pypeline_iface_derived` memo. A genuinely valid-only
    stream (e.g. `stream.make_stream_t(...)`) has no reverse half to pair, so
    it falls into that exemption."""
    ports = {}  # name -> {"fwd": side|None, "fb": side|None, "iface": iface}

    def note(name, t, side):
        iface, role, _ = _interface_half_of(t)
        if iface is not None:
            ports.setdefault(name, {"fwd": None, "fb": None, "iface": iface})[role] = side

    for p in params:
        note(p, ann.get(p), "arg")
    ret_fields = getattr(ret_t, "_fields", ()) if ret_t is not None else ()
    ret_anns = getattr(ret_t, "__annotations__", {}) if ret_fields else {}
    for f in ret_fields:
        note(f, ret_anns.get(f), "ret")

    for name, e in ports.items():
        if not name.endswith("_if"):
            _warnings.warn(
                f"hw_func {getattr(fn, '__qualname__', fn)!r}: interface port "
                f"{name!r} does not end in '_if' -- by convention, an "
                "arg/return-field name that pairs a port's two halves should "
                "(e.g. 'stream_in_if')",
                stacklevel=3,
            )
        derived = getattr(e["iface"], "_pypeline_iface_derived", {})
        if derived.get("fwd") is None or derived.get("fb") is None:
            continue  # one-directional interface: a single half is complete
        if (e["fwd"] is None) == (e["fb"] is None):
            continue  # both halves present (or, wrongly, both on one side)
        present_role = "fwd" if e["fwd"] is not None else "fb"
        present_side = e[present_role]
        # the missing half travels the opposite way, so it sits on the other side
        where = "return field" if present_side == "arg" else "argument"
        present_word = "feedforward" if present_role == "fwd" else "reverse"
        missing_word = "reverse" if present_role == "fwd" else "feedforward"
        iname = getattr(e["iface"], "__name__", repr(e["iface"]))
        raise InterfacePortError(
            f"hw_func {getattr(fn, '__qualname__', fn)!r}: interface port {name!r} "
            f"(interface {iname}) declares only its {present_word} half; add its "
            f"{missing_word} half as a {where} named {name!r}. If {name!r} is "
            "meant to be an intentional valid-only / data-only signal, build it "
            "as a genuinely one-directional type instead (e.g. "
            "stream.make_stream_t(...) / axi.make_axis_t(...))."
        )


def _sim_type_wrap(fn):
    """Wrap a pypeline hardware function for bit-accurate simulation.

    On each call: records the call-site location for register instance identity,
    casts positional arguments to their annotated input types, pushes any scoped
    operator registrations, calls the original function (or a register-aware
    simulation body for Reg[T] functions), pops registrations, then casts the
    return value to the annotated return type.

    Transparent to the hardware elaborator: _elaborate_live_func uses
    inspect.unwrap() to recover the original function for source analysis.
    functools.wraps copies __annotations__, so hw_arg_types()/hw_return_type()
    (see below) work the same whether called on the wrapped or original function.

    Idempotent: if `fn` is already hw_func-wrapped (e.g. `@MAIN`/`@wires`/`@hw_func`
    stacked on the same function in either order -- `wires`'s docstring promises
    "stacks with @MAIN in either order"), returns it unchanged instead of wrapping
    again. Re-wrapping an already-wrapped function is never correct: the outer call
    would rebuild the simulation body from `fn.__globals__`/`fn.__closure__`, but for
    an already-wrapped `fn` those reflect wherever *this* wrapper function is defined
    (pypeline.py itself), not the original function's module -- silently dropping
    every module-level name (e.g. a testbench's own imported constants) the original
    body actually needs, raising NameError deep inside the rewritten sim body.
    """
    if is_hw_func(fn):
        return fn
    ann = fn.__annotations__
    try:
        params = list(_inspect.signature(fn).parameters.keys())
    except (ValueError, TypeError):
        params = []
    ret_t = ann.get("return")

    # Hard error if a port declares only one of its two interface halves.
    _check_partial_interface_ports(fn, ann, params, ret_t)

    # Scan source for Reg[T]/Feedback[T] annotations and build register-aware sim body.
    # Returns (fn_or_None, has_state) where has_state=True means the body calls
    # _sim_current_inst_path() so the instance stack must be maintained.
    sim_body_fn, has_state = _build_reg_sim_func(fn)

    # sim_model routing cell: sim_model(target) fills this one-element list
    # with (model, kind, copy_state); every wrapper variant checks it per call
    # (one is-None test on the no-model hot path).
    _model_cell = [None]

    # Helper: cast args and kwargs to their annotated types, run the body, cast result.
    # Extracted so both wrapper variants share the same arg-casting logic.
    def _run_body(new_args, kwargs):
        new_kwargs = dict(kwargs)
        for k, v in kwargs.items():
            pt = ann.get(k)
            if (
                pt is not None
                and isinstance(v, int)  # covers int, SimVal, IntEnum members
                and _is_scalar_pypeline_int(pt)
            ):
                new_kwargs[k] = _sim_cast(v, pt)
            elif pt is not None and _is_char_like_array(pt):
                new_kwargs[k] = _sim_cast_deep(v, pt)
        # Scope key must be `wrapper` (the object register_operator(...,
        # scope=...) was actually called with -- registration happens after
        # `@hw_func` has already wrapped the function, so the name in the
        # defining scope refers to the wrapper, not `fn`), not the pre-wrap
        # `fn` this closure captured. Using `fn` here would never match any
        # scope key, silently disabling this function's own scoped
        # NEGATE/SR/SL registrations for every nested (non-sim_call) call --
        # only working by accident when an *outer* sim_call(wrapper, ...)
        # happened to push the same entries first.
        saved = _push_scoped_registrations(wrapper)
        try:
            if _model_cell[0] is not None:
                result = _call_sim_model(_model_cell[0], new_args, new_kwargs)
            elif sim_body_fn is not None:
                result = sim_body_fn(*new_args, **new_kwargs)
            else:
                result = fn(*new_args, **new_kwargs)
        finally:
            _pop_scoped_registrations(saved)
        if (
            ret_t is not None
            and isinstance(result, int)  # covers int, SimVal, IntEnum members
            and _is_scalar_pypeline_int(ret_t)
        ):
            result = _sim_cast(result, ret_t)
        elif ret_t is not None and _is_char_like_array(ret_t):
            result = _sim_cast_deep(result, ret_t)
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
                if _model_cell[0] is not None:
                    # Class models key their state by instance path, so this
                    # otherwise stateless path must maintain the stack. Raw
                    # mode: model args/results are not cast.
                    _sim_inst_stack.append(
                        (fn.__qualname__, _sim_capture_call_loc(_sys._getframe(1)))
                    )
                    try:
                        return _call_sim_model(_model_cell[0], args, kwargs)
                    finally:
                        _sim_inst_stack.pop()
                # See the matching comment in _run_body: scope key must be
                # `wrapper`, not the pre-wrap `fn` this closure captured.
                saved = _push_scoped_registrations(wrapper)
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
                # See the matching comment in _run_body: scope key must be
                # `wrapper`, not the pre-wrap `fn` this closure captured.
                saved = _push_scoped_registrations(wrapper)
                try:
                    if _model_cell[0] is not None:
                        return _call_sim_model(_model_cell[0], args, kwargs)
                    return (
                        sim_body_fn(*args, **kwargs)
                        if sim_body_fn is not None
                        else fn(*args, **kwargs)
                    )
                finally:
                    _pop_scoped_registrations(saved)
                    _sim_inst_stack.pop()

        wrapper._is_hw_func = True
        wrapper._sim_model_cell = _model_cell
        wrapper._pypeline_has_state = has_state
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
                    new_args[i] = _sim_cast_call_arg(ann.get(params[i]), a)
            if _model_cell[0] is None:
                return _run_body(new_args, kwargs)
            # A model is attached: class models key their state by instance
            # path, so this otherwise stateless fast path must maintain the
            # stack (the no-model hot path pays only the is-None check above).
            _sim_inst_stack.append(
                (fn.__qualname__, _sim_capture_call_loc(_sys._getframe(1)))
            )
            try:
                return _run_body(new_args, kwargs)
            finally:
                _sim_inst_stack.pop()
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
                        new_args[i] = _sim_cast_call_arg(ann.get(params[i]), a)
                return _run_body(new_args, kwargs)
            finally:
                _sim_inst_stack.pop()

    wrapper._is_hw_func = True
    wrapper._sim_model_cell = _model_cell
    wrapper._pypeline_has_state = has_state
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


def hw_arg_types(func):
    """Returns a hardware function's parameter types, in declaration order, as a tuple.

    For user-facing code that needs to introspect an already-annotated hardware
    function (e.g. a factory wrapping a caller-supplied function), instead of reaching
    into func.__annotations__ directly.
    """
    fn = _inspect.unwrap(func)
    return tuple(v for k, v in fn.__annotations__.items() if k != "return")


def hw_return_type(func):
    """Returns a hardware function's declared return type.

    See hw_arg_types — the return-type counterpart for the same introspection use case.
    """
    fn = _inspect.unwrap(func)
    return fn.__annotations__["return"]


def is_hw_func(func):
    """Returns True if func is already @hw_func-decorated (or @MAIN, which implies
    @hw_func).

    For factories that accept a caller-supplied function (see hw_arg_types/
    hw_return_type) and need to validate it's been decorated before using it inside
    their own hardware function body — an undecorated func's own Reg[T]/Feedback[T]
    and bare struct/array locals won't be simulated correctly otherwise.
    """
    return getattr(func, "_is_hw_func", False)


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

    Each top-level (non-reentrant) sim_call() represents one clock cycle for
    Layer-1 simulation, so @sim_input's once-per-cycle result cache is cleared
    here on the outermost call only (prev_active is already True on a nested/
    reentrant sim_call(), so mid-cycle helper calls don't spuriously reset it).

    The outermost call also opens a register-write buffer (the same
    _sim_reg_begin_buffer/_sim_reg_flush_buffer machinery pypeline_sim.py uses
    per clock cycle) so the whole call tree commits Reg[T]/@sim_model writes
    atomically, once, after the call returns -- matching one hardware clock
    edge. This is what makes a Feedback[T] convergence loop's re-invocations
    of a stateful child safe: _sim_reg_read always reads the last *committed*
    value regardless of how many buffered writes have piled up this call, so
    every convergence pass (including the first) sees the true cycle-start
    state for every descendant register, not a mix of this-call passes.
    pypeline_sim.py is unaffected: it sets _sim_active once before its cycle
    loop and never resets it per-MAIN-call, so prev_active is already True by
    the time it calls sim_call(main_fn), and this branch is skipped there --
    pypeline_sim.py's own per-cycle begin/flush bracket already covers it.
    """
    global _sim_active
    prev_active = _sim_active
    if not prev_active:
        _sim_input_cache.clear()
        _sim_reg_begin_buffer()
    _sim_active = True
    saved = _push_scoped_registrations(func)
    try:
        return func(*args, **kwargs)
    finally:
        _pop_scoped_registrations(saved)
        _sim_active = prev_active
        if not prev_active:
            _sim_reg_flush_buffer()
