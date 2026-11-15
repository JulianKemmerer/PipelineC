#!/usr/bin/env python3
"""The design diagram page (src/diagram/viewer.html) renders in a real
browser: headless Chrome loads pages written for four designs and

- test_every_view_draws: the #selftest route draws the design view, every
  file's view, and each function with a graph three times (default filters,
  everything shown, everything hidden), checking what each must and must not
  draw (DIAGRAM_DESIGN.md#self-test); it marks <body> data-ready (data-error on
  any failed check or exception);
- test_design_view_draws_blocks: the default route draws blocks and no error;
- on diagram_interfaces_design.py's page, what its default views draw, as the
  self-test records it (blocks and wire names per view): a returned struct as
  an output per field, wires named as the code names them, sideband and
  feedback ports left out, feedback data left out, an operator implemented by
  a call inside a logic block, a global wire write taking only the fields it
  drives, labels putting one variable's fields on one line, and pins packed
  into one wire as one port.

Pages are written in-process (PARSE_FILE + DIAGRAM.WRITE_DIAGRAM, as a
--no_synth build) for built_hardware_top_design.py, multi_clock_design.py,
diagram_interfaces_design.py (Feedback edges of each interface role, operators
in logic blocks, a @wires call site, sideband, returned structs, a Wire of an
interface, packed pins) and the C example examples/shared_globals.c. Needs
google-chrome.
"""

import json

import functools
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import C_TO_LOGIC
import DIAGRAM
import PY_TO_LOGIC
import SYN

INST_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(INST_DIR, "../../../.."))
INTERFACES = os.path.join(INST_DIR, "diagram_interfaces_design.py")
DESIGNS = (
    os.path.join(INST_DIR, "built_hardware_top_design.py"),
    os.path.join(INST_DIR, "multi_clock_design.py"),
    INTERFACES,
    os.path.join(REPO_ROOT, "examples", "shared_globals.c"),
)


@functools.lru_cache(maxsize=None)
def _pages():
    pages = []
    for design in DESIGNS:
        SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="diagram_render_")
        if design.endswith(".c"):
            C_TO_LOGIC.MULT_STYLE = C_TO_LOGIC.MULT_STYLE_INFERRED  # --mult default
            state = C_TO_LOGIC.PARSE_FILE(design)
        else:
            state = PY_TO_LOGIC.PARSE_FILE(design)
        pages.append(DIAGRAM.WRITE_DIAGRAM(state, None, design))
    return pages


@functools.lru_cache(maxsize=None)
def _dom(page, route):
    """The page's DOM after headless Chrome loaded it at #route."""
    run = subprocess.run(
        [
            "google-chrome",
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--user-data-dir=" + tempfile.mkdtemp(prefix="diagram_chrome_"),
            "--dump-dom",
            "file://" + page + "#" + route,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        universal_newlines=True,
        timeout=300,
    )
    assert run.returncode == 0, f"chrome exited {run.returncode}"
    return run.stdout


def test_every_view_draws():
    for page in _pages():
        dom = _dom(page, "selftest")
        body = dom[dom.index("<body") : dom.index('<div id="app">')]  # its attributes
        assert "data-error" not in body, (page, body)
        ready = re.search(r'data-ready="(\d+)"', body)
        assert ready and int(ready.group(1)) >= 3, (page, body)


def _drawn(view):
    """{blocks, wires} that the self-test recorded for one default view of
    diagram_interfaces_design.py's page ("design" or a function)."""
    page = _pages()[DESIGNS.index(INTERFACES)]
    dom = _dom(page, "selftest")
    found = re.search(r'<script type="application/json" id="drawn">(.*?)</script>', dom, re.S)
    assert found, "no recorded views"
    return json.loads(found.group(1))[view]


def test_returned_struct_draws_an_output_per_field():
    blocks = _drawn("pair_main")["blocks"]
    assert "first" in blocks and "second" in blocks, blocks
    assert "return_output" not in blocks, blocks


def test_wires_are_named_as_the_code_names_them():
    # o.first = bump(p.second); o.second = p.first, with p = make_pair(x)
    wires = set(_drawn("pair_main")["wires"])
    assert {"x", "p.second", "o.first", "p.first"} <= wires, wires
    # return make_pair(x): no variable, so named by both ends
    wires = set(_drawn("pass_main")["wires"])
    assert wires == {"x", "make_pair.first → first", "make_pair.second → second"}, wires


def test_sideband_and_feedback_ports_are_left_out():
    # gain beside the streams in and out; out_port_if is the feedback half
    assert "gain" not in _drawn("side_main")["blocks"], _drawn("side_main")
    blocks = _drawn("loop_main")["blocks"]
    assert "axis_in_if" in blocks and "out_port_if" in blocks, blocks
    # the forward input and output only, not the feedback halves
    assert blocks.count("out_port_if") == 1 and blocks.count("axis_in_if") == 1, blocks


def test_feedback_data_is_left_out():
    for view in ("link_tx_main", "link_rx_main"):
        wires = _drawn(view)["wires"]
        assert not [w for w in wires if "ready" in w], (view, wires)
    # link_rx_main only writes ready: its write stub goes with it
    assert _drawn("link_rx_main")["blocks"].count("link") == 1, _drawn("link_rx_main")
    assert not [w for w in _drawn("design")["wires"] if "ready" in w], _drawn("design")


def test_global_wire_writes_take_only_the_fields_they_drive():
    # pair_tx_main writes pair_link.first and reads pair_link.second: the
    # elaborated write passes second through from the read, which is no wire
    edges = _drawn("pair_tx_main")["edges"]
    assert ["pair_link", "pair_link"] not in edges, edges
    assert ["x", "pair_link"] in edges and ["pair_link", "return_output"] in edges, edges


def test_labels_put_one_variables_fields_on_one_line():
    # add_pair(p.first, p.second): one edge, two fields of p
    view = _drawn("sum_main")
    labels = dict(zip(map(tuple, view["edges"]), view["labels"]))
    assert labels[("make_pair", "add_pair")] == ["p: first, second"], labels


def test_operator_calls_join_logic_blocks():
    blocks = _drawn("side_main")["blocks"]
    assert "soft_cmp_prefix" not in blocks, blocks  # gain > 100
    assert any(">" in b for b in blocks), blocks


def test_pins_packed_into_one_wire_draw_as_one_port():
    blocks = _drawn("design")["blocks"]
    assert "rx_stream" in blocks and "tx_stream" in blocks, blocks
    # rx_key is sideband beside them
    assert not {"rx_data", "rx_valid", "rx_key", "tx_data"} & set(blocks), blocks


def test_design_view_draws_blocks():
    for page in _pages():
        dom = _dom(page, "design")
        assert 'class="n ' in dom, page
        info = re.search(r'<div id="info">(.*?)</div>', dom, re.S).group(1)
        assert not info.strip(), (page, info)  # where a view's error is shown


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
