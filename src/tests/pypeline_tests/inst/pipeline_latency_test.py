# pyright: reportInvalidTypeForm=none
"""Fixed user pipelines: native alignment and compiler metadata regressions."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from pipeline_latency_import_design import imported_delay as renamed_delay

from pypeline import (
    MAIN,
    Reg,
    hw_func,
    pipeline_latency,
    sim_call,
    sim_reset,
    uint1_t,
    uint16_t,
)


@pipeline_latency(1)
def delay_one(x: uint16_t) -> uint16_t:
    saved: Reg[uint16_t]
    result: uint16_t = saved
    saved = x
    return result


@hw_func
def aligned_add(x: uint16_t) -> uint16_t:
    return delay_one(x) + x


@hw_func
def optional_join(x: uint16_t, bias: uint16_t = 5) -> uint16_t:
    return delay_one(x) + bias


@MAIN
def pipeline_latency_main(x: uint16_t) -> uint16_t:
    return aligned_add(x)


def make_delay(cycles):
    @pipeline_latency(cycles)
    def delay(x: uint16_t) -> uint16_t:
        registers: Reg[uint16_t[cycles]]
        result: uint16_t = registers[cycles - 1]
        for i in range(cycles - 1, 0, -1):
            registers[i] = registers[i - 1]
        registers[0] = x
        return result

    return delay


delay_two = make_delay(2)
delay_three = make_delay(3)


@hw_func
def fork_join(x: uint16_t) -> uint16_t:
    return delay_one(x) + delay_two(x) + delay_three(x) + x


@hw_func
def serial(x: uint16_t) -> uint16_t:
    return delay_two(delay_one(x))


@hw_func
def conditional(x: uint16_t, enable: uint1_t) -> uint16_t:
    result: uint16_t
    if enable:
        result = delay_one(x)
    return result


@hw_func
def unaffected(x: uint16_t) -> uint16_t:
    return x + 1


@pipeline_latency(0)
def zero_latency(x: uint16_t) -> uint16_t:
    return x


@hw_func
def zero_caller(x: uint16_t) -> uint16_t:
    return zero_latency(x) + x


@hw_func
def dynamic_join(x: uint16_t, index: uint1_t) -> uint16_t:
    choices: uint16_t[2] = [delay_one(x), x + 5]
    return choices[index]


@hw_func
def dynamic_write(x: uint16_t, index: uint1_t) -> uint16_t:
    choices: uint16_t[2] = [x, x + 5]
    choices[index] = delay_one(x)
    return choices[0] + choices[1]


@hw_func
def imported_join(x: uint16_t) -> uint16_t:
    return renamed_delay(x) + x


@hw_func
def multiple_instances(x: uint16_t) -> uint16_t:
    return delay_one(x) + delay_one(x + 1)


@hw_func
def loop_instances(x: uint16_t) -> uint16_t:
    result: uint16_t
    for i in range(3):
        result += delay_one(x + i)
    return result


@hw_func
def stateful_a(x: uint16_t) -> uint16_t:
    ticks: Reg[uint16_t]
    ticks += 1
    return aligned_add(x)


@hw_func
def stateful_b(x: uint16_t) -> uint16_t:
    ticks: Reg[uint16_t]
    ticks += 1
    return aligned_add(x)


def test_alternating_live_roots():
    sim_reset()
    outputs = [
        int(sim_call(fn, x))
        for fn, x in (
            (stateful_a, 3),
            (stateful_b, 8),
            (stateful_a, 17),
            (stateful_b, 2),
        )
    ]
    assert outputs == [0, 0, 6, 16], outputs


def test_standalone_alignment():
    sim_reset()
    outputs = [int(sim_call(aligned_add, x)) for x in (3, 8, 17, 2)]
    assert outputs == [0, 6, 16, 34], outputs
    sim_reset()
    outputs = [int(sim_call(optional_join, x=x)) for x in (3, 8, 17)]
    assert outputs == [0, 8, 13], outputs
    from pypeline import AUTOPIPELINE

    sim_reset()
    ap = AUTOPIPELINE(aligned_add)
    outputs = [int(sim_call(ap, x)) for x in (3, 8, 17, 2)]
    assert outputs == [0, 6, 16, 34], outputs


def test_direct_registers():
    sim_reset()
    outputs = [int(sim_call(delay_one, x)) for x in (3, 8, 17, 2)]
    assert outputs == [0, 3, 8, 17], outputs


def test_aliases_and_instances():
    for fn, expected in (
        (imported_join, [0, 6, 16]),
        (multiple_instances, [0, 7, 17]),
        (loop_instances, [0, 12, 27]),
    ):
        sim_reset()
        outputs = [int(sim_call(fn, x)) for x in (3, 8, 17)]
        assert outputs == expected, (fn, outputs)


def test_serial_and_parallel():
    for fn, scale in ((serial, 1), (fork_join, 4)):
        sim_reset()
        outputs = [int(sim_call(fn, x)) for x in (3, 8, 17, 2, 21, 5)]
        assert outputs == [0, 0, 0, 3 * scale, 8 * scale, 17 * scale], (fn, outputs)


def test_conditional_enable():
    sim_reset()
    pairs = ((3, 1), (8, 0), (17, 1), (2, 1), (21, 0))
    outputs = [int(sim_call(conditional, x, en)) for x, en in pairs]
    assert outputs == [0, 3, 0, 17, 2], outputs


def test_dynamic_array_alignment():
    sim_reset()
    pairs = ((3, 0), (8, 1), (17, 0), (2, 1), (21, 0))
    outputs = [int(sim_call(dynamic_join, x, index)) for x, index in pairs]
    assert outputs == [0, 3, 13, 17, 7], outputs
    sim_reset()
    outputs = [int(sim_call(dynamic_write, x, index)) for x, index in pairs]
    assert outputs[1:] == [11, 16, 39, 4], outputs


def test_unaffected_gate():
    import pypeline_sim_pipeline as model
    from unittest.mock import patch

    with patch.object(
        model, "prepare", side_effect=AssertionError("unexpected pipeline model")
    ):
        sim_reset()
        assert int(sim_call(unaffected, 4)) == 5
        assert int(sim_call(zero_caller, 4)) == 8
        assert int(sim_call(delay_one, 4)) == 0


def test_untagged_cli_does_not_import_model():
    import subprocess

    code = """
import sys
import runpy
import pypeline
import pypeline_sim
class Forbidden:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'pypeline_sim_pipeline' or (
            sys.argv[-1] == 'direct' and fullname == 'PY_TO_LOGIC'
        ):
            raise AssertionError('ordinary native sim imported ' + fullname)
sys.meta_path.insert(0, Forbidden())
# Also exercise the cheap reachability gate after a prior declaration existed.
pypeline._pipeline_latency_declared = True
if sys.argv[-1] == 'direct':
    pypeline_sim.run_sim(sys.argv[1], pypeline_sim.RUN_ALL)
else:
    from pathlib import Path
    driver = str(Path(pypeline.__file__).with_name('pypelinec'))
    sys.argv = [driver, sys.argv[1], '--sim', '--comb', '--run', 'all']
    runpy.run_path(driver, run_name='__main__')
"""
    env = dict(
        os.environ,
        PYTHONPATH=os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")),
    )
    for filename in (
        "self_check_bit_math_test.py",
        "self_check_counter_test.py",
        "native_vs_vhdl_ap_test.py",
        "self_check_autofsm_test.py",
    ):
        for mode in ("direct", "cli"):
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    code,
                    os.path.join(os.path.dirname(__file__), filename),
                    mode,
                ],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            assert result.returncode == 0, result.stdout


def test_decorator_validation():
    for value in (True, False, 1.5, "2", None):
        try:
            pipeline_latency(value)
        except TypeError:
            pass
        else:
            raise AssertionError(value)
    try:
        pipeline_latency(-1)
    except ValueError:
        pass
    else:
        raise AssertionError("negative latency accepted")
    assert pipeline_latency(1)(delay_one) is delay_one
    try:
        pipeline_latency(2)(delay_one)
    except ValueError:
        pass
    else:
        raise AssertionError("conflicting latency accepted")


def test_decorator_stacking():
    import pypeline as p

    registered = list(p._main_registry)
    rates = dict(p._main_mhz_registry)
    try:
        for decorators in (
            (MAIN, pipeline_latency(1), hw_func),
            (pipeline_latency(1), MAIN, hw_func),
        ):

            @hw_func
            def stacked(x: uint16_t) -> uint16_t:
                saved: Reg[uint16_t] = 9
                result: uint16_t = saved
                saved = x
                return result

            for decorate in decorators:
                stacked = decorate(stacked)
            sim_reset()
            assert int(sim_call(stacked, 12)) == 9
            assert int(sim_call(stacked, 15)) == 12
            assert stacked._pipeline_latency == 1
    finally:
        p._main_registry[:] = registered
        p._main_mhz_registry.clear()
        p._main_mhz_registry.update(rates)


def test_tagged_sim_model():
    from pypeline import sim_model

    @pipeline_latency(1)
    def modeled(x: uint16_t) -> uint16_t:
        saved: Reg[uint16_t]
        result: uint16_t = saved
        saved = x
        return result

    @sim_model(modeled)
    class DelayModel:
        def __init__(self):
            self.saved = 0

        def __call__(self, x):
            result, self.saved = self.saved, int(x)
            return result

    @hw_func
    def model_join(x: uint16_t) -> uint16_t:
        return modeled(x) + x

    sim_reset()
    outputs = [int(sim_call(model_join, x)) for x in (3, 8, 17)]
    assert outputs == [0, 6, 16], outputs


def test_file_parse_metadata():
    import subprocess

    code = """
import sys
import PY_TO_LOGIC as py
previous = None
for _ in range(2):
    state = py.PARSE_FILE(sys.argv[1])
    for name, fn in state.pypeline_entity_callables.items():
        cycles = getattr(fn, '_pipeline_latency', None)
        if cycles is not None:
            assert state.func_fixed_latency[name] == cycles, name
    assert any('imported_delay' in name for name in state.func_fixed_latency)
    assert {0, 1, 2, 3} <= set(state.func_fixed_latency.values())
    if previous is not None:
        assert state.func_fixed_latency == previous
    previous = dict(state.func_fixed_latency)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, os.path.abspath(__file__)],
        env=dict(
            os.environ,
            PYTHONPATH=os.path.abspath(
                os.path.join(os.path.dirname(__file__), "../../..")
            ),
        ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert result.returncode == 0, result.stdout


def test_convergence_and_reset():
    import pypeline as p

    sim_reset()
    sim_call(aligned_add, 5)
    p._sim_active = True
    p._sim_reg_begin_buffer()
    try:
        assert int(sim_call(aligned_add, 7)) == 10
        assert int(sim_call(aligned_add, 9)) == 10
    finally:
        p._sim_reg_flush_buffer()
        p._sim_active = False
    assert int(sim_call(aligned_add, 11)) == 18
    sim_reset()
    assert int(sim_call(aligned_add, 12)) == 0


def test_conflicting_autopipeline():
    from pypeline import AUTOPIPELINE
    import PY_TO_LOGIC as py

    try:
        AUTOPIPELINE(delay_one, depth=2)
    except ValueError:
        pass
    else:
        raise AssertionError("fixed function accepted a different depth")
    ap = AUTOPIPELINE(unaffected)

    @pipeline_latency(1)
    def invalid(x: uint16_t) -> uint16_t:
        return ap(x)

    try:
        py.ELABORATE_LIVE_ROOTS([invalid])
    except py.ElaborationError as error:
        assert "AUTOPIPELINE inside" in str(error), str(error)
    else:
        raise AssertionError("fixed implementation accepted internal AUTOPIPELINE")


def test_elaboration_metadata():
    import PY_TO_LOGIC as py
    import SYN
    import pypeline as p

    p._pipeline_latency_preparing = True
    try:
        for _ in range(2):
            state = py.ELABORATE_LIVE_ROOTS([fork_join])
            assert sorted(state.func_fixed_latency.values()) == [1, 2, 3]
            timing = {
                name: SYN.TimingParams(name, logic)
                for name, logic in state.LogicInstLookupTable.items()
            }
            for name, logic in state.LogicInstLookupTable.items():
                if logic.func_name in state.func_fixed_latency:
                    assert not logic.CAN_HAVE_ADDED_LATENCY(state)
                    assert (
                        timing[name].GET_TOTAL_LATENCY(state, timing)
                        == state.func_fixed_latency[logic.func_name]
                    )
                    assert (
                        timing[name].GET_PIPELINE_LOGIC_ADDED_LATENCY(state, timing)
                        == 0
                    )
    finally:
        p._pipeline_latency_preparing = False


def test_fixed_vhdl_has_no_added_registers():
    import tempfile
    from pathlib import Path
    import PY_TO_LOGIC as py
    import SYN
    import VHDL

    state = py.ELABORATE_LIVE_ROOTS([aligned_add])
    timing = {
        name: SYN.TimingParams(name, logic)
        for name, logic in state.LogicInstLookupTable.items()
    }
    with tempfile.TemporaryDirectory() as directory:
        for inst, logic in state.LogicInstLookupTable.items():
            if logic.func_name in state.func_fixed_latency:
                VHDL.WRITE_LOGIC_ENTITY(inst, logic, directory, state, timing)
        files = list(Path(directory).glob("*.vhd"))
        assert files
        for filename in files:
            text = filename.read_text()
            assert "constant ADDED_PIPELINE_LATENCY : integer := 0;" in text, filename


def test_placement_respects_entire_fixed_boundary():
    import PY_TO_LOGIC as py
    import SYN
    import SWEEP

    @pipeline_latency(1)
    def registered_sum(x: uint16_t) -> uint16_t:
        saved: Reg[uint16_t]
        result: uint16_t = saved
        saved = x + 1
        return result

    state = py.ELABORATE_LIVE_ROOTS([registered_sum])
    timing = {
        name: SYN.TimingParams(name, logic)
        for name, logic in state.LogicInstLookupTable.items()
    }
    assert len(timing) > 1
    for inst, tp in timing.items():
        placement = SWEEP.PipelinePlacement(
            SWEEP.PipelinePlacement.INSTANCE_OUTPUT, inst, tp.logic.func_name, 0, 0.0
        )
        for apply in (
            lambda: SWEEP.APPLY_PIPELINE_PLACEMENTS([placement], state, timing),
            lambda: SYN.SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(
                inst, tp.logic, 0.5, state, timing, False, write_files=False
            ),
        ):
            try:
                apply()
            except ValueError as error:
                assert "fixed latency 1" in str(error), str(error)
            else:
                raise AssertionError(f"placement entered fixed implementation: {inst}")
        assert tp.IS_EMPTY()


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
