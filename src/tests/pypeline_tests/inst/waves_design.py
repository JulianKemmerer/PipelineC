# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Fixture of waves_test.py: a design whose waveform (pypelinec --sim --wave)
holds every kind of signal, with values the test computes per cycle.

- Ports: the reset Input rst (1 in cycle 0, then 0), the Output count and the
  return port counter_return_output.
- Global Wires: sample, a struct of an array, an @enum and a signed field
  (recorded with --wave_signals sample), unselected (never recorded) and
  link, an AXI-Stream interface shown flat by axis_wave as /s_axis_t*.
- sim_wave signals: n (named after its source), snap.delta (a scope from the
  source text), /marker (a str at the top scope) and pair (an array).
- Stream perf probes: the handshake beat and the state probe fsm.

n counts from reset: 0 in cycles 0 and 1 (the reset edge ends cycle 0), then
k - 1 in cycle k. The run ends with sim_finish() in cycle FINISH_CYCLE, before
the MAIN returns.
"""

from enum import auto
from typing import NamedTuple

from pypeline import *
from axi.axis import axis_wave, make_axis_interface
from stream.stream_perf_probe import hs, state

# The cycle whose sim_finish() ends the run: the one where n reaches 7
FINISH_CYCLE = 8


@enum
class phase_t(PypelineEnum):
    IDLE = auto()
    COUNT = auto()
    DONE = auto()


# phase_t's member names in declaration order, for the state probe
PHASE_NAMES = ("IDLE", "COUNT", "DONE")


@struct
class sample_t(NamedTuple):
    lanes: uint8_t[2]
    phase: phase_t
    delta: int8_t


axis_if_t = make_axis_interface(2)

rst: Input[uint1_t] = make_reset()
count: Output[uint8_t]
sample: Wire[sample_t]
unselected: Wire[uint8_t]
link: Wire[axis_if_t]


@MAIN(50.0, reset=rst, reset_registers="all")
def counter() -> uint8_t:
    n: Reg[uint8_t]
    phase: Reg[phase_t]
    down: Reg[int8_t]
    snap: sample_t = sample_t(lanes=[n, n + 1], phase=phase, delta=down)
    sample = snap
    unselected = n
    count = n
    s: axis_if_t.stream_t
    s.data.frag.data[0] = n
    s.data.frag.data[1] = n + 0x10
    s.data.frag.keep[0] = 1
    s.data.frag.keep[1] = n[0]
    s.data.eod[0] = n == 3
    s.valid = 1
    link.stream = s
    link.ready = n[1]
    axis_wave("/s_axis", link)
    sim_wave(n)
    sim_wave(snap.delta)
    sim_wave("/marker", "low" if n < 4 else "high")
    sim_wave("pair", [n, n + 2])
    hs("beat", n[0], n[1])
    state("fsm", phase, PHASE_NAMES)
    if phase == phase_t.IDLE:
        phase = phase_t.COUNT
    elif n == 4:
        phase = phase_t.DONE
    down -= 1
    if n == FINISH_CYCLE - 1:
        sim_finish()
    n += 1
    return n
