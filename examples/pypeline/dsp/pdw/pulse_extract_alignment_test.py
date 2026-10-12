"""Candidate/frequency pairing with variable response delays and live noise.

The engine receives packets, candidates and ordered frequency responses from
independent schedules. No detector latency is provided. Compare released
records and every sample with a transaction oracle, including rejected pulses.
"""

import random

import pdw_paths  # noqa: F401
from pypeline import sim_call, sim_reset
from pulse_detect import make_pulse_detect
from pulse_extract import STATUS_FREQ_DEGENERATE, STATUS_PRI_INVALID, make_pulse_extract
from pulse_measure import golden_pulse_measure


def test_variable_frequency_completion():
    dp, _ = make_pulse_detect()
    # A latency-counting engine would fail to construct with this detector.
    del dp.freq_latency
    engine, _ = make_pulse_extract(dp, depth=256, n_pkts=32)
    rng = random.Random(9876)
    beats, candidates, responses = {}, {}, {}
    expected_records, expected_packets = [], []
    start, last_response, prev_toa, have_prev = 5, -1, 0, False
    for i in range(28):
        width = (3, 1, 4, 2, 8, 5, 3)[i % 7]
        toa = 1000 + start
        peak = (i + 1) * 171717
        noise = (i + 1) * 313
        # Quadrants, axes and zero vectors; each pulse has a distinct oracle.
        fre, fim = (i * 711 - 8000, 12000 - i * 1931) if i != 6 else (0, 0)
        lre, lim = (i * 193 - 2300, i * 137 - 777)
        end = start + width - 1
        packet = []
        for k in range(width):
            sample = (i * 100 + k + 1, -(i * 100 + k + 1))
            packet.append(sample)
            beats[start + k] = (sample, int(k == width - 1))
        candidates[end] = (toa, width, peak, noise)
        response_at = max(end + rng.randrange(0, 21), last_response + 1)
        last_response = response_at
        responses[response_at] = (fre, fim, lre, lim)
        if 3 <= width < 8:
            m = golden_pulse_measure(
                engine.pulse_measure,
                fre,
                fim,
                lre,
                lim,
                noise,
                peak,
                toa,
                prev_toa,
                have_prev,
            )
            flags = (STATUS_PRI_INVALID if not have_prev else 0) | (
                STATUS_FREQ_DEGENERATE if m["freq_degenerate"] else 0
            )
            expected_records.append(
                (
                    toa,
                    width,
                    peak,
                    width,
                    m["pri"],
                    m["peak_power_db"],
                    m["noise_power_db"],
                    m["freq_start"],
                    m["freq_stop"],
                    flags,
                )
            )
            expected_packets.append(packet)
            prev_toa, have_prev = toa, True
        start = end + rng.randrange(2, 5)

    sim_reset()
    records, packets, packet = [], [], []
    for c in range(last_response + 300):
        sample, last = beats.get(c, ((0, 0), 0))
        toa, width, peak, noise = candidates.get(c, (0, 0, 0, 999999))
        phasor = responses.get(c, (0, 0, 0, 0))
        o = sim_call(
            engine,
            gated_in=dp.gated_sample_t(
                data=dp.complex_t(
                    i=dp.rail_t(val=sample[0]), q=dp.rail_t(val=sample[1])
                ),
                valid=int(c in beats),
                last=last,
            ),
            pdw_in_if=dp.out_fwd_t(
                stream=dp.out_fwd_t.typeof("stream")(
                    data=dp.candidate_pdw_t(
                        toa=toa, pulse_width=width, peak_power=dp.power_t(val=peak)
                    ),
                    valid=int(c in candidates),
                )
            ),
            dsp_overflow=0,
            min_width=3,
            max_width=8,
            freq_acc=dp.freq_accum_t(
                first_re=phasor[0],
                first_im=phasor[1],
                last_re=phasor[2],
                last_im=phasor[3],
                valid=int(c in responses),
            ),
            noise_est=dp.noise_t(val=noise),
            pkt_out_if=engine.pkt_out_intrf.fb_t(1),
            pdw_out_if=engine.pdw_out_intrf.fb_t(1),
            rst=0,
        )
        assert not (o.fifo_full or o.desc_drop or o.meas_drop)
        if o.pdw_out_if.stream.valid:
            r = o.pdw_out_if.stream.data
            records.append(
                tuple(
                    int(getattr(r, field))
                    for field in (
                        "toa",
                        "pulse_width",
                        "peak_power",
                        "pkt_samples",
                        "pri",
                        "peak_power_db",
                        "noise_power_db",
                        "freq_start",
                        "freq_stop",
                        "status_flags",
                    )
                )
            )
        if o.pkt_out_if.stream.valid:
            b = o.pkt_out_if.stream.data
            packet.append((int(b.sample.i.val), int(b.sample.q.val)))
            if b.last:
                packets.append(packet)
                packet = []
    assert not packet
    assert records == expected_records, (records, expected_records)
    assert packets == expected_packets
    print(
        f"variable completion: {len(candidates)} candidates, {len(records)} records and exact packets"
    )


if __name__ == "__main__":
    test_variable_frequency_completion()
