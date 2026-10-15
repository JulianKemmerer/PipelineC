# pyright: reportInvalidTypeForm=none
"""Factory-object attributes in hardware ports and direct submodule calls."""

from types import SimpleNamespace

from axi.axis import make_keep_count
from fixed_point import make_fixed_t, register_fixed_ops
from kept_data_bus import make_kept_data_bus_t
from pypeline import MAIN, hw_func, uint8_t, uint16_t
from stream.stream_auto_pipeline import make_stream_auto_pipeline

# Numeric operand type and its registered arithmetic bundle.
operand_t = make_fixed_t(3, 4)
# Registered arithmetic callable objects for operand_t.
ops = register_fixed_ops(operand_t)
# Peer bundles can nest without changing the contained functions' identity.
bundle = SimpleNamespace(arithmetic=ops)
# Four byte lanes and their validity bits.
bus_t = make_kept_data_bus_t(uint8_t, 4)
# An undecorated HDL factory callable still exposes its annotated return type.
keep_count = make_keep_count(bus_t, 4)


@MAIN
def registered_add(a: ops.operand_t, b: ops.operand_t) -> ops.add.return_t:
    return ops.add(a, b)


@MAIN
def nested_add(a: operand_t, b: operand_t) -> bundle.arithmetic.add.return_t:
    return bundle.arithmetic.add(a, b)


@MAIN
def count_kept(x: bus_t) -> keep_count.return_t:
    return keep_count(x)


@hw_func
def widen(x: uint8_t) -> uint16_t:
    return x


# Stream ports retain input/output direction while .return_t includes both.
pipeline = make_stream_auto_pipeline(widen, start_latency=2)


@MAIN
def stream_stage(
    stream_in_if: pipeline.in_fwd_t, stream_out_if: pipeline.out_fb_t
) -> pipeline.return_t:
    return pipeline(stream_in_if, stream_out_if)
