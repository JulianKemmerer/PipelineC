# pyright: reportInvalidTypeForm=none
"""Single-object HDL factory contracts; native checks without synthesis.

Registered in unit. Existing native/VHDL designs exercise .return_t in port,
Feedback and register annotations; these tests cover metadata and bundle identity.
"""

import inspect
from pathlib import Path
import sys
from unittest.mock import patch
import tempfile

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include" / "pypeline")]

import pypeline as py
from axi.axis import make_dwidth_narrow, make_dwidth_widen, make_keep_count
from fixed_point import make_fixed_t, register_fixed_ops
from floating_point import float16_t, register_float_ops
from interface.interface_func import make_hw_func_from_interface_func
from ram import make_ram
from stream.skid_buffer import make_skid_buffer
from stream.stream import make_stream_interface
from stream.stream_auto_pipeline import make_stream_auto_pipeline
from stream.stream_ram import make_stream_ram


def test_return_type_survives_all_simulation_wrapper_variants():
    for raw in (False, True):
        with patch.object(py, "SIM_RAW_INTS", raw):

            @py.hw_func
            def combinational(x: py.uint8_t) -> py.uint16_t:
                return x + 1

            @py.hw_func
            def stateful(x: py.uint8_t) -> py.uint16_t:
                previous: py.Reg[py.uint16_t]
                result: py.uint16_t = previous
                previous = x
                return result

        for func in (combinational, stateful):
            assert func.return_t is py.uint16_t
            assert inspect.unwrap(func).return_t is func.return_t
            assert py.hw_return_type(func) is func.return_t
            assert py.hw_func(func) is func
        py.sim_reset()
        assert int(py.sim_call(combinational, 8)) == 9
        assert int(py.sim_call(stateful, 8)) == 0
        assert int(py.sim_call(stateful, 9)) == 8


def test_void_and_unannotated_functions_expose_none():
    @py.hw_func
    def void() -> None:
        pass

    @py.hw_func
    def unannotated():
        pass

    assert void.return_t is None
    assert unannotated.return_t is None


def test_internal_pipeline_factory_returns_the_callable_and_tag_metadata():
    @py.hw_func
    def widen(x: py.uint8_t) -> py.uint16_t:
        return x + 1

    for input_reg in (False, True):
        for output_reg in (False, True):
            block = py._auto_pipeline_with_io_regs(
                widen, input_reg, output_reg, latency=2
            )
            assert callable(block)
            assert block.return_t is py.uint16_t
            assert block.auto_pipeline.func is widen
            assert block.auto_pipeline.fixed_latency == 2


def test_stacked_decorators_preserve_return_type():
    @py.hw_func
    @py.wires
    def forward(x: py.uint8_t) -> py.uint8_t:
        return x

    assert forward.return_t is py.uint8_t
    assert inspect.unwrap(forward).return_t is py.uint8_t


def test_stream_result_contains_both_port_directions():
    @py.hw_func
    def widen(x: py.uint8_t) -> py.uint16_t:
        return x

    block = make_stream_auto_pipeline(widen, latency=1)
    assert callable(block)
    assert block.return_t.typeof("stream_in_if") is block.in_fb_t
    assert block.return_t.typeof("stream_out_if") is block.out_fwd_t
    assert py.hw_arg_types(block) == (block.in_fwd_t, block.out_fb_t)
    assert block.in_intrf.stream_t.typeof("data") is py.uint8_t
    assert block.out_intrf.stream_t.typeof("data") is py.uint16_t


def test_width_converters_expose_directional_port_types():
    widen = make_dwidth_widen(py.uint8_t, 2, 3)
    narrow = make_dwidth_narrow(py.uint8_t, 2, 3)
    assert py.hw_arg_types(widen) == (
        widen.narrow_in_intrf.fwd_t,
        widen.wide_out_intrf.fb_t,
    )
    assert py.hw_arg_types(narrow) == (
        narrow.wide_in_intrf.fwd_t,
        narrow.narrow_out_intrf.fb_t,
    )
    assert widen.return_t.typeof("wide_out_if") is widen.wide_out_intrf.fwd_t
    assert narrow.return_t.typeof("narrow_out_if") is narrow.narrow_out_intrf.fwd_t


def test_ram_cache_returns_the_complete_callable():
    for factory in (make_ram, make_stream_ram):
        first = factory(py.uint8_t, 4)
        second = factory(py.uint8_t, 4)
        different = factory(py.uint16_t, 4)
        assert first is second
        assert first is not different
        assert callable(first)
        assert first.return_t is first.out_t
        assert different.return_t is not first.return_t


def test_generated_interface_cache_returns_the_complete_callable():
    intrf = make_stream_interface(py.uint8_t)
    skid = make_skid_buffer(intrf)

    def wiring(stream_in_if: intrf) -> intrf:
        stage = skid(stream_in_if)
        return stage.stream_out_if

    first = make_hw_func_from_interface_func(wiring)
    assert make_hw_func_from_interface_func(wiring) is first
    assert callable(first)
    assert first.return_t is py.hw_return_type(first)
    assert first.return_t.typeof("stream_in_if") is intrf.fb_t
    assert first.return_t.typeof("out_port_if") is intrf.fwd_t


def test_fixed_operations_distinguish_operands_from_widened_results():
    operand_t = make_fixed_t(4, 4)
    ops = register_fixed_ops(operand_t)
    assert ops.operand_t is operand_t
    assert ops.add.return_t.int_bits == 5
    assert ops.subtract.return_t.int_bits == 5
    assert ops.multiply.return_t.int_bits == 8
    assert ops.negate.return_t is operand_t
    py.sim_reset()
    a, b = operand_t.as_const(2.0), operand_t.as_const(1.0)
    assert float(py.sim_call(ops.add, a, b)) == 3.0
    assert float(py.sim_call(ops.subtract, a, b)) == 1.0
    assert float(py.sim_call(ops.multiply, a, b)) == 2.0
    assert float(py.sim_call(ops.negate, a)) == -2.0


def test_unsigned_fixed_operations_expose_no_negate():
    operand_t = make_fixed_t(4, 4, signed=False)
    ops = register_fixed_ops(operand_t)
    assert ops.operand_t is operand_t
    assert ops.negate is None


def test_float_operations_bundle_contains_registered_callables():
    ops = register_float_ops(float16_t)
    assert ops.operand_t is float16_t
    for func in (ops.add, ops.subtract, ops.multiply, ops.divide):
        assert py.hw_arg_types(func) == (float16_t, float16_t)
        assert func.return_t is float16_t
    py.sim_reset()
    a, b = float16_t.as_const(6.0), float16_t.as_const(2.0)
    assert float(py.sim_call(ops.add, a, b)) == 8.0
    assert float(py.sim_call(ops.subtract, a, b)) == 4.0
    assert float(py.sim_call(ops.multiply, a, b)) == 12.0
    assert float(py.sim_call(ops.divide, a, b)) == 3.0


def test_undecorated_factory_callable_exposes_its_return_type():
    from kept_data_bus import make_kept_data_bus_t

    bus_t = make_kept_data_bus_t(py.uint8_t, 4)
    count = make_keep_count(bus_t, 4)
    assert not py.is_hw_func(count)
    assert count.return_t is py.hw_return_type(count)
    assert int(py.sim_call(count, bus_t(data=[0] * 4, keep=[1, 0, 1, 1]))) == 3


def test_factory_object_attributes_elaborate_as_hardware_types_and_calls():
    import PY_TO_LOGIC
    import SYN

    with tempfile.TemporaryDirectory(prefix="factory_api_") as output:
        with patch.object(SYN, "SYN_OUTPUT_DIRECTORY", output):
            state = PY_TO_LOGIC.PARSE_FILE(
                str(Path(__file__).with_name("factory_api_design.py"))
            )
    assert {"registered_add", "nested_add", "count_kept", "stream_stage"} <= set(
        state.main_mhz
    )
    for name in ("registered_add", "nested_add", "count_kept", "stream_stage"):
        assert state.FuncLogicLookupTable[name].submodule_instances


def test_hardware_local_cannot_resolve_a_shadowed_operation_bundle():
    import PY_TO_LOGIC
    import SYN

    with tempfile.TemporaryDirectory(prefix="factory_api_shadow_") as output:
        with patch.object(SYN, "SYN_OUTPUT_DIRECTORY", output):
            try:
                PY_TO_LOGIC.PARSE_FILE(
                    str(Path(__file__).with_name("factory_api_shadow_design.py"))
                )
            except NotImplementedError as error:
                assert "ops" in str(error) and "add" in str(error)
            else:
                raise AssertionError("hardware input resolved to the global bundle")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
