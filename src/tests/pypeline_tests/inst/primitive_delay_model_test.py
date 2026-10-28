#!/usr/bin/env python3
"""SYN.PrimitiveDelayModel: built-in primitive delays at a new width are
estimated from the widths a tool/part has measured, and AUTO_FSM measures an
estimate only where it could change a fits-in-a-state decision.

On WireGuard's 256-bit build, 76 cold primitive runs (about 1.3 minutes each,
mostly Vivado start-up) took 1.6 hours. Leave-one-out over the same Vivado
logs predicted those delays within 0.04-0.20 ns median error."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../"))

import LOGIC
import SYN
import AUTO
import AUTO_FSM

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../")
VIVADO_200T = os.path.join(REPO, "cache/delay/vivado/xc7a200tffg1156-2/syn")


def _cache(entries):
    tmp = tempfile.mkdtemp(prefix="primitive_delay_model_test_")
    for name, delay_ns in entries.items():
        with open(os.path.join(tmp, name + ".delay"), "w") as f:
            f.write(str(delay_ns))
    return tmp


def test_names_parse_to_family_and_width():
    assert SYN.PRIMITIVE_DELAY_SHAPE("BIN_OP_PLUS_uint37_t_uint3_t") == ("PLUS", False, 37)
    assert SYN.PRIMITIVE_DELAY_SHAPE("BIN_OP_MINUS_int11_t_int11_t") == ("MINUS", True, 11)
    assert SYN.PRIMITIVE_DELAY_SHAPE("UNARY_OP_NOT_uint9_t") == ("NOT", False, 9)
    for name in (
        "BIN_OP_INFERRED_MULT_uint34_t_uint34_t",
        "BIN_OP_GT_uint8_t_uint8_t",
        "soft_cmp_prefix_n_leaves_3_level_6_s9c4ee2fa95a6",
        "MUX_uint8_t",
    ):
        assert SYN.PRIMITIVE_DELAY_SHAPE(name) is None, name


def test_fit_shapes_and_interpolation_only():
    model = SYN.PrimitiveDelayModel(_cache({
        # Linear in width
        "BIN_OP_PLUS_uint8_t_uint8_t": 1.4,
        "BIN_OP_PLUS_uint16_t_uint16_t": 1.8,
        "BIN_OP_PLUS_uint32_t_uint32_t": 2.6,
        # Linear in log2 width
        "BIN_OP_EQ_uint4_t_uint4_t": 1.2,
        "BIN_OP_EQ_uint16_t_uint16_t": 1.6,
        "BIN_OP_EQ_uint64_t_uint64_t": 2.0,
        # Constant
        "BIN_OP_AND_uint1_t_uint1_t": 1.019,
        "BIN_OP_AND_uint8_t_uint8_t": 1.019,
        "BIN_OP_AND_uint32_t_uint32_t": 1.019,
        # Too few widths for a fit
        "BIN_OP_XOR_uint1_t_uint1_t": 1.019,
        "BIN_OP_XOR_uint8_t_uint8_t": 1.019,
    }))
    delay, error = model.estimate("BIN_OP_PLUS_uint24_t_uint24_t")
    assert abs(delay - 2.2) < 1e-9 and error < 1e-9, (delay, error)
    delay, error = model.estimate("BIN_OP_EQ_uint32_t_uint32_t")
    assert abs(delay - 1.8) < 1e-9 and error < 1e-9, (delay, error)
    assert model.estimate("BIN_OP_AND_uint20_t_uint20_t") == (1.019, 0.0)
    # Never outside the measured widths, nor from too few of them, nor for a
    # signedness the fit never saw.
    assert model.estimate("BIN_OP_PLUS_uint64_t_uint64_t") is None
    assert model.estimate("BIN_OP_PLUS_uint4_t_uint4_t") is None
    assert model.estimate("BIN_OP_XOR_uint4_t_uint4_t") is None
    assert model.estimate("BIN_OP_PLUS_int16_t_int16_t") is None


def test_committed_vivado_cache_fits_within_the_reported_errors():
    model = SYN.PrimitiveDelayModel(VIVADO_200T)
    for family, worst_ns in ((("PLUS", False), 0.7), (("MINUS", False), 0.6),
                             (("EQ", False), 0.5), (("AND", False), 0.0)):
        assert family in model.fits, family
        error = model.fits[family][-1]
        assert error <= worst_ns + 1e-9, (family, error)
    # A cached width is predicted within that family's bound.
    with open(os.path.join(VIVADO_200T, "BIN_OP_PLUS_uint64_t_uint64_t.delay")) as f:
        measured = float(f.readline())
    delay, error = model.estimate("BIN_OP_PLUS_uint64_t_uint64_t")
    assert abs(delay - measured) <= error, (delay, measured, error)


def test_auto_fsm_measures_only_estimates_near_the_budget():
    parser_state = LOGIC.ParserState()
    for name, delay, estimated, model_error in (
        ("far", 40, True, 6),  # 4.0 ns + 1 ns mux against an 11.2 ns state
        ("near", 103, True, 6),  # 10.3 + 1 within 0.6 ns of 11.2
        ("derived", 40, True, None),  # a sum of children: always measured
        ("measured", 40, False, None),
    ):
        logic = LOGIC.Logic()
        logic.func_name = name
        logic.delay = delay
        logic.delay_is_estimated = estimated
        logic.delay_model_error = model_error
        parser_state.FuncLogicLookupTable[name] = logic
    budget_du = 112
    assert AUTO.MUX_PENALTY_DU == 10
    decide = AUTO_FSM._estimate_could_decide
    assert not decide(parser_state, "far", budget_du)
    assert decide(parser_state, "near", budget_du)
    assert decide(parser_state, "derived", budget_du)


if __name__ == "__main__":
    test_names_parse_to_family_and_width()
    test_fit_shapes_and_interpolation_only()
    test_committed_vivado_cache_fits_within_the_reported_errors()
    test_auto_fsm_measures_only_estimates_near_the_budget()
    print("All primitive delay model tests passed.")
