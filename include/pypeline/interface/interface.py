# pyright: reportInvalidTypeForm=none
"""`@interface` -- a bundle of signals with per-field direction.

An interface groups signals that travel together but not necessarily in the same
direction. Plain fields are *feedforward*; fields marked `Feedback[T]` are
*reverse*. Nothing here assumes a particular protocol: the reverse channel may be
any number of fields of any type. Valid/ready streaming is one use of this, not
its definition -- a credit counter, a req/ack pair, or a wide multi-signal bus are
all expressed the same way.

    @interface
    class my_intrf(NamedTuple):
        payload: some_data_t         # feedforward
        go:      uint1_t             # feedforward
        credit:  Feedback[uint4_t]   # reverse

Hardware functions never take an interface directly -- they take the two ordinary
`@struct`s it derives, one per direction:

    my_intrf_t          = make_interface_type(my_intrf)           # feedforward fields
    my_intrf_feedback_t = make_interface_feedback_type(my_intrf)  # Feedback fields, unwrapped

Because the halves travel opposite ways, an *input* interface puts its
feedforward half in an arg and its feedback half in a return field, and an
*output* interface does the reverse. Both halves of one port share the same name,
which is how they are paired (see `interface_func`).

Derived types are memoized per interface and named deterministically from the
interface's own canonical name, so repeated derivation yields identical
definitions (canonical-name determinism).
"""

import sys as _sys

from pypeline import (
    NamedTuple,
    struct,
    _FeedbackType,
    _array_elem_ctype,
    _array_len,
    _enclosing_factory_param_suffix,
    _struct_class_getitem,
)

FWD = "fwd"
FB = "fb"


class InterfaceError(Exception):
    """Raised for an invalid `@interface` declaration or use."""


# ─────────────────────────────────────────────────────────────────────────────
# Recognition helpers
# ─────────────────────────────────────────────────────────────────────────────
def is_interface(t):
    """True if `t` is an `@interface` type."""
    return bool(getattr(t, "_pypeline_is_interface", False))


def interface_of(t):
    """The `@interface` a derived (feedforward/feedback) struct came from, else None."""
    return getattr(t, "_pypeline_interface", None)


def interface_role(t):
    """`FWD`/`FB` for a derived struct, else None."""
    return getattr(t, "_pypeline_interface_role", None)


def _tname(t):
    return getattr(t, "__name__", None) or repr(t)


# ─────────────────────────────────────────────────────────────────────────────
# Validation: a plain type may not hide interface/Feedback fields
# ─────────────────────────────────────────────────────────────────────────────
def _reject_nested(t, where, seen=None):
    """A plain (non-interface) type must not contain an interface or a
    `Feedback[...]` field -- those only have meaning inside an `@interface`,
    where a direction can be assigned to them."""
    if seen is None:
        seen = set()
    if id(t) in seen:
        return
    seen.add(id(t))

    elem = _array_elem_ctype(t)
    if elem is not None:
        _reject_nested(elem, where, seen)
        return
    if not hasattr(t, "_fields"):
        return  # scalar
    for fname in t._fields:
        ann = t.__annotations__[fname]
        if is_interface(ann):
            raise InterfaceError(
                f"interface-typed field {fname!r} inside plain @struct "
                f"{_tname(t)!r} ({where}); use @interface for bundles that "
                "contain interfaces"
            )
        if isinstance(ann, _FeedbackType):
            raise InterfaceError(
                f"Feedback[...] field {fname!r} inside plain @struct {_tname(t)!r} "
                f"({where}); reverse fields are only allowed in an @interface"
            )
        _reject_nested(ann, where, seen)


# ─────────────────────────────────────────────────────────────────────────────
# The split
# ─────────────────────────────────────────────────────────────────────────────
def _split_field(ann, where):
    """Return `(feedforward_type, feedback_type)` for one field annotation.
    Either may be None (the field contributes nothing in that direction)."""
    if isinstance(ann, _FeedbackType):
        return (None, ann.inner_ctype)
    if is_interface(ann):
        return (make_interface_type(ann), make_interface_feedback_type(ann))
    elem = _array_elem_ctype(ann)
    if elem is not None:
        f, b = _split_field(elem, where)
        n = _array_len(ann)
        return (None if f is None else f[n], None if b is None else b[n])
    _reject_nested(ann, where)
    return (ann, None)


def _derive(iface, role):
    if not is_interface(iface):
        raise InterfaceError(f"{iface!r} is not an @interface")
    memo = iface._pypeline_iface_derived
    if role in memo:
        return memo[role]
    memo[role] = None  # recursion guard
    where = f"@interface {iface._pypeline_iface_canonical}"
    fields = []
    for fname in iface._fields:
        f, b = _split_field(iface.__annotations__[fname], where)
        chosen = f if role == FWD else b
        if chosen is not None:
            fields.append((fname, chosen))
    if not fields:
        return None
    name = f"{iface._pypeline_iface_canonical}_{'t' if role == FWD else 'feedback_t'}"
    cls = struct(NamedTuple(name, fields))
    cls._pypeline_interface = iface
    cls._pypeline_interface_role = role
    memo[role] = cls
    return cls


def make_interface_type(iface):
    """The `@struct` of `iface`'s feedforward fields (None if it has none)."""
    return _derive(iface, FWD)


def make_interface_feedback_type(iface):
    """The `@struct` of `iface`'s `Feedback` fields, unwrapped to their inner
    types (None if it has none)."""
    return _derive(iface, FB)


# ─────────────────────────────────────────────────────────────────────────────
# The decorator
# ─────────────────────────────────────────────────────────────────────────────
def interface(cls):
    """Mark a NamedTuple as an interface: plain fields feedforward, `Feedback[T]`
    fields reverse. Derives (and validates) both direction structs eagerly, so a
    bad declaration fails where it is written."""
    if not hasattr(cls, "_fields"):
        raise InterfaceError(
            f"@interface must be applied to a NamedTuple class (got {_tname(cls)!r})"
        )
    if not cls._fields:
        raise InterfaceError(f"@interface {_tname(cls)!r} has no fields")

    cls.__class_getitem__ = classmethod(_struct_class_getitem)
    cls._pypeline_is_interface = True
    cls._pypeline_iface_canonical = cls.__name__ + _enclosing_factory_param_suffix(
        cls, _sys._getframe(1)
    )
    cls._pypeline_iface_derived = {}

    fwd = make_interface_type(cls)
    fb = make_interface_feedback_type(cls)
    if fwd is None and fb is None:
        raise InterfaceError(
            f"@interface {_tname(cls)!r} is empty: no feedforward and no Feedback fields"
        )
    return cls
