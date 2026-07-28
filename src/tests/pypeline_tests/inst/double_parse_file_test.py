#!/usr/bin/env python3
# In-process regression test: PY_TO_LOGIC.PARSE_FILE called twice in one
# process (the pipelinec driver's AUTOPIPELINE pin-and-confirm loop does
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


def test_stream_pipeline_design_reparses():
    # Exercises AUTOPIPELINE tagging + built-in C ops (the trim-memo repro)
    parse_twice_and_compare(os.path.join(INST_DIR, "stream_pipeline_test.py"))


def test_fir_design_reparses():
    # Deep factory-closure chains (make_fir -> make_fir_core -> resize
    # callables etc.) whose canonical names come from the derived-closure-var
    # hash branches -- the repr-address instability repro.
    parse_twice_and_compare(os.path.join(INST_DIR, "fir_sweep_test.py"))


def test_autofsm_design_reparses():
    # AUTOFSM tagging: the driver's schedule-and-confirm loop re-parses the
    # design between passes, and AUTOFSM leans hard on that being reproducible
    # -- the generated FSM's entity name is a hash of the schedule, whose node
    # ids come from source coordinates. Any re-parse instability here would
    # rename the entity every pass and break cross-pass matching.
    parse_twice_and_compare(os.path.join(INST_DIR, "autofsm_test.py"))


if __name__ == "__main__":
    test_multi_file_design_reparses()
    test_stream_pipeline_design_reparses()
    test_fir_design_reparses()
    test_autofsm_design_reparses()
    print("All double PARSE_FILE tests passed.")
