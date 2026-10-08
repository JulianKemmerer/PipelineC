# pyright: reportInvalidTypeForm=none
"""Elaborated hierarchy of Karatsuba leaf policies (operators/soft_mult.py's
make_soft_mult_karatsuba leaf=, make_inferred_mult and
make_mult_karatsuba_inferred_leaves).

Checked via PY_TO_LOGIC.PARSE_FILE + FuncLogicLookupTable rather than values:
every leaf policy computes the right product, so a silently ignored leaf
override or a leaf that redispatched to another soft multiplier would pass
any numeric test. Native sim values are covered by soft_ops_test.py and
native/VHDL parity by self_check_mult_karatsuba_test.py.

Operator registrations are process-global, so each configuration in
soft_mult_karatsuba_leaves_design.py (-D CASE=...) is parsed in its own
subprocess (`python3 this_file.py --case <CASE>`).
"""
import collections
import os
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DESIGN = os.path.join(THIS_DIR, "soft_mult_karatsuba_leaves_design.py")
sys.path.insert(0, os.path.join(THIS_DIR, "..", "..", ".."))

INFERRED_PREFIX = "BIN_OP_INFERRED_MULT_"


def _instance_counts(parser_state, root):
    """Every func name instantiated under root, with multiplicity."""
    table = parser_state.FuncLogicLookupTable
    memo = {}

    def walk(func_name, stack):
        assert func_name not in stack, f"{func_name} instantiates itself: {stack}"
        if func_name in memo:
            return memo[func_name]
        counts = collections.Counter()
        logic = table.get(func_name)
        if logic is not None:
            for child in logic.submodule_instances.values():
                counts[child] += 1
                counts.update(walk(child, stack + (func_name,)))
        memo[func_name] = counts
        return counts

    return walk(root, ())


def _leaf_widths(counts):
    """Sorted operand-type pairs of the built-in multiplies under a root."""
    widths = []
    for name, n in counts.items():
        if name.startswith(INFERRED_PREFIX):
            widths += [name[len(INFERRED_PREFIX):]] * n
    return sorted(widths)


def _soft_leaves(counts):
    return sum(n for name, n in counts.items() if name.startswith("soft_mult_shift_add"))


def _karatsuba_entity(parser_state, root):
    names = [
        n for n in parser_state.FuncLogicLookupTable[root].submodule_instances.values()
        if "soft_mult_karatsuba" in n
    ]
    assert len(names) == 1, f"{root}: expected one top Karatsuba instance, got {names}"
    return names[0]


def _sq(*bits):
    return sorted(f"uint{b}_t_uint{b}_t" for b in bits)


def _check_global130(ps):
    counts = _instance_counts(ps, "plain_mult_main")
    # 130 -> 65/65/66 -> leaves 32,33,34 + 32,33,34 + 33,33,34.
    assert _leaf_widths(counts) == _sq(32, 32, 33, 33, 33, 33, 34, 34, 34), _leaf_widths(counts)
    assert _soft_leaves(counts) == 0
    assert not any("soft_add_tree" in n for n in counts), sorted(counts)
    karatsuba = [n for n in counts if "soft_mult_karatsuba" in n]
    assert len(karatsuba) == 3, f"130, 65 and 66-bit levels (65 shared): {karatsuba}"


def _check_direct(ps):
    hybrid64 = _instance_counts(ps, "hybrid64_main")
    assert _leaf_widths(hybrid64) == _sq(32, 32, 33), _leaf_widths(hybrid64)
    assert _soft_leaves(hybrid64) == 0

    # Unequal operands: n = 37 splits 18/19 with a 20-bit middle.
    unequal = _instance_counts(ps, "hybrid_37x20_main")
    assert _leaf_widths(unequal) == _sq(18, 19, 20), _leaf_widths(unequal)

    # Same width and threshold, different leaf: same split, different leaves.
    hybrid40 = _instance_counts(ps, "hybrid40_main")
    assert _leaf_widths(hybrid40) == _sq(10, 10, 10, 10, 10, 11, 11, 11, 12), _leaf_widths(hybrid40)
    assert _soft_leaves(hybrid40) == 0
    soft40 = _instance_counts(ps, "soft40_main")
    assert _leaf_widths(soft40) == [], _leaf_widths(soft40)
    assert _soft_leaves(soft40) == 9
    soft40_t24 = _instance_counts(ps, "soft40_t24_main")
    assert _soft_leaves(soft40_t24) == 3

    tops = {
        root: _karatsuba_entity(ps, root)
        for root in ("hybrid40_main", "soft40_main", "soft40_t24_main")
    }
    assert len(set(tops.values())) == 3, f"configurations aliased: {tops}"


def _check_exact_soft(ps):
    # A global soft multiplier plus an exact uint34 one at a leaf width: the
    # pinned leaves stay built-in multiplies regardless.
    counts = _instance_counts(ps, "exact_soft_main")
    assert _leaf_widths(counts) == _sq(32, 32, 33, 33, 33, 33, 34, 34, 34), _leaf_widths(counts)
    assert not any("soft_mult_carry_save" in n for n in counts), sorted(counts)


def _check_soft_default(ps):
    counts = _instance_counts(ps, "plain_mult_main")
    # Default threshold 16: 24 -> 12/12/13, shift-and-add leaves.
    assert _leaf_widths(counts) == [], _leaf_widths(counts)
    assert _soft_leaves(counts) == 3
    top = _karatsuba_entity(ps, "plain_mult_main")
    assert "threshold_16" in top and "make_soft_mult_shift_add" in top, top


CHECKS = {
    "global130": _check_global130,
    "direct": _check_direct,
    "exact_soft": _check_exact_soft,
    "soft_default": _check_soft_default,
}


def _run_case(case):
    import tempfile

    import pypeline
    import PY_TO_LOGIC
    import SYN

    pypeline.SET_DESIGN_PARAMS({"CASE": case})
    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix=f"karatsuba_leaves_{case}_")
    CHECKS[case](PY_TO_LOGIC.PARSE_FILE(DESIGN))
    print(f"case {case} passed")


def _spawn(case):
    result = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--case", case],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"case {case} failed:\n{result.stdout[-4000:]}\n{result.stderr[-4000:]}"
    )


def test_hybrid_registered_globally():
    _spawn("global130")


def test_direct_calls_and_distinct_configurations():
    _spawn("direct")


def test_leaves_ignore_exact_soft_registration():
    _spawn("exact_soft")


def test_default_soft_karatsuba_unchanged():
    _spawn("soft_default")


if __name__ == "__main__":
    if "--case" in sys.argv:
        _run_case(sys.argv[sys.argv.index("--case") + 1])
    else:
        from _test_main import run_module_tests

        run_module_tests()
