#!/usr/bin/env python3
"""Bring up the PDW design on a Deepwave AIR-T (AirStack) and verify its output.

NOT part of `run_all.py`. This needs SoapySDR and real hardware. What *is*
covered in-repo, with no radio, is everything it depends on: the control frame
this script builds comes from the same generated layout the hardware serializer
was built from (so it cannot disagree by construction), `pdw_verify_test.py`
proves the checks below actually catch a wrong record, and `--replay` runs this
file's entire capture loop over a recorded session so that loop is tested too.
Run those before trusting a red result here.

COPY THESE FOUR FILES TO THE RADIO -- nothing else, and no Pypeline checkout:

    airt_pdw_test.py          this script (config arithmetic lives here)
    pypeline_host_types.py    GENERATED -- every struct layout and constant
    gr_pdw_record.py          gr-pdw's columns and dB/frequency scaling
    pdw_verify.py             independent FFT check of a record vs its samples

`pypeline_host_types.py` is not written by hand and must not be edited. Every
`pypelinec` build of ../top.py drops it in `<out_dir>/host/`; `pdw_host_gen.py`
produces the same file without a build. It carries the three struct layouts and
the design's exported constants -- so the frame this script sends cannot
disagree with the frame the hardware expects, and the FIFO depths this script
sizes its configuration against are the design's own numbers.

CHANNEL MAP (2-channel bitstream mode). Deepwave names ports from ITS side, so
every m/s letter is mirrored relative to this design's names -- they pair
correctly, only the letter flips. Getting this backwards silently swaps a whole
channel, so it is spelled out:

    writeStream(TX,0)  dwd_tx0_m_axis <- tx0_s_axis   pdw_ctrl_t, 10 beats
    readStream (RX,0)  dwd_rx0_s_axis <- rx0_m_axis   pulse packets, variable
    readStream (RX,1)  dwd_rx1_s_axis <- rx1_m_axis   valid_pdw_t, 40 bytes
    writeStream(TX,1)  dwd_tx1_m_axis                 priming only, discarded
                       dwd_tx1_s_axis <- tx1_m_axis   packet replay, to radio

There is no RX2 in 2-channel mode, so the candidate-record stream is left
unconnected: tie `rx2_m_axis_rst` LOW and `rx2_m_axis_tready` HIGH in the
wrapper. Tying that reset low is not optional -- `global_rst` is the OR of every
channel reset, so a floating or asserted one holds the whole design in reset
forever and this script simply times out with no pulses.

⚠ THE ONE SYMPTOM. Because RX2 does not exist here, a detected-but-REJECTED
pulse produces nothing at all, and so does a design held in reset, a
configuration that never landed, a threshold off by the x4096 scaling, and a
wrong bitstream. Six root causes, one symptom: silence. That is why bring-up is
a ladder rather than a single run of this script -- see README.md's "Bring-up
and debugging", and use `--stage` to stop at the rung you are proving.

BRING-UP ORDER IS LOAD-BEARING. The design has two reset domains: `pdw_ctrl`
follows tx0's reset alone, everything else follows the OR of all of them. That
exists so configuration can land while the datapath is still held:

    1. nothing activated              all resets asserted, buffers draining
    2. activateStream(TX,0)           control block live, datapath still held
    3. write one pdw_ctrl_t frame     config lands, datapath still held
    4. activate RX0, RX1, TX1         datapath starts ALREADY CONFIGURED

Step 4 is the payoff: the detector's first sample is measured against real
thresholds rather than running on CTRL_DEFAULTS for however long a frame takes
to arrive. It also guarantees the RX0/RX1 lockstep the capture loop below
depends on -- because `global_rst` is the OR, nothing is emitted until every
stream is open, so both start empty whatever order they activate in.

FRAMING. readStream surfaces no end-of-burst, so the RX side is framed by
counting: records are a fixed 40 bytes, and each record's `pkt_samples` gives
the exact length of the packet that follows it. That field is the TRUE on-wire
length even when a full FIFO ate beats, so one damaged packet cannot desync the
stream. writeStream DOES produce tlast via SOAPY_SDR_END_BURST, which is how the
control frame gets its framing.

Counting only works while the count is trustworthy, so every record is
validated before it is acted on (`validate_record`). Four of its bytes --
`channel` and `padding` -- are known zero, which is a free desync detector, and
the alternative to having one is that the first thing this script does with a
desynchronised stream is allocate `pkt_samples` of memory from it.

RF WARNING. With loopback enabled the detector is fed internally, but TX0 still
carries the generator's samples to the radio. Use a cable and terminator, not an
antenna.
"""

import argparse
import struct
import sys
import time

try:
    from pypeline_host_types import (
        CTRL_FLAG_ALARM_EN,
        CTRL_FLAG_ALARM_TEST,
        CTRL_FLAG_LOOPBACK_EN,
        PKT_FIFO_DEPTH,
        PKT_QUEUE_DEPTH,
        POWER_FRAC_BITS,
        pdw_ctrl_t,
        valid_pdw_t,
    )
except ImportError as _e:  # pragma: no cover - the one setup mistake worth naming
    raise SystemExit(
        "pypeline_host_types.py not found -- it is GENERATED, not committed.\n"
        "  in the repo:  python3 pdw_host_gen.py .\n"
        "  from a build: copy <out_dir>/host/pypeline_host_types.py next to this\n"
        f"({_e})"
    )

import gr_pdw_record
import pdw_verify

# Channel assignments, per the map above.
CH_CTRL_TX = 0  # writeStream: pdw_ctrl_t frames
CH_REPLAY_TX = 1  # activated (and optionally primed); never carries real data
CH_PKT_RX = 0  # readStream: pulse packets
CH_PDW_RX = 1  # readStream: valid_pdw_t records

# One CS16 element is one 32-bit AXIS beat is 4 bytes. The packing matches
# exactly -- I = tdata[15:0] = the even int16, Q = tdata[31:16] = the odd one --
# so this is a reinterpret, never a conversion.
BYTES_PER_ELEM = 4
CTRL_ELEMS = pdw_ctrl_t.BYTE_LENGTH // BYTES_PER_ELEM
RECORD_ELEMS = valid_pdw_t.BYTE_LENGTH // BYTES_PER_ELEM


def bytes_to_cs16(raw):
    """Frame bytes -> the interleaved int16 buffer writeStream wants."""
    import numpy as np

    return np.frombuffer(raw, dtype="<i2").copy()


def cs16_to_bytes(buf, n_elems):
    """The first `n_elems` complex samples of a CS16 buffer -> frame bytes."""
    return buf[: 2 * n_elems].astype("<i2").tobytes()


class StreamTimeout(Exception):
    """readStream produced nothing within the deadline."""


class EndOfCapture(StreamTimeout):
    """A `--replay` file ran out. Not an error; the run is simply over."""


class StreamDesync(Exception):
    """The byte-counted framing is no longer trustworthy.

    Raised for anything that means the position in the stream is unknown: an
    overflow, a record that fails validation, a short packet. There is no way
    to recover by reading further -- the only remedy is a resync, which resets
    the design and starts over.
    """


# ─────────────────────────────────────────────
# Capture files (--record / --replay)
#
# Two jobs, and the second is why this exists at all. It lets a session that
# went wrong on a radio be replayed in the repo against the same checks; and it
# lets this script's capture loop -- framing, validation, verification, the
# whole thing -- be exercised by airt_pdw_replay_test.py with no hardware, which
# is otherwise the only part of this project with no test at all.
#
# Deliberately trivial and stdlib-only: an 8-byte magic and the sample rate,
# then (record, packet) pairs each prefixed by their two lengths. Raw bytes
# exactly as they came off the wire, so a replay parses what the radio sent
# rather than something this script already interpreted.
# ─────────────────────────────────────────────

CAP_MAGIC = b"PDWCAP01"
CAP_HEADER = "<8sd"
CAP_ITEM = "<II"


def capture_open(path, fs):
    f = open(path, "wb")
    f.write(struct.pack(CAP_HEADER, CAP_MAGIC, float(fs)))
    return f


def capture_write(f, rec_raw, pkt_raw):
    f.write(struct.pack(CAP_ITEM, len(rec_raw), len(pkt_raw)))
    f.write(rec_raw)
    f.write(pkt_raw)
    f.flush()  # a session that dies mid-run still leaves everything before it


def capture_read(path):
    """-> (fs, [(record_bytes, packet_bytes), ...]). Strict: a truncated file
    raises rather than silently yielding the pairs it managed to read, because
    "the last pulse is missing" and "the last pulse is corrupt" need different
    answers and only one of them is a hardware problem."""
    with open(path, "rb") as f:
        blob = f.read()
    n = struct.calcsize(CAP_HEADER)
    if len(blob) < n:
        raise ValueError(f"{path}: too short to be a capture file")
    magic, fs = struct.unpack(CAP_HEADER, blob[:n])
    if magic != CAP_MAGIC:
        raise ValueError(f"{path}: bad magic {magic!r}, expected {CAP_MAGIC!r}")
    items, off, item_n = [], n, struct.calcsize(CAP_ITEM)
    while off < len(blob):
        if off + item_n > len(blob):
            raise ValueError(f"{path}: truncated item header at byte {off}")
        rec_n, pkt_n = struct.unpack(CAP_ITEM, blob[off : off + item_n])
        off += item_n
        if off + rec_n + pkt_n > len(blob):
            raise ValueError(
                f"{path}: item {len(items)} claims {rec_n}+{pkt_n} bytes but "
                f"only {len(blob) - off} remain"
            )
        items.append((blob[off : off + rec_n], blob[off + rec_n : off + rec_n + pkt_n]))
        off += rec_n + pkt_n
    return fs, items


# ─────────────────────────────────────────────
# Config arithmetic: host POLICY, i.e. how to turn a physically-described pulse
# into register values. The pdw_ctrl_t layout itself is generated, and every
# hardware FACT this needs comes from that generated module.
# ─────────────────────────────────────────────

# pulse_gen's frequency unit: a phase increment per sample in turns x 2^32.
TURNS_32 = 1 << 32

# THRESHOLDS ARE NOT IN RAW I^2+Q^2 UNITS. They are compared against
# `pulse_detect.power_t`, which carries POWER_FRAC_BITS fraction bits, so the
# integer written to threshold_high/threshold_low is that many bits' worth of
# scaling above the intended power. POWER_FRAC_BITS is exported by the design
# rather than restated here, because getting it wrong does not fail loudly: too
# small is crossed by the noise floor and the detector declares one endless
# pulse, too large is never crossed and the device looks simply dead.
POWER_SCALE = 1 << POWER_FRAC_BITS

# The uint32_t port width then caps usable power at 2**32 / POWER_SCALE, i.e. a
# rail amplitude just over 1024. Past that both threshold_high and the record's
# peak_power wrap silently, so amplitude is range-checked rather than trusted.
# Derived, not hardcoded -- it moves if the design's fixed-point format does.
MAX_AMPLITUDE = int(((1 << 32) // POWER_SCALE) ** 0.5) - 1

# The detector's pipeline must drain between one pulse ending and the next
# beginning; ../pdw_tb.py asserts the same margin on every phase it drives.
IDLE_MARGIN = 64

# HOW LONG THIS HOST MAY STALL, in seconds, before the design corrupts itself.
# PKT_QUEUE_DEPTH completed pulses may await release at once; the next one loses
# its descriptor, which orphans its beats in the data FIFO and offsets every
# later packet permanently, with nothing in-band to say so. So the pulse rate is
# not a throughput choice, it is the thing that buys the time this script needs
# to do an FFT and print. `build_config` refuses a rate that leaves less than
# MIN_HEADROOM_S, and the capture loop measures what it actually uses against
# what it asked for.
MIN_HEADROOM_S = 1.0
WANT_HEADROOM_S = 2.0


def queue_headroom_s(pulses_per_sec):
    """Seconds this host may stall before a descriptor is dropped."""
    return PKT_QUEUE_DEPTH / float(pulses_per_sec)


def build_config(
    fs,
    pulses_per_sec=4.0,
    pulse_width_s=4e-6,
    amplitude=800,
    freq_frac=0.125,
    chirp_rate=0,
    noise_amp=0,
    loopback=True,
    threshold_scale=0.6,
    alarm=False,
    alarm_test=False,
):
    """A physically-described pulse -> a `pdw_ctrl_t` config dict.

    `fs` is the sample rate in Hz; the generator counts in samples, so every
    time-domain argument is converted here rather than by the caller.

    THRESHOLDS. `threshold_high` is set to `threshold_scale` of the pulse's
    expected linear power and `threshold_low` to half that -- the same 0.6/0.3
    ratio ../pdw_tb.py calibrates its own phases with. "Expected power" is
    `amplitude**2`, since the generator's NCO emits a constant-magnitude
    carrier at that peak I/Q amplitude, SCALED BY POWER_SCALE because that is
    the fixed-point format the comparison actually happens in -- see the
    constant. Note the direction of any residual error is safe: underestimating
    the power makes the thresholds more permissive and the pulse is still
    detected, whereas overestimating would silently detect nothing.

    AMPLITUDE IS CAPPED near 1024, not by the int16 rail but by that same
    scaling: the uint32_t threshold ports and the record's `peak_power` both
    hold `power * 4096`, which overflows past a real power of 2^20. This is why
    ../pdw_tb.py runs its phases at amplitudes of 400-800 rather than anything
    near full scale.

    WIDTH QUALIFICATION. `min_width`/`max_width` are placed either side of the
    real width by a factor of four, so a correctly generated pulse is neither
    rejected as a glitch nor force-closed as CW, while both mechanisms stay
    live enough to reject a genuinely wrong pulse.

    PULSE RATE IS A CORRECTNESS CONSTRAINT, not a taste. See MIN_HEADROOM_S.
    """
    pri = int(round(fs / pulses_per_sec))
    width = int(round(fs * pulse_width_s))
    if width < 1:
        raise ValueError(
            f"pulse_width_s={pulse_width_s} is under one sample at fs={fs}"
        )
    if pri < width + IDLE_MARGIN:
        raise ValueError(
            f"pri ({pri}) must be >= width ({width}) + IDLE_MARGIN "
            f"({IDLE_MARGIN}); raise pulse_width_s or lower pulses_per_sec"
        )
    headroom = queue_headroom_s(pulses_per_sec)
    if headroom < MIN_HEADROOM_S:
        raise ValueError(
            f"pulses_per_sec={pulses_per_sec} leaves only {headroom:.2f} s of "
            f"queue headroom against a {PKT_QUEUE_DEPTH}-deep descriptor FIFO. "
            "A host that stalls longer than that loses a descriptor, which "
            "offsets every later packet permanently and reports nothing. Slow "
            "the pulse rate down."
        )
    if not -32768 <= amplitude <= 32767:
        raise ValueError(f"amplitude {amplitude} does not fit int16")
    if abs(amplitude) > MAX_AMPLITUDE:
        raise ValueError(
            f"amplitude {amplitude} exceeds MAX_AMPLITUDE ({MAX_AMPLITUDE}): "
            f"threshold_high would need {abs(amplitude) ** 2 * POWER_SCALE} "
            f"which overflows its uint32_t port, and the record's peak_power "
            f"would wrap. See POWER_SCALE."
        )

    # The field is int32 and `freq_frac` is a signed fraction of the sample
    # rate, so +-0.5 turns/sample (Nyquist) is the whole representable range.
    if not -0.5 <= freq_frac < 0.5:
        raise ValueError(f"freq_frac {freq_frac} is outside +-0.5 (Nyquist)")
    flags = CTRL_FLAG_LOOPBACK_EN if loopback else 0
    if alarm:
        flags |= CTRL_FLAG_ALARM_EN
    if alarm_test:
        # Ignored by the design unless ALARM_EN is set too, so setting it alone
        # would be a silent no-op.
        if not alarm:
            raise ValueError("alarm_test needs alarm=True -- see CTRL_FLAG_ALARM_TEST")
        flags |= CTRL_FLAG_ALARM_TEST
    expected_power = amplitude * amplitude
    return {
        "pulse_gen_pri": pri,
        "pulse_gen_width": width,
        "pulse_gen_freq": int(round(freq_frac * TURNS_32)),
        "pulse_gen_chirp_rate": chirp_rate,
        "pulse_gen_amplitude": amplitude,
        "pulse_gen_noise_amp": noise_amp,
        "threshold_high": int(threshold_scale * expected_power * POWER_SCALE),
        "threshold_low": int(threshold_scale * 0.5 * expected_power * POWER_SCALE),
        "max_width": width * 4,
        "min_width": max(1, width // 4),
        "flags": flags,
    }


def describe(cfg, fs):
    """A config dict -> human-readable lines, for logs and --dry-run."""
    pri, width = cfg["pulse_gen_pri"], cfg["pulse_gen_width"]
    freq_turns = cfg["pulse_gen_freq"]  # already signed: the field is int32
    pps = fs / pri
    flag_names = []
    if cfg["flags"] & CTRL_FLAG_LOOPBACK_EN:
        flag_names.append("loopback")
    if cfg["flags"] & CTRL_FLAG_ALARM_EN:
        flag_names.append("alarm")
    if cfg["flags"] & CTRL_FLAG_ALARM_TEST:
        flag_names.append("alarm-test")
    return [
        f"PRI          {pri} samples ({pri / fs * 1e3:.3f} ms, "
        f"{pps:.3f} pulses/s)",
        f"width        {width} samples ({width / fs * 1e6:.3f} us)",
        f"carrier      {freq_turns / TURNS_32 * fs / 1e6:+.4f} MHz "
        f"({freq_turns / TURNS_32:+.6f} turns/sample)",
        f"chirp rate   {cfg['pulse_gen_chirp_rate']}",
        f"amplitude    {cfg['pulse_gen_amplitude']}  "
        f"(noise {cfg['pulse_gen_noise_amp']})",
        # Shown in both forms, because the raw integers are 4096x the power
        # they mean and a reviewer checking them against an amplitude would
        # otherwise conclude they are wildly wrong.
        f"thresholds   hi {cfg['threshold_high']}  lo {cfg['threshold_low']}  "
        f"(= power {cfg['threshold_high'] / POWER_SCALE:.0f} / "
        f"{cfg['threshold_low'] / POWER_SCALE:.0f}, i.e. "
        f"{cfg['threshold_high'] / POWER_SCALE / max(1, cfg['pulse_gen_amplitude'] ** 2):.2f}"
        f"/{cfg['threshold_low'] / POWER_SCALE / max(1, cfg['pulse_gen_amplitude'] ** 2):.2f}"
        f" of amplitude^2)",
        f"width limits min {cfg['min_width']}  max {cfg['max_width']}",
        # Not decoration: this is the number that says how long this host may
        # stall before the design silently corrupts every later packet.
        f"queue        {queue_headroom_s(pps):.2f} s of headroom "
        f"({PKT_QUEUE_DEPTH} descriptors at {pps:.3f} pulses/s)",
        f"flags        0x{cfg['flags']:08x}"
        + ("  " + " ".join(flag_names) if flag_names else ""),
    ]


# ─────────────────────────────────────────────
# Record validation -- the framing's only safety net
# ─────────────────────────────────────────────


def validate_record(rec, cfg=None, prev_toa=None):
    """-> list of reasons this record cannot be trusted (empty means fine).

    Framing here is pure counting: read 40 bytes, believe `pkt_samples`, read
    that many. Nothing re-synchronises, so a single lost or extra byte makes
    every later read garbage while still looking exactly like data. These are
    the invariants that catch it, cheapest first.
    """
    bad = []
    # Four bytes of known zero in every record. Free, and the strongest single
    # signal that the stream has slipped.
    if rec["channel"] != 0:
        bad.append(f"channel is {rec['channel']}, must be 0 (single-channel design)")
    if rec["padding"] != 0:
        bad.append(f"padding is {rec['padding']}, must be 0")
    # Margins are unbuilt, so the packet is exactly the detected pulse. Two
    # independently-transmitted fields that must agree is a real check.
    if rec["pkt_samples"] != rec["pulse_width"]:
        bad.append(
            f"pkt_samples ({rec['pkt_samples']}) != pulse_width "
            f"({rec['pulse_width']}); they are equal while N_pre/N_post are unbuilt"
        )
    if not 0 < rec["pkt_samples"] <= PKT_FIFO_DEPTH:
        bad.append(
            f"pkt_samples ({rec['pkt_samples']}) is outside 1..{PKT_FIFO_DEPTH}, "
            "the data FIFO's depth -- no real packet can be longer"
        )
    # STATUS_PKT_FIFO_FULL is unreachable in a DELIVERED record: a packet that
    # loses beats is force-rejected by packet_store (`accept & ~new_bad`) and
    # flushed, so its record never leaves. Seeing the bit means the stream has
    # slipped, or the design changed and this comment is now wrong.
    if rec["status_flags"] & gr_pdw_record.STATUS_PKT_FIFO_FULL:
        bad.append(
            "status_flags has pkt_fifo_full set, which a delivered record "
            "cannot carry -- packet_store force-rejects any packet that lost "
            "beats, so this is a desync (or the design changed)"
        )
    known = 0
    for bit in gr_pdw_record.STATUS_NAMES:
        known |= bit
    if rec["status_flags"] & ~known:
        bad.append(f"status_flags has undefined bits set: 0x{rec['status_flags']:08x}")
    if cfg is not None:
        if rec["pulse_width"] < cfg["min_width"]:
            bad.append(
                f"pulse_width {rec['pulse_width']} is below min_width "
                f"{cfg['min_width']}; it would have been glitch-rejected"
            )
        if rec["pulse_width"] >= cfg["max_width"]:
            bad.append(
                f"pulse_width {rec['pulse_width']} reaches max_width "
                f"{cfg['max_width']}; it would have been CW-rejected"
            )
    if prev_toa is not None and rec["toa"] <= prev_toa:
        bad.append(
            f"toa {rec['toa']} did not advance past the previous {prev_toa}"
            " (toa restarts only across a reset)"
        )
    return bad


# ─────────────────────────────────────────────
# Stream I/O
# ─────────────────────────────────────────────


def read_exact(sdr, stream, n_elems, timeout_us, deadline_s, alarm_armed=False):
    """Read exactly `n_elems` CS16 elements, accumulating across partial reads.

    This is the load-bearing helper. readStream may return fewer elements than
    asked for -- at a DMA boundary, at a tlast if the driver ends a transfer
    there, or just because that is all that had arrived -- and it returns
    SOAPY_SDR_TIMEOUT rather than blocking forever when the pulse rate is slow.
    Looping here makes the caller correct under all of those without needing to
    know which one is happening.

    Deepwave documents that a tlast arriving before the requested count can
    raise a SoapySDR exception rather than returning short, so exceptions are
    caught as well as return codes -- a bare exception here would otherwise
    escape as a traceback from the middle of a capture.
    """
    import numpy as np
    import SoapySDR

    buf = np.empty(2 * n_elems, np.int16)
    got = 0
    end = time.time() + deadline_s
    while got < n_elems:
        view = buf[2 * got :]
        try:
            sr = sdr.readStream(stream, [view], n_elems - got, timeoutUs=timeout_us)
        except Exception as e:  # noqa: BLE001 - see the docstring
            raise StreamDesync(
                f"readStream raised after {got}/{n_elems} elements ({e}). A "
                "tlast short of the requested count does this; the stream "
                "position is now unknown."
            ) from e
        ret = sr.ret
        if ret > 0:
            got += ret
        elif ret == SoapySDR.SOAPY_SDR_TIMEOUT:
            if time.time() > end:
                raise StreamTimeout(f"got {got}/{n_elems} elements before the deadline")
        elif ret == SoapySDR.SOAPY_SDR_OVERFLOW:
            # Two causes, one code. Either the host fell behind, or -- if the
            # alarm is armed -- the design deliberately dropped ADC samples to
            # report an internal error it has no other way to tell us about.
            # The right response is the same either way (resync: a descriptor
            # drop is permanent), so the distinction is in what we say, not in
            # what we do.
            raise StreamDesync(
                "readStream reported OVERFLOW after "
                f"{got}/{n_elems} elements. "
                + (
                    "The alarm is armed, so this is most likely the DESIGN "
                    "reporting an internal error (a dropped descriptor or "
                    "measurement) -- which has already corrupted the packet "
                    "stream. Either way the alignment is lost."
                    if alarm_armed
                    else "The host fell behind and the stream alignment is "
                    "lost. Lower --pulses-per-sec or shorten --pulse-us."
                )
            )
        else:
            raise RuntimeError(f"readStream failed: {SoapySDR.errToStr(ret)} ({ret})")
    return buf


def write_frame(sdr, stream, raw, timeout_us=1_000_000):
    """Write one AXIS frame, tlast on its final beat via END_BURST."""
    import SoapySDR

    buf = bytes_to_cs16(raw)
    n = len(raw) // BYTES_PER_ELEM
    rc = sdr.writeStream(
        stream, [buf], n, flags=SoapySDR.SOAPY_SDR_END_BURST, timeoutUs=timeout_us
    )
    ret = rc.ret if hasattr(rc, "ret") else rc
    if ret != n:
        raise RuntimeError(
            f"writeStream wrote {ret} of {n} elements"
            + (f": {SoapySDR.errToStr(ret)}" if ret < 0 else "")
        )
    return ret


class RadioSource:
    """Records and packets from a live radio."""

    def __init__(self, sdr, rx_pdw, rx_pkt, args, alarm_armed):
        self.sdr, self.rx_pdw, self.rx_pkt = sdr, rx_pdw, rx_pkt
        self.args, self.alarm_armed = args, alarm_armed
        self.deadline = max(4.0, 4.0 / args.pulses_per_sec)

    def record(self):
        buf = read_exact(
            self.sdr, self.rx_pdw, RECORD_ELEMS, self.args.timeout_us,
            self.deadline, self.alarm_armed,
        )
        return cs16_to_bytes(buf, RECORD_ELEMS)

    def packet(self, n_elems):
        buf = read_exact(
            self.sdr, self.rx_pkt, n_elems, self.args.timeout_us,
            self.deadline, self.alarm_armed,
        )
        return buf, cs16_to_bytes(buf, n_elems)


class ReplaySource:
    """The same two calls, served from a `--record` file. No SoapySDR, no
    numpy beyond what pdw_verify already needs -- which is what makes the
    capture loop testable without hardware."""

    def __init__(self, path):
        self.fs, self.items = capture_read(path)
        self.i = 0

    def record(self):
        if self.i >= len(self.items):
            raise EndOfCapture(f"capture file held {len(self.items)} pulses")
        return self.items[self.i][0]

    def packet(self, n_elems):
        import numpy as np

        _rec_raw, pkt_raw = self.items[self.i]
        self.i += 1
        if len(pkt_raw) != n_elems * BYTES_PER_ELEM:
            raise StreamDesync(
                f"capture item {self.i - 1}: record says {n_elems} samples "
                f"({n_elems * BYTES_PER_ELEM} bytes) but {len(pkt_raw)} were stored"
            )
        return np.frombuffer(pkt_raw, dtype="<i2"), pkt_raw


WEDGE_HELP = """
The packet path is wedged, not merely slow.

packet_store's FSM is IDLE -> WAIT_MEAS -> EMIT_PDW -> SEND_PKT. EMIT_PDW waits
on the PDW port's ready (RX1), but SEND_PKT waits on the broadcast interlock's
`all_sinks_ready` -- the AND of RX0's ready AND the TX1 replay leg's. So a TX1
that never asserts tready parks the FSM in SEND_PKT forever, and the signature
is exactly what just happened: one record arrived on RX1, then nothing at all
on RX0.

Try, in order:
  * confirm activateStream(TX,1) succeeded -- its reset also feeds global_rst
  * run with --prime-tx1 (the default) so a dummy burst starts that datapath
  * in the bitstream wrapper, tie tx1_m_axis_tready HIGH; the design documents
    this tie-off for exactly the case where the replay port is unused
""".strip()

SILENCE_HELP = """
No records at all, which is the one symptom this design cannot narrow down on
its own -- there is no RX2 in 2-channel mode, so a rejected pulse and a dead
design look identical from here. Work down README.md's bring-up ladder rather
than guessing; in cost order the causes are:

  * a channel reset still asserted. global_rst is the OR of all seven, so
    rx2_m_axis_rst floating or held is enough. Check the wrapper tie-offs.
  * the configuration never landed, or was wiped. AirStack is documented to
    pulse dwd_tx_axis_rst between transmissions, and tx0's reset is what the
    control register file follows -- reverting it to CTRL_DEFAULTS, whose
    thresholds are 0xFFFFFFFF, which is indistinguishable from dead. Put a
    receiver on the TX0 SMA and look for the generator's pulse train: that is
    the one measurement that separates this cause from the others.
  * thresholds wrong by the x4096 scaling. --dry-run prints them both ways.
  * every pulse rejected as a glitch or as CW. Widen min_width/max_width.
  * the wrong bitstream, or none. Check rung 1.
""".strip()


def preflight(sdr, args):
    """Rung 1: identify the platform before believing anything below it."""
    import SoapySDR
    from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_TX

    print("-- preflight --")
    # The BitStream version is the one that matters: 2.1.0 is where AirStack
    # documents pulsing dwd_tx_axis_rst between transmissions, which is rung 3.
    try:
        info = sdr.getHardwareInfo()
    except Exception:  # noqa: BLE001 - informational only
        info = {}
    for key, value in sorted(info.items()):
        print(f"  {key:10s} {value}")
    try:
        print(f"  SoapySDR   {SoapySDR.getLibVersion()}")
    except Exception:  # noqa: BLE001
        pass

    fs = sdr.getSampleRate(SOAPY_SDR_RX, CH_PKT_RX)
    print(f"  rate       {fs / 1e6:.3f} MSPS")
    # Deepwave enforces that the sample rate equals the AXIS master clock, so a
    # mismatch is not a performance question -- every sample-derived number
    # this script prints would be wrong by that ratio.
    tx_fs = sdr.getSampleRate(SOAPY_SDR_TX, CH_CTRL_TX)
    if abs(tx_fs - fs) > 1.0:
        raise SystemExit(
            f"RX rate {fs} and TX rate {tx_fs} differ. The design is one clock "
            "domain; every derived time and frequency below would be wrong."
        )
    print(
        f"  queue      {queue_headroom_s(args.pulses_per_sec):.2f} s of headroom "
        f"at {args.pulses_per_sec} pulses/s ({PKT_QUEUE_DEPTH} descriptors)"
    )
    return fs


def resync(sdr, streams, active, cfg, args):
    """Reset the design and bring it back up, in the documented order.

    Used at startup so a crashed previous run cannot leave a half-open design,
    and after a desync so a soak survives one bad packet. Deactivating every
    stream asserts every channel reset, and global_rst is their OR -- so this
    is a full reset of the datapath, which is the only thing that clears a
    dropped descriptor.
    """
    for s in list(active):
        try:
            sdr.deactivateStream(s)
        except Exception:  # noqa: BLE001
            pass
    active.clear()
    # RST_MIN_HOLD_CYCLES (16448) at 125 MHz is ~132 us; the drain is only as
    # fast as the data, so a short reset leaves buffers partly full. Milliseconds
    # here cost nothing and remove the question.
    time.sleep(max(0.05, args.settle))

    tx_ctrl, tx_replay, rx_pkt, rx_pdw = streams
    sdr.activateStream(tx_ctrl)
    active.append(tx_ctrl)
    write_frame(sdr, tx_ctrl, pdw_ctrl_t.to_bytes(pdw_ctrl_t(**cfg)))
    time.sleep(args.settle)
    for s in (rx_pkt, rx_pdw, tx_replay):
        sdr.activateStream(s)
        active.append(s)
    if args.prime_tx1:
        try:
            write_frame(sdr, tx_replay, bytes(64 * BYTES_PER_ELEM))
        except Exception as e:  # noqa: BLE001 - priming is best-effort
            print(f"warning: TX{CH_REPLAY_TX} priming write failed ({e})")


def run(args):
    import SoapySDR
    from SoapySDR import SOAPY_SDR_CS16, SOAPY_SDR_RX, SOAPY_SDR_TX

    print("opening SoapyAIRT ...")
    sdr = SoapySDR.Device(dict(driver=args.driver))

    if args.rate:
        for d, ch in ((SOAPY_SDR_RX, CH_PKT_RX), (SOAPY_SDR_TX, CH_CTRL_TX)):
            sdr.setSampleRate(d, ch, args.rate)
    fs = preflight(sdr, args)
    if args.stage == "preflight":
        print("\nstage=preflight: stopping here")
        return 0
    if args.freq:
        sdr.setFrequency(SOAPY_SDR_RX, CH_PKT_RX, args.freq)
        sdr.setFrequency(SOAPY_SDR_TX, CH_CTRL_TX, args.freq)

    cfg = build_cfg(args, fs)
    print()
    for line in describe(cfg, fs):
        print("  " + line)
    print()

    # --- streams: set every one up before activating any of them ---------
    tx_ctrl = sdr.setupStream(SOAPY_SDR_TX, SOAPY_SDR_CS16, [CH_CTRL_TX])
    tx_replay = sdr.setupStream(SOAPY_SDR_TX, SOAPY_SDR_CS16, [CH_REPLAY_TX])
    rx_pkt = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CS16, [CH_PKT_RX])
    rx_pdw = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CS16, [CH_PDW_RX])
    streams = [tx_ctrl, tx_replay, rx_pkt, rx_pdw]
    active = []

    try:
        # --- step 2: the control channel, alone ---------------------------
        print(f"activating TX{CH_CTRL_TX} (control) -- datapath stays held")
        sdr.activateStream(tx_ctrl)
        active.append(tx_ctrl)

        # --- step 3: configure while the datapath is still in reset -------
        raw = pdw_ctrl_t.to_bytes(pdw_ctrl_t(**cfg))
        print(
            f"writing {len(raw)}-byte pdw_ctrl_t frame ({CTRL_ELEMS} beats, END_BURST)"
        )
        write_frame(sdr, tx_ctrl, raw)
        time.sleep(args.settle)
        if args.stage == "ctrl":
            print(
                "\nstage=ctrl: stopping here. The frame was accepted; whether it\n"
                "SURVIVED is rung 3 and cannot be read back -- put a receiver on\n"
                "the TX0 SMA and look for the generator's pulse train."
            )
            return 0

        # --- step 4: release the datapath ---------------------------------
        print(
            f"activating RX{CH_PKT_RX} (packets), RX{CH_PDW_RX} (records), "
            f"TX{CH_REPLAY_TX} (replay)"
        )
        for s in (rx_pkt, rx_pdw, tx_replay):
            sdr.activateStream(s)
            active.append(s)

        if args.prime_tx1:
            # The replay leg's tready gates the packet release path through the
            # broadcast interlock. A short dummy burst starts that datapath.
            # Requires dwd_tx1_m_axis_tready tied HIGH in the wrapper, since
            # this design has no tx1 slave port to consume it.
            n = 64
            try:
                write_frame(sdr, tx_replay, bytes(n * BYTES_PER_ELEM))
                print(f"primed TX{CH_REPLAY_TX} with {n} dummy elements")
            except Exception as e:  # noqa: BLE001 - priming is best-effort
                print(
                    f"warning: TX{CH_REPLAY_TX} priming write failed ({e});"
                    " continuing -- see --no-prime-tx1"
                )
        if args.stage == "streams":
            print("\nstage=streams: every channel is open; stopping before capture")
            return 0

        print()
        armed = bool(cfg["flags"] & CTRL_FLAG_ALARM_EN)
        source = RadioSource(sdr, rx_pdw, rx_pkt, args, armed)
        return capture(
            source, cfg, fs, args,
            reset=lambda: resync(sdr, streams, active, cfg, args),
        )

    finally:
        for s in active:
            try:
                sdr.deactivateStream(s)
            except Exception:  # noqa: BLE001 - teardown must not mask errors
                pass
        for s in streams:
            try:
                sdr.closeStream(s)
            except Exception:  # noqa: BLE001
                pass


def capture(source, cfg, fs, args, reset=None):
    """Read records and their packets, verify each, report. Radio or replay."""
    records = []
    prev_toa = None
    n_failed = n_resync = 0
    slowest = 0.0
    cap = capture_open(args.record, fs) if args.record else None
    headroom = queue_headroom_s(args.pulses_per_sec)
    end_at = time.time() + args.duration if args.duration else None

    i = 0
    try:
        while True:
            if end_at is None and i >= args.pulses:
                break
            # A resync does not advance `i`, so a fault that reappears
            # immediately after every reset would otherwise spin here forever
            # -- and with --duration unset there is no time bound to stop it.
            # Repeated resyncs mean the fault is not transient, which is worth
            # saying rather than retrying.
            if n_resync > args.max_resyncs:
                print(
                    f"giving up after {args.max_resyncs} resyncs -- the fault "
                    "returns immediately, so it is not the transient kind a "
                    "reset fixes"
                )
                break
            if end_at is not None and time.time() > end_at:
                break
            t0 = time.time()
            try:
                raw_rec = source.record()
            except EndOfCapture as e:
                print(f"replay complete ({e})")
                break
            except StreamTimeout as e:
                print(f"pulse {i}: no PDW record ({e})")
                if i == 0:
                    print("\n" + SILENCE_HELP)
                n_failed += 1
                break
            except StreamDesync as e:
                print(f"pulse {i}: {e}")
                n_failed += 1
                if reset and args.resync_on_error:
                    n_resync += 1
                    print("  resyncing ...")
                    reset()
                    prev_toa = None
                    continue
                break

            rec = valid_pdw_t.from_bytes(raw_rec)._asdict()
            bad = validate_record(rec, cfg=cfg, prev_toa=prev_toa)
            if bad:
                print(f"pulse {i}: record failed validation, framing is lost:")
                for b in bad:
                    print(f"    {b}")
                n_failed += 1
                if reset and args.resync_on_error:
                    n_resync += 1
                    print("  resyncing ...")
                    reset()
                    prev_toa = None
                    continue
                break

            try:
                pkt_buf, pkt_raw = source.packet(rec["pkt_samples"])
            except StreamTimeout as e:
                print(f"pulse {i}: record received but its packet did not arrive ({e})")
                print("\n" + WEDGE_HELP)
                n_failed += 1
                break
            except StreamDesync as e:
                print(f"pulse {i}: {e}")
                n_failed += 1
                break

            if cap:
                capture_write(cap, raw_rec, pkt_raw)

            d = gr_pdw_record.decode(rec, fs)
            flags = gr_pdw_record.status_list(rec["status_flags"])
            print(
                f"pulse {i}: toa={rec['toa']} width={rec['pulse_width']} samples "
                f"({d['pulse_width_secs'] * 1e6:.3f} us) "
                f"peak={d['pulse_power_db']:.2f} dBFS "
                f"snr={d['snr_db']:.2f} dB "
                f"freq={d['freq_start_hz'] / 1e6:+.4f} MHz "
                f"pri={d['pri_secs'] * 1e3:.3f} ms"
            )
            print(
                f"    packet: {rec['pkt_samples']} samples, "
                f"{len(pkt_buf) // 2} read"
                + (f"  status: {', '.join(flags)}" if flags else "")
            )
            if "pri_invalid" in flags and i > 0:
                print(
                    "    NOTE: pri_invalid after the first pulse means the "
                    "design reset between pulses -- toa restarted too"
                )
            if "dsp_overflow" in flags:
                print(
                    "    NOTE: dsp_overflow is STICKY until reset. It says the "
                    "detector overflowed at some point, not that this pulse did"
                )

            rows = pdw_verify.check(rec, pkt_buf, fs, cfg=cfg, prev_toa=prev_toa)
            for line in pdw_verify.format_rows(rows):
                print(line)
            if not pdw_verify.all_ok(rows):
                n_failed += 1

            prev_toa = rec["toa"]
            records.append(rec)
            dt = time.time() - t0
            slowest = max(slowest, dt)
            print()
            i += 1
    finally:
        if cap:
            cap.close()

    print(f"{len(records)} pulses captured, {n_failed} with failures", end="")
    print(f", {n_resync} resyncs" if n_resync else "")
    if slowest and not isinstance(source, ReplaySource):
        # The measurement that says whether the pulse rate was actually safe.
        # Descriptors queue while this host is busy; PKT_QUEUE_DEPTH of them is
        # all there is, and exceeding it corrupts silently.
        margin = headroom / slowest if slowest else float("inf")
        note = "" if margin >= 2 else "  <-- TOO CLOSE, slow --pulses-per-sec down"
        print(
            f"slowest iteration {slowest * 1000:.1f} ms against {headroom:.2f} s "
            f"of queue headroom ({margin:.0f}x margin){note}"
        )
    if args.record:
        print(f"wrote {args.record} -- replay it with --replay {args.record}")
    if records and args.csv:
        n = gr_pdw_record.write_csv(args.csv, records, fs, args.ref_level_db)
        print(f"wrote {n} rows to {args.csv} in gr-pdw's column order")
    return n_failed


def build_cfg(args, fs):
    return build_config(
        fs,
        pulses_per_sec=args.pulses_per_sec,
        pulse_width_s=args.pulse_us * 1e-6,
        amplitude=args.amplitude,
        freq_frac=args.freq_frac,
        chirp_rate=args.chirp_rate,
        noise_amp=args.noise_amp,
        loopback=args.loopback,
        threshold_scale=args.threshold_scale,
        alarm=args.alarm,
        alarm_test=args.alarm_test,
    )


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--driver", default="SoapyAIRT")
    p.add_argument(
        "--rate",
        type=float,
        default=0.0,
        help="sample rate in Hz; 0 = leave the radio's current rate",
    )
    p.add_argument(
        "--freq",
        type=float,
        default=0.0,
        help="RF centre frequency in Hz; 0 = leave as-is",
    )
    p.add_argument("--pulses", type=int, default=10)
    p.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="soak for this many seconds instead of stopping after --pulses",
    )
    p.add_argument(
        "--pulses-per-sec",
        type=float,
        default=4.0,
        help="slow BY NECESSITY, not by taste: only PKT_QUEUE_DEPTH (16) "
        "completed pulses may await release, and the next one loses its "
        "descriptor and offsets every later packet with no in-band sign. "
        "This rate is what buys the time to verify and print",
    )
    p.add_argument(
        "--pulse-us",
        type=float,
        default=4.0,
        help="pulse width. Kept well under the DC blocker's "
        "~1024-sample time constant so it does not erode the "
        "measured peak power",
    )
    p.add_argument("--amplitude", type=int, default=800,
                   help="peak I/Q amplitude. Capped near 1024 (not by the int16 "
                        "rail but by the uint32 threshold/peak_power ports, which "
                        "hold power x 4096) -- see POWER_SCALE")
    p.add_argument(
        "--freq-frac",
        type=float,
        default=0.125,
        help="carrier as a fraction of fs, -0.5..0.5",
    )
    p.add_argument(
        "--chirp-rate",
        type=int,
        default=0,
        help="non-zero makes freq_start differ from freq_stop, which "
        "turns that pair into a real check rather than a duplicate",
    )
    p.add_argument("--noise-amp", type=int, default=0)
    p.add_argument("--threshold-scale", type=float, default=0.6)
    p.add_argument(
        "--no-loopback",
        dest="loopback",
        action="store_false",
        help="feed the detector from RX0 instead of the internal "
        "generator (needs a real TX->RX path)",
    )
    p.add_argument(
        "--no-prime-tx1",
        dest="prime_tx1",
        action="store_false",
        help="skip the dummy write that starts the replay datapath",
    )
    p.add_argument(
        "--alarm",
        action="store_true",
        help="arm the internal-error alarm (CTRL_FLAG_ALARM_EN). The design "
        "then drops ADC samples on purpose when it detects an error it has no "
        "other way to report, which software sees as a receive overflow",
    )
    p.add_argument(
        "--alarm-test",
        action="store_true",
        help="fire one alarm immediately, to prove the signalling path works "
        "while everything else is known good (rung 6). Needs --alarm",
    )
    p.add_argument(
        "--stage",
        choices=("preflight", "ctrl", "streams", "capture"),
        default="capture",
        help="stop after this bring-up rung, so a failure is localised "
        "instead of reported from the bottom of the capture loop",
    )
    p.add_argument(
        "--resync-on-error",
        action="store_true",
        help="on a desync, reset the design and start over rather than "
        "stopping -- for soaks. Every resync restarts toa and loses the "
        "pulses in flight",
    )
    p.add_argument(
        "--max-resyncs",
        type=int,
        default=5,
        help="stop after this many resyncs; a fault that returns immediately "
        "after every reset is not the transient kind a reset fixes",
    )
    p.add_argument(
        "--settle",
        type=float,
        default=0.05,
        help="seconds between the config write and releasing the datapath",
    )
    p.add_argument("--timeout-us", type=int, default=500_000)
    p.add_argument("--csv", default=None, help="write gr-pdw's nine columns here")
    p.add_argument(
        "--record",
        default=None,
        help="write every raw record and packet here, so a session that went "
        "wrong can be replayed and debugged off the radio",
    )
    p.add_argument(
        "--replay",
        default=None,
        help="run the whole capture loop over a --record file, with no radio",
    )
    p.add_argument(
        "--ref-level-db",
        type=float,
        default=0.0,
        help="added to the dBFS power columns, as gr-pdw's "
        "calibration-table block does",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="build and print the config frame, then exit without " "touching SoapySDR",
    )
    args = p.parse_args(argv)

    # build_config raises ValueError for the two mistakes worth refusing --
    # a threshold/amplitude that would overflow its port, and a pulse rate that
    # leaves less queue headroom than this host needs. Both are configuration
    # errors, so they get a sentence rather than a traceback.
    try:
        return _dispatch(args)
    except ValueError as e:
        raise SystemExit(f"configuration error: {e}")


def _dispatch(args):
    if args.dry_run:
        fs = args.rate or 125e6
        cfg = build_cfg(args, fs)
        raw = pdw_ctrl_t.to_bytes(pdw_ctrl_t(**cfg))
        print(f"dry run at fs = {fs / 1e6:.3f} MSPS")
        for line in describe(cfg, fs):
            print("  " + line)
        print(f"  frame: {len(raw)} bytes / {CTRL_ELEMS} CS16 elements")
        print(f"  raw:   {raw.hex()}")
        print(f"  record reads: {RECORD_ELEMS} elements each")
        print(
            f"  capture: {args.pulses} pulses at {args.pulses_per_sec}/s "
            f"= {args.pulses / args.pulses_per_sec:.1f} s"
        )
        return 0

    if args.replay:
        source = ReplaySource(args.replay)
        fs = args.rate or source.fs
        cfg = build_cfg(args, fs)
        print(f"replaying {args.replay}: {len(source.items)} pulses at "
              f"fs = {fs / 1e6:.3f} MSPS\n")
        return 1 if capture(source, cfg, fs, args) else 0

    return 1 if run(args) else 0


if __name__ == "__main__":
    sys.exit(main())
