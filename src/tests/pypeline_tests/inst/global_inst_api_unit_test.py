"""Unit checks of pypeline.py's global instance API, with no design build:
Inst[f], the ports it derives from f (_global_inst_ports) and the wire type
they make, the errors for hardware that cannot be an instance, the MAIN
generator's source, the MAIN name native sim gives an instance, and MAIN()
checking a user's name= where an instance's own MAIN name is not checked.
"""

import inspect
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "include", "pypeline"
    ),
)

import pypeline
from pypeline import (
    AUTO_PIPELINE,
    MAIN,
    Fifo,
    GlobalInstError,
    Inst,
    NamedTuple,
    Reg,
    hw_func,
    struct,
    uint1_t,
    uint8_t,
    uint16_t,
)
from interface.interface import interface
from stream.skid_buffer import make_skid_buffer
from stream.stream import make_stream_interface


def _raises(exc_type, fn, *must_contain):
    try:
        fn()
    except exc_type as e:
        for token in must_contain:
            assert token in str(e), f"expected {token!r} in: {e}"
        return str(e)
    raise AssertionError(f"expected {exc_type.__name__}")


@hw_func
def add(a: uint8_t, b: uint8_t) -> uint8_t:
    return a + b


@struct
class pair_t(NamedTuple):
    lo: uint8_t
    hi: uint8_t


@hw_func
def split(x: uint16_t) -> pair_t:
    return pair_t(lo=x, hi=x >> 8)


intrf = make_stream_interface(uint8_t)


@struct
class source_t(NamedTuple):
    out_if: intrf.fwd_t
    idle: uint1_t


@hw_func
def source(go: uint1_t, out_if: intrf.fb_t) -> source_t:
    o: source_t
    return o


@interface
class oneway(NamedTuple):
    v: uint8_t


@hw_func
def take(x_if: oneway.fwd_t) -> uint8_t:
    return x_if.v


def _ports(ann):
    return [(p.name, p.is_input, p.interface is not None) for p in ann.ports]


def test_plain_ports():
    ann = Inst[add]
    assert str(ann) == "Inst[add]"
    assert isinstance(ann, pypeline._WireType) and not ann.volatile
    assert _ports(ann) == [("a", True, False), ("b", True, False), ("out", False, False)]
    wire_t = ann.inner_ctype
    assert wire_t._fields == ("a", "b", "out"), wire_t._fields
    assert wire_t.__annotations__["out"] is uint8_t
    # One wire type per hardware, whatever the declaration
    assert Inst[add].inner_ctype is wire_t
    # A struct return value is one output port of that type
    out_t = Inst[split].inner_ctype.__annotations__["out"]
    assert out_t is pair_t, out_t
    print("plain ports PASS")


def test_interface_ports():
    sb = Inst[make_skid_buffer(uint8_t)]
    assert _ports(sb) == [("stream_in_if", True, True), ("stream_out_if", False, True)]
    end_t = sb.inner_ctype.__annotations__["stream_in_if"]
    assert end_t._fields == ("stream", "ready"), end_t._fields
    # A port bundle's plain field is an output port of its own
    assert _ports(Inst[source]) == [
        ("go", True, False),
        ("out_if", False, True),
        ("idle", False, False),
    ]
    # A one-directional interface port has no returned half
    (x_if, out) = Inst[take].ports
    assert x_if.is_input and x_if.ret_t is None and out.name == "out"
    # Different hardware, different types; the same factory call, the same names
    names = {
        Inst[make_skid_buffer(t)].inner_ctype._pypeline_ctype_name
        for t in (uint8_t, uint16_t, uint8_t)
    }
    assert len(names) == 2, names
    print("interface ports PASS")


def test_auto_pipeline_tag():
    ann = Inst[AUTO_PIPELINE(add, latency=2)]
    assert str(ann) == "Inst[AUTO_PIPELINE(add)]", str(ann)
    assert [p.name for p in ann.ports] == ["a", "b", "out"]
    print("AUTO_PIPELINE tag PASS")


def test_errors():
    err = GlobalInstError
    _raises(err, lambda: Inst[add, add], "takes one hardware function", "Inst[add, add]")
    _raises(err, lambda: Inst[42], "Inst[42]", "must be a @hw_func")
    _raises(err, lambda: Inst[lambda x: x], "must be a @hw_func")

    def made_main():
        @MAIN
        def lone_main():
            pass

        return Inst[lone_main]

    _raises(err, made_main, "it is a @MAIN")

    @hw_func
    def nothing():
        pass

    _raises(err, lambda: Inst[nothing], "Inst[nothing]", "no ports")

    @hw_func
    def lanes(xs_if: oneway.fwd_t[2]) -> uint8_t:
        return 0

    _raises(err, lambda: Inst[lanes], "argument 'xs_if'", "not supported yet")

    @hw_func
    def clash(out: uint8_t) -> uint8_t:
        return out

    _raises(err, lambda: Inst[clash], "argument 'out'", "rename the argument")

    @struct
    class mixed_t(NamedTuple):
        out_if: intrf.fwd_t
        go: uint1_t

    @hw_func
    def same_name(go: uint1_t, out_if: intrf.fb_t) -> mixed_t:
        o: mixed_t
        return o

    _raises(err, lambda: Inst[same_name], "return field 'go'", "share a name")
    print("errors PASS")


def test_main_generator():
    ann = Inst[source]
    module_globals = {
        "__name__": "some_design",
        "__annotations__": {"src": ann},
        "inst_hardware": 1,
    }
    main = pypeline._make_global_inst_main(
        "src_INST", "src", ann, ann.hardware("src", None), module_globals
    )
    src = inspect.getsource(inspect.unwrap(main))
    assert src.startswith("def src_INST():"), src
    for line in (
        "    inst_ports = inst_hardware_2(",
        "        go=src.go,",
        "        out_if=inst_out_if_t(ready=src.out_if.ready),",
        "    src.out_if.stream = inst_ports.out_if.stream",
        "    src.idle = inst_ports.idle",
    ):
        assert line + "\n" in src, (line, src)
    assert main.__module__ == "some_design" and pypeline.is_hw_func(main)
    _raises(
        GlobalInstError,
        lambda: ann.hardware("src", 3),
        "global instance 'src'",
        "takes no initializer",
    )
    print("MAIN generator PASS")


def test_main_names():
    name = pypeline._global_inst_main_name
    assert name("pypeline_design", "alu0", Inst[add]) == "alu0_INST"
    assert name("pkg.sub", "alu0", Inst[add]) == "pkg_sub_alu0_INST"
    assert name("pkg.sub", "rx", Fifo[uint8_t]) == "pkg_sub_rx_FIFO"
    print("MAIN names PASS")


def test_name_checks():
    @hw_func
    def lane():
        n: Reg[uint8_t]
        n += 1

    # A user's name= is checked by MAIN()
    _raises(ValueError, lambda: MAIN(lane, name="two__underscores"), "MAIN(name=")
    # An instance's MAIN name is its wire's key plus a suffix, used verbatim
    # even past the 64-character limit on user names
    long_name = "a" * 70 + "_INST"
    main = pypeline._register_main(lane, None, long_name, "here")
    assert main._pypeline_main.name == long_name
    print("name checks PASS")


if __name__ == "__main__":
    test_plain_ports()
    test_interface_ports()
    test_auto_pipeline_tag()
    test_errors()
    test_main_generator()
    test_main_names()
    test_name_checks()
    print("global_inst_api_unit_test: all PASS")
