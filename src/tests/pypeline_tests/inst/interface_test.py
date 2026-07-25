# pyright: reportInvalidTypeForm=none
"""Phase 1: the `@interface` primitive.

Deliberately uses a NON-stream interface (multi-bit credit + a second reverse
field) so the primitive cannot quietly grow valid/ready assumptions. Covers the
derived feedforward/feedback structs, nesting/arrays, mixed plain+interface
bundles, memoized determinism, the explicit hand-written hw_func split-struct
form (elaborated + native-simulated), and every declaration error.
"""
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)
from pypeline import (
    MAIN,
    hw_func,
    struct,
    NamedTuple,
    Feedback,
    uint1_t,
    uint4_t,
    uint8_t,
    uint16_t,
    uint32_t,
    sim_call,
    sim_reset,
)

from interface.interface import (
    interface,
    interface_of,
    interface_role,
    is_interface,
    InterfaceError,
    FWD,
    FB,
)


# ── a neutral bus: two feedforward fields, a multi-bit + a 1-bit reverse field ──
@interface
class bus_intrf(NamedTuple):
    payload: uint32_t
    go: uint1_t
    credit: Feedback[uint4_t]
    nack: Feedback[uint1_t]


def test_derived_types_split_by_direction():
    assert bus_intrf.fwd_t._fields == ("payload", "go")
    assert bus_intrf.fb_t._fields == ("credit", "nack")
    # Feedback[T] fields are unwrapped to their inner type
    assert bus_intrf.fb_t.__annotations__["credit"] is uint4_t
    assert bus_intrf.fb_t.__annotations__["nack"] is uint1_t
    assert bus_intrf.fwd_t.__annotations__["payload"] is uint32_t
    # back-tags let introspection recover the interface + direction
    assert interface_of(bus_intrf.fwd_t) is bus_intrf
    assert interface_of(bus_intrf.fb_t) is bus_intrf
    assert interface_role(bus_intrf.fwd_t) == FWD
    assert interface_role(bus_intrf.fb_t) == FB
    assert is_interface(bus_intrf) and not is_interface(bus_intrf.fwd_t)


def test_derivation_is_memoized_and_deterministic():
    assert bus_intrf.fwd_t is bus_intrf.fwd_t
    assert bus_intrf.fb_t is bus_intrf.fb_t
    # canonical names are pure functions of the declaration
    assert bus_intrf.fwd_t._pypeline_ctype_name == "bus_intrf_t_payload_uint32_t_go_uint1_t"
    assert (
        bus_intrf.fb_t._pypeline_ctype_name
        == "bus_intrf_feedback_t_credit_uint4_t_nack_uint1_t"
    )


# ── nesting: interfaces inside interfaces, arrays of interfaces, plain mixed in ──
@interface
class outer_intrf(NamedTuple):
    lanes: bus_intrf[2]
    side: bus_intrf
    tag: uint8_t  # plain -> feedforward only, pruned from the feedback half


def test_nested_and_mixed_bundle():
    # plain field rides along feedforward and contributes nothing reverse
    assert outer_intrf.fwd_t._fields == ("lanes", "side", "tag")
    assert outer_intrf.fb_t._fields == ("lanes", "side")
    assert outer_intrf.fwd_t.__annotations__["side"] is bus_intrf.fwd_t
    assert outer_intrf.fb_t.__annotations__["side"] is bus_intrf.fb_t
    assert outer_intrf.fwd_t.__annotations__["tag"] is uint8_t


# ── one-directional interfaces ──
@interface
class oneway_intrf(NamedTuple):
    d: uint16_t


@interface
class rev_only_intrf(NamedTuple):
    r: Feedback[uint1_t]


def test_one_directional_interfaces():
    assert oneway_intrf.fb_t is None
    assert oneway_intrf.fwd_t is not None
    assert rev_only_intrf.fwd_t is None
    assert rev_only_intrf.fb_t is not None


# ── the explicit hw_func form: y <- x, both directions wired by hand ──
@struct
class x_to_y_t(NamedTuple):
    x_if: bus_intrf.fb_t  # input x_if's reverse travels out
    y_if: bus_intrf.fwd_t  # output y_if's feedforward travels out


@hw_func
def x_to_y_hw_func(x_if: bus_intrf.fwd_t, y_if: bus_intrf.fb_t) -> x_to_y_t:
    o: x_to_y_t
    # Each direction carries a little real logic (rather than being a pure wire
    # rename) so synthesis sees a non-zero critical path on both paths.
    o.y_if.payload = x_if.payload + 1  # feedforward
    o.y_if.go = x_if.go
    o.x_if.credit = y_if.credit + 1  # feedback (narrows back into uint4_t)
    o.x_if.nack = y_if.nack
    return o


@MAIN
def top_x_to_y(x_if: bus_intrf.fwd_t, y_if: bus_intrf.fb_t) -> x_to_y_t:
    return x_to_y_hw_func(x_if, y_if)


def test_explicit_split_struct_hw_func_simulates():
    sim_reset()
    for payload, go, credit, nack in [(7, 1, 3, 0), (0, 0, 0, 1), (0xDEAD, 1, 15, 1)]:
        r = sim_call(
            top_x_to_y,
            bus_intrf.fwd_t(payload=payload, go=go),
            bus_intrf.fb_t(credit=credit, nack=nack),
        )
        # feedforward flows x -> y, feedback flows y -> x, independently
        assert int(r.y_if.payload) == (payload + 1) & 0xFFFFFFFF
        assert int(r.y_if.go) == go
        assert int(r.x_if.credit) == (credit + 1) & 0xF
        assert int(r.x_if.nack) == nack


# ── declaration errors ──
def _iface_from(name, anns):
    return lambda: interface(type(name, (NamedTuple,), {"__annotations__": anns}))


def _expect(fn, exc, needle):
    try:
        fn()
    except exc as e:
        assert needle in str(e), f"wrong message: {e}"
        return
    raise AssertionError(f"expected {exc.__name__} containing {needle!r}")


def test_plain_struct_rejects_directional_fields():
    """A plain @struct has one direction, so a reverse field or a whole
    interface inside it is meaningless -- caught at declaration, not later."""
    _expect(
        lambda: struct(
            type("bad_fb_t", (NamedTuple,), {"__annotations__": {"x": Feedback[uint1_t]}})
        ),
        TypeError,
        "only meaningful in an @interface",
    )
    _expect(
        lambda: struct(
            type("bad_if_t", (NamedTuple,), {"__annotations__": {"x": bus_intrf}})
        ),
        TypeError,
        "use @interface for bundles",
    )


def test_interface_declaration_errors():
    # A raw (undecorated) NamedTuple sidesteps @struct's check, so @interface
    # still validates nested plain types itself -- including several levels down.
    raw_fb = type("raw_fb", (NamedTuple,), {"__annotations__": {"x": Feedback[uint1_t]}})
    raw_intrf = type("raw_intrf", (NamedTuple,), {"__annotations__": {"x": bus_intrf}})
    raw_deep = type("raw_deep", (NamedTuple,), {"__annotations__": {"inner": raw_intrf}})

    _expect(_iface_from("a_intrf", {"f": raw_intrf}), InterfaceError, "use @interface")
    _expect(_iface_from("e_intrf", {"f": raw_deep}), InterfaceError, "use @interface")
    _expect(
        _iface_from("b_intrf", {"f": raw_fb}),
        InterfaceError,
        "only allowed in an @interface",
    )
    _expect(_iface_from("c_intrf", {}), InterfaceError, "has no fields")
    _expect(
        lambda: interface(type("d_intrf", (object,), {})),
        InterfaceError,
        "must be applied to a NamedTuple",
    )
    # A plain @struct is not an @interface, so it never gets .fwd_t/.fb_t --
    # there is no public derivation function left to call directly on it.
    try:
        x_to_y_t.fwd_t
        raise AssertionError("expected AttributeError")
    except AttributeError:
        pass


if __name__ == "__main__":
    test_derived_types_split_by_direction()
    test_derivation_is_memoized_and_deterministic()
    test_nested_and_mixed_bundle()
    test_one_directional_interfaces()
    test_explicit_split_struct_hw_func_simulates()
    test_plain_struct_rejects_directional_fields()
    test_interface_declaration_errors()
    print("OK: @interface primitive (split, nesting, mixed bundles, errors)")
