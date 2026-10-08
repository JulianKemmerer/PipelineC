# pyright: reportInvalidTypeForm=none
"""Design modules chosen by module-level `if`/`try` imports.

A design can pick its building blocks while it is being imported:

    if sharing["poly1305"]:
        import poly1305_mcp_shared

Python runs only the chosen branch. Native sim scans live module objects, so it
always saw the chosen module's wires; hardware discovery (_process_imports) used
to scan only each file's top-level statements, so the chosen module's wires,
functions and @MAINs were never registered (KeyError / "Unknown reference base"
at elaboration). Discovery now also walks module-level if/try/with/for/while
blocks, and takes a nested import only when the module's live binding proves
that statement ran.

Untaken branches must stay out of the hardware even when their module is already
loaded for some other reason: every untaken module here declares a wire nothing
writes, so discovering it by mistake fails the "written by at least 1 function"
check. And a @MAIN whose module ran but was never discovered (imported only
inside a function) now raises instead of silently vanishing from the hardware.

Design modules are written to a temp dir under unique names. Each PARSE_FILE
re-executes them (sys.modules eviction), so the env vars set before a parse
select the branch.
"""
import importlib
import itertools
import os
import subprocess
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "../../../")
sys.path.insert(0, SRC)

import PY_TO_LOGIC as py  # noqa: E402
import pypeline  # noqa: E402
import SYN  # noqa: E402

TMP = tempfile.mkdtemp(prefix="conditional_import_")
sys.path.insert(0, TMP)
SYN.SYN_OUTPUT_DIRECTORY = os.path.join(TMP, "syn_out")
_counter = itertools.count()

HEADER = """\
# pyright: reportInvalidTypeForm=none
from pypeline import MAIN, Wire, hw_func, param, uint8_t
"""


def _write(name, body):
    path = os.path.join(TMP, f"{name}.py")
    with open(path, "w") as fh:
        fh.write(HEADER + textwrap.dedent(body))
    importlib.invalidate_caches()
    return path


def _fresh(prefix):
    return f"{prefix}_{next(_counter)}"


def _selectable(prefix):
    """A self-contained choice: its own MAIN drives the wire read_value reads."""
    name = _fresh(prefix)
    _write(
        name,
        """
        value: Wire[uint8_t]

        @MAIN
        def drive(x: uint8_t):
            value = x

        @hw_func
        def read_value() -> uint8_t:
            return value
        """,
    )
    return name


def _untaken(prefix):
    """A module no branch may select. Nothing writes `orphan`, so discovering
    this module fails PARSE_FILE's at-least-one-writer check."""
    name = _fresh(prefix)
    _write(
        name,
        """
        orphan: Wire[uint8_t]

        @hw_func
        def read_value() -> uint8_t:
            return orphan
        """,
    )
    return name


def _parse(path, **params):
    """PARSE_FILE with these -D design parameters installed."""
    pypeline.SET_DESIGN_PARAMS(params)
    try:
        return py.PARSE_FILE(path)
    finally:
        pypeline.SET_DESIGN_PARAMS({})


def _prefixes(state):
    return set(state.file_to_module_prefix.values())


def _assert_selected(state, chosen, others, how):
    assert f"{chosen}_value" in state.global_vars, (how, sorted(state.global_vars))
    assert f"{chosen}_drive" in state.main_mhz, (how, sorted(state.main_mhz))
    assert f"{chosen}_read_value" in state.FuncLogicLookupTable, how
    for other in others:
        leaked = [
            n
            for n in list(state.global_vars) + list(state.FuncLogicLookupTable)
            if n.startswith(other + "_")
        ]
        assert not leaked, (how, other, leaked)
        assert other not in _prefixes(state), (how, other)


# Loaded before the first PARSE_FILE of this process, so the parses' sys.modules
# eviction never removes it: "already in sys.modules" while its branch is untaken.
PRELOADED_UNTAKEN = _untaken("cond_preloaded")
importlib.import_module(PRELOADED_UNTAKEN)


def test_minimal_conditional_import():
    """The handoff's minimal repro: a module-qualified wire write and function
    call through a module imported inside an `if`, plus its unconditional
    control. Both elaboration entry points and the pypelinec CLI."""
    leaf = _fresh("cond_leaf")
    _write(
        leaf,
        """
        sig: Wire[uint8_t]

        @hw_func
        def read_sig() -> uint8_t:
            return sig
        """,
    )
    body = """
        @MAIN
        def top(x: uint8_t) -> uint8_t:
            {leaf}.sig = x
            return {leaf}.read_sig()
    """
    tops = {}
    for how, imports in (
        (
            "conditional",
            f"if param('COND_IMPORT_LEAF', True):\n    import {leaf}\n",
        ),
        ("unconditional", f"import {leaf}\n"),
    ):
        top = _fresh(f"cond_min_{how}")
        tops[how] = _write(top, imports + textwrap.dedent(body.format(leaf=leaf)))
        state = py.PARSE_FILE(tops[how])
        assert f"{leaf}_sig" in state.global_vars, (how, sorted(state.global_vars))
        assert f"{leaf}_read_sig" in state.FuncLogicLookupTable, how
        top_logic = state.FuncLogicLookupTable["top"]
        assert f"{leaf}_sig" in top_logic.write_only_global_wires, how
        assert state.module_alias_to_actual.get(leaf) == leaf, how

    # Branch not taken: the module name is simply unbound, which is an
    # ElaborationError naming it (it was a raw KeyError from _write_ref).
    try:
        _parse(tops["conditional"], COND_IMPORT_LEAF="0")
    except py.ElaborationError as err:
        assert f"Unknown reference base '{leaf}'" in str(err), str(err)
    else:
        raise AssertionError("an unbound module-qualified wire write elaborated")

    # ELABORATE_LIVE_ROOTS (native-sim pipeline alignment) runs the same discovery.
    top_mod = importlib.import_module(os.path.basename(tops["conditional"])[:-3])
    state = py.ELABORATE_LIVE_ROOTS([top_mod.top])
    assert f"{leaf}_sig" in state.global_vars, sorted(state.global_vars)

    # The pypelinec CLI: freezes design sources, then PARSE_FILE.
    out_dir = os.path.join(TMP, "cli_out")
    result = subprocess.run(
        [
            sys.executable,
            os.path.join(SRC, "pypelinec"),
            tops["conditional"],
            "--no_synth",
            "--out_dir",
            out_dir,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-3000:]
    print("test_minimal_conditional_import PASS")


def test_if_else_alias_picks_the_chosen_module():
    """`if: import A as impl / else: import B as impl` -- same wire and function
    names in both -- registers only the chosen module, under its own prefix."""
    a, b = _selectable("cond_alias_a"), _selectable("cond_alias_b")
    top = _write(
        _fresh("cond_alias_top"),
        f"""
        if param("COND_IMPORT_SEL") == "a":
            import {a} as impl
        else:
            import {b} as impl

        @MAIN
        def top() -> uint8_t:
            return impl.read_value()
        """,
    )
    for sel, chosen, other in (("a", a, b), ("b", b, a), ("a", a, b)):
        state = _parse(top, COND_IMPORT_SEL=sel)
        _assert_selected(state, chosen, [other], f"alias sel={sel}")
        assert state.module_alias_to_actual["impl"] == chosen, sel
        callees = set(state.FuncLogicLookupTable["top"].submodule_instances.values())
        assert f"{chosen}_read_value" in callees, (sel, callees)
    print("test_if_else_alias_picks_the_chosen_module PASS")


def test_elif_try_and_from_imports():
    """elif chains, an except handler that ran, and conditional from-imports."""
    a, b = _selectable("cond_from_a"), _selectable("cond_from_b")
    fallback = _selectable("cond_fallback")
    top = _write(
        _fresh("cond_from_top"),
        f"""
        SEL = param("COND_IMPORT_SEL")
        if SEL == "a":
            from {a} import read_value
        elif SEL == "b":
            from {b} import read_value
        else:
            raise ValueError(SEL)
        try:
            import cond_import_no_such_module
        except ImportError:
            import {fallback} as fb

        @MAIN
        def top() -> uint8_t:
            return read_value() + fb.read_value()
        """,
    )
    for sel, chosen, other in (("a", a, b), ("b", b, a)):
        state = _parse(top, COND_IMPORT_SEL=sel)
        _assert_selected(state, chosen, [other], f"from sel={sel}")
        assert f"{fallback}_drive" in state.main_mhz, sel
        assert state.module_alias_to_actual["fb"] == fallback, sel
    print("test_elif_try_and_from_imports PASS")


def test_selected_callable_passed_to_factory():
    """The WireGuard shape: the chosen module's function is passed into a factory
    in another module, and the closure calls it. The callee reads its own
    module's wire by bare name, which needs that module discovered."""
    a, b = _selectable("cond_fn_a"), _selectable("cond_fn_b")
    factory = _fresh("cond_factory")
    _write(
        factory,
        """
        def make_wrapper(func):
            @hw_func
            def wrapper() -> uint8_t:
                return func()

            return wrapper
        """,
    )
    top = _write(
        _fresh("cond_fn_top"),
        f"""
        from {factory} import make_wrapper

        if param("COND_IMPORT_SEL") == "a":
            import {a}
            chosen = {a}.read_value
        else:
            import {b}
            chosen = {b}.read_value
        wrapper = make_wrapper(chosen)

        @MAIN
        def top() -> uint8_t:
            return wrapper()
        """,
    )
    for sel, chosen, other in (("a", a, b), ("b", b, a)):
        state = _parse(top, COND_IMPORT_SEL=sel)
        _assert_selected(state, chosen, [other], f"factory sel={sel}")
        callers = [
            name
            for name, logic in state.FuncLogicLookupTable.items()
            if f"{chosen}_read_value" in logic.submodule_instances.values()
        ]
        assert any(name != "top" for name in callers), (sel, callers)
    print("test_selected_callable_passed_to_factory PASS")


def _diamond():
    """Two direction modules each pick a shared resource (with its own MAIN and
    a CAPACITY-sized wire) or a private one; the top imports both directions."""
    shared = _fresh("cond_shared")
    _write(
        shared,
        """
        CAPACITY = param("COND_IMPORT_CAPACITY", type=int)

        enc_req: Wire[uint8_t]
        dec_req: Wire[uint8_t]
        slots: Wire[uint8_t[CAPACITY]]

        @hw_func
        def submit_enc(x: uint8_t) -> uint8_t:
            enc_req = x
            return slots[0]

        @hw_func
        def submit_dec(x: uint8_t) -> uint8_t:
            dec_req = x
            return slots[CAPACITY - 1]

        @MAIN
        def arbiter():
            s: uint8_t[CAPACITY]
            for i in range(CAPACITY):
                s[i] = enc_req ^ dec_req
            slots = s
        """,
    )
    privates, mids = {}, {}
    for direction in ("enc", "dec"):
        privates[direction] = _fresh(f"cond_private_{direction}")
        _write(
            privates[direction],
            """
            req: Wire[uint8_t]

            @hw_func
            def submit(x: uint8_t) -> uint8_t:
                req = x
                return x
            """,
        )
        mids[direction] = _fresh(f"cond_mid_{direction}")
        _write(
            mids[direction],
            f"""
            if param("COND_IMPORT_SHARE", False):
                import {shared}
                submit = {shared}.submit_{direction}
            else:
                import {privates[direction]}
                submit = {privates[direction]}.submit

            @MAIN
            def {direction}(x: uint8_t) -> uint8_t:
                return submit(x)
            """,
        )
    top = _write(
        _fresh("cond_diamond_top"),
        f"""
        import {mids["enc"]}
        import {mids["dec"]}
        """,
    )
    return top, shared, privates, mids


def test_diamond_shared_resource_and_reparse():
    """One shared module reached from both directions is discovered once, under
    its own prefix, with one copy of its MAIN; unselected private modules stay
    out. A re-parse after the capacity changes (what the pin-and-confirm loop
    does when a latency changes a lane count) rediscovers the new sizes."""
    top, shared, privates, mids = _diamond()
    mains_by_capacity = {}
    for capacity in (2, 5):
        state = _parse(top, COND_IMPORT_SHARE="1", COND_IMPORT_CAPACITY=str(capacity))
        how = f"shared capacity={capacity}"
        for wire in ("enc_req", "dec_req", "slots"):
            assert f"{shared}_{wire}" in state.global_vars, (how, wire)
        slots_type = state.global_vars[f"{shared}_slots"].type_name
        assert slots_type.endswith(f"[{capacity}]"), (how, slots_type)
        assert f"{shared}_arbiter" in state.main_mhz, (how, sorted(state.main_mhz))
        assert list(state.file_to_module_prefix.values()).count(shared) == 1, how
        for direction in ("enc", "dec"):
            callee = f"{shared}_submit_{direction}"
            assert len(state.FuncToInstances.get(callee, ())) == 1, (how, callee)
            assert privates[direction] not in _prefixes(state), (how, direction)
        mains_by_capacity[capacity] = sorted(state.main_mhz)
    assert mains_by_capacity[2] == mains_by_capacity[5], mains_by_capacity

    state = _parse(top, COND_IMPORT_SHARE="0")
    assert shared not in _prefixes(state)
    assert not [n for n in state.global_vars if n.startswith(shared)], sorted(
        state.global_vars
    )
    for direction in ("enc", "dec"):
        assert f"{privates[direction]}_req" in state.global_vars, direction
    print("test_diamond_shared_resource_and_reparse PASS")


def test_untaken_branch_excluded_even_if_loaded():
    """Untaken imports of modules that ARE in sys.modules -- one loaded before
    any parse, one loaded by the design itself under another name -- are not
    discovered. Includes an untaken from-import that also names a shared
    object (uint8_t), which alone must not count as proof."""
    chosen = _selectable("cond_taken")
    design_loaded = _untaken("cond_design_loaded")
    top = _write(
        _fresh("cond_untaken_top"),
        f"""
        import importlib

        _side_loaded = importlib.import_module("{design_loaded}")

        if param("COND_IMPORT_SEL") == "a":
            import {chosen} as impl
            from {chosen} import read_value
        else:
            import {PRELOADED_UNTAKEN} as impl
            from {PRELOADED_UNTAKEN} import read_value, uint8_t
            import {design_loaded}
            from {design_loaded} import read_value as other_read

        @MAIN
        def top() -> uint8_t:
            return impl.read_value() + read_value()
        """,
    )
    assert PRELOADED_UNTAKEN in sys.modules
    state = _parse(top, COND_IMPORT_SEL="a")
    assert design_loaded in sys.modules
    _assert_selected(state, chosen, [PRELOADED_UNTAKEN, design_loaded], "untaken")
    print("test_untaken_branch_excluded_even_if_loaded PASS")


def test_main_in_undiscovered_module_fails_loud():
    """A module imported only inside a function body runs (its @MAIN registers,
    and native sim would run it) but is not discovered. PARSE_FILE must say so
    rather than leave that MAIN out of the hardware."""
    lonely = _fresh("cond_lonely")
    _write(
        lonely,
        """
        @MAIN
        def lonely_main(x: uint8_t) -> uint8_t:
            return x
        """,
    )
    top = _write(
        _fresh("cond_lonely_top"),
        f"""
        def _load():
            import {lonely}

        _load()

        @MAIN
        def top(x: uint8_t) -> uint8_t:
            return x
        """,
    )
    try:
        py.PARSE_FILE(top)
    except py.ElaborationError as err:
        msg = str(err)
        assert "lonely_main" in msg and lonely in msg, msg
    else:
        raise AssertionError("PARSE_FILE dropped a registered @MAIN silently")
    print("test_main_in_undiscovered_module_fails_loud PASS")


if __name__ == "__main__":
    test_minimal_conditional_import()
    test_if_else_alias_picks_the_chosen_module()
    test_elif_try_and_from_imports()
    test_selected_callable_passed_to_factory()
    test_diamond_shared_resource_and_reparse()
    test_untaken_branch_excluded_even_if_loaded()
    test_main_in_undiscovered_module_fails_loud()
    print("All conditional_import tests passed.")
