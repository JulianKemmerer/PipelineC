#!/usr/bin/env python3
"""Exercise the live-radio bring-up path with a SoapySDR stand-in."""

import contextlib
import io
import sys
import types
from unittest.mock import patch

import pdw_paths  # noqa: F401
import pdw_host_gen

HOST = pdw_host_gen.ensure_host_types()

import airt_pdw_test as A
import pdw_verify_test as V


def options(*argv):
    with patch.object(A, "_dispatch", side_effect=lambda args: args):
        return A.main(list(argv))


class Radio:
    def __init__(self):
        self.master = 62.5e6
        self.rates = {}
        self.events = []
        self.fail_activate = None
        self.fail_deactivate = False
        self.alarm = False
        samples = V.make_pulse(amp=800)
        rec = V.make_record(samples)
        self.buffers = {
            (0, 1): bytearray(HOST.valid_pdw_t.to_bytes(HOST.valid_pdw_t(**rec))),
            (0, 0): bytearray(samples.astype("<i2").tobytes()),
        }

    def getHardwareInfo(self):
        return {"carrier_firmware_version": "Core mock"}

    def setMasterClockRate(self, rate):
        self.events.append(("master", rate))
        self.master = rate

    def getMasterClockRate(self):
        return self.master

    def getSampleRate(self, direction, ch):
        return self.rates.get((direction, ch), self.master)

    def hasGainMode(self, direction, ch):
        return True

    def setGainMode(self, direction, ch, automatic):
        self.events.append(("gain-mode", direction, ch, automatic))

    def setGain(self, direction, ch, gain):
        self.events.append(("gain", direction, ch, gain))

    def setupStream(self, direction, fmt, channels):
        stream = direction, channels[0]
        self.events.append(("setup", stream))
        return stream

    def activateStream(self, stream):
        self.events.append(("activate", stream))
        return -7 if stream == self.fail_activate else 0

    def deactivateStream(self, stream):
        self.events.append(("deactivate", stream))
        return -7 if self.fail_deactivate else 0

    def closeStream(self, stream):
        self.events.append(("close", stream))

    def writeStream(self, stream, buffers, n, **kwargs):
        if stream == (1, 0):
            cfg = HOST.pdw_ctrl_t.from_bytes(
                buffers[0][: 2 * n].astype("<i2").tobytes()
            )
            self.events.append(("control", cfg.flags))
            self.alarm = bool(cfg.flags & HOST.CTRL_FLAG_ALARM_TEST)
        return types.SimpleNamespace(ret=n)

    def readStream(self, stream, buffers, n, **kwargs):
        self.events.append(("read", stream))
        if self.alarm:
            return types.SimpleNamespace(ret=-4 if stream == (0, 0) else -1)
        data = self.buffers[stream]
        count = min(n, len(data) // 4)
        if not count:
            return types.SimpleNamespace(ret=-1)
        import numpy as np

        buffers[0][: 2 * count] = np.frombuffer(bytes(data[: 4 * count]), "<i2")
        del data[: 4 * count]
        return types.SimpleNamespace(ret=count)


@contextlib.contextmanager
def radio_environment(radio):
    soap = types.ModuleType("SoapySDR")
    soap.SOAPY_SDR_RX, soap.SOAPY_SDR_TX = 0, 1
    soap.SOAPY_SDR_CS16 = "CS16"
    soap.SOAPY_SDR_END_BURST = 2
    soap.SOAPY_SDR_TIMEOUT, soap.SOAPY_SDR_OVERFLOW = -1, -4
    soap.getLibVersion = lambda: "mock"
    soap.errToStr = lambda code: f"mock {code}"
    soap.Device = lambda args: radio
    output = io.StringIO()
    with patch.dict(sys.modules, SoapySDR=soap), patch.object(
        A.time, "sleep"
    ), contextlib.redirect_stdout(output):
        yield output


def expect_error(action, text):
    try:
        action()
    except RuntimeError as e:
        assert text in str(e), str(e)
    else:
        raise AssertionError(f"missing error: {text}")


def test_clock_and_informational_identity():
    radio = Radio()
    with radio_environment(radio):
        assert A.run(options("--stage", "preflight", "--rate", "125e6")) == 0
    assert radio.events == [("master", 125e6)]
    radio.rates[(0, 1)] = 62.5e6
    with radio_environment(radio):
        expect_error(lambda: A.preflight(radio, options()), "RX1 rate")
    radio.rates.clear()
    radio.master = 62.5e6
    with radio_environment(radio):
        expect_error(lambda: A.preflight(radio, options()), "requires 125 MHz")


def test_ctrl_stage_stays_held_and_closes():
    radio = Radio()
    with radio_environment(radio) as output:
        assert (
            A.run(options("--stage", "ctrl", "--rate", "125e6", "--settle", "0")) == 0
        )
    assert [e for e in radio.events if e[0] == "activate"] == [("activate", (1, 0))]
    assert ("deactivate", (1, 0)) in radio.events
    assert "generator stays in reset" in output.getvalue()


def test_rf_thresholds_use_the_received_amplitude():
    try:
        A.build_config(V.FS, loopback=False)
    except ValueError as e:
        assert "--rx-amplitude" in str(e)
    else:
        raise AssertionError("RF test accepted an uncalibrated threshold reference")
    radio = Radio()
    with radio_environment(radio) as output:
        assert (
            A.run(
                options(
                    "--stage",
                    "ctrl",
                    "--rate",
                    "125e6",
                    "--no-loopback",
                    "--rx-amplitude",
                    "400",
                    "--rx-gain",
                    "-25",
                    "--tx-gain",
                    "-10",
                )
            )
            == 0
        )
    assert ("gain-mode", 0, 0, False) in radio.events
    assert ("gain", 0, 0, -25) in radio.events
    assert ("gain", 1, 0, -10) in radio.events
    assert "hi 393216000" in output.getvalue()
    assert "of RX amplitude^2" in output.getvalue()


def test_initial_rf_capture_can_use_explicit_thresholds():
    cfg = A.build_config(
        V.FS, loopback=False, threshold_high_power=2000, threshold_low_power=1000
    )
    assert cfg["threshold_high"] == 2000 * (1 << HOST.POWER_FRAC_BITS)
    assert cfg["threshold_low"] == 1000 * (1 << HOST.POWER_FRAC_BITS)
    # The packet can be checked against its record before an amplitude reference
    # exists, without comparing the analog receive level to the TX digital level.
    samples = V.make_pulse(amp=400)
    rows = A.pdw_verify.check(V.make_record(samples), samples, V.FS, cfg=cfg)
    assert A.pdw_verify.all_ok(rows)
    assert not any("amplitude vs samples" in row["name"] for row in rows)
    for high, low in ((1000, 2000), (2**32, 1), (1e-8, 0)):
        try:
            A.build_config(
                V.FS, loopback=False, threshold_high_power=high, threshold_low_power=low
            )
        except ValueError:
            pass
        else:
            raise AssertionError("unrepresentable receive thresholds were accepted")


def test_failed_activation_stops_and_cleans_up():
    radio = Radio()
    radio.fail_activate = (0, 1)
    with radio_environment(radio):
        expect_error(
            lambda: A.run(options("--stage", "streams", "--rate", "125e6")),
            "RX1 records",
        )
    assert ("activate", (1, 1)) not in radio.events
    assert ("deactivate", (0, 1)) not in radio.events
    assert {e[1] for e in radio.events if e[0] == "close"} == {
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
    }


def test_resync_requires_a_successful_reset():
    radio = Radio()
    radio.fail_deactivate = True
    with radio_environment(radio):
        expect_error(
            lambda: A.resync(
                radio,
                [(1, 0), (1, 1), (0, 0), (0, 1)],
                [(1, 0)],
                A.build_config(V.FS),
                options(),
            ),
            "could not deactivate",
        )
    assert not any(e[0] == "activate" for e in radio.events)


def test_alarm_fires_after_verified_traffic_and_checks_both_channels():
    radio = Radio()
    # Make the deliberate RX1 silence finish promptly; the real probe still
    # checks RX0 for its pending OVERFLOW after the requested alarm.
    original_init = A.RadioSource.__init__

    def short_deadline(self, *args):
        original_init(self, *args)
        self.deadline = 0

    with radio_environment(radio) as output, patch.object(
        A.RadioSource, "__init__", short_deadline
    ):
        result = A.run(
            options("--rate", "125e6", "--alarm", "--alarm-test", "--pulses", "1")
        )
    assert result == 0, output.getvalue()
    startup = radio.events.index(("control", 3))
    warmup = radio.events.index(("read", (0, 0)))
    firing = radio.events.index(("control", 7))
    assert startup < warmup < firing
    assert "verified traffic established" in output.getvalue()
    assert "Rung 6 PASSES" in output.getvalue()


def test_alarm_timeout_is_inconclusive():
    class TimeoutSource:
        def record(self):
            raise A.StreamTimeout("no transport completion")

        def probe_alarm_overflow(self):
            return None

    with contextlib.redirect_stdout(io.StringIO()) as output:
        failures = A.capture(
            TimeoutSource(),
            A.build_config(V.FS, alarm=True, alarm_test=True),
            V.FS,
            options("--alarm", "--alarm-test"),
        )
    assert failures == 1
    assert "INCONCLUSIVE" in output.getvalue()
    assert "does NOT reach" not in output.getvalue()
    assert "Rung 6 PASSES" not in output.getvalue()


if __name__ == "__main__":
    for test in (
        test_clock_and_informational_identity,
        test_ctrl_stage_stays_held_and_closes,
        test_rf_thresholds_use_the_received_amplitude,
        test_initial_rf_capture_can_use_explicit_thresholds,
        test_failed_activation_stops_and_cleans_up,
        test_resync_requires_a_successful_reset,
        test_alarm_fires_after_verified_traffic_and_checks_both_channels,
        test_alarm_timeout_is_inconclusive,
    ):
        test()
        print(test.__name__, "passed")
    print("All airt_pdw_host tests passed")
