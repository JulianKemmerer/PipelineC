"""A nested record starting with 'signed_' is mistaken for a VHDL scalar.

The FIFO's outer record forces serialization of signed_payload_t. Its generated
conversion incorrectly uses signed()/std_logic_vector() instead of the record's
conversion helper. Native simulation succeeds; GHDL analysis currently fails.
The NCO uses amplitudes_t to avoid this type-name collision.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include/pypeline")]
from pypeline import MAIN, NamedTuple, struct, uint16_t
from fifo import make_fifo


@struct
class signed_payload_t(NamedTuple):
    value: uint16_t


fifo = make_fifo(signed_payload_t, 4)


@MAIN(125.0)
def signed_prefix_main(value: uint16_t) -> fifo.return_t:
    return fifo(1, signed_payload_t(value=value), 1)
