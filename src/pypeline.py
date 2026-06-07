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
        lambda value: float_t(**_float_to_fields(value, exponent_width, mantissa_width))
    )
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
    """

    def __new__(cls, value, ctype=None):
        obj = int.__new__(cls, int(value))
        object.__setattr__(obj, "_ctype", ctype)
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
                if not isinstance(result, SimVal) or result._ctype is None:
                    ret_t = getattr(
                        getattr(fn, "__wrapped__", fn), "__annotations__", {}
                    ).get("return")
                    if ret_t is not None:
                        return _sim_cast(result, ret_t)
                return result
        return SimVal(fallback)

    def __neg__(self):
        return self._dispatch_unary("NEGATE", -int(self))

    def __invert__(self):
        return self._dispatch_unary("NOT", ~int(self))

    def _dispatch_binary(self, op_name, other, fallback_int):
        if self._ctype is not None:
            rc = getattr(other, "_ctype", None)
            fn = rc and _operator_registry.get(
                (op_name, _ctype_str(self._ctype), _ctype_str(rc))
            )
            fn = fn or _left_operator_registry.get((op_name, _ctype_str(self._ctype)))
            if callable(fn):
                result = fn(self, other)
                if not isinstance(result, SimVal) or result._ctype is None:
                    ret_t = getattr(
                        getattr(fn, "__wrapped__", fn), "__annotations__", {}
                    ).get("return")
                    if ret_t is not None:
                        return _sim_cast(result, ret_t)
                return result
        return SimVal(fallback_int)

    def __rshift__(self, o):
        return self._dispatch_binary("SR", o, int(self) >> int(o))

    def __lshift__(self, o):
        return self._dispatch_binary("SL", o, int(self) << int(o))

    # Arithmetic preserves SimVal type; ctype is intentionally not propagated
    # (use _sim_cast or @hw_func return-type casting to restore type info).
    def __add__(self, o):
        return SimVal(int(self) + int(o))

    def __sub__(self, o):
        return SimVal(int(self) - int(o))

    def __mul__(self, o):
        return SimVal(int(self) * int(o))

    def __and__(self, o):
        return SimVal(int(self) & int(o))

    def __or__(self, o):
        return SimVal(int(self) | int(o))

    def __xor__(self, o):
        return SimVal(int(self) ^ int(o))

    def __radd__(self, o):
        return SimVal(int(o) + int(self))

    def __rsub__(self, o):
        return SimVal(int(o) - int(self))

    def __rlshift__(self, o):
        return SimVal(int(o) << int(self))

    def __rrshift__(self, o):
        return SimVal(int(o) >> int(self))


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
        for fname, v in kwargs.items():
            ftype = klass.__annotations__.get(fname)
            if (
                ftype is not None
                and isinstance(v, (int, SimVal))
                and _is_scalar_pypeline_int(ftype)
            ):
                if not isinstance(v, SimVal) or v._ctype is None:
                    v = SimVal(int(v), ctype=ftype)
            typed[fname] = v
        return _orig_new(klass, **typed)

    cls.__new__ = staticmethod(_typed_new)
    return cls


# ─────────────────────────────────────────────
# MAIN decorator
# ─────────────────────────────────────────────

_main_registry: list = []


def MAIN(func):
    """Marks a function as a top-level hardware process.
    Implies @hw_func: inputs/outputs are type-cast for simulation and
    the function can be passed to sim_call().
    """
    wrapped = _sim_type_wrap(func)
    _main_registry.append(wrapped)
    return wrapped


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
    else:
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
    else:
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
    else:
        _scoped_unary_operator_registry.setdefault(id(scope), {})[key] = func


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
    with ctype = make_uint(total_bits).

    In hardware (PY_TO_LOGIC elaboration) this function is intercepted and treated
    as variadic tuple concat — see the 'concat' branch in _elab_bit_manip_call.
    """
    widths = []
    for a in args:
        if isinstance(a, SimVal) and a._ctype is not None:
            widths.append(len(a._ctype))
        elif isinstance(a, int):
            widths.append(max(1, int(a).bit_length()))
        else:
            raise TypeError(f"concat: cannot infer bit width for {a!r}")
    total = sum(widths)
    result = 0
    for a, w in zip(args, widths):
        result = (result << w) | (int(a) & ((1 << w) - 1))
    return SimVal(result, ctype=make_uint(total))


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
# Sim infrastructure: _sim_cast, _sim_type_wrap / hw_func, sim_call
# ─────────────────────────────────────────────

import functools as _functools
import inspect as _inspect
import sys as _sys
import dis as _dis
import ast as _ast
import textwrap as _textwrap


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

# Global wire simulation state.
_sim_wire_state: dict = {}  # wire name → current int value
_sim_converging: bool = False  # True during delta-cycle convergence passes
_sim_reg_write_buffer = None  # None = direct commit; dict = buffered mode
_sim_current_main = None  # MAIN fn currently executing (for reader tracking)
_sim_wire_readers: dict = {}  # wire name → set of MAINs that have read it


def _sim_current_inst_path():
    """Return the current simulation instance path as an immutable tuple."""
    return tuple(_sim_inst_stack)


def _sim_reg_read(inst_path, reg_name):
    """Return the current register value for this instance (0 if never written)."""
    return _sim_reg_state.get(inst_path, {}).get(reg_name, 0)


def _sim_reg_write(inst_path, reg_name, value):
    """Update the register value, routing to buffer if buffering is active."""
    if _sim_reg_write_buffer is not None:
        _sim_reg_write_buffer.setdefault(inst_path, {})[reg_name] = int(value)
    else:
        _sim_reg_state.setdefault(inst_path, {})[reg_name] = int(value)


def _sim_wire_read(name: str):
    """Return the current global wire value (0 if not yet driven).
    Records the calling MAIN as a reader of this wire for dependency tracking.
    """
    if _sim_current_main is not None:
        _sim_wire_readers.setdefault(name, set()).add(_sim_current_main)
    return _sim_wire_state.get(name, 0)


def _sim_wire_write(name: str, value) -> None:
    """Set the current global wire value."""
    _sim_wire_state[name] = int(value)


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
      - Name(id='wire', ctx=Load)  →  _sim_wire_read('wire')
      - wire = expr                →  _sim_wire_write('wire', expr)   (Expr stmt)
      - wire: T = expr             →  _sim_wire_write('wire', expr)   (AnnAssign with value)
    """

    def __init__(self, wire_names):
        self._wire_names = frozenset(wire_names)

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
        src = _textwrap.dedent(_inspect.getsource(orig_fn))
    except (OSError, TypeError):
        return None
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return None

    func_def = next((n for n in tree.body if isinstance(n, _ast.FunctionDef)), None)
    if func_def is None:
        return None

    # Discover global wire names from the function's defining module and rewrite
    # all reads/writes in the function body to go through _sim_wire_read/write.
    global_wire_names = {
        name
        for name, ann in fn.__globals__.get("__annotations__", {}).items()
        if isinstance(ann, (_WireType, _InputType, _OutputType))
    }
    if global_wire_names:
        _GlobalWireRewriter(global_wire_names).visit(func_def)
        _ast.fix_missing_locations(func_def)

    # Discover register and feedback variable names by evaluating each
    # annotation-only AnnAssign against the function's globals.
    reg_names = []
    feedback_names = []
    for stmt in func_def.body:
        if not (
            isinstance(stmt, _ast.AnnAssign)
            and isinstance(stmt.target, _ast.Name)
            and stmt.value is None
        ):
            continue
        try:
            ann_val = eval(
                compile(_ast.Expression(body=stmt.annotation), "<ann>", "eval"),
                fn.__globals__,
            )
        except Exception:
            continue
        if isinstance(ann_val, _RegType):
            reg_names.append(stmt.target.id)
        elif isinstance(ann_val, _FeedbackType):
            feedback_names.append(stmt.target.id)

    if not reg_names and not feedback_names and not global_wire_names:
        return None

    # Strip both Reg[T] and Feedback[T] annotation-only statements from the body.
    stripped = set(reg_names) | set(feedback_names)
    orig_body = [
        stmt
        for stmt in func_def.body
        if not (
            isinstance(stmt, _ast.AnnAssign)
            and isinstance(stmt.target, _ast.Name)
            and stmt.target.id in stripped
            and stmt.value is None
        )
    ]

    # --- Build transformed function body ---

    new_stmts = []

    # Register reads and initial-value snapshots (only when reg_names non-empty).
    if reg_names:
        new_stmts.append(_ast.parse("__ip__ = _sim_current_inst_path()").body[0])
        for name in reg_names:
            new_stmts.append(
                _ast.parse(f'{name} = _sim_reg_read(__ip__, "{name}")').body[0]
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
        return None

    new_globals = dict(fn.__globals__)
    new_globals.update(
        _sim_current_inst_path=_sim_current_inst_path,
        _sim_reg_read=_sim_reg_read,
        _sim_reg_write=_sim_reg_write,
        _SIM_FEEDBACK_MAX_ITER=_SIM_FEEDBACK_MAX_ITER,
        _sim_wire_read=_sim_wire_read,
        _sim_wire_write=_sim_wire_write,
    )
    exec(code, new_globals)  # noqa: S102
    return new_globals.get(orig_fn.__name__)


def _sim_cast(val, ctype):
    """Cast a Python int/SimVal to a pypeline ctype: mask to n bits, handle signedness.

    This is the sim equivalent of a hardware type assignment. It implements unsigned
    wrap-on-overflow and signed two's complement masking.
    """
    n = len(ctype)  # uses _CTypeMeta.__len__ for bit width
    mask = (1 << n) - 1
    v = int(val) & mask
    if str(ctype).startswith("int") and v >= (1 << (n - 1)):
        v -= 1 << n  # sign-extend to Python negative
    return SimVal(v, ctype=ctype)


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

    # Scan source for Reg[T] local annotations and build register-aware sim body.
    # Done once at decoration time; returns None when no registers are present.
    sim_body_fn = _build_reg_sim_func(fn)

    @_functools.wraps(fn)
    def wrapper(*args, **kwargs):
        # Capture call-site (filename, lineno, col, end_col) from caller's frame.
        # This mirrors the hardware elaborator's _loc_str instance-naming convention
        # and uniquely identifies which hardware instance is being simulated.
        caller_f = _sys._getframe(1)
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
        _sim_inst_stack.append((fn.__qualname__, (filename, lineno, col, end_col)))
        try:
            new_args = list(args)
            for i, a in enumerate(args):
                if i < len(params):
                    pt = ann.get(params[i])
                    if (
                        pt is not None
                        and isinstance(a, (int, SimVal))
                        and _is_scalar_pypeline_int(pt)
                    ):
                        new_args[i] = _sim_cast(a, pt)
            saved = _push_scoped_registrations(fn)
            try:
                if sim_body_fn is not None:
                    result = sim_body_fn(*new_args, **kwargs)
                else:
                    result = fn(*new_args, **kwargs)
            finally:
                _pop_scoped_registrations(saved)
            if (
                ret_t is not None
                and isinstance(result, (int, SimVal))
                and _is_scalar_pypeline_int(ret_t)
            ):
                result = _sim_cast(result, ret_t)
            return result
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


def sim_call(func, *args, **kwargs):
    """Call a pypeline function in simulation mode with scoped operators active.

    Pushes scoped operator registrations keyed on func's id before calling.
    When @hw_func is applied to the function, scoped ops are registered under
    id(wrapped_func), so func must be passed as-is (not unwrapped).
    The @hw_func wrapper itself calls _push_scoped_registrations(original),
    which is a no-op for the original, so there is no double-push conflict.
    """
    saved = _push_scoped_registrations(func)
    try:
        return func(*args, **kwargs)
    finally:
        _pop_scoped_registrations(saved)
