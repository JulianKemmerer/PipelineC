#!/usr/bin/env python3
"""Identity and readability contracts, including interfaces and overflow."""
import inspect
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../../include/pypeline")
    ),
)

import pypeline as PL
import PY_TO_LOGIC as P
import pypeline_names as N
from axi.axis import (
    make_axis_interface,
    make_axis_broadcast_interlock,
    make_axis_skid_buffer,
)
from kept_data_bus import make_kept_data_bus_t


def test_interface_specializations_have_distinct_keys_and_keep_pairing():
    keys = {}
    for width in (8, 4, 8, 4):
        iface = make_axis_interface(width)
        broadcast, result = make_axis_broadcast_interlock(iface, 2)
        skid, skid_result = make_axis_skid_buffer(iface)
        for fn, result_t in ((broadcast, result), (skid, skid_result)):
            assert inspect.unwrap(fn).__annotations__["return"] is result_t
            assert fn.axis_intrf is iface
            key = P.CANONICAL_CALLABLE_KEY(fn)
            slot = (fn.__name__, width)
            assert keys.setdefault(slot, key) == key
            rendered = fn._pypeline_name_info.render(N.BASE_LIMIT)
            assert "_n_" + str(width) in rendered, rendered
            assert "uint8_t" in rendered, rendered
        assert iface.fwd_t._pypeline_interface is iface
        assert iface.fb_t._pypeline_interface is iface
    for function in ("axis_broadcast_interlock", "skid_buffer"):
        assert keys[(function, 4)] != keys[(function, 8)], keys


def test_record_names_describe_factory_and_interface_role():
    t = make_kept_data_bus_t(PL.uint8_t, 4)
    assert t._pypeline_name_info.render(N.BASE_LIMIT) == (
        "kept_data_bus_t_from_kept_data_bus_n_4_data_t_uint8_t"
    )
    iface = make_axis_interface(4)
    for role, t in (("fwd", iface.fwd_t), ("fb", iface.fb_t), ("wire", iface.wire_t)):
        name = t._pypeline_name_info.render(N.BASE_LIMIT)
        assert name.startswith("stream_intrf_" + role + "_t_from_stream_stream"), name
        assert "_n_4" in name and "uint8_t" in name, name
        assert t._pypeline_name_info.source.endswith("stream.py")


def test_typed_identity_survives_lossy_readable_encoding():
    def make_offset(config):
        @PL.hw_func
        def offset(x: PL.uint32_t) -> PL.uint32_t:
            return x

        return offset

    values = ("a-b", "a_b", True, 1, "1", [1, 2], (1, 2))
    keys = [P.CANONICAL_CALLABLE_KEY(make_offset(v)) for v in values]
    assert len(set(keys)) == len(keys), keys
    assert keys == [P.CANONICAL_CALLABLE_KEY(make_offset(v)) for v in values]
    assert N.identity({"b": 2, "a": 1}) == N.identity({"a": 1, "b": 2})


def test_overflow_preserves_roles_and_is_fully_decodable():
    iface = make_axis_interface(8)
    child = iface._pypeline_name_info
    for i in range(6):
        child = N.NameInfo(
            "function",
            "stream_pipeline",
            "stream.pipeline",
            params=(("MAX_IN_FLIGHT", str(i + 4)), ("func", child)),
            identity="layer" + str(i) + child.identity,
        )
    short = child.render(N.BASE_LIMIT)
    assert len(short) <= N.BASE_LIMIT and "MAX_IN_FLIGHT_9" in short, short
    assert "_h" in short and "stream_pipeline" in short, short
    assert "_n_8" in child.render() and "uint8_t" in child.render()
    names = N.EmissionNames({"logical_core": {child}})
    variant = names.identifier("logical_core_0CLK_1234abcd")
    assert variant.endswith("_0CLK_1234abcd"), variant
    assert names.identifier(variant) == variant
    huge = "helper_" * 60 + "_0CLK_1234abcd"
    assert N.shorten(huge).endswith("_0CLK_1234abcd")
    assert len(N.shorten(huge)) <= N.IDENTIFIER_LIMIT
    assert N.shorten("unbroken" * 50).startswith("generated_h")


def test_returned_factory_preserves_outer_closure_identity():
    from operators.soft_cmp import make_soft_cmp_prefix

    # The outer factory is no longer on the stack when the type-specialized
    # function is decorated. Its consumed op survives as greater/strict.
    keys = []
    for op in ("LT", "LTE", "GT", "GTE"):
        factory = make_soft_cmp_prefix(op)
        fn = factory(PL.uint4_t, PL.uint3_t)
        keys.append(P.CANONICAL_CALLABLE_KEY(fn))
        assert keys[-1] == P.CANONICAL_CALLABLE_KEY(factory(PL.uint4_t, PL.uint3_t))
    assert len(set(keys)) == 4, keys


def _make_late_interface_factory(iface):
    from interface.interface_func import make_hw_func_from_interface_func

    def build():
        skid, _ = make_axis_skid_buffer(iface)

        def chain(stream_in_if: iface) -> iface:
            stage = skid(stream_in_if)
            return stage.stream_out_if

        return make_hw_func_from_interface_func(chain)

    return build


def test_interface_function_identity_survives_a_returned_factory():
    factories = [_make_late_interface_factory(make_axis_interface(n)) for n in (4, 8)]
    generated = [factory()[0] for factory in factories]
    keys = [P.CANONICAL_CALLABLE_KEY(fn) for fn in generated]
    assert len(set(keys)) == 2, keys
    assert keys == [P.CANONICAL_CALLABLE_KEY(factory()[0]) for factory in factories]
    for fn, width in zip(generated, (4, 8)):
        info = fn._pypeline_name_info
        assert info.symbol == "chain"
        assert "_n_" + str(width) in info.render(), info.render()
        assert info.source == __file__


def test_presentation_collisions_are_deterministic_and_case_insensitive():
    info = N.NameInfo("struct", "packet_t", "packets", identity="layout1")
    other = replace(info, symbol="PACKET_T", identity="layout2")
    a = N.EmissionNames({"logical_a": {info}, "logical_b": {other}})
    b = N.EmissionNames({"logical_b": {other}, "logical_a": {info}})
    assert a.bases == b.bases
    assert a.bases["logical_a"].lower() != a.bases["logical_b"].lower()
    assert all(len(n) <= N.BASE_LIMIT for n in a.bases.values())
    fixed = N.EmissionNames({"logical_a": {info}}, protected={"PACKET_T_FROM_PACKETS"})
    assert fixed.bases["logical_a"].lower() != "packet_t_from_packets"
    assert fixed.identifier("PACKET_T_FROM_PACKETS") == "PACKET_T_FROM_PACKETS"


def test_vhdl_lexing_preserves_literals_comments_and_public_ports():
    info = N.NameInfo("struct", "packet_t", "packets", identity="packet")
    names = N.EmissionNames({"logical_packet": {info}}, protected={"external_port"})
    original = '''-- logical_packet
report "logical_packet and ""logical_packet""";
signal external_port : logical_packet;
signal c : character := 'x';
signal \\logical_packet\\ : logical_packet;
'''
    rendered = names.text(original)
    assert rendered.startswith(
        '-- logical_packet\nreport "logical_packet and ""logical_packet""";'
    )
    assert "signal external_port : packet_t_from_packets;" in rendered
    assert "'x'" in rendered and "\\logical_packet\\" in rendered
    assert names.text(rendered) == rendered


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
