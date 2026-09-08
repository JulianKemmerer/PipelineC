"""Host-side bridge: this FPGA's PDW records -> gr-pdw's own PDW array.

gr-pdw (https://github.com/gtri/gr-pdw) writes each pulse as a row of nine
float64 columns, and ships a reader (`examples/pdw.py`) that turns those into
pandas / HDF5. This module produces exactly that array from what the hardware
emits, so gr-pdw's tooling works on FPGA output unmodified.

The FPGA does NOT emit gr-pdw's float64 rows directly, and pretending
otherwise would be silly: it emits a compact fixed-point record and this
module does the conversion, in the same place gr-pdw does its own scaling.

    rx1_m_axis_* (40-byte frames)  ->  records_from_bytes()  ->  to_gr_pdw_rows()
                                                                    |
                                          gr-pdw's pdw.py / pandas / HDF5

These are literally the bytes on `rx1_m_axis_*`: one 40-byte frame per accepted
pulse, ten 32-bit beats, tlast on the last. No host-side reassembly beyond
concatenating a frame's beats is needed. `pdw_tb.py` feeds captured frames
straight into `records_from_bytes()` and compares field by field against its
golden model, so this module is checked against real hardware output rather than
only against the synthetic record in `__main__` below.

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

from pypeline_host_types import (
    STATUS_ADC_CLIP,
    STATUS_DSP_OVERFLOW,
    STATUS_FREQ_DEGENERATE,
    STATUS_PKT_FIFO_FULL,
    STATUS_PRI_INVALID,
    valid_pdw_t,
)

# THE LAYOUT LIVES IN THE GENERATED MODULE, NOT HERE. `pypeline_host_types.py`
# is written by every `pypelinec` build of ../top.py (and by pdw_host_gen.py
# without one), from the same leaf walk the hardware serializer is built from.
# This file used to carry `RECORD_FORMAT = "<QIIIIhhhhIHH"` and a hand-listed
# field tuple; the generator derives that string character for character, which
# is asserted in src/tests/pypeline_tests/inst/host_types_test.py.
#
# So parse with the generated type and convert once at the boundary:
#
#     rec = valid_pdw_t.from_bytes(raw)._asdict()
#
# The `_asdict()` is deliberate. Everything below takes a plain dict, and
# keeping it that way is what let this migration touch the layout and nothing
# else -- `decode`, `to_gr_pdw_rows` and pdw_verify.py are all unchanged.
RECORD_BYTES = valid_pdw_t.BYTE_LENGTH

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


def records_from_bytes(data):
    """Back-to-back record frames -> dicts, via the generated layout.

    The only place this file touches bytes. Splitting a buffer into frames is
    host convenience; the layout inside each one comes from `valid_pdw_t`.
    """
    if len(data) % RECORD_BYTES:
        raise ValueError(
            f"gr_pdw_record: {len(data)} bytes is not a whole number of "
            f"{RECORD_BYTES}-byte records"
        )
    return [
        valid_pdw_t.from_bytes(data[off : off + RECORD_BYTES])._asdict()
        for off in range(0, len(data), RECORD_BYTES)
    ]


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
    blob = valid_pdw_t.to_bytes(valid_pdw_t(**demo))
    assert len(blob) == RECORD_BYTES
    (back,) = records_from_bytes(blob)
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
