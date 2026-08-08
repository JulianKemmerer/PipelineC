# pyright: reportInvalidTypeForm=none
"""Regression test for the pypeline_sim.py _discover_wire_names two-hop recursion
gap: the top design here only imports wire_discovery_dataflow (a pure cross-module
wiring file with zero Wire[T] of its own), which in turn imports
wire_discovery_leaf_a/_b (which DO declare Wire[T]). Pre-fix, _discover_wire_names's
_scan only recursed into a submodule if that submodule itself already carried a
Wire/Input/Output annotation -- so wire_discovery_leaf_a/_b's struct-typed wires were
never discovered, and reading them returned a bare int 0 instead of a zeroed pair_t,
crashing on first field access (AttributeError: 'int' object has no attribute 'a').
This exact shape is what wireguard-fpga's *_dataflow.py files hit -- deliberately do
NOT import wire_discovery_leaf_a/_b directly here, only the pass-through module.

Run: pypeline_sim.py wire_discovery_passthrough_sim_test.py --run N
 or: pypelinec wire_discovery_passthrough_sim_test.py --sim --run N
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

import wire_discovery_dataflow  # noqa: F401
