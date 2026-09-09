#!/usr/bin/env python3
"""Tests for the internal-error alarm (pdw_alarm.py).

The alarm's entire job is to destroy a known number of ADC samples so the
platform reports an overflow to software. So the property worth testing is not
"tready went low" -- it is "exactly N samples were actually dropped", and the
difference between those two only shows up when the input is GAPPED.

That is what test_gapped_valid_still_drops_the_full_count is for, and
test_a_cycle_counter_would_fail_the_gapped_test is its negative control: it
runs a deliberately-wrong cycle-counting model through the same stimulus and
asserts it gets the wrong answer. Without that second test the first one is
just a number that happens to match.

Composed with sim_call, so this runs in under a second.

Run: python3 pdw_alarm_test.py
"""

import pdw_paths  # noqa: F401  (puts include/pypeline on sys.path)

from pypeline import sim_call, sim_reset

from pdw_alarm import make_error_alarm

# Small numbers so a test is a few hundred cycles, not a few million. The
# backstop still has to exceed the drop count -- make_error_alarm asserts it --
# because otherwise IT would be what ends every alarm and the drop count would
# stop meaning anything.
DROPS = 8
MAX_CYCLES = 200
ALARM, _ = make_error_alarm(drop_samples=DROPS, max_cycles=MAX_CYCLES)


def _run(cycles, trig_of, valid_of, en=1, rst_of=lambda c: 0):
    """Drive the alarm and return (n_dropped, n_low_cycles, fire_cycles)."""
    sim_reset()
    dropped = low = 0
    fires = []
    for c in range(cycles):
        valid = int(valid_of(c))
        o = sim_call(
            ALARM,
            trig=int(trig_of(c)),
            en=int(en),
            in_valid=valid,
            rst=int(rst_of(c)),
        )
        if int(o.firing):
            fires.append(c)
        if not int(o.ready):
            low += 1
            # A sample is destroyed only where tvalid met a low tready.
            if valid:
                dropped += 1
    return dropped, low, fires


def test_continuous_valid_drops_exactly_the_count():
    dropped, low, fires = _run(400, lambda c: c == 10, lambda c: 1)
    assert fires == [10], f"expected one alarm at cycle 10, got {fires}"
    assert dropped == DROPS, f"dropped {dropped}, expected {DROPS}"
    # With tvalid always high the two counts coincide, which is exactly why
    # this test alone cannot tell a correct implementation from a wrong one.
    assert low == DROPS, f"held ready low for {low} cycles, expected {DROPS}"
    print(f"test_continuous_valid_drops_exactly_the_count passed "
          f"({dropped} samples in {low} cycles)")


def test_gapped_valid_still_drops_the_full_count():
    """THE test. tvalid every 4th cycle, so cycles and samples diverge 4:1."""
    dropped, low, fires = _run(400, lambda c: c == 10, lambda c: c % 4 == 0)
    assert fires == [10], f"expected one alarm at cycle 10, got {fires}"
    assert dropped == DROPS, (
        f"dropped {dropped} samples, expected {DROPS} -- the countdown is "
        "following cycles rather than samples"
    )
    assert low >= 4 * DROPS - 4, (
        f"ready was only low for {low} cycles; at a 1-in-4 duty cycle it must "
        f"stay low roughly 4x longer than the {DROPS} samples it destroys"
    )
    print(f"test_gapped_valid_still_drops_the_full_count passed "
          f"({dropped} samples in {low} cycles, 1-in-4 duty)")


def test_a_cycle_counter_would_fail_the_gapped_test():
    """Negative control for the test above: the wrong implementation, run
    through the same stimulus, must get a visibly wrong answer. Without this
    the gapped test proves only that some number came out."""
    remaining, dropped = 0, 0
    for c in range(400):
        valid = 1 if c % 4 == 0 else 0
        if c == 10 and remaining == 0:
            remaining = DROPS  # counts CYCLES -- the bug being excluded
        if remaining:
            if valid:
                dropped += 1
            remaining -= 1
    assert dropped != DROPS, (
        "the cycle-counting model dropped the right number of samples, so the "
        "gapped test cannot tell the two implementations apart"
    )
    print(f"test_a_cycle_counter_would_fail_the_gapped_test passed "
          f"(cycle-counting model drops {dropped}, not {DROPS})")


def test_disarmed_does_nothing():
    dropped, low, fires = _run(400, lambda c: 1, lambda c: 1, en=0)
    assert (dropped, low, fires) == (0, 0, []), (
        f"a disarmed alarm still acted: dropped={dropped} low={low} fires={fires}"
    )
    print("test_disarmed_does_nothing passed")


def test_standing_trigger_fires_once():
    """The FIFO-drop conditions are sticky until reset. A level-triggered alarm
    would hold tready low forever and turn a corrupted-stream fault into a
    dead-radio fault."""
    dropped, low, fires = _run(400, lambda c: c >= 10, lambda c: 1)
    assert fires == [10], f"a standing trigger fired {len(fires)} times: {fires}"
    assert dropped == DROPS, f"dropped {dropped}, expected {DROPS}"
    print("test_standing_trigger_fires_once passed")


def test_retriggers_after_the_trigger_clears():
    """Which is what lets CTRL_FLAG_ALARM_TEST be fired again by toggling."""
    dropped, _low, fires = _run(
        400, lambda c: c in range(10, 20) or c in range(200, 210), lambda c: 1
    )
    assert len(fires) == 2, f"expected two alarms, got {fires}"
    assert dropped == 2 * DROPS, f"dropped {dropped}, expected {2 * DROPS}"
    print(f"test_retriggers_after_the_trigger_clears passed (fires at {fires})")


def test_backstop_releases_when_no_samples_arrive():
    """tvalid never asserts: nothing is being dropped, so ready must not stay
    low on its account for longer than the backstop."""
    dropped, low, fires = _run(2 * MAX_CYCLES, lambda c: c == 10, lambda c: 0)
    assert fires == [10] and dropped == 0
    assert low == MAX_CYCLES, (
        f"ready was low for {low} cycles, expected the {MAX_CYCLES}-cycle "
        "backstop to end it"
    )
    print(f"test_backstop_releases_when_no_samples_arrive passed ({low} cycles)")


def test_reset_abandons_an_alarm_in_flight():
    dropped, low, fires = _run(
        400, lambda c: c == 10, lambda c: 1, rst_of=lambda c: 12 <= c < 30
    )
    assert fires == [10]
    assert dropped < DROPS, (
        f"reset did not cut the alarm short: {dropped} samples dropped"
    )
    assert low < 25, f"ready stayed low for {low} cycles across a reset"
    print(f"test_reset_abandons_an_alarm_in_flight passed "
          f"({dropped} of {DROPS} samples before reset)")


def test_backstop_must_exceed_the_drop_count():
    try:
        make_error_alarm(drop_samples=64, max_cycles=32)
    except AssertionError:
        print("test_backstop_must_exceed_the_drop_count passed")
        return
    raise AssertionError("make_error_alarm accepted max_cycles < drop_samples")


if __name__ == "__main__":
    print(f"pdw_alarm_test: drop_samples={DROPS} max_cycles={MAX_CYCLES}")
    test_continuous_valid_drops_exactly_the_count()
    test_gapped_valid_still_drops_the_full_count()
    test_a_cycle_counter_would_fail_the_gapped_test()
    test_disarmed_does_nothing()
    test_standing_trigger_fires_once()
    test_retriggers_after_the_trigger_clears()
    test_backstop_releases_when_no_samples_arrive()
    test_reset_abandons_an_alarm_in_flight()
    test_backstop_must_exceed_the_drop_count()
    print("All pdw_alarm tests passed")
