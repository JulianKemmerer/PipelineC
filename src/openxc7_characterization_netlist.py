#!/usr/bin/env python3
"""Prepare a synthesized OpenXC7 characterization netlist for nextpnr.

PipelineC's isolated timing harness deliberately wraps logic in input/output
registers. Those synthetic harness ports are useful to Yosys, but they are not
physical FPGA I/O. nextpnr-xilinx otherwise turns every top-level port into a
package PAD, which makes characterization depend on package pin count and can
auto-place ports onto unbonded/nonexistent I/O BELs.

After Yosys has mapped the harness with ``synth_xilinx -noiopad``, remove the
top-level port declarations only. The mapped boundary registers, combinational
logic, clock net, and their connections remain intact for register-to-register
timing analysis.
"""

import json
import sys


def strip_top_ports(json_path, top_entity_name):
    with open(json_path, "r") as f:
        design = json.load(f)
    try:
        module = design["modules"][top_entity_name]
    except KeyError as exc:
        raise RuntimeError(
            f"Yosys JSON is missing top module {top_entity_name!r}"
        ) from exc

    module["ports"] = {}

    with open(json_path, "w") as f:
        json.dump(design, f)
        f.write("\n")


def main(argv):
    if len(argv) != 3:
        raise SystemExit(
            "usage: openxc7_characterization_netlist.py YOSYS_JSON TOP_ENTITY"
        )
    strip_top_ports(argv[1], argv[2])


if __name__ == "__main__":
    main(sys.argv)
