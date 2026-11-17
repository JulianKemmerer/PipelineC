"""Enum defaults are legal package constants and retain their first encoding.

One shared-IR fixture covers both front ends, including C's signed/one-hot
enums. GHDL treats elaboration warnings as errors and checks nested defaults.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import LOGIC
import SYN
import VHDL


def test_enum_null_uses_first_declared_encoding():
    state = LOGIC.ParserState()
    # First need not mean zero, the smallest encoding, or bit zero.
    cases = [
        ("zero", "uint2_t", [0, 2], False),
        ("sparse", "uint4_t", [9, 1], False),
        ("negative", "int4_t", [-3, -7, 2], False),
        ("positive_signed", "int4_t", [5, -3], False),
        ("onehot", "uint41_t", [1 << 40, 1, 2], True),
    ]
    fields = {}
    checks = []
    for field, int_type, values, onehot in cases:
        enum_name = field + "_enum_t"
        info = LOGIC.EnumInfo()
        info.name = enum_name
        info.int_c_type = int_type
        info.id_to_int_val.update(
            (field + "_member_" + str(i), value) for i, value in enumerate(values)
        )
        state.enum_info_dict[enum_name] = info
        if onehot:
            state.marked_onehot.add(enum_name)
        fields[field] = enum_name
        width = LOGIC.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(int_type)
        bits = format(values[0] & ((1 << width) - 1), "0{}b".format(width))
        for prefix in ("bank_t_NULL", "outer_t_NULL.banks(0)", "outer_t_NULL.banks(1)"):
            checks.append(
                'assert std_logic_vector({}.{}) = "{}" severity failure;'.format(
                    prefix, field, bits
                )
            )
    state.struct_to_field_type_dict["bank_t"] = fields
    state.struct_to_field_type_dict["outer_t"] = {
        "banks": "bank_t[2]",
        "states": "sparse_enum_t[2]",
    }
    checks.extend(
        'assert outer_t_NULL.states({}) = "1001" severity failure;'.format(i)
        for i in range(2)
    )
    with tempfile.TemporaryDirectory(prefix="enum_null_") as out_dir:
        previous_out_dir = SYN.SYN_OUTPUT_DIRECTORY
        SYN.SYN_OUTPUT_DIRECTORY = out_dir
        try:
            VHDL.WRITE_C_DEFINED_VHDL_STRUCTS_PACKAGE(state)
        finally:
            SYN.SYN_OUTPUT_DIRECTORY = previous_out_dir
        Path(out_dir, "tb.vhd").write_text(
            "library ieee; use ieee.std_logic_1164.all; use ieee.numeric_std.all;\n"
            "use work.c_structs_pkg.all;\n"
            "entity tb is end; architecture test of tb is begin\n"
            "process begin\n" + "\n".join(checks) + "\nwait; end process; end;\n"
        )
        for args in (
            ["-a", "c_structs_pkg.pkg.vhd", "tb.vhd"],
            ["-e", "tb"],
            ["-r", "tb", "--assert-level=error"],
        ):
            result = subprocess.run(
                ["ghdl", args[0], "--std=08", "-Werror=elaboration"] + args[1:],
                cwd=out_dir,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
