"""A ROM whose words come from words.txt, which the design declares with
depends_on, the way a firmware helper declares its sources. See
depends_on_test.py."""

from pathlib import Path

from pypeline import MAIN, depends_on, uint2_t, uint8_t
from ram import make_ram

words = [int(w) for w in depends_on(Path(__file__).with_name("words.txt")).read_text().split()]
rom = make_ram(uint8_t, 4, ports=("r",), read_latency=0, init=words)


@MAIN(10.0, name="rom_reader")
def read_word(index: uint2_t) -> uint8_t:
    result = rom(rom.p0_in_t(addr=index, valid=1))
    return result.p0.rd_data
