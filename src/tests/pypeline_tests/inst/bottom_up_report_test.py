#!/usr/bin/env python3
# pyright: reportInvalidTypeForm=none
"""In-process unit tests for the bottom-up value report (the pin-and-confirm
pass table and sweep_history.json "latency_passes"):
  - an AUTO_PIPELINE .latency read records the design line that read it; a
    read inside a library factory (make_stream_auto_pipeline sizing its FIFO)
    records the library line and the design line that called the factory;
  - AUTO_MULTI_CYCLE .latency and .ncycles reads record their sites too, and
    a read inside a hardware body (folded by the elaborator) records the
    body's own file and line;
  - AUTO_PIPELINE.RECORD_LATENCY_PASS rows hold read vs built, whether they
    match and the sites, and print one line per read value;
  - the documented sizing attributes (pypeline_guide.md, "Passing a bottom-up
    value to the rest of the design") exist with their documented values.
The re-elaborating build that writes the record into sweep_history.json is
design_params_build_test.py's pass-2 case."""
import contextlib
import io
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(THIS_DIR, "..", "..", ".."))
sys.path.insert(0, os.path.join(THIS_DIR, "..", "..", "..", "..", "include", "pypeline"))

import AUTO_PIPELINE as AUTO_PIPELINE_MODULE
import PY_TO_LOGIC  # noqa: F401  (canonical keys)
import pypeline
from pypeline import AUTO_MULTI_CYCLE, AUTO_PIPELINE, hw_func, uint8_t
from stream.skid_buffer import make_skid_buffer
from stream.stream_auto_pipeline import make_stream_auto_pipeline
from stream.stream_fifo import make_stream_fifo
from stream.stream_multi_cycle import make_stream_auto_multi_cycle
from stream.stream_ram import make_stream_ram

LIBRARY_FILE = os.path.abspath(
    os.path.join(THIS_DIR, "..", "..", "..", "..", "include", "pypeline", "stream", "stream_auto_pipeline.py")
)
MULTI_CYCLE_LIBRARY_FILE = os.path.join(os.path.dirname(LIBRARY_FILE), "stream_multi_cycle.py")


@hw_func
def plus_one(x: uint8_t) -> uint8_t:
    return x + 1


@hw_func
def plus_two(x: uint8_t) -> uint8_t:
    return x + 2


def _line_of(marker, path=__file__):
    with open(path) as f:
        for number, text in enumerate(f, 1):
            if marker in text and "_line_of(" not in text:
                return number
    raise AssertionError(marker)


def test_auto_pipeline_read_sites_and_pass_record():
    pypeline.SET_AUTO_PIPELINE_BUILD_MODE("sweep")
    pypeline.CLEAR_AUTO_PIPELINE_LATENCY_READ_FLAG()
    try:
        ap = AUTO_PIPELINE(plus_one, start_latency=2)
        assert ap.latency == 2  # DIRECT_READ
        sap, _ = make_stream_auto_pipeline(plus_two, start_latency=3)  # FACTORY_CALL
        sites = pypeline.AUTO_PIPELINE_READ_SITES()
        assert sites[ap.canonical_key] == [f"{__file__}:{_line_of('# DIRECT_READ')}"], sites
        (library_site,) = sites[sap.auto_pipeline.canonical_key]
        assert library_site.startswith(LIBRARY_FILE + ":"), library_site
        assert library_site.endswith(f"(via {__file__}:{_line_of('# FACTORY_CALL')})"), library_site

        AUTO_PIPELINE_MODULE.LATENCY_PASS_RECORDS.clear()
        built = {ap.canonical_key: 2, sap.auto_pipeline.canonical_key: 5}
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            AUTO_PIPELINE_MODULE.RECORD_LATENCY_PASS(1, built, {}, "re-elaborate (pass 2)")
        (record,) = AUTO_PIPELINE_MODULE.LATENCY_PASS_RECORDS
        assert record["pass"] == 1 and record["outcome"] == "re-elaborate (pass 2)"
        rows = {row["key"]: row for row in record["reads"]}
        direct, grown = rows[ap.canonical_key], rows[sap.auto_pipeline.canonical_key]
        assert (direct["read"], direct["built"], direct["matches"]) == ([2], 2, True)
        assert (grown["read"], grown["built"], grown["matches"]) == ([3], 5, False)
        assert grown["read_at"] == [library_site]
        text = printed.getvalue()
        assert "Bottom-up values read during pass 1 elaboration (read -> built):" in text
        assert f"AUTO_PIPELINE {sap.auto_pipeline.canonical_key}: 3 -> 5  <- differs" in text
        assert "  => re-elaborate (pass 2)" in text

        # Nothing read: nothing recorded
        pypeline.CLEAR_AUTO_PIPELINE_LATENCY_READ_FLAG()
        AUTO_PIPELINE_MODULE.RECORD_LATENCY_PASS(2, built, {}, "converged")
        assert len(AUTO_PIPELINE_MODULE.LATENCY_PASS_RECORDS) == 1
    finally:
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE(None)
        pypeline.CLEAR_AUTO_PIPELINE_LATENCY_READ_FLAG()
        AUTO_PIPELINE_MODULE.LATENCY_PASS_RECORDS.clear()


def test_auto_multi_cycle_read_sites():
    pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
    mc = AUTO_MULTI_CYCLE(start_latency=4)
    assert mc.latency == 4  # MC_LATENCY_READ
    assert mc.ncycles == 4  # MC_NCYCLES_READ
    sites = pypeline.AUTO_MULTI_CYCLE_READ_SITES()[mc.canonical_key]
    assert sites == [
        f"{__file__}:{_line_of('# MC_LATENCY_READ')}",
        f"{__file__}:{_line_of('# MC_NCYCLES_READ')}",
    ], sites
    pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
    assert pypeline.AUTO_MULTI_CYCLE_READ_SITES() == {}


def test_hardware_body_read_site():
    # The multi-cycle wrapper's handshake compares against MC.latency inside its
    # hardware body. Elaboration folds that read in code compiled under a pseudo
    # file name (<const_eval>); the site must still name the real file and line.
    PY_TO_LOGIC.PARSE_FILE(os.path.join(THIS_DIR, "stream_auto_multi_cycle_test.py"))
    sites = [site for read in pypeline.AUTO_MULTI_CYCLE_READ_SITES().values() for site in read]
    body_line = _line_of("== (MC.latency + 1)", MULTI_CYCLE_LIBRARY_FILE)
    assert f"{MULTI_CYCLE_LIBRARY_FILE}:{body_line}" in sites, sites
    assert not any("<" in site for site in sites), sites


def test_documented_sizing_attributes():
    # Outside a build: .latency reads the constructor value (0, or latency=)
    sap, _ = make_stream_auto_pipeline(plus_one)
    assert isinstance(sap.auto_pipeline, AUTO_PIPELINE)
    assert sap.auto_pipeline.latency == 0 and sap.max_in_flight == 0 + 5
    fixed, _ = make_stream_auto_pipeline(plus_two, latency=3)
    assert fixed.auto_pipeline.latency == 3 and fixed.max_in_flight == 3 + 5
    assert not hasattr(sap, "latency")  # valid/ready is not a fixed latency

    pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
    mcp, _ = make_stream_auto_multi_cycle(plus_one, start_latency=3)
    assert isinstance(mcp.mcp, AUTO_MULTI_CYCLE) and mcp.mcp.latency == 3

    fifo, _ = make_stream_fifo(uint8_t, 100)
    assert (fifo.depth, fifo.capacity_beats) == (100, 128 + 1)
    fifo, _ = make_stream_fifo(uint8_t, 64)
    assert (fifo.depth, fifo.capacity_beats) == (64, 64 + 1)

    skid, _ = make_skid_buffer(uint8_t)
    assert isinstance(skid.latency, int)
    ram, _ = make_stream_ram(uint8_t, 16)
    assert isinstance(ram.latency, int)


if __name__ == "__main__":
    test_auto_pipeline_read_sites_and_pass_record()
    test_auto_multi_cycle_read_sites()
    test_documented_sizing_attributes()
    test_hardware_body_read_site()
    print("All bottom-up report tests passed.")
