"""Native simulation stores every write to a global wire as a value of the
wire's type, as the hardware wire holds it. Each test runs a small design
natively (pypeline_sim.py) and asserts what the hardware gives.

- `~q`, where q is a Wire[uint1_t] written from a comparison (`q = t >= 2`),
  is the one-bit NOT, not the NOT of a Python bool (`~True` is -2).
- A list of plain ints written to a Wire[uint8_t[2]] packs at the wire's
  element width: array_to_uint_le of [1, 2] is 0x0201 = 513, not 5.
- A value wider than the wire (`w = t + 250` on a Wire[uint8_t]) and an
  augmented write (`acc += n`) wrap at the wire's width.
- Unpacking into several wires (or several fields of one wire) of different
  types casts each leaf to its own type.
- The same list written to an array field of a struct wire packs to 513.

The cast is native sim's equivalent of the type assignment in
_GlobalWireRewriter (pypeline.py).
"""

import os
import subprocess
import sys
import tempfile

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

DESIGN = """
import sys
sys.path.insert(0, {src!r})
from pypeline import *

q: Wire[uint1_t]

@MAIN
def a():
    t: Reg[uint8_t]
    q = t >= 2
    t = t + 1

@MAIN
def b():
    if ~q:
        sim_print("not q")
    else:
        sim_print("q")
"""


PACK_DESIGN = """
import sys
sys.path.insert(0, {src!r})
from pypeline import *

lanes_w: Wire[uint8_t[2]]
packed: Output[uint16_t]

@MAIN(10.0)
def writer():
    lanes_w = [1, 2]

@MAIN(10.0)
def reader():
    packed = array_to_uint_le(lanes_w)
    sim_print(f"packed={{packed}}")
"""


# t counts 0, 1, 2, ...: t + 250 passes 255 in cycle 6.
TRUNCATE_DESIGN = """
import sys
sys.path.insert(0, {src!r})
from pypeline import *

w: Wire[uint8_t]

@MAIN
def writer():
    t: Reg[uint8_t]
    w = t + 250
    t = t + 1

@MAIN
def reader():
    sim_print(f"w={{w}}")
"""


AUG_DESIGN = """
import sys
sys.path.insert(0, {src!r})
from pypeline import *

acc: Wire[uint8_t]

@MAIN
def writer():
    n: Reg[uint8_t]
    acc = 250
    acc += n
    n = n + 1

@MAIN
def reader():
    sim_print(f"acc={{acc}}")
"""


UNPACK_WIRES_DESIGN = """
import sys
sys.path.insert(0, {src!r})
from pypeline import *

wide: Wire[uint16_t]
narrow: Wire[uint8_t]

@MAIN
def writer():
    wide, narrow = 300, 257

@MAIN
def reader():
    sim_print(f"wide={{wide}} narrow={{narrow}}")
"""


UNPACK_FIELDS_DESIGN = """
import sys
from typing import NamedTuple
sys.path.insert(0, {src!r})
from pypeline import *

@struct
class pair_t(NamedTuple):
    wide: uint16_t
    narrow: uint8_t

s: Wire[pair_t]

@MAIN
def writer():
    s.wide, s.narrow = 300, 257

@MAIN
def reader():
    sim_print(f"wide={{s.wide}} narrow={{s.narrow}}")
"""


STRUCT_PACK_DESIGN = """
import sys
from typing import NamedTuple
sys.path.insert(0, {src!r})
from pypeline import *

@struct
class frame_t(NamedTuple):
    lanes: uint8_t[2]

f: Wire[frame_t]
packed: Output[uint16_t]

@MAIN(10.0)
def writer():
    f.lanes = [1, 2]

@MAIN(10.0)
def reader():
    packed = array_to_uint_le(f.lanes)
    sim_print(f"packed={{packed}}")
"""


def _native_run(design, cycles):
    """The stdout of a native run of design for cycles cycles."""
    with tempfile.TemporaryDirectory(prefix="native_invert_compare_wire_") as tmpdir:
        path = os.path.join(tmpdir, "design.py")
        with open(path, "w") as f:
            f.write(design.format(src=os.path.abspath(SRC)))
        proc = subprocess.run(
            [sys.executable, os.path.join(SRC, "pypeline_sim.py"), path, "--run", cycles],
            capture_output=True,
            text=True,
        )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


def _printed(design, cycles, prefix):
    """The sim_print lines of a native run that start with prefix."""
    return [l for l in _native_run(design, cycles).splitlines() if l.startswith(prefix)]


def test_invert_of_comparison_wire():
    lines = [l for l in _native_run(DESIGN, "4").splitlines() if l in ("q", "not q")]
    assert lines == ["not q", "not q", "q", "q"], lines


def test_packing_a_list_written_to_an_array_wire():
    lines = _printed(PACK_DESIGN, "2", "packed=")
    assert lines == ["packed=513", "packed=513"], lines


def test_wider_value_wraps_at_the_wire_width():
    lines = _printed(TRUNCATE_DESIGN, "8", "w=")
    assert lines == [f"w={v}" for v in (250, 251, 252, 253, 254, 255, 0, 1)], lines


def test_augmented_write_wraps_at_the_wire_width():
    lines = _printed(AUG_DESIGN, "8", "acc=")
    assert lines == [f"acc={v}" for v in (250, 251, 252, 253, 254, 255, 0, 1)], lines


def test_unpacking_into_wires_of_different_types():
    lines = _printed(UNPACK_WIRES_DESIGN, "2", "wide=")
    assert lines == ["wide=300 narrow=1"] * 2, lines


def test_unpacking_into_fields_of_different_types():
    lines = _printed(UNPACK_FIELDS_DESIGN, "2", "wide=")
    assert lines == ["wide=300 narrow=1"] * 2, lines


def test_packing_a_list_written_to_an_array_field_of_a_struct_wire():
    lines = _printed(STRUCT_PACK_DESIGN, "2", "packed=")
    assert lines == ["packed=513", "packed=513"], lines


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
