# pyright: reportInvalidTypeForm=none
from typing import NamedTuple
from pypeline import hw_func, struct, uint1_t

# Reached from importfrom_test.py two hops away: importfrom_test.py does
# `from importfrom_mid import make_mid_wrapper` (ast.ImportFrom), and this
# file is only discovered because importfrom_mid.py does `import
# importfrom_leaf` (ast.Import) -- mirrors the wireguard-fpga
# encrypt_dataflow.py -> (ImportFrom) -> encrypt_dataflow_core.py ->
# (Import) -> poly1305.py shape that exposed the bug.


@struct
class leaf_inner_t(NamedTuple):
    a: uint1_t
    b: uint1_t


@struct
class leaf_outer_t(NamedTuple):
    inner: leaf_inner_t
    flag: uint1_t


@hw_func
def leaf_func(x: uint1_t) -> uint1_t:
    # leaf_outer_t is only ever referenced by name here, as a body-local
    # variable declaration -- never as leaf_func's own param/return type --
    # so it can't "self-heal" via _annotation_to_ctype's live-class handling
    # the way a struct-typed parameter/return annotation would. Registering
    # it (and its nested leaf_inner_t field) depends entirely on
    # _discover_structs_from_module having run on this file.
    v: leaf_outer_t
    v.inner.a = x
    v.inner.b = ~x
    v.flag = x
    return v.flag
