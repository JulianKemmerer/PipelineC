#!/usr/bin/env python3
"""Known issue #413: the diagram draws diagram_feedback_pair_design.py's `top`
with all three blocks in one column.

`layout()` in src/diagram/viewer.html reverses the narrower edge of a two-way
pair, or at equal widths the one from the later node. That reverses the
forward edge stage_reg -> stage_b, while the Feedback edge stage_b -> stage_reg
also stays reversed, so the layering graph keeps a cycle and its blocks stay in
layer 0. This test writes the page in-process (as a --no_synth build), loads
the `top` view in headless Chrome and checks the blocks' columns left to right.
Needs google-chrome.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import DIAGRAM
import PY_TO_LOGIC
import SYN

INST_DIR = os.path.dirname(os.path.abspath(__file__))
DESIGN = os.path.join(INST_DIR, "diagram_feedback_pair_design.py")

# Appended after the viewer's script, which draws the view as it loads:
# records each drawn block's first line and left edge
REPORT = """<script>
const layoutOut = document.createElement("pre");
layoutOut.id = "layout";
layoutOut.textContent = JSON.stringify(state.last.nodes.map((n) => [n.lines[0], n.x]));
document.body.appendChild(layoutOut);
</script>
"""


def _block_x():
    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="diagram_feedback_pair_")
    page = DIAGRAM.WRITE_DIAGRAM(PY_TO_LOGIC.PARSE_FILE(DESIGN), None, DESIGN)
    with open(page) as f:
        text = f.read()
    end = text.rindex("</body>")
    with open(page, "w") as f:
        f.write(text[:end] + REPORT + text[end:])
    # Chrome runs with TMPDIR=/tmp and its profile there, removed afterwards:
    # it makes its singleton socket under TMPDIR, and under this test's long
    # per-test TMPDIR from the runner the socket path passes the 108-byte
    # limit of a Unix socket name and Chrome aborts.
    profile = tempfile.mkdtemp(prefix="dfp", dir="/tmp")
    try:
        run = subprocess.run(
            [
                "google-chrome",
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                "--user-data-dir=" + profile,
                "--dump-dom",
                "file://" + page + "#inst=top",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=300,
            env=dict(os.environ, TMPDIR="/tmp"),
        )
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    assert run.returncode == 0, f"chrome exited {run.returncode}"
    found = re.search(r'<pre id="layout">(.*?)</pre>', run.stdout, re.S)
    assert found, "the page drew no layout"
    return dict(json.loads(found.group(1).replace("&quot;", '"')))


def test_feedback_pair_keeps_columns():
    x = _block_x()
    assert x["stage_reg"] < x["stage_a"] < x["stage_b"], x


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
