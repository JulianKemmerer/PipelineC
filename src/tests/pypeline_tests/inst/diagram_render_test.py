#!/usr/bin/env python3
"""The design diagram page (src/diagram/viewer.html) renders in a real
browser: headless Chrome loads pages written for three designs and

- test_every_view_draws: the #selftest route draws the design view, every
  file's view and one view per function with a graph, and marks <body>
  data-ready (data-error on any exception);
- test_design_view_draws_blocks: the default route draws blocks and no error.

Pages are written in-process (PARSE_FILE + DIAGRAM.WRITE_DIAGRAM, as a
--no_synth build) for built_hardware_top_design.py, multi_clock_design.py and
the C example examples/shared_globals.c. Needs google-chrome.
"""

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
DESIGNS = (
    os.path.join(INST_DIR, "built_hardware_top_design.py"),
    os.path.join(INST_DIR, "multi_clock_design.py"),
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


def test_design_view_draws_blocks():
    for page in _pages():
        dom = _dom(page, "design")
        assert 'class="n ' in dom, page
        info = re.search(r'<div id="info">(.*?)</div>', dom, re.S).group(1)
        assert not info.strip(), (page, info)  # where a view's error is shown


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
