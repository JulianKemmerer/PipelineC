#!/usr/bin/env python3
"""Isolated wrapper selection, filename and emitted declaration agree.

No vendor tools run. Supply an entity at the real emission budget, append the
isolated-wrapper suffix through GET_TOP_ENTITY_NAME, and render its declaration
through the actual file-boundary naming pass. The backend must select that
declaration's name, and its input file must carry that same name.
"""

import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import AUTO_PIPELINE
import PY_TO_LOGIC
import SYN
import VHDL


def main():
    with tempfile.TemporaryDirectory() as out, patch.object(
        SYN, "SYN_OUTPUT_DIRECTORY", out
    ):
        ps = PY_TO_LOGIC.PARSE_FILE(
            str(Path(__file__).with_name("isolated_top_name_design.py"))
        )
        params = AUTO_PIPELINE.MultiMainTimingParams()
        params.TimingParamsLookupTable = (
            AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(ps)
        )
        for case, body, names in [
            ("short", "leaf_short", ps.pypeline_emission_names),
            ("long", "leaf_" + "x" * 235, ps.pypeline_emission_names),
            ("classic", "leaf_" + "x" * 235, None),
        ]:
            directory = Path(out) / case
            with patch.object(VHDL, "GET_ENTITY_NAME", return_value=body), patch.object(
                ps, "pypeline_emission_names", names
            ):
                selected = VHDL.GET_TOP_ENTITY_NAME(ps, params, "leaf")
                VHDL.WRITE_LOGIC_TOP(
                    "leaf",
                    ps.LogicInstLookupTable["leaf"],
                    str(directory),
                    ps,
                    params.TimingParamsLookupTable,
                )
            wrapper = next(directory.glob("*_top.vhd"))
            declared = re.search(r"entity (\w+) is", wrapper.read_text()).group(1)
            assert selected == declared == wrapper.stem, (
                f"Backend selects {len(selected)}-character top {selected}; "
                f"VHDL declares {len(declared)}-character top {declared}; "
                f"filename is {wrapper.name}"
            )


if __name__ == "__main__":
    main()
