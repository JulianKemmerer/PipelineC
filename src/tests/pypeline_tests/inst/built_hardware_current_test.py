#!/usr/bin/env python3
"""Up-to-date builds (SIM.BUILD_INPUTS, SIM.BUILT_HARDWARE_IS_CURRENT), in-process,
on records written the way WRITE_BUILT_HARDWARE writes them:

- test_identical_inputs_are_up_to_date;
- test_each_input_makes_the_build_run: the design source, -D values, a build
  setting, a setting new since the record, a --latency_hints file's contents,
  the compiler, a compiler environment knob, and a record with no build inputs
  (an older compiler's) each make the run build, naming what changed;
- test_operational_settings_are_not_inputs: -j, --out_dir, --syn_cache,
  --syn_cache_prune, simulation-only settings, -D order and other environment
  variables keep the build up to date;
- test_only_a_plain_build_of_the_recorded_top_can_be_up_to_date: --sim,
  --rebuild, another top and a C top;
- test_declared_file_is_an_input: a file declared with pypeline.depends_on
  joins PY_TO_LOGIC.DESIGN_SOURCE_HASHES, and editing it makes the build run;
- test_file_changed_between_imports_keeps_first_contents: a later
  declaration that finds other contents warns once and keeps the first hash,
  so the next build runs.
"""

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
from types import SimpleNamespace

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(THIS_DIR, "..", "..", ".."))

import PY_TO_LOGIC
import SIM
import SYN
import pypeline

DESIGN = """
from pypeline import MAIN, uint16_t
from pypeline import Input, make_reset, uint1_t
rst: Input[uint1_t] = make_reset()  # every register resets; pulsed in cycle 0

@MAIN(30.0, reset=rst, reset_registers="all")
def top(x: uint16_t, y: uint16_t) -> uint16_t:
    return x - y
"""


def make_args(**overrides):
    """The pypelinec settings these tests vary, as argparse leaves them."""
    settings = dict(
        src_file="design.py",
        out_dir="out",
        define=["A=1", "B"],
        latency_hints=[],
        pins=None,
        pipeline_min_effort=2,
        syn_tool="pyrtl",
        part=None,
        comb=False,
        no_synth=False,
        jobs=None,
        syn_cache=None,
        syn_cache_prune=None,
        rebuild=False,
        sim=False,
        sim_comb=False,
        run=10,
        cocotb=False,
        ghdl=False,
    )
    settings.update(overrides)
    return SimpleNamespace(**settings)


def write_record(design, args, declared=None):
    """A built_hardware.json for a build of design with args, as
    WRITE_BUILT_HARDWARE writes it (the fields the up-to-date check reads).
    declared: {path: sha256} of files the design declared (depends_on)."""
    with open(design, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    record = dict(
        version=SIM.BUILT_HARDWARE_VERSION,
        top=os.path.abspath(design),
        sources={os.path.abspath(design): sha, **(declared or {})},
        build_inputs=SIM.BUILD_INPUTS(args, design),
    )
    path = os.path.join(SYN.SYN_OUTPUT_DIRECTORY, SIM.BUILT_HARDWARE_FILE)
    with open(path, "w") as f:
        json.dump(record, f)
    return path


def is_current(design, args):
    """BUILT_HARDWARE_IS_CURRENT's verdict for a run of design with args, and
    what it printed."""
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        verdict = SIM.BUILT_HARDWARE_IS_CURRENT(SIM.BUILD_INPUTS(args, design), args)
    return verdict, printed.getvalue()


@contextlib.contextmanager
def built(tmp, args=None):
    """A design built in an output directory under tmp with args; yields the
    design's path."""
    design = os.path.join(tmp, "design.py")
    with open(design, "w") as f:
        f.write(DESIGN)
    SYN.SYN_OUTPUT_DIRECTORY = os.path.join(tmp, "out")
    os.makedirs(SYN.SYN_OUTPUT_DIRECTORY, exist_ok=True)
    write_record(design, args or make_args())
    yield design


def expect_build(design, args, reason):
    verdict, printed = is_current(design, args)
    assert not verdict, f"up to date despite {reason}"
    assert f"Building again: {reason} changed since the build in" in printed, printed


def test_identical_inputs_are_up_to_date():
    with tempfile.TemporaryDirectory() as tmp, built(tmp) as design:
        verdict, printed = is_current(design, make_args())
        assert verdict, printed
        assert printed.startswith("Up to date: "), printed
    print("test_identical_inputs_are_up_to_date PASS")


def test_each_input_makes_the_build_run():
    with tempfile.TemporaryDirectory() as tmp, built(tmp) as design:
        with open(design, "a") as f:
            f.write("# edited after the build\n")
        expect_build(design, make_args(), os.path.abspath(design))
    with tempfile.TemporaryDirectory() as tmp, built(tmp) as design:
        expect_build(design, make_args(define=["A=2", "B"]), "the -D values")
        expect_build(design, make_args(define=["A=1"]), "the -D values")
        expect_build(
            design,
            make_args(pipeline_min_effort=0),
            "the --pipeline_min_effort setting",
        )
        # A setting the record does not know counts too
        expect_build(design, make_args(new_setting=True), "the --new_setting setting")
        saved = SYN._COMPILER_SOURCE_HASH
        SYN._COMPILER_SOURCE_HASH = "another compiler"
        try:
            expect_build(
                design, make_args(), "the compiler's sources (src/, include/pypeline/)"
            )
        finally:
            SYN._COMPILER_SOURCE_HASH = saved
        os.environ["PIPELINEC_BUILT_HARDWARE_CURRENT_TEST"] = "1"
        try:
            expect_build(
                design,
                make_args(),
                "the environment variable PIPELINEC_BUILT_HARDWARE_CURRENT_TEST",
            )
        finally:
            del os.environ["PIPELINEC_BUILT_HARDWARE_CURRENT_TEST"]
    with tempfile.TemporaryDirectory() as tmp:
        hints = os.path.join(tmp, "hints.json")
        with open(hints, "w") as f:
            json.dump({"AUTO_PIPELINE": {"body": 3}}, f)
        args = make_args(latency_hints=[hints])
        with built(tmp, args) as design:
            assert is_current(design, args)[0]
            with open(hints, "w") as f:
                json.dump({"AUTO_PIPELINE": {"body": 4}}, f)
            expect_build(design, args, "the --latency_hints setting")
    with tempfile.TemporaryDirectory() as tmp, built(tmp) as design:
        path = os.path.join(SYN.SYN_OUTPUT_DIRECTORY, SIM.BUILT_HARDWARE_FILE)
        with open(path) as f:
            record = json.load(f)
        del record["build_inputs"]
        with open(path, "w") as f:
            json.dump(record, f)
        expect_build(
            design, make_args(), "the compiler's sources (src/, include/pypeline/)"
        )
    print("test_each_input_makes_the_build_run PASS")


def test_operational_settings_are_not_inputs():
    with tempfile.TemporaryDirectory() as tmp, built(tmp) as design:
        for overrides in (
            dict(jobs=4),
            dict(out_dir="another_out"),
            dict(syn_cache="store"),
            dict(syn_cache_prune=30.0),
            dict(run=99, cocotb=True, ghdl=True),
            dict(wave="run.vcd", wave_signals=["*"]),
            dict(define=["B", "A=1", "A=1"]),
        ):
            verdict, printed = is_current(design, make_args(**overrides))
            assert verdict, f"{overrides} made the build run: {printed}"
        os.environ["BUILT_HARDWARE_CURRENT_TEST_OTHER"] = "1"
        try:
            assert is_current(design, make_args())[
                0
            ], "an unrelated environment variable"
        finally:
            del os.environ["BUILT_HARDWARE_CURRENT_TEST_OTHER"]
    print("test_operational_settings_are_not_inputs PASS")


def test_only_a_plain_build_of_the_recorded_top_can_be_up_to_date():
    with tempfile.TemporaryDirectory() as tmp, built(tmp) as design:
        for overrides in (dict(sim=True), dict(rebuild=True)):
            verdict, printed = is_current(design, make_args(**overrides))
            assert not verdict and not printed, overrides
        other = os.path.join(tmp, "other.py")
        with open(other, "w") as f:
            f.write(DESIGN)
        verdict, printed = is_current(other, make_args())
        assert not verdict and not printed, "another top"
        verdict, printed = is_current(os.path.join(tmp, "design.c"), make_args())
        assert not verdict and not printed, "a C top"
    print("test_only_a_plain_build_of_the_recorded_top_can_be_up_to_date PASS")


@contextlib.contextmanager
def declared_files():
    """A clean pypeline depends_on registry, restored afterwards."""
    saved = (dict(pypeline._declared_files), set(pypeline._declared_files_changed))
    pypeline._declared_files.clear()
    pypeline._declared_files_changed.clear()
    try:
        yield
    finally:
        pypeline._declared_files.clear()
        pypeline._declared_files.update(saved[0])
        pypeline._declared_files_changed.clear()
        pypeline._declared_files_changed.update(saved[1])


def test_declared_file_is_an_input():
    with tempfile.TemporaryDirectory() as tmp, declared_files():
        data = os.path.join(tmp, "words.txt")
        with open(data, "w") as f:
            f.write("1 2 3 4")
        assert pypeline.depends_on(data) == data, "depends_on returns its path"
        sha = hashlib.sha256(b"1 2 3 4").hexdigest()
        assert PY_TO_LOGIC.DESIGN_SOURCE_HASHES()[data] == sha
        design = os.path.join(tmp, "design.py")
        with open(design, "w") as f:
            f.write(DESIGN)
        SYN.SYN_OUTPUT_DIRECTORY = os.path.join(tmp, "out")
        os.makedirs(SYN.SYN_OUTPUT_DIRECTORY)
        write_record(design, make_args(), declared=PY_TO_LOGIC.DESIGN_SOURCE_HASHES())
        assert is_current(design, make_args())[0], "an unchanged declared file"
        with open(data, "w") as f:
            f.write("6 2 3 4")
        expect_build(design, make_args(), data)
    print("test_declared_file_is_an_input PASS")


def test_file_changed_between_imports_keeps_first_contents():
    with tempfile.TemporaryDirectory() as tmp, declared_files():
        data = os.path.join(tmp, "words.txt")
        with open(data, "w") as f:
            f.write("1 2 3 4")
        pypeline.depends_on(data)
        with open(data, "w") as f:
            f.write("6 2 3 4")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            pypeline.depends_on(data)
            pypeline.depends_on(data)
        assert printed.getvalue().count("WARNING: ") == 1, printed.getvalue()
        assert data in printed.getvalue()
        first = hashlib.sha256(b"1 2 3 4").hexdigest()
        assert pypeline.DECLARED_FILES()[data][0] == first
        changed = SIM._changed_sources(PY_TO_LOGIC.DESIGN_SOURCE_HASHES())
        assert changed == [data], changed
    print("test_file_changed_between_imports_keeps_first_contents PASS")


if __name__ == "__main__":
    test_identical_inputs_are_up_to_date()
    test_each_input_makes_the_build_run()
    test_operational_settings_are_not_inputs()
    test_only_a_plain_build_of_the_recorded_top_can_be_up_to_date()
    test_declared_file_is_an_input()
    test_file_changed_between_imports_keeps_first_contents()
