#!/usr/bin/env python3
"""`vivado -version` parsing (VIVADO.PARSE_VIVADO_VERSION). No Vivado run.

Real bug: the version was compared as float(VIVADO_VERSION) < 2022.2, which
raised ValueError on every update release ("v2023.2.2" is not a float), so
any Vivado build on such an install crashed generating its TCL.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import C_TO_LOGIC  # Establish PipelineC's normal module-import order.
import VIVADO

# Real 2019.2 output (local install); the others swap in update-release /
# newer first lines as Vivado prints them.
VIVADO_2019_2 = """Vivado v2019.2 (64-bit)
SW Build 2708876 on Wed Nov  6 21:39:14 MST 2019
IP Build 2700528 on Thu Nov  7 00:09:20 MST 2019
Copyright 1986-2019 Xilinx, Inc. All Rights Reserved.
"""


def _with_first_line(first_line):
    return first_line + "\n" + VIVADO_2019_2.split("\n", 1)[1]


def test_parses_two_and_three_part_versions():
    assert VIVADO.PARSE_VIVADO_VERSION(VIVADO_2019_2) == (2019, 2)
    assert VIVADO.PARSE_VIVADO_VERSION(
        _with_first_line("Vivado v2023.2.2 (64-bit)")
    ) == (2023, 2, 2)
    assert VIVADO.PARSE_VIVADO_VERSION(
        _with_first_line("vivado v2025.1 (64-bit)")
    ) == (2025, 1)
    assert VIVADO.PARSE_VIVADO_VERSION("no version here") is None


def test_fixed_pkg_cutoff_compares_as_a_version_not_a_float():
    cutoff = VIVADO.NATIVE_FIXED_PKG_VERSION
    assert (2019, 2) < cutoff
    assert (2022, 1, 1) < cutoff
    assert not (2022, 2) < cutoff
    assert not (2022, 2, 1) < cutoff
    assert not (2023, 2, 2) < cutoff
    # As floats, 2022.10 < 2022.2; as a version it is later.
    assert not (2022, 10) < cutoff


if __name__ == "__main__":
    test_parses_two_and_three_part_versions()
    test_fixed_pkg_cutoff_compares_as_a_version_not_a_float()
    print("All Vivado version unit tests passed.")
