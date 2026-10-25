#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-clock build tests: wrapper scripts that build a design on two or
more clocks and check what came out -- its crossing report, its top level,
its constraints and timing results, its behavior in GHDL. sky130 and PyRTL
cannot time a design with more than one clock (their constraint writers
stop on one), so these build with open_tools (ECP5 nextpnr), Vivado, or no
synthesis tool at all. Each Test names the tool its builds may use
(Test.syn_tool), which run_all's tool check holds it to.

The in-process multi-clock checks (clock assignment, crossings, async FIFO
realization, sweep attribution) live in elab_introspect_tests.py and
unit_tests.py.

Run standalone: python3 multi_clock_tests.py [-j N]
"""

import sys

from common import INST_DIR, Test, main

CATEGORY = "multi_clock"


def get_tests() -> list:
    tests = []
    # The guide's Part IV design, --comb --no_synth, run in GHDL with a
    # two-clock testbench: bytes cross the built-in async FIFO in order and
    # the async flag rises; also its crossing report and top level. About
    # 20 s, no synthesis tool.
    tests.append(
        Test(
            name="multi_clock_ghdl_test",
            category=CATEGORY,
            cmd=[INST_DIR / "multi_clock_ghdl_test.py"],
            needs_out_dir=True,
            requires=["ghdl"],
        )
    )
    # ECP5 builds of the two-clock synth fixture: --comb (a PASS line per
    # clock), the Part IV design --comb (its pin clock ETH_RX_CLK, which
    # nextpnr reports by the pin's name, gets its PASS line), a sweep that
    # cuts crunch at 80 MHz but not the FIFO side MAINs, and an async FIFO
    # whose read clock misses 900 MHz inside the FIFO (TIMING NOT MET names
    # the FIFO). 50 s to 2 min.
    tests.append(
        Test(
            name="multi_clock_open_tools_test",
            category=CATEGORY,
            cmd=[INST_DIR / "multi_clock_open_tools_test.py"],
            needs_out_dir=True,
            syn_tool="open_tools",
        )
    )
    # Artix-7 --comb builds of the same fixture, xpm_fifo_async and the
    # built-in FIFO (FIFO_IMPL=builtin), run at once: async clock groups in
    # clocks.xdc and a PASS line per clock. About 2.5 min.
    tests.append(
        Test(
            name="multi_clock_vivado_test",
            category=CATEGORY,
            cmd=[INST_DIR / "multi_clock_vivado_test.py"],
            needs_out_dir=True,
            syn_tool="vivado",
        )
    )
    return tests


if __name__ == "__main__":
    sys.exit(main(get_tests, __doc__))
