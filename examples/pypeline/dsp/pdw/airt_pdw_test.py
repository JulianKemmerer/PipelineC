#!/usr/bin/env python3
"""Bring up the PDW design on a Deepwave AIR-T (AirStack) and verify its output.

NOT part of `run_all.py`. This needs SoapySDR and real hardware. What *is*
covered in-repo, with no radio, is everything it depends on: `pdw_host_types_test.py`
proves the control frame this script builds is byte-identical to what the
hardware's own deserializer expects, and `pdw_verify_test.py` proves the checks
below actually catch a wrong record. Run those before trusting a red result here.

COPY THESE FOUR FILES TO THE RADIO -- nothing else, and no Pypeline checkout:

    airt_pdw_test.py     this script
    pdw_ctrl_record.py   builds the pdw_ctrl_t config frame
    gr_pdw_record.py     parses valid_pdw_t records, and gr-pdw's columns
    pdw_verify.py        independent FFT check of a record against its samples

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

RF WARNING. With loopback enabled the detector is fed internally, but TX0 still
carries the generator's samples to the radio. Use a cable and terminator, not an
antenna.
"""

import argparse
import sys
import time

import gr_pdw_record
import pdw_ctrl_record
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
CTRL_ELEMS = pdw_ctrl_record.CTRL_BYTES // BYTES_PER_ELEM
RECORD_ELEMS = gr_pdw_record.RECORD_BYTES // BYTES_PER_ELEM


def bytes_to_cs16(raw):
    """Frame bytes -> the interleaved int16 buffer writeStream wants."""
    import numpy as np

    return np.frombuffer(raw, dtype="<i2").copy()


def cs16_to_bytes(buf, n_elems):
    """The first `n_elems` complex samples of a CS16 buffer -> frame bytes."""
    return buf[: 2 * n_elems].astype("<i2").tobytes()


class StreamTimeout(Exception):
    """readStream produced nothing within the deadline."""


def read_exact(sdr, stream, n_elems, timeout_us, deadline_s):
    """Read exactly `n_elems` CS16 elements, accumulating across partial reads.

    This is the load-bearing helper. readStream may return fewer elements than
    asked for -- at a DMA boundary, at a tlast if the driver ends a transfer
    there, or just because that is all that had arrived -- and it returns
    SOAPY_SDR_TIMEOUT rather than blocking forever when the pulse rate is slow.
    Looping here makes the caller correct under all of those without needing to
    know which one is happening.
    """
    import numpy as np
    import SoapySDR

    buf = np.empty(2 * n_elems, np.int16)
    got = 0
    end = time.time() + deadline_s
    while got < n_elems:
        view = buf[2 * got :]
        sr = sdr.readStream(stream, [view], n_elems - got, timeoutUs=timeout_us)
        ret = sr.ret
        if ret > 0:
            got += ret
        elif ret == SoapySDR.SOAPY_SDR_TIMEOUT:
            if time.time() > end:
                raise StreamTimeout(f"got {got}/{n_elems} elements before the deadline")
        elif ret == SoapySDR.SOAPY_SDR_OVERFLOW:
            # Host fell behind. Data has already been lost, so the byte-counted
            # framing is broken from here on: say so rather than limp along.
            raise RuntimeError(
                "readStream reported OVERFLOW -- the host fell behind and the "
                "stream alignment is lost. Lower --pulses-per-sec or shorten "
                "--pulse-us."
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


def run(args):
    import numpy as np
    import SoapySDR
    from SoapySDR import SOAPY_SDR_CS16, SOAPY_SDR_RX, SOAPY_SDR_TX

    print("opening SoapyAIRT ...")
    sdr = SoapySDR.Device(dict(driver=args.driver))

    if args.rate:
        for d, ch in ((SOAPY_SDR_RX, CH_PKT_RX), (SOAPY_SDR_TX, CH_CTRL_TX)):
            sdr.setSampleRate(d, ch, args.rate)
    fs = sdr.getSampleRate(SOAPY_SDR_RX, CH_PKT_RX)
    print(f"sample rate: {fs / 1e6:.3f} MSPS")
    if args.freq:
        sdr.setFrequency(SOAPY_SDR_RX, CH_PKT_RX, args.freq)
        sdr.setFrequency(SOAPY_SDR_TX, CH_CTRL_TX, args.freq)

    cfg = build_cfg(args, fs)

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
        raw = pdw_ctrl_record.pack(cfg)
        print(
            f"writing {len(raw)}-byte pdw_ctrl_t frame ({CTRL_ELEMS} beats, END_BURST)"
        )
        write_frame(sdr, tx_ctrl, raw)
        time.sleep(args.settle)

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

        print()
        return capture(sdr, rx_pdw, rx_pkt, cfg, fs, args)

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


def capture(sdr, rx_pdw, rx_pkt, cfg, fs, args):
    """Read `args.pulses` records, each followed by its own packet."""
    records = []
    prev_toa = None
    n_failed = 0
    deadline = max(4.0, 4.0 / args.pulses_per_sec)

    for i in range(args.pulses):
        try:
            rec_buf = read_exact(sdr, rx_pdw, RECORD_ELEMS, args.timeout_us, deadline)
        except StreamTimeout as e:
            print(f"pulse {i}: no PDW record ({e})")
            if i == 0:
                print(
                    "\nNo records at all. Check that every channel reset is "
                    "released (global_rst is the OR of all of them) and that "
                    "the thresholds suit the amplitude."
                )
            n_failed += 1
            break

        rec = gr_pdw_record.unpack_records(cs16_to_bytes(rec_buf, RECORD_ELEMS))[0]

        try:
            pkt_buf = read_exact(
                sdr, rx_pkt, rec["pkt_samples"], args.timeout_us, deadline
            )
        except StreamTimeout as e:
            print(f"pulse {i}: record received but its packet did not arrive ({e})")
            print("\n" + WEDGE_HELP)
            n_failed += 1
            break

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

        if "pkt_fifo_full" in flags:
            print(
                "    WARNING: this packet lost beats to a full FIFO -- the "
                "host is not draining fast enough"
            )

        rows = pdw_verify.check(rec, pkt_buf, fs, cfg=cfg, prev_toa=prev_toa)
        for line in pdw_verify.format_rows(rows):
            print(line)
        if not pdw_verify.all_ok(rows):
            n_failed += 1

        prev_toa = rec["toa"]
        records.append(rec)
        print()

    print(f"{len(records)} pulses captured, {n_failed} with failures")
    if records and args.csv:
        n = gr_pdw_record.write_csv(args.csv, records, fs, args.ref_level_db)
        print(f"wrote {n} rows to {args.csv} in gr-pdw's column order")
    return n_failed


def build_cfg(args, fs):
    return pdw_ctrl_record.build_config(
        fs,
        pulses_per_sec=args.pulses_per_sec,
        pulse_width_s=args.pulse_us * 1e-6,
        amplitude=args.amplitude,
        freq_frac=args.freq_frac,
        chirp_rate=args.chirp_rate,
        noise_amp=args.noise_amp,
        loopback=args.loopback,
        threshold_scale=args.threshold_scale,
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
        "--pulses-per-sec",
        type=float,
        default=4.0,
        help="slow by design: the packet FIFO holds ~16 pulses, so "
        "this leaves seconds of headroom before the host must read",
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
                        "hold power x 4096) -- see pdw_ctrl_record.POWER_SCALE")
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
        "--settle",
        type=float,
        default=0.05,
        help="seconds between the config write and releasing the datapath",
    )
    p.add_argument("--timeout-us", type=int, default=500_000)
    p.add_argument("--csv", default=None, help="write gr-pdw's nine columns here")
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

    if args.dry_run:
        fs = args.rate or 125e6
        cfg = build_cfg(args, fs)
        raw = pdw_ctrl_record.pack(cfg)
        print(f"dry run at fs = {fs / 1e6:.3f} MSPS")
        for line in pdw_ctrl_record.describe(cfg, fs):
            print("  " + line)
        print(f"  frame: {len(raw)} bytes / {CTRL_ELEMS} CS16 elements")
        print(f"  raw:   {raw.hex()}")
        print(f"  record reads: {RECORD_ELEMS} elements each")
        print(
            f"  capture: {args.pulses} pulses at {args.pulses_per_sec}/s "
            f"= {args.pulses / args.pulses_per_sec:.1f} s"
        )
        return 0

    return 1 if run(args) else 0


if __name__ == "__main__":
    sys.exit(main())
