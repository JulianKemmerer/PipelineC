"""Host-side bridge: this FPGA's PDW records -> gr-pdw's own PDW array.

gr-pdw (https://github.com/gtri/gr-pdw) writes each pulse as a row of nine
float64 columns, and ships a reader (`examples/pdw.py`) that turns those into
pandas / HDF5. This module produces exactly that array from what the hardware
emits, so gr-pdw's tooling works on FPGA output unmodified.

The FPGA does NOT emit gr-pdw's float64 rows directly, and pretending
otherwise would be silly: it emits a compact fixed-point record and this
module does the conversion, in the same place gr-pdw does its own scaling.

    FPGA (40-byte fixed-point record)  ->  unpack_records()  ->  to_gr_pdw_rows()
                                                                       |
                                             gr-pdw's pdw.py / pandas / HDF5

WHAT MAPS CLEANLY, AND WHAT DOES NOT
------------------------------------
Seven of gr-pdw's nine columns come straight across. Two need saying out loud:

* `pulse_power` / `noise_power` are dBFS here. gr-pdw computes
  `pulse_power = dbfs + ref_level`, where `ref_level` comes from its USRP
  calibration-table block. That block stays on the host; pass the same number
  as `ref_level_db` and the columns match. Uncalibrated, gr-pdw reports dBFS
  too, so leaving it at 0.0 is the honest default.

* `toa_course` / `toa_fine` are NOT a unix timestamp. gr-pdw's coarse column
  is integer unix seconds, taken from the host clock. This design has no PPS
  input and no time-of-day register, so its `toa` is a free-running count of
  samples since FPGA reset, split here at the sample rate purely so the two
  columns have their usual meaning relative to each other. It also carries a
  constant bias of the detector's DSP-chain latency (see ../README.md). Add
  `epoch_s` if you have a reference for when the counter started.

Nothing here imports numpy or h5py; `to_gr_pdw_rows()` returns plain lists,
and `to_numpy()` is available if numpy happens to be installed.
"""

import struct

# The hardware record: 320 bits / 40 bytes, little-endian, matching
# `valid_pdw_t` in pdw_engine/pdw_engine.py field for field. Ten 32-bit AXIS
# beats.
RECORD_FORMAT = "<QIIIIhhhhIHH"
RECORD_BYTES = struct.calcsize(RECORD_FORMAT)
assert RECORD_BYTES == 40, RECORD_BYTES

RECORD_FIELDS = (
    "toa",  # uint64  samples since reset (see the note above)
    "pulse_width",  # uint32  samples
    "peak_power",  # uint32  linear, power_t truncated
    "pkt_samples",  # uint32  beats in the released packet
    "pri",  # uint32  samples since the previous accepted pulse
    "peak_power_db",  # int16   Q8.8 dBFS
    "noise_power_db",  # int16   Q8.8 dBFS
    "freq_start",  # int16   turns x 2^16
    "freq_stop",  # int16   turns x 2^16
    "status_flags",  # uint32
    "channel",  # uint16
    "padding",  # uint16
)

# status_flags bits, mirroring pdw_engine.py.
STATUS_ADC_CLIP = 1 << 0
STATUS_DSP_OVERFLOW = 1 << 1
STATUS_PKT_FIFO_FULL = 1 << 2
STATUS_FREQ_DEGENERATE = 1 << 3
STATUS_PRI_INVALID = 1 << 4

STATUS_NAMES = {
    STATUS_ADC_CLIP: "adc_clip",
    STATUS_DSP_OVERFLOW: "dsp_overflow",
    STATUS_PKT_FIFO_FULL: "pkt_fifo_full",
    STATUS_FREQ_DEGENERATE: "freq_degenerate",
    STATUS_PRI_INVALID: "pri_invalid",
}

# gr-pdw's column order, from its pdw_to_file.py / the PDW-to-file slide.
GR_PDW_COLUMNS = (
    "pdw_channel",
    "pulse_width_samps",
    "pulse_width_secs",
    "pulse_power",
    "noise_power",
    "freq_start",
    "stop_freq",
    "toa_course",
    "toa_fine",
)

Q8_8 = 256.0  # dB fixed-point scale
TURNS = 65536.0  # frequency fixed-point scale (full int16 range = one circle)


def unpack_records(data):
    """Parse a byte string of back-to-back 40-byte records into dicts."""
    if len(data) % RECORD_BYTES:
        raise ValueError(
            f"gr_pdw_record: {len(data)} bytes is not a whole number of "
            f"{RECORD_BYTES}-byte records"
        )
    out = []
    for off in range(0, len(data), RECORD_BYTES):
        vals = struct.unpack_from(RECORD_FORMAT, data, off)
        out.append(dict(zip(RECORD_FIELDS, vals)))
    return out


def pack_record(rec):
    """Inverse of `unpack_records` for one record -- used by tests."""
    return struct.pack(RECORD_FORMAT, *(rec.get(f, 0) for f in RECORD_FIELDS))


def status_list(flags):
    """Human-readable status bits, e.g. ['adc_clip', 'pri_invalid']."""
    return [name for bit, name in sorted(STATUS_NAMES.items()) if flags & bit]


def decode(rec, fs, ref_level_db=0.0):
    """One record -> engineering units. `fs` is the sample rate in Hz."""
    return {
        "channel": rec["channel"],
        "toa_samples": rec["toa"],
        "toa_secs": rec["toa"] / fs,
        "pulse_width_samps": rec["pulse_width"],
        "pulse_width_secs": rec["pulse_width"] / fs,
        "pkt_samples": rec["pkt_samples"],
        "pri_samples": rec["pri"],
        "pri_secs": rec["pri"] / fs,
        "pulse_power_db": rec["peak_power_db"] / Q8_8 + ref_level_db,
        "noise_power_db": rec["noise_power_db"] / Q8_8 + ref_level_db,
        "snr_db": (rec["peak_power_db"] - rec["noise_power_db"]) / Q8_8,
        # Baseband frequency offset from the tuned centre, in Hz. Signed:
        # the estimator resolves the full +-fs/2.
        "freq_start_hz": rec["freq_start"] / TURNS * fs,
        "freq_stop_hz": rec["freq_stop"] / TURNS * fs,
        # Non-zero chirp rate is modulation on pulse (an LFM chirp).
        "chirp_rate_hz_per_s": (
            (rec["freq_stop"] - rec["freq_start"]) / TURNS * fs * fs / rec["pulse_width"]
            if rec["pulse_width"]
            else 0.0
        ),
        "peak_power_linear": rec["peak_power"],
        "status_flags": rec["status_flags"],
        "status": status_list(rec["status_flags"]),
    }


def to_gr_pdw_rows(records, fs, ref_level_db=0.0, epoch_s=0):
    """Records -> rows in gr-pdw's own 9-column order (see GR_PDW_COLUMNS).

    `epoch_s` is added to the coarse TOA column; supply the unix time the
    sample counter started if you have it, otherwise the column counts seconds
    since FPGA reset. See the module docstring.
    """
    rows = []
    for rec in records:
        toa = rec["toa"]
        rows.append(
            [
                float(rec["channel"]),
                float(rec["pulse_width"]),
                rec["pulse_width"] / fs,
                rec["peak_power_db"] / Q8_8 + ref_level_db,
                rec["noise_power_db"] / Q8_8 + ref_level_db,
                rec["freq_start"] / TURNS * fs,
                rec["freq_stop"] / TURNS * fs,
                float(int(toa // fs) + epoch_s),
                float(toa % fs),
            ]
        )
    return rows


def to_numpy(records, fs, ref_level_db=0.0, epoch_s=0):
    """`to_gr_pdw_rows` as an (N, 9) float64 array -- the shape gr-pdw's own
    reader produces. Requires numpy."""
    import numpy as np

    rows = to_gr_pdw_rows(records, fs, ref_level_db, epoch_s)
    return np.array(rows, dtype=np.float64).reshape((len(rows), 9))


def write_csv(path, records, fs, ref_level_db=0.0, epoch_s=0):
    """gr-pdw's nine columns as CSV, header included."""
    rows = to_gr_pdw_rows(records, fs, ref_level_db, epoch_s)
    with open(path, "w") as f:
        f.write(",".join(GR_PDW_COLUMNS) + "\n")
        for r in rows:
            f.write(",".join(repr(v) for v in r) + "\n")
    return len(rows)


if __name__ == "__main__":
    # Round-trip demonstration with one synthetic pulse: 1 us at 125 MSPS,
    # +fs/8 baseband, 55 dBFS peak over a 16 dBFS floor.
    FS = 125e6
    demo = {
        "toa": 375_000_123,
        "pulse_width": 125,
        "peak_power": 1 << 30,
        "pkt_samples": 125,
        "pri": 125_000,
        "peak_power_db": int(55.6 * Q8_8),
        "noise_power_db": int(16.2 * Q8_8),
        "freq_start": int(0.125 * TURNS),
        "freq_stop": int(0.125 * TURNS),
        "status_flags": 0,
        "channel": 0,
        "padding": 0,
    }
    blob = pack_record(demo)
    assert len(blob) == RECORD_BYTES
    (back,) = unpack_records(blob)
    assert back == demo, "record round-trip failed"
    d = decode(back, FS)
    print(f"record size: {RECORD_BYTES} bytes ({RECORD_BYTES * 8} bits)")
    print(f"  pulse width : {d['pulse_width_secs'] * 1e6:.3f} us")
    print(f"  power       : {d['pulse_power_db']:.2f} dBFS")
    print(f"  noise       : {d['noise_power_db']:.2f} dBFS  (SNR {d['snr_db']:.2f} dB)")
    print(f"  frequency   : {d['freq_start_hz'] / 1e6:+.3f} MHz")
    print(f"  PRI         : {d['pri_secs'] * 1e3:.3f} ms")
    print("gr-pdw row:")
    print("  " + ", ".join(f"{c}={v:g}" for c, v in
                           zip(GR_PDW_COLUMNS, to_gr_pdw_rows([back], FS)[0])))
