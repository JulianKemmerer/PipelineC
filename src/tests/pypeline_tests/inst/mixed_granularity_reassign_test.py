# pyright: reportInvalidTypeForm=none
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

from pypeline import MAIN, hw_func, uint1_t

import pypeline_tests


def point2d_zero():
    # Plain-Python compound-init helper (not @hw_func) -- mirrors wireguard-fpga's
    # axis128_null()/chacha20_loop_body_stream_null()/etc.
    return pypeline_tests.point2d_t(dim=[0, 0])


# Regression test for a silent miscompile: self.env kept stale finer-grained entries
# after a coarser write, so a later scalar read (here, the implicit false-branch of a
# nested `if` with no `else`) could return a wire that predates a whole-aggregate
# reassignment instead of the correct, more recent value. See
# docs/PY_TO_LOGIC_DESIGN.md "Alias Tracking -- Assignments Over Time" and
# _invalidate_descendant_env in PY_TO_LOGIC.py.
#
# Shape, mirroring wireguard-fpga's prep_auth_data_fsm/chacha20_fsm:
#   1. p = point2d_zero()   -- compound-init default: writes ONLY leaves p.dim[0], p.dim[1]
#   2. p = other            -- whole-aggregate reassign: bare-Name RHS -> ONE _write_ref(("p",),...)
#   3. if ~keep0: p.dim[0] = 0   -- nested if, no else: the implicit false branch must read
#      back other.dim[0] (the value just assigned in step 2), NOT the step-1 default.
#
# Neither sim_call (Layer 1 -- never touches PY_TO_LOGIC's AST elaborator) nor a plain
# "elaboration succeeds" check (no ElaborationError either way) can see this bug -- it's
# a silent wrong-wire bug in Logic() bookkeeping, so it's checked in-process via
# PY_TO_LOGIC.PARSE_FILE + direct Logic() inspection, same as two_factory_wrappers_test.py.


@hw_func
def mixed_granularity_reassign(
    other: pypeline_tests.point2d_t, keep0: uint1_t
) -> pypeline_tests.point2d_t:
    p: pypeline_tests.point2d_t
    p = point2d_zero()
    p = other
    if ~keep0:
        p.dim[0] = 0
    return p


@MAIN
def mixed_granularity_reassign_main(
    other: pypeline_tests.point2d_t, keep0: uint1_t
) -> pypeline_tests.point2d_t:
    # PARSE_FILE requires at least one @MAIN entry point; this just instantiates the
    # @hw_func under test so FuncLogicLookupTable/submodule_instances get populated.
    return mixed_granularity_reassign(other, keep0)


def test_mixed_granularity_reassign_uses_fresh_value():
    import tempfile
    import C_TO_LOGIC
    import PY_TO_LOGIC
    import SYN

    # See two_factory_wrappers_test.py: PARSE_FILE's _build_inst_lookup walk of
    # C-built-in submodule instances needs SYN.SYN_OUTPUT_DIRECTORY set -- normally done
    # by the pypelinec CLI wrapper before calling PARSE_FILE; replicate it here since
    # this test calls PARSE_FILE directly.
    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(
        prefix="mixed_granularity_reassign_test_"
    )

    parser_state = PY_TO_LOGIC.PARSE_FILE(os.path.abspath(__file__))
    logic = parser_state.FuncLogicLookupTable["mixed_granularity_reassign"]

    p_aliases = logic.wire_aliases_over_time["p"]
    leaf_ref_toks = ("p", "dim", 0)

    # The stale wire: the compound-init default's alias for p.dim[0] (written first,
    # before "p = other" superseded it). If the bug is present, this exact wire gets
    # returned again as the nested if's false-branch value.
    default_aliases = [
        a for a in p_aliases if logic.alias_to_driven_ref_toks.get(a) == leaf_ref_toks
    ]
    assert default_aliases, (
        "expected a leaf alias for p.dim[0] from the compound-init default "
        f"-- got aliases {p_aliases} with ref_toks "
        f"{[logic.alias_to_driven_ref_toks.get(a) for a in p_aliases]}"
    )
    default_alias = default_aliases[0]

    # Find the MUX instance emitted for `if ~keep0: p.dim[0] = 0` -- its tag embeds
    # "_if_" + the alias prefix for ("p","dim",0), i.e. "p_dim_0" (PY_TO_LOGIC.py's
    # _elab_if: mux_tag = f"{mux_func}_if_{key}").
    mux_insts = [
        inst
        for inst, func_name in logic.submodule_instances.items()
        if func_name.startswith("MUX_") and "_if_p_dim_0" in inst
    ]
    assert (
        len(mux_insts) == 1
    ), f"expected exactly one MUX instance for p.dim[0]'s if-statement, found {mux_insts}"
    mux_inst = mux_insts[0]

    iffalse_port_wire = f"{mux_inst}{C_TO_LOGIC.SUBMODULE_MARKER}iffalse"
    false_wire = logic.wire_driven_by[iffalse_port_wire]

    assert false_wire != default_alias, (
        "nested if's false-branch value for p.dim[0] is wired directly to the stale "
        "compound-init-default alias -- it should instead be a fresh CONST_REF_RD "
        "extraction from 'other' (the value assigned by 'p = other'), reflecting the "
        "whole-aggregate reassignment that happened after the default. "
        f"default_alias={default_alias!r} false_wire={false_wire!r}"
    )
    print("test_mixed_granularity_reassign_uses_fresh_value PASS")


if __name__ == "__main__":
    test_mixed_granularity_reassign_uses_fresh_value()
    print("All mixed_granularity_reassign tests passed.")
