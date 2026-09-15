"""Delay-first combinational API, graph, equivalence and timing regressions."""
import inspect
import os
import random
import sys
import tempfile
import textwrap

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
from pypeline import AUTO_COMB_SHARE, AUTO_COMB_UNSHARE, MAIN, hw_func, uint1_t, uint8_t, uint16_t


@hw_func
def core(a: uint8_t, b: uint8_t, c: uint8_t, d: uint8_t, sel: uint1_t) -> uint16_t:
    product: uint16_t = a * b
    choose: uint1_t = (product > c) ^ sel
    left: uint8_t = a if choose else c
    right: uint8_t = b if choose else d
    return left * right


ACU = AUTO_COMB_UNSHARE(core)


@MAIN(1.0)
def top(a: uint8_t, b: uint8_t, c: uint8_t, d: uint8_t, sel: uint1_t) -> uint16_t:
    return ACU(a, b, c, d, sel)


def test_native():
    assert ACU.latency == 0
    assert inspect.signature(ACU) == inspect.signature(core)
    assert AUTO_COMB_UNSHARE(ACU).func is core
    assert AUTO_COMB_SHARE(ACU).func is ACU
    assert AUTO_COMB_UNSHARE(AUTO_COMB_SHARE(core)).func.func is core
    assert ACU(9, 7, 6, 5, 0) == core(9, 7, 6, 5, 0)


def test_native_without_optimizer():
    import subprocess

    code = """
import importlib.abc, runpy, sys
class NoCompiler(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'AUTO_COMB_SHARE', 'HLS', 'HLS_SPEED', 'HLS_TIMING', 'AUTO_FSM', 'PY_TO_LOGIC', 'C_TO_LOGIC', 'SYN'}:
            raise AssertionError('native UNSHARE imported ' + fullname)
sys.meta_path.insert(0, NoCompiler())
ns = runpy.run_path(sys.argv[1], run_name='native_gate')
ns['test_native']()
"""
    subprocess.run([sys.executable, "-c", code, os.path.abspath(__file__)], check=True)


def test_timing_dependencies():
    from types import SimpleNamespace
    from HLS_TIMING import TimingModel
    import HLS

    parser = SimpleNamespace(FuncLogicLookupTable={"add": SimpleNamespace(inputs=["a", "b"])})
    model = TimingModel(parser, {"add": ({"a": 3., "b": 3.}, ["test snapshot"])})
    def node(a, b):
        return {"kind": "binop", "op": {"kind": "binop", "op": "+"}, "entity": "add", "out_type": "uint8_t",
                "port_types": ["uint8_t", "uint8_t"], "operands": [a, b], "casts": [[], []], "delay_du": 3}
    dag = {"nodes": {"a": node(["in", "x"], ["in", "y"]),
                     "b": node(["in", "z"], ["in", "w"]),
                     "c": node(["node", "a"], ["node", "b"])},
           "output": ["node", "c"], "out_type": "uint8_t", "output_casts": []}
    assert model.report(dag)["delay"] == 6  # max of parallel paths, not 9
    dag["nodes"]["b"]["operands"][0] = ["node", "a"]
    assert model.report(dag)["delay"] == 9  # repeated entities on a serial path
    model.snapshot["add"] = ({"a": 2.}, ["unused port b"])
    assert model.report(dag)["delay"] == 4  # b does not feed this output
    dag["nodes"]["a"]["operands"][0] = ["node", "c"]
    try:
        HLS.order(dag)
    except ValueError:
        pass
    else:
        raise AssertionError("cycle accepted")


def test_cases():
    import PY_TO_LOGIC
    import SYN
    from pypeline import sim_call, sim_reset

    cases = [
        ("uint8_t", "x:uint8_t=a+b\ny:uint8_t=x+c\nz:uint8_t=y+d\nreturn z", "balanced unsigned +"),
        ("uint8_t", "x:uint8_t=a^b\ny:uint8_t=x^c\nz:uint8_t=y^d\nreturn z", "balanced unsigned ^"),
        ("uint8_t", "x:uint8_t=b+c\ny:uint8_t=a*x\nreturn y", "distributive expansion"),
        ("uint8_t", "x:uint8_t=b|c\ny:uint8_t=a&x\nreturn y", "distributive expansion"),
        ("uint16_t", "x:uint4_t=b+c\ny:uint16_t=a*x\nreturn y", None),
        ("uint16_t", "x:int8_t=a\ny:int16_t=x\nz:uint16_t=y+b\nreturn z", None),
        ("uint8_t", "x:uint8_t=a if sel else b\ny:uint8_t=c if sel else d\nreturn x+y", None),
    ]
    rng = random.Random(73)
    for return_t, body, expected_family in cases:
        root = tempfile.mkdtemp(prefix="acu_case_")
        filename = os.path.join(root, "design.py")
        source = ("from pypeline import *\n@hw_func\ndef core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->" + return_t + ":\n"
                  + textwrap.indent(body, "    ")
                  + "\nACU=AUTO_COMB_UNSHARE(core)\n@MAIN(1.0)\ndef top(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->" + return_t + ":\n    return ACU(a,b,c,d,sel)\n")
        with open(filename, "w") as f:
            f.write(source)
        SYN.SYN_OUTPUT_DIRECTORY = os.path.join(root, "build")
        parser = PY_TO_LOGIC.PARSE_FILE(filename)
        seen = set()
        for entries in parser.pypeline_comb_unshare_candidates.values():
            for candidate, info in entries[1:]:
                seen.update(info["moves"])
                for _ in range(120):
                    args = [rng.randrange(256) for _ in range(4)] + [rng.randrange(2)]
                    sim_reset()
                    expected = sim_call(entries[0][0], *args)
                    sim_reset()
                    assert sim_call(candidate, *args) == expected, (body, info["moves"], args)
        if expected_family:
            assert expected_family in seen, (expected_family, seen)
        first = next(iter(parser.pypeline_comb_unshare_reports.values()))
        again = PY_TO_LOGIC.PARSE_FILE(filename)
        assert next(iter(again.pypeline_comb_unshare_reports.values())) == first


def test_nested_and_pure():
    import PY_TO_LOGIC
    import SYN

    root = tempfile.mkdtemp(prefix="acu_nested_")
    SYN.SYN_OUTPUT_DIRECTORY = os.path.join(root, "build")
    filename = os.path.join(root, "design.py")
    for body in ("return a+b", "r:Reg[uint8_t]\n    r=a\n    return r"):
        source = ("from pypeline import *\n@hw_func\ndef core(a:uint8_t,b:uint8_t)->uint8_t:\n    " + body
            + "\nONE=AUTO_COMB_UNSHARE(AUTO_COMB_SHARE(core))\nTWO=AUTO_COMB_SHARE(AUTO_COMB_UNSHARE(core))\n"
              "@MAIN(1.0)\ndef top(a:uint8_t,b:uint8_t)->uint8_t:\n    return ONE(a,b)^TWO(a,b)\n")
        with open(filename, "w") as f:
            f.write(source)
        if "Reg" in body:
            try:
                PY_TO_LOGIC.PARSE_FILE(filename)
            except Exception as e:
                assert "pure" in str(e), str(e)
            else:
                raise AssertionError("stateful UNSHARE accepted")
        else:
            parser = PY_TO_LOGIC.PARSE_FILE(filename)
            assert len(parser.pypeline_comb_share_reports) == 2
            assert len(parser.pypeline_comb_unshare_reports) == 2


def test_elaboration():
    import PY_TO_LOGIC
    import SYN
    from pypeline import sim_call, sim_reset

    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="acu_test_")
    parser = PY_TO_LOGIC.PARSE_FILE(__file__)
    report = next(iter(parser.pypeline_comb_unshare_reports.values()))
    assert report["delay"] < report["delay_before"], report
    assert report["timing_is_estimate"]
    assert report["timing_provenance"]
    assert report["critical_path"]
    assert report["objective"] == "delay"
    rng = random.Random(919)
    for entries in parser.pypeline_comb_unshare_candidates.values():
        original = entries[0][0]
        for candidate, info in entries[1:]:
            for _ in range(200):
                args = [rng.randrange(256) for _ in range(4)] + [rng.randrange(2)]
                sim_reset()
                expected = sim_call(original, *args)
                sim_reset()
                actual = sim_call(candidate, *args)
                assert actual == expected, (info["moves"], args, actual, expected)
    return parser


if __name__ == "__main__":
    test_native()
    test_native_without_optimizer()
    test_elaboration()
    test_timing_dependencies()
    test_cases()
    test_nested_and_pure()
    print("All AUTO_COMB_UNSHARE tests passed.")
