"""Parse one design and analyze its type package with GHDL for issue #394."""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import PY_TO_LOGIC
import SYN
import VHDL


def test_host_namedtuples_do_not_emit_empty_records():
    design = os.path.join(os.path.dirname(__file__), "untyped_namedtuple_design.py")
    with tempfile.TemporaryDirectory(prefix="untyped_namedtuple_") as out_dir:
        previous_out_dir = SYN.SYN_OUTPUT_DIRECTORY
        SYN.SYN_OUTPUT_DIRECTORY = out_dir
        try:
            state = PY_TO_LOGIC.PARSE_FILE(design)
            VHDL.WRITE_C_DEFINED_VHDL_STRUCTS_PACKAGE(state)
            package = os.path.join(out_dir, "c_structs_pkg" + VHDL.VHDL_PKG_EXT)
            result = subprocess.run(
                ["ghdl", "-a", "--std=08", "-frelaxed", package],
                cwd=out_dir,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            fields = state.struct_to_field_type_dict
            assert "UntypedPair" not in fields
            assert "LinearRegression" not in fields
            assert fields["TypedPair"] == {"slope": "uint8_t", "intercept": "uint8_t"}
            (outer_name,) = [name for name in fields if name.startswith("outer_t_")]
            inner_name = fields[outer_name]["inner"]
            assert fields[inner_name] == {"value": "uint8_t"}
        finally:
            SYN.SYN_OUTPUT_DIRECTORY = previous_out_dir


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
