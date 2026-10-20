"""Ordered timing arcs, register writers, late selection and local scheduling."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

# Standalone compiler imports; all scratch data belongs to the test runner.
sys.path[:0] = [
    str(Path(__file__).resolve().parents[3]),
    str(Path(__file__).resolve().parents[4] / "include" / "pypeline"),
]

import AUTO_FSM
import SYN
import VIVADO


def design():
    nodes = {}
    for nid, entity, operand in (
        ("a", "add", ["in", "x"]),
        ("b", "multiply", ["node", "a"]),
    ):
        nodes[nid] = dict(
            kind="binop",
            entity=entity,
            op=dict(kind="binop", op="+"),
            operands=[operand],
            casts=[[]],
            port_types=["uint32_t"],
            out_type="uint32_t",
            delay_du=30,
            state=1,
            launch_state=1,
            end_du=30 if nid == "a" else 60,
            fu=entity,
        )
    schedule = dict(
        entity="auto_fsm_example_1234",
        nodes=nodes,
        fus=dict(add="add", multiply="multiply"),
    )
    provenance = dict(
        registers={
            "st_r": dict(role="control", node_ids=[], states=[0, 1]),
            "v0_r": dict(role="work", node_ids=["b"], states=[1]),
        },
        lines=[
            dict(line=20, kind="operand_mux", fu="add", node_ids=["a"], states=[1]),
            dict(line=22, kind="unit", fu="multiply", node_ids=["b"], states=[1]),
        ],
    )
    return schedule, provenance


def test_vivado_ordered_arcs_keep_carry_routing_and_endpoint_times():
    # Captured Vivado report layout, reduced to the relevant carry/data arcs.
    header = "    Location             Delay type                Incr(ns)  Path(ns)    Netlist Resource(s)"
    column = header.index("Netlist Resource")
    report = [
        "  Slack (VIOLATED) : -3.500ns  (required time - arrival time)",
        "  Source:                 top/auto_fsm_example_1234/st_r_reg/Q",
        "                            (rising edge-triggered cell FDRE clocked by clk {rise@0.000ns fall@6.250ns period=12.500ns})",
        "  Destination:            top/auto_fsm_example_1234/v0_r_reg/D",
        "                            (rising edge-triggered cell FDRE clocked by clk {rise@0.000ns fall@6.250ns period=12.500ns})",
        "  Requirement:            12.500ns",
        "  Data Path Delay:        16.000ns  (logic 5.920ns (37.0%) route 10.080ns (63.0%))",
        "  Logic Levels:           39 (CARRY4=9 LUT6=30)",
        header,
        "    SLICE_X0Y0           FDRE (Prop_fdre_C_Q)          0.200     0.200 r".ljust(
            column
        )
        + "top/auto_fsm_example_1234/st_r_reg/Q",
        "                         net (fo=223)                3.000     3.200".ljust(
            column
        )
        + "top/auto_fsm_example_1234/st_r",
        "    SLICE_X0Y1           CARRY4 (Prop_carry4_CI_CO)    0.100     3.300 r".ljust(
            column
        )
        + "top/auto_fsm_example_1234_py_l20_c3/carry/CO[3]",
        "                         data arrival time            16.000",
        "                         slack                       -3.500",
    ]
    parsed = VIVADO.PathReport("\n".join(report))
    assert parsed.path_delay_ns == 16.0
    assert len(parsed.path_elements) == 3, parsed.path_elements
    assert [row["arrival_ns"] for row in parsed.path_elements] == [0.2, 3.2, 3.3]
    assert "CARRY4" in parsed.path_elements[-1]["delay_type"]
    serialized = SYN.SERIALIZE_PATH_REPORT(parsed)
    schedule, provenance = design()
    row = AUTO_FSM._attribute_path(serialized, schedule, provenance)
    assert row["attributed"] and row["start_role"] == "control"
    assert row["node_ids"] == ["a", "b"] and row["states"] == [1]
    corrected = AUTO_FSM._corrected_timing_model(schedule, [row])
    assert corrected["select_arrivals"]["add"] == 33
    assert corrected["corrected_entity_delays"] == dict(add=80, multiply=80)


def test_vivado_coordinates_follow_the_fsm_instance_on_cells_only():
    # The FSM instance label carries its call site in the caller (line 79);
    # only coordinates after it name generated FSM lines. Net names may come
    # from a neighbouring module, so only cell arcs place a boundary.
    schedule, provenance = design()
    provenance["lines"].append(
        dict(line=79, kind="writeback", fu=None, node_ids=["b"], states=[1])
    )
    inst = "top/fsm_call_caller_py_l79_c8"
    path = dict(
        start_reg_name=inst + "/st_r_reg",
        end_reg_name=inst + "/v0_r_reg",
        path_delay_ns=9.5,
        path_elements=[
            dict(
                delay_type="FDRE (Prop_fdre_C_Q)",
                resource=inst + "/st_r_reg/Q",
                arrival_ns=0.2,
            ),
            dict(
                delay_type="net (fo=3, unplaced)",
                resource=inst + "/mult_py_l22_c1/x[0]",
                arrival_ns=1.0,
            ),
            dict(
                delay_type="CARRY4 (Prop_carry4_CI_CO)",
                resource=inst + "/add_py_l20_c3/carry/CO[3]",
                arrival_ns=2.0,
            ),
            dict(
                delay_type="LUT2 (Prop_lut2_I0_O)",
                resource=inst + "/mult_py_l22_c5/lut/O",
                arrival_ns=9.0,
            ),
        ],
    )
    row = AUTO_FSM._attribute_path(
        path, schedule, provenance, ["fsm_call_caller_py_l79_c8"]
    )
    assert row["attributed"]
    assert [(b["kind"], b["arrival_ns"]) for b in row["boundaries"]] == [
        ("operand_mux", 2.0),
        ("unit", 9.0),
    ]


def test_unit_stage_measurements_follow_the_elaborated_fsm_instance():
    # Endpoint names from a Poly1305 prologue build at cap 32: the FSM's
    # elaborated instance (named by its caller) holds the pinned multiply's
    # unit call at generated line 375. The state register launched a 20.2 ns
    # path into the unit's first stage, predicted at 10.9 ns. It is a
    # measurement of that placement; a path from another unit is not.
    fsm = "top/service_py_l49/compute_from_kernels_stream_auto_fsm_py_l97_c8_ec14"
    unit = fsm + "/auto_fsm_selected_unit_4ffd_compute_from_kernels_py_l375_c19_ec62"
    schedule = dict(
        entity="auto_fsm_compute_089210db",
        fus={"mul": "residue_mul_mod", "add": "add"},
        implementations={
            "residue_mul_mod": dict(placement_digest="5c58", worst_stage_du=109)
        },
    )
    provenance = dict(
        lines=[
            dict(line=375, kind="unit", fu="mul", node_ids=["m"], states=[11]),
            dict(line=380, kind="unit", fu="add", node_ids=["s"], states=[11]),
        ]
    )
    stage0 = (
        unit + "/v_af_unit5_py_l5/karatsuba_py_l53/REG_STAGE0_minus_left_reg[130]/D"
    )
    observation = dict(
        paths=[
            dict(
                start_reg_name=fsm + "/st_r_reg[1]/C",
                end_reg_name=stage0,
                path_delay_ns="20.185",
            ),
            dict(
                start_reg_name=fsm + "/add_u_py_l380_c3/out_reg/C",
                end_reg_name=stage0,
                path_delay_ns="30.0",
            ),
            dict(
                start_reg_name=fsm + "/st_r_reg[0]/C",
                end_reg_name=fsm + "/v2_r_reg[66]/D",
                path_delay_ns="12.73",
            ),
        ]
    )
    aliases = [fsm.rsplit("/", 1)[1]]
    measured = AUTO_FSM._unit_measurements(observation, schedule, provenance, aliases)
    assert set(measured) == {"5c58"}, measured
    assert measured["5c58"]["worst_stage_du"] == 202
    assert [row["launch"] for row in measured["5c58"]["paths"]] == [True]
    assert not AUTO_FSM._unit_measurements(observation, schedule, provenance, [])
    profile = dict(placement_digest="5c58", worst_stage_du=109, latency=5)
    assert AUTO_FSM._with_measurements(profile, measured)["worst_stage_du"] == 202
    assert (
        AUTO_FSM._with_measurements(dict(profile, placement_digest="6d"), measured)[
            "worst_stage_du"
        ]
        == 109
    )


def test_placements_measured_over_budget_are_rescheduled_before_building():
    # Each chosen pinned placement is synthesized on its own before a
    # whole-design build; one over budget is rescheduled away, and a miss the
    # search cannot avoid ends the rounds instead of repeating them.
    worst_du = {"5c58": 202, "e53a": 184, "b0": 100}

    def measure(_parser_state, schedules):
        over = {}
        for key, schedule in schedules.items():
            if worst_du[schedule["placement"]] > schedule["budget_du"]:
                over.setdefault(key, set()).add(schedule["placement"])
        return over

    later = iter(["e53a", "b0"])

    def harvest(_parser_state, previous, keys):
        return {key: dict(previous[key], placement=next(later)) for key in keys}

    original = AUTO_FSM._measure_unit_placements
    AUTO_FSM._measure_unit_placements = measure
    try:
        chosen = AUTO_FSM._confirm_unit_placements(
            None, {"k": dict(placement="5c58", budget_du=112)}, harvest
        )
        assert chosen["k"]["placement"] == "b0", chosen
        stuck = AUTO_FSM._confirm_unit_placements(
            None,
            {"k": dict(placement="5c58", budget_du=112)},
            lambda _state, previous, keys: {key: dict(previous[key]) for key in keys},
        )
        assert stuck["k"]["placement"] == "5c58", stuck
    finally:
        AUTO_FSM._measure_unit_placements = original


def test_endpoint_only_sky130_path_and_unattributed_evidence():
    schedule, provenance = design()
    # sky130 reports endpoint names without an ordered arc list.
    path = dict(
        start_reg_name="top/auto_fsm_example_1234/in_r",
        end_reg_name="top/auto_fsm_example_1234/v0_r",
        path_delay_ns=9.0,
    )
    row = AUTO_FSM._attribute_path(path, schedule, provenance)
    assert row["attributed"] and row["node_ids"] == ["a", "b"]
    unknown = dict(
        path,
        end_reg_name="flattened/$abc$DFF_42",
        start_reg_name="flattened/$abc$DFF_17",
    )
    missed = AUTO_FSM._attribute_path(unknown, schedule, provenance)
    assert not missed["attributed"] and missed["path"] == unknown
    other = dict(schedule, entity="auto_fsm_unrelated_5678")
    assert not AUTO_FSM._attribute_path(path, other, provenance)["attributed"]


def test_flattened_sky130_endpoints_use_only_verified_netlist_aliases():
    schedule, provenance = design()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mapped = json.dumps(
            dict(
                modules=dict(
                    top=dict(
                        cells={
                            "$auto$ff:17": dict(connections=dict(Q=[1])),
                            "$auto$ff:42": dict(connections=dict(Q=[2])),
                        },
                        netnames={
                            "top.auto_fsm_example_1234.st_r": dict(bits=[1]),
                            "top.auto_fsm_example_1234.v0_r": dict(bits=[2]),
                        },
                    )
                )
            )
        ).encode()
        (root / "mapped.json").write_bytes(mapped)
        timing = dict(
            mapped_json_path="mapped.json",
            mapped_json_sha256=hashlib.sha256(mapped).hexdigest(),
        )
        (root / "device_models_timing.json").write_text(json.dumps(timing))
        observation = dict(log_path=str(root / "device_models.log"))
        aliases, status = AUTO_FSM._mapped_endpoint_aliases(observation)
        assert "verified" in status
        path = dict(
            start_reg_name="$auto$ff:17",
            end_reg_name="$auto$ff:42",
            path_delay_ns=9.0,
            start_reg_aliases=aliases["$auto$ff:17"],
            end_reg_aliases=aliases["$auto$ff:42"],
        )
        row = AUTO_FSM._attribute_path(path, schedule, provenance)
        assert (
            row["attributed"]
            and row["start_role"] == "control"
            and row["node_ids"] == ["a", "b"]
        )
        (root / "mapped.json").write_bytes(mapped + b" ")
        aliases, status = AUTO_FSM._mapped_endpoint_aliases(observation)
        assert not aliases and "differs" in status


def test_select_arrival_is_parallel_with_data_and_mux_is_serial():
    schedule, _provenance = design()
    dag = dict(nodes=schedule["nodes"], output=["node", "b"])
    # b's data arrives at 4 ns; its select arrives at 5 ns. The mux+unit
    # add another 4 ns: max(4,5)+4=9, so it cannot fit in an 8 ns state.
    plan = AUTO_FSM.SCHEDULE_DAG(
        dag, 80, lambda nid: 10, select_du_of=lambda nid: 50 if nid == "b" else 0
    )
    assert plan["state_of"] == dict(a=1, b=2), plan
    # When the data is later, charging select in series would incorrectly
    # separate these operations.
    plan = AUTO_FSM.SCHEDULE_DAG(
        dag, 80, lambda nid: 10, select_du_of=lambda nid: 20 if nid == "b" else 0
    )
    assert plan["state_of"] == dict(a=1, b=1), plan


def test_no_chain_repair_waits_and_identical_trials_terminate():
    schedule, _provenance = design()
    dag = dict(nodes=schedule["nodes"], output=["node", "b"])
    first = AUTO_FSM.SCHEDULE_DAG(dag, 100, lambda nid: 0, no_chain_edges=[("a", "b")])
    assert first["state_of"] == dict(a=1, b=2) and not first["at_floor"]
    again = AUTO_FSM.SCHEDULE_DAG(
        copy.deepcopy(dag), 100, lambda nid: 0, no_chain_edges=[("a", "b")]
    )
    assert first == again


def test_separation_cuts_only_the_first_late_entity_pair_in_every_lane():
    schedule, _provenance = design()
    schedule["budget_du"] = 80
    schedule["fus"]["compare"] = "compare"
    schedule["fu_order"] = ["compare", "add", "multiply"]
    evidence = [
        dict(
            boundaries=[
                dict(kind="unit", fu="compare", arrival_ns=2.0),
                dict(kind="unit", fu="add", arrival_ns=4.0),
                dict(kind="unit", fu="multiply", arrival_ns=9.0),
            ]
        )
    ]
    pairs = AUTO_FSM._separation_entity_pairs(schedule, evidence)
    assert pairs == {("add", "multiply")}
    # A merged cell named after an earlier unit runs against emission order:
    # a naming artifact, never the producer-to-consumer edge to separate.
    mislabeled = [
        dict(
            boundaries=[
                dict(kind="unit", fu="compare", arrival_ns=2.0),
                dict(kind="unit", fu="add", arrival_ns=4.0),
                dict(kind="unit", fu="compare", arrival_ns=8.5),
                dict(kind="unit", fu="multiply", arrival_ns=9.0),
            ]
        )
    ]
    assert AUTO_FSM._separation_entity_pairs(schedule, mislabeled) == {
        ("add", "multiply")
    }
    # An endpoint-only path cannot identify the late boundary and must not
    # indiscriminately split every edge in its possible writer chains.
    assert not AUTO_FSM._separation_entity_pairs(schedule, [dict(boundaries=[])])
    dag = dict(nodes=schedule["nodes"], output=["node", "b"])
    plan = AUTO_FSM.SCHEDULE_DAG(dag, 100, lambda nid: 0, no_chain_entity_pairs=pairs)
    assert plan["state_of"] == dict(a=1, b=2)


def test_decode_proxies_are_keyed_only_by_encoding_and_widths():
    import pypeline
    from auto_fsm_cache_test import DESIGN, parse

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "controls.py"
        path.write_text(DESIGN)
        parser, key, _tag = parse(str(path))
        for mode in ("v2", "v3", "onehot"):
            record = AUTO_FSM._control_proxy(parser, key, mode, 4, 2)
            assert AUTO_FSM._control_proxy(parser, key, mode, 4, 2) is record
            for state in range(4):
                value = 1 << state if mode == "onehot" else state
                if mode == "onehot":
                    expected = state & 3
                else:
                    expected = sum(
                        (
                            sum(
                                (value >> ((bit + offset) % 4)) & 1
                                for offset in range(3)
                            )
                            & 1
                        )
                        << bit
                        for bit in range(2)
                    )
                assert int(pypeline.sim_call(record["function"], value)) == expected
        assert len(parser.pypeline_auto_fsm_control_proxies) == 3
        wire = AUTO_FSM._control_proxy(parser, key, "v3", 1, 1)
        assert wire["wiring"]
        assert (
            AUTO_FSM._control_snapshot(parser)[wire["entity"]]["source"]
            == "wiring proof"
        )


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
