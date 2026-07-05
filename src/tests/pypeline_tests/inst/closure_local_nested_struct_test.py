# pyright: reportInvalidTypeForm=none
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from typing import NamedTuple

from pypeline import MAIN, hw_func, struct, uint1_t

# Regression test for _elaborate_live_func's struct/enum registration
# fallback (PY_TO_LOGIC.py, inside _elaborate_live_func): it used to build
# each struct's field-type dict by hand with bare str(a) instead of
# _inner_ctype_to_str(a), and never recursed into nested struct-typed
# fields. For a struct-typed field, str(a) invokes type.__repr__, producing
# a "<class '...'>"-shaped string instead of the field's canonical VHDL
# type name.
#
# thing_outer_t/thing_inner_t below are defined *inside* make_thing (never
# bound at module level anywhere), so _discover_structs_from_module can
# never see them regardless of how this file itself is reached -- the only
# way either type can end up in parser_state.struct_to_field_type_dict is
# via _elaborate_live_func's own struct-registration loop, triggered when
# `thing` (the closure that captures thing_outer_t) is elaborated on demand.
# thing_inner_t itself is never directly bound as a name in thing's own
# closure/globals -- it's only reachable by recursing into thing_outer_t's
# own field annotations, mirroring the actual wireguard-fpga bug
# (poly1305_mac_loop_body_in_t's r/a fields, typed u320_t, only reachable by
# recursing into a struct that itself was directly in scope).


def make_thing():
    @struct
    class thing_inner_t(NamedTuple):
        a: uint1_t
        b: uint1_t

    @struct
    class thing_outer_t(NamedTuple):
        inner: thing_inner_t
        flag: uint1_t

    @hw_func
    def thing(x: uint1_t) -> uint1_t:
        # Deliberately a struct-constructor-call compound init, not an
        # annotated declaration (`v: thing_outer_t`) -- an annotated local
        # var declaration resolves its type via _annotation_to_ctype's
        # eval_ns path, which already correctly (and recursively) registers
        # the struct regardless of this test, masking the bug this test is
        # meant to catch. A plain `v = thing_outer_t(...)` compound-init
        # assignment instead resolves its type via a getattr on the callee's
        # own _pypeline_ctype_name (PY_TO_LOGIC.py's compound-init handling)
        # without registering anything -- so this is the one construction
        # that puts thing_outer_t/thing_inner_t into thing's closure (by
        # referencing them by name) while leaving the closure-scan loop in
        # _elaborate_live_func as the *only* thing that can ever register
        # them.
        v = thing_outer_t(inner=thing_inner_t(a=x, b=~x), flag=x)
        return v.flag

    return thing


thing = make_thing()


@MAIN
def main(x: uint1_t) -> uint1_t:
    return thing(x)


def test_closure_local_nested_struct_registration():
    import inspect
    import tempfile

    import PY_TO_LOGIC
    import SYN

    # PARSE_FILE walks C-built-in submodule instances via _build_inst_lookup,
    # which needs SYN.SYN_OUTPUT_DIRECTORY set -- normally done by the
    # pipelinec CLI wrapper before it calls PARSE_FILE; replicate that here
    # since this test calls PARSE_FILE directly.
    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(
        prefix="closure_local_nested_struct_test_"
    )

    # Recover thing_outer_t/thing_inner_t via thing's own closure cells --
    # deliberately not bound at module level anywhere, since that would give
    # _discover_structs_from_module a *second*, unrelated path to register
    # them and defeat the point of this test. thing is @hw_func-wrapped
    # (_sim_type_wrap), so unwrap it first to get back the original function
    # whose __code__/__closure__ actually reference thing_outer_t -- same
    # thing _elaborate_live_func itself does via inspect.unwrap().
    thing_orig = inspect.unwrap(thing)
    idx = thing_orig.__code__.co_freevars.index("thing_outer_t")
    thing_outer_t = thing_orig.__closure__[idx].cell_contents
    thing_inner_t = thing_outer_t.__annotations__["inner"]

    parser_state = PY_TO_LOGIC.PARSE_FILE(os.path.abspath(__file__))

    outer_name = thing_outer_t._pypeline_ctype_name
    inner_name = thing_inner_t._pypeline_ctype_name

    fields = parser_state.struct_to_field_type_dict.get(outer_name)
    assert fields is not None, (
        f"{outer_name!r} (a factory-local struct, never bound at module "
        f"level) never got registered in struct_to_field_type_dict"
    )
    assert fields["inner"] == inner_name, (
        f"thing_outer_t.inner should resolve to the canonical struct name "
        f"{inner_name!r}, got {fields['inner']!r} instead -- looks like a "
        f"raw str(class) repr fallback"
    )
    print("test_closure_local_nested_struct_registration PASS")


if __name__ == "__main__":
    test_closure_local_nested_struct_registration()
    print("All closure_local_nested_struct tests passed.")
