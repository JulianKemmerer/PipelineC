"""Combinational sharing API, generated graph, and semantic regressions."""
import os
import sys
import tempfile
import random
import textwrap

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
from pypeline import AUTO_COMB_SHARE, MAIN, hw_func, uint1_t, uint8_t, uint16_t


@hw_func
def select_product(a: uint8_t, b: uint8_t, c: uint8_t, d: uint8_t, sel: uint1_t) -> uint16_t:
    x: uint16_t = a * b
    y: uint16_t = c * d
    return x if sel else y


ACS = AUTO_COMB_SHARE(select_product)


@MAIN(5.0)
def top(a: uint8_t, b: uint8_t, c: uint8_t, d: uint8_t, sel: uint1_t) -> uint16_t:
    return ACS(a, b, c, d, sel)


def test_native():
    import pypeline

    assert ACS.latency == 0
    assert pypeline.hw_arg_types(ACS) == pypeline.hw_arg_types(select_product)
    assert pypeline.hw_return_type(ACS) == uint16_t
    for a in range(8):
        for b in range(8):
            for s in (0, 1):
                assert ACS(a, b, 7, 9, s) == (a * b if s else 63)
                assert ACS(a=a, b=b, c=7, d=9, sel=s) == select_product(a, b, 7, 9, s)
    assert AUTO_COMB_SHARE(ACS).func is select_product


def test_native_without_optimizer():
    import subprocess

    code = """
import importlib.abc, runpy, sys
class NoCompiler(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'AUTO_COMB_SHARE', 'HLS', 'AUTO_FSM', 'PY_TO_LOGIC', 'C_TO_LOGIC', 'SYN'}:
            raise AssertionError('native ACS imported ' + fullname)
sys.meta_path.insert(0, NoCompiler())
ns = runpy.run_path(sys.argv[1], run_name='native_gate')
ns['test_native']()
"""
    subprocess.run([sys.executable, "-c", code, os.path.abspath(__file__)], check=True)


def test_elaboration():
    import PY_TO_LOGIC
    import SYN
    from pypeline import sim_call

    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="acs_test_")
    parser = PY_TO_LOGIC.PARSE_FILE(__file__)
    reports = parser.pypeline_comb_share_reports
    assert len(reports) == 1, reports
    report = next(iter(reports.values()))
    assert report["area"] < report["area_before"], report
    generated = [(fn, info) for entries in parser.pypeline_comb_share_candidates.values()
                 for fn, info in entries if hasattr(fn, "_auto_comb_share_generated_src")]
    assert generated
    for fn, _ in generated:
        for a in range(16):
            for b in range(16):
                for s in (0, 1):
                    assert sim_call(fn, a, b, 7, 9, s) == (a * b if s else 63)


def _parse_case(body, return_t="uint8_t"):
    import PY_TO_LOGIC
    import SYN

    path = tempfile.mkdtemp(prefix="acs_case_")
    source = ("from pypeline import *\n" + textwrap.dedent(body)
              + f"\nACS = AUTO_COMB_SHARE(core)\n@MAIN(1.0)\ndef top(a: uint8_t, b: uint8_t, c: uint8_t, d: uint8_t, sel: uint1_t) -> {return_t}:\n    return ACS(a,b,c,d,sel)\n")
    filename = os.path.join(path, "design.py")
    with open(filename, "w") as f:
        f.write(source)
    SYN.SYN_OUTPUT_DIRECTORY = os.path.join(path, "build")
    parser = PY_TO_LOGIC.PARSE_FILE(filename)
    return parser, filename


def _check_candidates(parser, samples=80):
    from pypeline import sim_call, sim_reset

    rng = random.Random(73)
    for entries in parser.pypeline_comb_share_candidates.values():
        original = entries[0][0]
        for candidate, _ in entries[1:]:
            for sample in range(samples):
                args = [rng.randrange(256) for _ in range(4)] + [rng.randrange(2)]
                if sample < 16:
                    args[0] = sample % 4
                sim_reset()
                expected = sim_call(original, *args)
                sim_reset()
                actual = sim_call(candidate, *args)
                assert actual == expected, (candidate.__name__, args, actual, expected)


def test_arithmetic_and_casts():
    cases = [
        """
        @hw_func
        def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->uint16_t:
            byte:uint8_t = 255
            signed:int8_t = byte
            constant:uint16_t = signed
            product:uint16_t = a*constant
            return product
        """,
        """
        @hw_func
        def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->uint16_t:
            x:uint16_t = a*b
            y:uint16_t = a*c
            return x+y
        """,
        """
        @hw_func
        def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->uint16_t:
            x:uint8_t = a*b
            y:uint8_t = a*c
            u:uint16_t = x
            v:uint16_t = y
            return u+v
        """,
        """
        @hw_func
        def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->uint8_t:
            x:uint8_t = a*b
            y:uint8_t = c*d
            zero:uint8_t = 0
            u:uint8_t = x if a == 1 else zero
            v:uint8_t = y if a == 2 else zero
            return u + v
        """,
        """
        @hw_func
        def narrow_override(a:uint4_t,b:uint4_t)->uint8_t:
            return a ^ b
        register_operator("INFERRED_MULT", uint4_t, uint4_t, narrow_override)
        @hw_func
        def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->uint8_t:
            x:uint4_t = a
            y:uint4_t = b
            u:uint32_t = x
            v:uint32_t = y
            return u*v
        """,
        """
        @hw_func
        def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->uint8_t:
            x:uint8_t = a * b
            y:uint8_t = a * c
            return x + y
        """,
        """
        @hw_func
        def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->uint8_t:
            x:uint32_t = a
            y:uint32_t = b
            z:uint32_t = x * y
            return z
        """,
        """
        @hw_func
        def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->uint8_t:
            x:uint8_t = a * 31
            y:uint8_t = b / 8
            z:uint8_t = c % 16
            return x + y + z
        """,
        """
        @hw_func
        def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->uint8_t:
            x:int8_t = a
            y:int8_t = b
            z:int4_t = x + y
            w:int16_t = z
            return w * c if sel else w * d
        """,
        """
        @hw_func
        def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->uint8_t:
            x:uint16_t = a*b
            y:uint16_t = c*d
            selected:uint16_t = x if sel else y
            return selected + x
        """,
    ]
    for body in cases:
        parser, _ = _parse_case(body)
        _check_candidates(parser)


def test_scoped_operators_and_bounded_graph():
    import HLS

    predicates = {"nodes": {str(value): {
        "op": {"kind": "binop", "op": "=="}, "out_type": "uint1_t",
        "operands": [["in", "sel"], ["lit", value, "uint8_t"]],
        "casts": [[], []], "port_types": ["uint8_t", "uint8_t"],
    } for value in (1, 2)}}
    bdd = HLS.BDD()
    one = bdd.expression(predicates, ["node", "1"])
    two = bdd.expression(predicates, ["node", "2"])
    assert bdd.apply("and", one, two) == 0
    assert bdd.apply("and", one, one) != 0

    # A signed constant cast followed by widening must not be interpreted as
    # unsigned masking: uint16(int8(255)) is 65535, not 255.
    signed_predicate = {"nodes": {"eq": {
        "op": {"kind": "binop", "op": "=="}, "out_type": "uint1_t",
        "operands": [["in", "sel"], ["lit", 255, "uint8_t"]],
        "casts": [[], ["int8_t"]], "port_types": ["uint16_t", "uint16_t"],
    }}}
    bdd = HLS.BDD()
    predicate = bdd.expression(signed_predicate, ["node", "eq"])
    assert bdd.render(signed_predicate, predicate) == ["node", "eq"]

    parser, _ = _parse_case("""
        @hw_func
        def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->uint8_t:
            return a*b if sel else c*d
        register_operator("INFERRED_MULT", uint8_t, uint8_t, INFERRED, scope=core)
    """)
    report = next(iter(parser.pypeline_comb_share_reports.values()))
    assert "scoped" in report["unsupported"], report
    # Deep-but-legal wiring must not exhaust Python's recursion limit.
    graph = {"nodes": {}, "output": ["node", "4999"]}
    for i in range(5000):
        graph["nodes"][str(i)] = {"operands": [["node", str(i-1)]] if i else [["in", "x"]]}
    assert len(HLS.order(graph)) == 5000
    graph["nodes"]["0"]["operands"] = [["node", "4999"]]
    try:
        HLS.order(graph)
    except ValueError as error:
        assert "cycle" in str(error)
    else:
        raise AssertionError("cyclic graph accepted")


def test_shared_fsm_operand_keys_stay_dags():
    import AUTO_FSM

    class CountedNodes(dict):
        reads = 0

        def get(self, *args):
            self.reads += 1
            return super().get(*args)

    def key(prefix, leaf):
        nodes = CountedNodes()
        ref = ["in", leaf]
        for i in range(60):
            nid = prefix + str(i)
            nodes[nid] = {
                "delay_du": 0, "op": {"kind": "bitmanip", "builtin": "concat"},
                "out_type": "uint64_t", "port_types": ["uint64_t", "uint64_t"],
                "operands": [ref, ref], "casts": [[], []],
            }
            ref = ["node", nid]
        result = AUTO_FSM._value_equiv_key(nodes, ref, 1, {})
        assert nodes.reads < 4 * len(nodes), nodes.reads
        return result

    a, b, c = key("left_", "x"), key("right_", "x"), key("other_", "y")
    assert a == b and hash(a) == hash(b)
    assert len({a, b, c}) == 2
    # Cached hashes accelerate comparison; they never substitute for it.
    x = AUTO_FSM._GlueValueKey(("x",))
    y = AUTO_FSM._GlueValueKey(("y",))
    y._hash = x._hash
    assert x != y


def test_default_fsm_uses_shared_choices():
    import PY_TO_LOGIC
    import AUTO_FSM
    import SYN

    path = tempfile.mkdtemp(prefix="acs_fsm_")
    filename = os.path.join(path, "design.py")
    with open(filename, "w") as f:
        f.write(textwrap.dedent("""
            from pypeline import *
            @struct
            class inputs_t(NamedTuple):
                a:uint8_t
                b:uint8_t
                c:uint8_t
                d:uint8_t
                sel:uint1_t
            @hw_func
            def core(i:inputs_t)->uint16_t:
                return i.a*i.b if i.sel else i.c*i.d
            FSM = AUTO_FSM(core)
            @MAIN(1.0)
            def top(i:FSM.in_stream_t)->FSM.out_stream_t:
                return FSM(i)
        """))
    SYN.SYN_OUTPUT_DIRECTORY = os.path.join(path, "build")
    parser = PY_TO_LOGIC.PARSE_FILE(filename)
    key, tag = next(iter(parser.pypeline_auto_fsm_tags.items()))
    for logic in parser.FuncLogicLookupTable.values():
        logic.delay = 1  # deterministic unit-test timing; real timing is tested separately
    baseline = AUTO_FSM._SWEEP_MIN_AREA_SCHEDULE(parser, key, tag, 0.9)
    shared = AUTO_FSM.SWEEP_MIN_AREA_SCHEDULE(parser, key, tag, 0.9)
    assert shared.get("comb_share_candidates", 0) > 0, shared
    assert shared["est_area"] <= baseline["est_area"], (shared, baseline)


def test_purity_and_repeat_parse():
    import PY_TO_LOGIC

    parser, filename = _parse_case("""
        @hw_func
        def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->uint8_t:
            return a*b if sel else c*d
    """)
    second = PY_TO_LOGIC.PARSE_FILE(filename)
    assert parser.pypeline_comb_share_reports == second.pypeline_comb_share_reports
    try:
        _parse_case("""
            @hw_func
            def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->uint8_t:
                state:Reg[uint8_t]
                state = a
                return state
        """)
    except Exception as error:
        assert "pure combinational" in str(error), error
    else:
        raise AssertionError("stateful function accepted by ACS")
    try:
        _parse_case("""
            @pipeline_latency(1)
            @hw_func
            def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,sel:uint1_t)->uint8_t:
                return a+b
        """)
    except Exception as error:
        assert "pure combinational" in str(error), error
    else:
        raise AssertionError("fixed pipeline accepted by ACS")


if __name__ == "__main__":
    from _test_main import run_module_tests
    run_module_tests()
