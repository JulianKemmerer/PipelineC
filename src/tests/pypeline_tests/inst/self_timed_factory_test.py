"""Construct the self-timed datapath when automatic latency queries are forbidden.

Reading an automatic component's latency during construction forces compiler
re-elaboration. The converters and PDW engine must build with no such reads;
only an explicit diagnostic get_latency() is allowed to request that value.
"""

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [
    str(ROOT / "src"),
    str(ROOT / "include/pypeline"),
    str(ROOT / "examples/pypeline/dsp/pdw"),
]
from pypeline import int16_t, int32_t
from fixed_point import make_fixed_t
from dsp import nco, lut_atan2, log2_db
from pulse_detect import make_pulse_detect
from pulse_extract import make_pulse_extract
from pulse_gen import make_pulse_gen


class _NoLatency:
    def __init__(self, core):
        self.core = core

    def __getattr__(self, name):
        if name == "latency":
            raise AssertionError("self-timed factory read automatic latency")
        return getattr(self.core, name)

    def __call__(self, *args, **kwargs):
        return self.core(*args, **kwargs)


def _guard(factory):
    def guarded(*args, **kwargs):
        block = factory(*args, **kwargs)
        return _NoLatency(block)

    return guarded


def test_factories_do_not_query_latency():
    with patch.object(
        nco, "make_auto_pipeline_ram", _guard(nco.make_auto_pipeline_ram)
    ), patch.object(
        lut_atan2, "make_auto_pipeline_ram", _guard(lut_atan2.make_auto_pipeline_ram)
    ), patch.object(
        log2_db, "make_auto_pipeline_ram", _guard(log2_db.make_auto_pipeline_ram)
    ):
        nco.make_lut_nco(int16_t)
        lut_atan2.make_lut_atan2(int32_t)
        log2_db.make_log2_db(make_fixed_t(34, 12, signed=True))
        make_pulse_gen()
        detector = make_pulse_detect()
        del detector.freq_latency
        engine = make_pulse_extract(detector, join_depth=64)
        assert engine.pulse_measure.join_depth == 64
        assert engine.pulse_measure.log_db.join_depth == 64
        assert engine.pulse_measure.log_db_noise.join_depth == 64
        if engine.pulse_measure.atan2_method == "rom":
            assert engine.pulse_measure.angle_unit.join_depth == 64
    print("self-timed factories build without automatic latency queries")


if __name__ == "__main__":
    test_factories_do_not_query_latency()
