# pyright: reportInvalidTypeForm=none
"""Pure cross-module wiring, no Wire[T]/Input[T]/Output[T] of its own -- mirrors
wireguard-fpga's encrypt_dataflow.py shape that exposed the _discover_wire_names
two-hop recursion gap (regression test for that fix). One-directional connection
only (leaf_a -> leaf_b) so this has no combinational loop of its own."""

from pypeline import MAIN, sim_output

import wire_discovery_leaf_a
import wire_discovery_leaf_b


@sim_output
def sim_print(*args, **kwargs):
    print("SIM", *args, **kwargs)


@MAIN
def wire_discovery_dataflow():
    wire_discovery_leaf_b.leaf_b_in = wire_discovery_leaf_a.leaf_a_out
    sim_print(
        "leaf_a.leaf_a_out",
        wire_discovery_leaf_a.leaf_a_out,
        "leaf_b.leaf_b_out",
        wire_discovery_leaf_b.leaf_b_out,
    )
