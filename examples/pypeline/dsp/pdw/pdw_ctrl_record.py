"""Host-side bridge: this FPGA's control register struct <-> plain bytes.

The mirror image of `gr_pdw_record.py`, for the other direction. That module
parses the 40-byte `valid_pdw_t` records the design emits; this one builds the
40-byte `pdw_ctrl_t` frames a host writes to configure it.

    build_config(...) -> dict  ->  pack()  ->  40 bytes  ->  tx0_s_axis_*
                                                             (one AXIS frame,
                                                              ten 32-bit beats)

WHY THIS EXISTS RATHER THAN IMPORTING PYPELINE. The design's own
`pdw_ctrl/pdw_ctrl.py` defines `pdw_ctrl_t`, and `pypeline.type_to_bytes()`
packs it -- that is what `../pdw_tb.py` uses, and it is the single source of
truth. But a radio running AirStack has SoapySDR and numpy, not a Pypeline
checkout, and dragging the whole compiler onto it to serialise eleven integers
would be silly. So this module carries the layout in pure `struct`, exactly as
`gr_pdw_record.py` already does for the record direction, and the three files a
host needs (`gr_pdw_record.py`, this, `pdw_verify.py`) copy across on their own.

THE DUPLICATION IS GUARDED, NOT TRUSTED. Two copies of a wire format drift, and
a drifted control frame is the worst kind of bug here: the deserializer would
still accept 40 well-formed bytes and quietly load the wrong fields into the
wrong registers. `pdw_host_types_test.py` runs in the repo, where Pypeline *is*
importable, and asserts byte-for-byte that `pack()` here agrees with
`type_to_bytes(pdw_ctrl_t, ...)` -- and that `CTRL_DEFAULTS` below matches the
hardware's own. If the struct changes and this file does not, that test fails.

FRAMING. The design instantiates its deserializer with `frame="one_per_packet"`
and `on_runt="discard"`, so a frame must be exactly 40 bytes with `tlast` on
its final beat: longer is truncated, shorter is thrown away. On AirStack that
is one `writeStream(..., flags=SOAPY_SDR_END_BURST)` of ten CS16 elements --
`END_BURST` is what produces the `tlast` cycle.
"""

import struct

# `pdw_ctrl_t` -- 320 bits / 40 bytes, little-endian, matching pdw_ctrl.py
# field for field and in order. Ten 32-bit AXIS beats.
#
# Widths are NOT arbitrary: `<` means no alignment padding, so the int16/uint16
# pair in the middle packs tight and the total is exactly 40. `type_to_bytes`
# emits each field as ceil(width/8) little-endian bytes in declaration order,
# which is what this format string reproduces.
CTRL_FORMAT = "<IIiihHIIIII"
CTRL_BYTES = struct.calcsize(CTRL_FORMAT)
assert CTRL_BYTES == 40, CTRL_BYTES

CTRL_FIELDS = (
    "pulse_gen_pri",  # uint32  PRI in samples
    "pulse_gen_width",  # uint32  pulse width in samples
    "pulse_gen_freq",  # int32   phase increment/sample, turns x 2^32
    "pulse_gen_chirp_rate",  # int32   added to that increment each pulse sample
    "pulse_gen_amplitude",  # int16   peak I/Q amplitude
    "pulse_gen_noise_amp",  # uint16  LFSR noise scale, 0 = off
    "threshold_high",  # uint32  hysteresis SM upper threshold
    "threshold_low",  # uint32  hysteresis SM lower threshold
    "max_width",  # uint32  Path A force-close cap AND CW rejection
    "min_width",  # uint32  glitch rejection
    "flags",  # uint32  CTRL_FLAG_* below
)

# `flags` bit assignments, mirroring pdw_ctrl.py.
CTRL_FLAG_LOOPBACK_EN = 1 << 0  # 1 = feed the detector from pulse_gen, not RX0

# Power-on / in-reset values, mirroring pdw_ctrl.py's CTRL_DEFAULTS.
#
# Note what this state is FOR: thresholds at maximum mean the hysteresis state
# machine cannot leave IDLE, so an unconfigured device emits nothing rather
# than emitting garbage. That is exactly the right behaviour for the window
# between the datapath leaving reset and the host's first write, which is why
# the bring-up sequence does not need it changed.
CTRL_DEFAULTS = {
    "pulse_gen_pri": 1,
    "pulse_gen_width": 0,
    "pulse_gen_freq": 0,
    "pulse_gen_chirp_rate": 0,
    "pulse_gen_amplitude": 0,
    "pulse_gen_noise_amp": 0,
    "threshold_high": 0xFFFFFFFF,
    "threshold_low": 0xFFFFFFFF,
    "max_width": 0xFFFFFFFF,
    "min_width": 0,
    "flags": 0,
}

# pulse_gen's frequency unit: a phase increment per sample in turns x 2^32.
# Multiply a fraction-of-sample-rate by this to get the field value, e.g.
# fs/8 -> int(0.125 * TURNS_32) == 1 << 29.
TURNS_32 = 1 << 32

# THRESHOLDS ARE NOT IN RAW I^2+Q^2 UNITS. They are compared against
# `detect_pulses.power_t` -- the DC-blocked, moving-averaged power estimate --
# which carries 12 fractional bits (dc_k=10 plus log2(ma_n=4)=2, both
# make_detect_pulses() defaults). So the integer written to threshold_high /
# threshold_low must be 4096x the intended power in magnitude's own units.
#
# Getting this wrong does not fail loudly, which is why it is a named constant
# with a range check below rather than a factor buried in an expression: a
# threshold 4096x too small is crossed by the noise floor and the detector
# declares one endless pulse, while 4096x too large is never crossed and the
# device looks simply dead. Both look like "the hardware is broken".
POWER_FRAC_BITS = 12
POWER_SCALE = 1 << POWER_FRAC_BITS

# The uint32_t port width then caps usable power at 2^32 / 4096 = 2^20, i.e. a
# rail amplitude of about 1024. Past that both threshold_high and the record's
# `peak_power` wrap silently (see pdw_engine.py's note on the truncation from
# the full 46-bit power_t), so amplitude is range-checked rather than trusted.
MAX_AMPLITUDE = 1023

# The detector's pipeline must drain between one pulse ending and the next
# beginning; ../pdw_tb.py asserts the same margin on every phase it drives.
IDLE_MARGIN = 64


def pack(cfg):
    """A config dict -> 40 bytes, ready to write as one AXIS frame."""
    missing = set(CTRL_FIELDS) - set(cfg)
    if missing:
        raise ValueError(f"pdw_ctrl_record.pack: missing fields {sorted(missing)}")
    return struct.pack(CTRL_FORMAT, *(cfg[f] for f in CTRL_FIELDS))


def unpack(data):
    """Inverse of `pack` -- used by tests and to echo back what was sent."""
    if len(data) != CTRL_BYTES:
        raise ValueError(
            f"pdw_ctrl_record.unpack: {len(data)} bytes, expected {CTRL_BYTES}"
        )
    return dict(zip(CTRL_FIELDS, struct.unpack(CTRL_FORMAT, data)))


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
        "flags": CTRL_FLAG_LOOPBACK_EN if loopback else 0,
    }


def describe(cfg, fs):
    """A config dict -> human-readable lines, for logs and --dry-run."""
    pri, width = cfg["pulse_gen_pri"], cfg["pulse_gen_width"]
    freq_turns = cfg["pulse_gen_freq"]  # already signed: the field is int32
    return [
        f"PRI          {pri} samples ({pri / fs * 1e3:.3f} ms, "
        f"{fs / pri:.3f} pulses/s)",
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
        f"flags        0x{cfg['flags']:08x}"
        + (" loopback" if cfg["flags"] & CTRL_FLAG_LOOPBACK_EN else ""),
    ]


if __name__ == "__main__":
    FS = 125e6
    cfg = build_config(FS)
    blob = pack(cfg)
    assert len(blob) == CTRL_BYTES, len(blob)
    assert unpack(blob) == cfg, "config round-trip failed"
    assert unpack(pack(CTRL_DEFAULTS)) == CTRL_DEFAULTS, "defaults round-trip failed"
    print(f"config frame: {CTRL_BYTES} bytes ({CTRL_BYTES // 4} AXIS beats)")
    for line in describe(cfg, FS):
        print("  " + line)
    print("  raw: " + blob.hex())
