# pyright: reportInvalidTypeForm=none
"""The rules that keep the two wiring styles honest where they meet.

A hand-written module becomes callable from an interface function by declaring
both halves of each port under the port's own name. Getting that half-right is
the easy mistake -- a module that still has a legacy scalar `axis_out_ready`
alongside an interface-typed `axis_out` looks *almost* wireable, and silently
mis-wiring it would be the worst outcome. So it is a hard error that names the
port and the missing side. Restoring a `_ready` naming convention was considered
and rejected: the affix is only ever quoted in the diagnostic, never used to
decide a connection.

Also covers what a plain statement may touch, and that two instantiations of one
factory stay distinct (a generated module's canonical name must be a pure
function of its inputs, factory parameters included).
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
    uint8_t,
    sim_call,
    sim_reset,
)
from interface.interface import interface
from interface.interface_func import (
    InterfaceFuncError,
    make_hw_func_from_interface_func,
    callee_ports,
)


@interface
class chan(NamedTuple):
    data: uint8_t
    valid: uint1_t
    ready: Feedback[uint1_t]


chan_t = chan.fwd_t
chan_fb_t = chan.fb_t


def _expect(fn, needle):
    try:
        fn()
    except InterfaceFuncError as e:
        assert needle in str(e), f"expected {needle!r} in:\n{e}"
        return str(e)
    raise AssertionError(f"expected InterfaceFuncError mentioning {needle!r}")


# ── a legacy module: interface-typed ports, but the reverse halves are still
#    loose scalars under the old names -- deliberately NOT `_if`-suffixed:
#    this fixture's whole point is a port that predates the `_if` convention,
#    matched against a legacy `_ready` scalar by the old bare name ──
@struct
class legacy_t(NamedTuple):
    stream_in_ready: uint1_t
    stream_out: chan_t


def legacy(stream_in: chan_t, stream_out_ready: uint1_t) -> legacy_t:
    """Deliberately not `@hw_func`-decorated: this fixture is only ever
    introspected structurally (via `callee_ports`/`make_hw_func_from_interface_func`
    below), never simulated or elaborated as a real submodule, so it must not
    go through `@hw_func`'s own def-site half-pairing check -- the whole point
    of this fixture is to reach the richer, composition-time error instead
    (see the module docstring)."""
    o: legacy_t
    o.stream_out = stream_in
    o.stream_in_ready = stream_out_ready
    return o


def test_legacy_scalar_ready_ports_are_rejected_by_name():
    msg = _expect(lambda: callee_ports(legacy), "declares only its")
    assert "'stream_in'" in msg or "'stream_out'" in msg
    # the diagnostic quotes the leftover scalar, to say what to replace
    assert "_ready" in msg and "legacy scalar handshake ports" in msg


def test_half_migrated_module_cannot_be_instantiated():
    def wiring(stream_in_if: chan) -> chan:
        a = legacy(stream_in_if)
        return a.stream_out

    _expect(lambda: make_hw_func_from_interface_func(wiring), "declares only its")


# ── array ports are an output-side (fan-out) feature ──
@struct
class arr_in_t(NamedTuple):
    sinks_if: chan_fb_t[2]
    stream_out_if: chan_t


@hw_func
def arr_in(sinks_if: chan_t[2], stream_out_if: chan_fb_t) -> arr_in_t:
    o: arr_in_t
    o.stream_out_if = sinks_if[0]
    o.sinks_if[0].ready = stream_out_if.ready
    o.sinks_if[1].ready = 0
    return o


def test_array_input_port_is_rejected_clearly():
    _expect(lambda: callee_ports(arr_in), "array ports are supported on outputs")


# ── a plain field in a mixed return bundle must actually be driven ──
@struct
class pass_t(NamedTuple):
    stream_in_if: chan_fb_t
    stream_out_if: chan_t
    tag: uint8_t


@hw_func
def passthru(stream_in_if: chan_t, stream_out_if: chan_fb_t) -> pass_t:
    o: pass_t
    o.stream_out_if = stream_in_if
    o.stream_in_if = stream_out_if
    o.tag = stream_in_if.data
    return o


@interface
class tagged_ports(NamedTuple):
    stream_out_if: chan
    tag: uint8_t


def test_unassigned_plain_bundle_field_is_rejected():
    def wiring(stream_in_if: chan) -> tagged_ports:
        a = passthru(stream_in_if)
        return tagged_ports(stream_out_if=a.stream_out_if)

    _expect(lambda: make_hw_func_from_interface_func(wiring), "never assigned")


# ── plain statements: non-interface fields of a call result are readable,
#    the interface ports themselves are not ──
def plain_reads_wiring(stream_in_if: chan) -> tagged_ports:
    a = passthru(stream_in_if)
    doubled: uint8_t = a.tag + a.tag  # plain field of a call result: fine
    return tagged_ports(stream_out_if=a.stream_out_if, tag=doubled)


plain_reads, plain_reads_t = make_hw_func_from_interface_func(plain_reads_wiring)


@MAIN
def top_plain_reads(stream_in_if: chan_t, stream_out_if: chan_fb_t) -> plain_reads_t:
    return plain_reads(stream_in_if, stream_out_if)


def test_plain_statement_may_read_non_interface_fields():
    sim_reset()
    r = sim_call(top_plain_reads, chan_t(data=7, valid=1), chan_fb_t(ready=1))
    assert int(r.tag) == 14
    assert int(r.stream_out_if.data) == 7 and int(r.stream_in_if.ready) == 1


def test_plain_statement_may_not_touch_an_interface():
    def wiring(stream_in_if: chan) -> chan:
        a = passthru(stream_in_if)
        alias = a.stream_out_if  # an interface, outside of a call
        return alias

    _expect(
        lambda: make_hw_func_from_interface_func(wiring),
        "outside of a module call",
    )


# ── a generated module defined inside a factory must be named for that
#    factory's parameters, or two instantiations collide ──
def make_bump(step):
    @struct
    class bump_t(NamedTuple):
        stream_in_if: chan_fb_t
        stream_out_if: chan_t

    @hw_func
    def bump(stream_in_if: chan_t, stream_out_if: chan_fb_t) -> bump_t:
        o: bump_t
        o.stream_out_if.data = stream_in_if.data + step
        o.stream_out_if.valid = stream_in_if.valid
        o.stream_in_if.ready = stream_out_if.ready
        return o

    def wiring(stream_in_if: chan) -> chan:
        a = bump(stream_in_if)
        return a.stream_out_if

    return make_hw_func_from_interface_func(wiring)


bump3, bump3_t = make_bump(3)
bump9, bump9_t = make_bump(9)


@MAIN
def top_bump3(stream_in_if: chan_t, out_port_if: chan_fb_t) -> bump3_t:
    return bump3(stream_in_if, out_port_if)


@MAIN
def top_bump9(stream_in_if: chan_t, out_port_if: chan_fb_t) -> bump9_t:
    return bump9(stream_in_if, out_port_if)


def test_factory_instances_are_named_apart():
    assert bump3.__name__ != bump9.__name__
    assert "step_3" in bump3.__name__ and "step_9" in bump9.__name__
    assert bump3_t.__name__ != bump9_t.__name__
    sim_reset()
    r3 = sim_call(top_bump3, chan_t(data=10, valid=1), chan_fb_t(ready=1))
    r9 = sim_call(top_bump9, chan_t(data=10, valid=1), chan_fb_t(ready=1))
    assert int(r3.out_port_if.data) == 13 and int(r9.out_port_if.data) == 19


if __name__ == "__main__":
    test_legacy_scalar_ready_ports_are_rejected_by_name()
    test_half_migrated_module_cannot_be_instantiated()
    test_array_input_port_is_rejected_clearly()
    test_unassigned_plain_bundle_field_is_rejected()
    test_plain_statement_may_read_non_interface_fields()
    test_plain_statement_may_not_touch_an_interface()
    test_factory_instances_are_named_apart()
    print("OK: mixing rules enforced with errors that name what to fix")
