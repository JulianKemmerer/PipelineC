#!/usr/bin/env python3
# In-process regression test: PY_TO_LOGIC.PARSE_FILE called twice in one
# process (the pypelinec driver's AUTO_PIPELINE pin-and-confirm loop does
# exactly this) must behave like two fresh parses.
#
# Guards two once-latent bugs:
#  1. sys.modules staleness: a second exec_module only re-runs the TOP design
#     file; imported sub-files stayed cached, so their @MAIN registrations
#     vanished (registry is cleared per parse). PARSE_FILE now evicts every
#     module imported as a consequence of executing a design.
#  2. Trim-memo staleness: TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE's func-name-keyed
#     done-memo made the second parse skip trimming its freshly rebuilt Logic,
#     leaking normally-pruned dead logic (built-in ops' unused clock-enable
#     branch muxes, whose generated wire names GHDL rejects) into VHDL.
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import tempfile

import C_TO_LOGIC
import PY_TO_LOGIC
import SYN

SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="double_parse_file_test_")

INST_DIR = os.path.dirname(os.path.abspath(__file__))


def parse_twice_and_compare(design_path):
    ps1 = PY_TO_LOGIC.PARSE_FILE(design_path)
    mains1 = sorted(ps1.main_mhz)
    funcs1 = {
        name: len(logic.wires) for name, logic in ps1.FuncLogicLookupTable.items()
    }

    ps2 = PY_TO_LOGIC.PARSE_FILE(design_path)
    mains2 = sorted(ps2.main_mhz)
    funcs2 = {
        name: len(logic.wires) for name, logic in ps2.FuncLogicLookupTable.items()
    }

    assert mains1 == mains2, (
        f"{os.path.basename(design_path)}: @MAIN set changed on re-parse "
        f"(sys.modules staleness): {mains1} vs {mains2}"
    )
    # Canonical func names must be a pure function of the design source --
    # identical across re-executions (no repr-address-derived hashes). The
    # pin-and-confirm loop matches funcs across passes by these names.
    assert set(funcs1) == set(funcs2), (
        f"{os.path.basename(design_path)}: canonical func-name set changed "
        f"on re-parse:\n  only in parse1: {sorted(set(funcs1) - set(funcs2))}"
        f"\n  only in parse2: {sorted(set(funcs2) - set(funcs1))}"
    )
    # Same-named funcs must have identically-sized logic on both parses --
    # in particular the second parse's rebuilt built-ins must be trimmed the
    # same way the first parse's were (trim-memo staleness).
    for name in funcs1:
        assert funcs1[name] == funcs2[name], (
            f"{os.path.basename(design_path)}: {name} wire count changed on "
            f"re-parse ({funcs1[name]} -> {funcs2[name]}): second parse's "
            f"Logic was built/trimmed differently"
        )
    # No parse may leave untrimmed clock-enable branch-mux wires behind
    # (their generated names contain '__' which GHDL rejects as identifiers)
    for tag, ps in (("parse1", ps1), ("parse2", ps2)):
        for name, logic in ps.FuncLogicLookupTable.items():
            bad = [w for w in logic.wires if "CLOCK_ENABLE__" in w]
            assert not bad, f"{tag}: {name} has untrimmed CE-mux wires: {bad[:3]}"
    return ps1, ps2


def test_multi_file_design_reparses():
    # import_test.py imports design sub-files ('import file_a' style) whose
    # @MAINs must survive a re-parse
    parse_twice_and_compare(os.path.join(INST_DIR, "import_test.py"))


def test_stream_auto_pipeline_design_reparses():
    # Exercises AUTO_PIPELINE tagging + built-in C ops (the trim-memo repro)
    parse_twice_and_compare(os.path.join(INST_DIR, "stream_auto_pipeline_test.py"))


def test_fir_design_reparses():
    # Deep factory-closure chains (make_fir -> make_fir_core -> resize
    # callables etc.) whose canonical names come from the derived-closure-var
    # hash branches -- the repr-address instability repro.
    parse_twice_and_compare(os.path.join(INST_DIR, "fir_sweep_test.py"))


def test_auto_fsm_design_reparses():
    # AUTO_FSM tagging: the driver's schedule-and-confirm loop re-parses the
    # design between passes, and AUTO_FSM leans hard on that being reproducible
    # -- the generated FSM's entity name is a hash of the schedule, whose node
    # ids come from source coordinates. Any re-parse instability here would
    # rename the entity every pass and break cross-pass matching.
    parse_twice_and_compare(os.path.join(INST_DIR, "auto_fsm_test.py"))


def test_var_ref_naming_design_reparses():
    # Two sequential runtime variable-index writes to the same array -- the
    # second write's covering wire is the first write's own alias, whose
    # ref_toks contains a Python AST node. In-process repro for the
    # entity-name instability bug: str(ast_node) embeds a repr memory
    # address, so VAR_REF_ASSIGN/VAR_REF_RD/CONST_REF_RD func names built
    # from covering_ref_toks_list changed on every re-parse -- found via
    # wireguard-fpga's --continue builds re-synthesizing instead of reusing
    # existing logs despite an unchanged design. ps1 stays alive while ps2
    # parses, so parse 2's AST nodes cannot land on parse 1's addresses --
    # the fastest way to catch this without a real subprocess rebuild.
    parse_twice_and_compare(os.path.join(INST_DIR, "var_ref_naming_design.py"))


def test_design_source_is_frozen_across_reparses():
    # pypelinec re-parses the design in later AUTO_PIPELINE passes, possibly
    # hours later. Edits to design files in the meantime must not reach those
    # passes: re-imports, AST reads and inspect.getsource keep the first-read
    # bytes, and source_provenance.json records the drift. The compiler's own
    # modules, stdlib and generated output-directory source are not frozen.
    # A subprocess keeps the import hook out of this test process.
    import subprocess

    code = r"""
import inspect, json, os, pathlib, sys
import PY_TO_LOGIC, SYN
temp = pathlib.Path(sys.argv[1])
out = temp / "out"
SYN.SYN_OUTPUT_DIRECTORY = str(out)
helper = temp / "freeze_helper.py"
helper.write_text("from pypeline import hw_func, uint8_t\n\n@hw_func\ndef helper(x: uint8_t) -> uint8_t:\n    return x + 1\n")
design = temp / "freeze_design.py"
design.write_text("from pypeline import MAIN, uint8_t\nfrom freeze_helper import helper\n\n@MAIN\ndef freeze_main(x: uint8_t) -> uint8_t:\n    return helper(x)\n")
os.chdir(temp)
PY_TO_LOGIC.FREEZE_DESIGN_SOURCES(str(out))
first = set(PY_TO_LOGIC.PARSE_FILE("freeze_design.py").FuncLogicLookupTable)
helper.write_text(helper.read_text().replace("x + 1", "x * x"))
design.write_text(design.read_text() + "\n# edited\n")
second = set(PY_TO_LOGIC.PARSE_FILE("freeze_design.py").FuncLogicLookupTable)
assert first == second, (sorted(first ^ second))
assert not any("MULT" in f for f in second), sorted(second)
assert "x + 1" in inspect.getsource(sys.modules["freeze_helper"].helper)
assert "# edited" not in PY_TO_LOGIC.READ_SOURCE_TEXT("freeze_design.py")
import linecache
linecache.checkcache()  # inspect.getsource on the top design file reads this
assert not any("# edited" in line for line in linecache.getlines(str(design)))
assert not PY_TO_LOGIC._is_frozen_source(os.path.abspath(PY_TO_LOGIC.__file__))
for packages in ("site-packages", "dist-packages"):
    assert not PY_TO_LOGIC._is_frozen_source(str(temp / packages / "m.py"))
assert PY_TO_LOGIC._is_frozen_source(str(temp / "lib" / "m.py"))
generated = out / "generated.py"
generated.write_text("x = 1")
PY_TO_LOGIC.READ_SOURCE_TEXT(str(generated))
generated.write_text("x = 2")
assert PY_TO_LOGIC.READ_SOURCE_TEXT(str(generated)) == "x = 2"
PY_TO_LOGIC.WRITE_SOURCE_PROVENANCE()
sources = json.loads((out / "source_provenance.json").read_text())["sources"]
assert sources[str(helper)]["disk_drift"] and sources[str(design)]["disk_drift"]
assert any("/include/pypeline/" in p for p in sources), sorted(sources)
assert not any(os.path.dirname(p) == os.path.dirname(PY_TO_LOGIC.__file__) for p in sources)
assert json.__file__ not in sources and str(generated) not in sources
import sysconfig
stdlib = tuple(os.path.abspath(sysconfig.get_paths()[k]) + os.sep for k in ("stdlib", "platstdlib"))
assert not any(p.startswith(stdlib) for p in sources), sorted(sources)
assert not (out / "source_snapshot").exists()
print("FROZEN OK")
"""
    with tempfile.TemporaryDirectory(prefix="design_source_freeze_") as temp:
        result = subprocess.run(
            [sys.executable, "-c", code, temp],
            env=dict(os.environ, PYTHONPATH=os.path.join(INST_DIR, "../../../")),
            capture_output=True,
            text=True,
        )
    assert result.returncode == 0 and "FROZEN OK" in result.stdout, (
        result.stdout[-2000:] + result.stderr[-3000:]
    )


if __name__ == "__main__":
    test_multi_file_design_reparses()
    test_stream_auto_pipeline_design_reparses()
    test_fir_design_reparses()
    test_auto_fsm_design_reparses()
    test_var_ref_naming_design_reparses()
    test_design_source_is_frozen_across_reparses()
    print("All double PARSE_FILE tests passed.")
