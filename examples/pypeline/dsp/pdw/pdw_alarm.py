# pyright: reportInvalidTypeForm=none
"""The internal-error alarm for the PDW pipeline (see ../README.md).

WHY THIS EXISTS. In the 2-channel AIR-T deployment this design has exactly one
way to reach a host: a `valid_pdw_t` record on RX1, followed by that pulse's
packet on RX0. There is no third channel. That is survivable for everything the
record can describe in-band -- and fatal for the two failures that cannot be:

  * a completed pulse's DESCRIPTOR dropped because the descriptor FIFO was full.
    Its beats stay in the data FIFO with no owner, so every later packet is
    offset by them for the rest of the session.
  * that pulse's MEASUREMENT dropped for the same reason, which breaks the
    descriptor/measurement lockstep so every later record carries the previous
    pulse's frequency, dB and PRI.

Both corrupt everything after them, both are permanent short of a reset, and
both keep producing records that look perfectly well formed. Until now the only
thing that noticed either was a `sim_assert`, which halts GHDL and compiles to
nothing at all in a bitstream.

THE BACK-CHANNEL. The platform (Deepwave AirStack) documents that on the ADC
receive interface "constant flow control tready assertion is assumed,
deasserting tready drops tdata samples causing overflow", and that overflow
events are reported by its API. So a slave that deliberately deasserts tready
can make software see something. It is one bit, it costs real samples, and it is
the only outward signal available -- which is the whole argument for it.

THE COUNTER COUNTS DROPPED SAMPLES, NOT CYCLES.
This is the mechanism, not an implementation detail. A sample is destroyed only
on a cycle where `in_valid` is high AND ready is low. Holding ready low while
the input is idle destroys nothing, raises no overflow, and delivers no message
-- so a cycle-based countdown would fail silently in exactly the case that a
gapped or not-yet-running input makes likely, which is the case a bring-up is
most likely to be in. Counting `in_valid & ~ready` instead makes the number of
samples destroyed a property of this block rather than a property of the
input's duty cycle.

`max_cycles` is only a backstop for the other side of that: an input that never
presents a sample can never complete the drop count, and ready must not stay low
forever on its account. It is deliberately far larger than `drop_samples`, so on
a continuously-valid stream it never decides anything.

ARMING. `en` comes from CTRL_FLAG_ALARM_EN and is off in CTRL_DEFAULTS. Arming
means consenting to lose real samples to send a one-bit message, which is only
the right trade when a host is watching for it. CTRL_FLAG_ALARM_TEST drives the
same `trig` input directly, so the signalling path can be proved on a good day
rather than first exercised during a fault.
"""

import pdw_paths  # noqa: F401  (puts include/pypeline on sys.path)

from pypeline import NamedTuple, Reg, hw_func, struct, uint1_t, uint32_t


def make_error_alarm(drop_samples=4096, max_cycles=1 << 20):
    """Build the alarm. Returns (error_alarm, error_alarm_t).

        error_alarm(trig: uint1_t, en: uint1_t, in_valid: uint1_t,
                    rst: uint1_t) -> error_alarm_t

    `trig` is the OR of every condition worth reporting, plus the test bit.
    `in_valid` is the guarded stream's tvalid -- read ONLY to decide whether a
    sample was really dropped, never to gate `ready`, so nothing here puts
    tvalid into the tready path.

    Result fields:
        .ready   (uint1_t) drive the slave port's tready with this
        .active  (uint1_t) 1 while an alarm is being sent
        .firing  (uint1_t) pulses on the cycle an alarm starts

    ONE ALARM PER EVENT. The error conditions upstream are sticky until reset,
    so a raw level-triggered alarm would hold ready low forever and take the
    receive path down permanently -- turning a corrupted-packet-stream fault
    into a dead-radio fault. The internal `seen` register is what limits a
    standing trigger to a single alarm. It clears when the trigger goes away,
    which is also what lets CTRL_FLAG_ALARM_TEST fire again by toggling.
    """
    assert max_cycles > drop_samples, (
        f"max_cycles ({max_cycles}) is the backstop for an input that never "
        f"presents a sample, so it must exceed drop_samples ({drop_samples}) "
        "-- otherwise it, not the drop count, is what ends every alarm, and "
        "the number of samples actually destroyed becomes a function of the "
        "input's duty cycle again"
    )

    @struct
    class error_alarm_t(NamedTuple):
        ready: uint1_t
        active: uint1_t
        firing: uint1_t

    @hw_func
    def error_alarm(
        trig: uint1_t, en: uint1_t, in_valid: uint1_t, rst: uint1_t
    ) -> error_alarm_t:
        o: error_alarm_t
        # Counts DOWN from drop_samples, one per sample actually dropped.
        drops: Reg[uint32_t]
        cycles: Reg[uint32_t]
        seen: Reg[uint1_t]

        # Derived from registers alone -- this is what keeps `in_valid` out of
        # the combinational path to `ready`, which would be a loop through the
        # platform.
        active: uint1_t = (drops != 0) & (cycles != 0)
        start: uint1_t = en & trig & (~seen) & (~active) & (~rst)

        o.active = active
        o.ready = ~active
        o.firing = start

        if active:
            cycles = cycles - 1
            # The load-bearing line: a sample is only lost if one was there.
            if in_valid:
                drops = drops - 1
        elif start:
            drops = drop_samples
            cycles = max_cycles
            seen = 1

        # Re-arm once the trigger goes away. Placed after the start above so a
        # trigger that is still asserted cannot clear its own `seen`.
        if ~trig:
            seen = 0

        # Reset LAST, so it wins over everything, exactly as packet_store's
        # does. An alarm in flight is abandoned: reset is already the recovery
        # the alarm was reporting the need for.
        if rst:
            drops = 0
            cycles = 0
            seen = 0
        return o

    error_alarm.drop_samples = drop_samples
    error_alarm.max_cycles = max_cycles
    error_alarm.error_alarm_t = error_alarm_t
    return error_alarm, error_alarm_t
