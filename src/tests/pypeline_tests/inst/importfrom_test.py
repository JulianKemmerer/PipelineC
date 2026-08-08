# pyright: reportInvalidTypeForm=none
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

from pypeline import MAIN, uint1_t

# Regression test: _process_imports used to only follow ast.Import nodes,
# never ast.ImportFrom, so a sub-module reached only via `from X import Y`
# (and everything *that* sub-module in turn imports) was invisible to the
# module/struct discovery pass entirely.
#
# This file reaches importfrom_mid.py *only* through `from importfrom_mid
# import make_mid_wrapper` below -- an ast.ImportFrom. Before the fix,
# importfrom_mid.py's own `import importfrom_leaf` was therefore never
# discovered either, so importfrom_leaf.py's structs never got
# _discover_structs_from_module'd. leaf_outer_t (whose `inner` field is typed
# leaf_inner_t) is only ever referenced by name inside leaf_func's body --
# never as any function's own param/return annotation -- so nothing about it
# can "self-heal" via _annotation_to_ctype's live-class path; it depends
# entirely on the module-level discovery pass this test checks for. Mirrors
# the actual wireguard-fpga encrypt_dataflow.py -> (ImportFrom) ->
# encrypt_dataflow_core.py -> (Import) -> poly1305.py shape that originally
# exposed the bug (see PY_TO_LOGIC.py's _process_imports /
# _discover_and_queue_module).
from importfrom_mid import make_mid_wrapper

mid_wrapper = make_mid_wrapper()


@MAIN
def main(x: uint1_t) -> uint1_t:
    return mid_wrapper(x)


def test_importfrom_transitive_struct_discovery():
    import tempfile

    import PY_TO_LOGIC
    import SYN

    # PARSE_FILE walks C-built-in submodule instances via _build_inst_lookup,
    # which needs SYN.SYN_OUTPUT_DIRECTORY set -- normally done by the
    # pypelinec CLI wrapper before it calls PARSE_FILE; replicate that here
    # since this test calls PARSE_FILE directly.
    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="importfrom_test_")

    parser_state = PY_TO_LOGIC.PARSE_FILE(os.path.abspath(__file__))

    # Fetch the real canonical ctype names from the already-imported (via the
    # transitive chain under test) module, rather than importing it directly
    # here ourselves -- that would add a second, direct discovery path to
    # importfrom_leaf and defeat the point of testing the two-hop-only case.
    # importfrom_leaf._pypeline_ctype_name is a fully-expanded, structural
    # name (not just the Python class name), stamped by @struct at
    # decoration time -- see pypeline.py.
    importfrom_leaf = sys.modules["importfrom_leaf"]
    leaf_outer_name = importfrom_leaf.leaf_outer_t._pypeline_ctype_name
    leaf_inner_name = importfrom_leaf.leaf_inner_t._pypeline_ctype_name

    fields = parser_state.struct_to_field_type_dict.get(leaf_outer_name)
    assert fields is not None, (
        f"{leaf_outer_name!r} never got registered in struct_to_field_type_dict "
        "-- importfrom_leaf.py (reached only via a transitive ast.ImportFrom hop "
        "through importfrom_mid.py) was never discovered"
    )
    assert fields["inner"] == leaf_inner_name, (
        f"leaf_outer_t.inner should resolve to the canonical struct name "
        f"{leaf_inner_name!r}, got {fields['inner']!r} instead -- looks like a "
        f"raw str(class) repr fallback"
    )
    print("test_importfrom_transitive_struct_discovery PASS")


if __name__ == "__main__":
    test_importfrom_transitive_struct_discovery()
    print("All importfrom_test tests passed.")
