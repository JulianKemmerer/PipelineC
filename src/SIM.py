import os
import sys

import COCOTB
import CXXRTL
import EDAPLAY
import MODELSIM
import pypeline_sim
import SYN
import AUTO_PIPELINE
import C_TO_LOGIC
import AUTO_MULTI_CYCLE
import VERILATOR
import VHDL

# Default simulation tool is free online edaplayground
SIM_TOOL = EDAPLAY


def SET_SIM_TOOL(cmd_line_args, source_file=None):
    global SIM_TOOL
    if cmd_line_args.cocotb:
        SIM_TOOL = COCOTB
    elif cmd_line_args.edaplay:
        SIM_TOOL = EDAPLAY
    elif cmd_line_args.cxxrtl:
        SIM_TOOL = CXXRTL
    elif cmd_line_args.verilator:
        SIM_TOOL = VERILATOR
    elif cmd_line_args.modelsim:
        SIM_TOOL = MODELSIM
    elif source_file is not None and source_file.endswith(".py"):
        # No simulator explicitly requested for a Pypeline (.py) design --
        # default to the built-in native Python simulator instead of
        # edaplayground.com.
        SIM_TOOL = pypeline_sim


def NATIVE_SIM_SKIPS_BUILD(args) -> bool:
    """True when a comb-only native (.py) Pypeline simulation run can go straight
    against the design's Python source -- no VHDL elaboration or synthesis needed.
    If SET_SIM_TOOL selected the native simulator (explicit --native or no other
    simulator requested) and comb simulation was requested, the caller should run the
    sim now and skip straight to done. A non---comb native --sim run instead falls
    through to the full build (sweep + AUTO_PIPELINE pin-and-confirm), and the sim
    launches at the end with the discovered latencies emulated -- the same
    no---comb-means-pipelined rule the VHDL simulators follow."""
    return (
        SIM_TOOL is pypeline_sim
        and (args.sim or args.sim_comb)
        and (args.comb or args.no_synth)
    )


def SIM_AT_COMB_STAGE(args) -> bool:
    """True when --comb build's optional sim should run: explicit --sim_comb, or a
    native-sim --sim run that got degraded to comb (e.g. no synth tool installed)."""
    return args.sim_comb or (SIM_TOOL is pypeline_sim and args.sim)


def DO_OPTIONAL_SIM(
    do_sim, parser_state, args, multimain_timing_params=None, source_file=None
):
    # The native sim runs a Pypeline design's @initial/@final(sim) hooks inside
    # its own run loop (pypeline_sim.run_sim); every other simulator is an
    # external tool run here, so its hooks wrap that run.
    pypeline = sys.modules.get("pypeline")
    if (
        do_sim
        and SIM_TOOL is not pypeline_sim
        and pypeline is not None
        and pypeline._hook_registry
    ):
        pending_exc = None
        try:
            pypeline.RUN_INITIAL_HOOKS("sim")
            _DO_OPTIONAL_SIM(
                do_sim, parser_state, args, multimain_timing_params, source_file
            )
        except BaseException as e:
            pending_exc = e
            raise
        finally:
            pypeline.RUN_FINAL_HOOKS("sim", pending_exc=pending_exc)
    else:
        _DO_OPTIONAL_SIM(
            do_sim, parser_state, args, multimain_timing_params, source_file
        )


def _DO_OPTIONAL_SIM(
    do_sim, parser_state, args, multimain_timing_params=None, source_file=None
):
    if SIM_TOOL is COCOTB:
        if do_sim:
            COCOTB.DO_SIM(multimain_timing_params, parser_state, args)
    elif SIM_TOOL is EDAPLAY:
        if do_sim:
            EDAPLAY.SETUP_EDAPLAY(0)
    elif SIM_TOOL is MODELSIM:
        MODELSIM.DO_OPTIONAL_DEBUG(do_sim, 0)
    elif SIM_TOOL is CXXRTL:
        if do_sim:
            CXXRTL.DO_SIM(0, parser_state)
    elif SIM_TOOL is VERILATOR:
        if do_sim:
            VERILATOR.DO_SIM(multimain_timing_params, parser_state, args)
    elif SIM_TOOL is pypeline_sim:
        if do_sim:
            # After a real (non---comb) build, hand the native sim the final
            # per-MAIN latencies and the converged AUTO_PIPELINE harvest so it
            # emulates the built pipeline latencies. Harvesting here (not
            # reusing pypeline's cache) also covers designs whose AP .latency
            # was never read -- the pin-and-confirm loop never ran for those,
            # so the cache is still empty. Harvest divergences are already a
            # fatal driver error for every non---comb .py build
            # (AUTO_PIPELINE.AUTO_PIPELINE_DIVERGENCE_EXIT), so ignore them here.
            main_latencies = None
            ap_latencies = None
            auto_multi_cycle_latencies = None
            auto_fsm_schedules = None
            pipeline_timing = None
            if parser_state is not None:
                main_latencies = GET_MAIN_FUNC_LATENCIES(
                    parser_state, multimain_timing_params
                )
                if multimain_timing_params is not None and any(
                    parser_state.func_fixed_latency.get(logic.func_name, 0)
                    for logic in parser_state.LogicInstLookupTable.values()
                ):
                    # Plain placement data crosses the normal design reimport.
                    # Only run_sim's reachability gate may import the evaluator.
                    pipeline_timing = {
                        name: (
                            list(tp._slices),
                            tp._has_input_regs,
                            tp._has_output_regs,
                            tp._exact_bit_boundaries,
                            tp.logic.delay,
                        )
                        for name, tp in multimain_timing_params.TimingParamsLookupTable.items()
                    }
                if multimain_timing_params is not None:
                    ap_latencies, _divergences = (
                        AUTO_PIPELINE.HARVEST_AUTO_PIPELINE_LATENCIES(
                            parser_state,
                            multimain_timing_params.TimingParamsLookupTable,
                        )
                    )
                # Fail loudly (rather than silently mis-model) if the design
                # uses a pipelined-native-sim construct the emulation can't
                # represent accurately -- see CHECK_PIPELINED_NATIVE_SIM_SUPPORTED.
                CHECK_PIPELINED_NATIVE_SIM_SUPPORTED(
                    parser_state, main_latencies, ap_latencies
                )
                if multimain_timing_params is not None:
                    # The multi-cycle counts actually constrained, so AUTO_MULTI_CYCLE
                    # handshakes count the same cycles as the built VHDL
                    auto_multi_cycle_latencies = (
                        AUTO_MULTI_CYCLE.HARVEST_AUTO_MULTI_CYCLE_NCYCLES(
                            parser_state, multimain_timing_params
                        )
                    )
                # The AUTO_FSM schedules the build actually used. Taken from
                # pypeline's installed cache rather than re-derived: the schedule
                # in force is by definition the one the final elaboration read,
                # and re-scheduling here could disagree with what was built.
                import pypeline

                auto_fsm_schedules = pypeline.AUTO_FSM_SCHEDULE_CACHE() or None
            pypeline_sim.run_sim(
                source_file,
                args.run,
                main_latencies=main_latencies,
                auto_pipeline_latencies=ap_latencies,
                auto_pipeline_ram_plans=(
                    AUTO_PIPELINE.RAM_PLANS_FROM_STATE(parser_state)
                    if parser_state is not None
                    else None
                ),
                auto_fsm_schedules=auto_fsm_schedules,
                pipeline_timing=pipeline_timing,
                auto_multi_cycle_latencies=auto_multi_cycle_latencies,
                part=getattr(args, "part", None),
                syn_tool=getattr(args, "syn_tool", None),
            )
    else:
        print("WARNING: Unknown simulation tool:", SIM_TOOL.__name__)


def GET_SIM_FILES(latency=0):
    # Get all vhd files in syn output
    vhd_files = []
    for root, dirs, filenames in os.walk(SYN.SYN_OUTPUT_DIRECTORY):
        for f in filenames:
            if f.endswith(".vhd"):
                # print "f",f
                fullpath = os.path.join(root, f)
                abs_path = os.path.abspath(fullpath)
                # print "fullpath",fullpath
                # f
                if (
                    (root == SYN.SYN_OUTPUT_DIRECTORY + "/main")
                    and f.startswith("main_")
                    and f.endswith("CLK.vhd")
                ):
                    clks = int(f.replace("main_", "").replace("CLK.vhd", ""))
                    if clks == latency:
                        print("Using top:", abs_path)
                        vhd_files.append(abs_path)
                else:
                    vhd_files.append(abs_path)

    return vhd_files


# Common info about what to generate for simulation
class SimGenInfo:
    def __init__(self):
        self.clock_name_to_mhz = None
        self.debug_input_to_vhdl_name = {}
        self.debug_output_to_vhdl_name = {}
        self.main_func_to_latency = {}


def GET_SIM_GEN_INFO(parser_state, multimain_timing_params=None):
    sim_gen_info = SimGenInfo()
    # Clocks
    clock_name_to_mhz, out_filepath = SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(
        parser_state, None, True
    )
    # Which ones are not from the user internal
    for user_clk_name, clk_mhz in parser_state.clk_mhz.items():
        clk_name = "clk_" + VHDL.CLK_MHZ_GROUP_TEXT(clk_mhz, None)
        # Remove assumed internally produced user clocks from dict
        clock_name_to_mhz.pop(clk_name, None)
        # If clock is external input save with new user name
        if user_clk_name in parser_state.input_wires:
            clock_name_to_mhz[user_clk_name] = clk_mhz
    sim_gen_info.clock_name_to_mhz = clock_name_to_mhz

    # Debug ports
    for output in parser_state.output_wires:
        if output.endswith("_DEBUG"):
            debug_name = output.split("_DEBUG")[0]
            sim_gen_info.debug_output_to_vhdl_name[debug_name] = output
    for input in parser_state.input_wires:
        if input.endswith("_DEBUG"):
            debug_name = input.split("_DEBUG")[0]
            sim_gen_info.debug_input_to_vhdl_name[debug_name] = input

    # Main func latencies
    sim_gen_info.main_func_to_latency = GET_MAIN_FUNC_LATENCIES(
        parser_state, multimain_timing_params
    )

    return sim_gen_info


def GET_MAIN_FUNC_LATENCIES(parser_state, multimain_timing_params=None):
    """{main func hw name -> total latency in clocks} from the final timing
    params (all zeros when multimain_timing_params is None, e.g. comb)."""
    main_func_to_latency = {}
    for func in parser_state.main_mhz:
        if multimain_timing_params is not None:
            main_timing_params = multimain_timing_params.TimingParamsLookupTable[func]
            main_latency = main_timing_params.GET_TOTAL_LATENCY(
                parser_state, multimain_timing_params.TimingParamsLookupTable
            )
        else:
            main_latency = 0
        main_func_to_latency[func] = main_latency
    return main_func_to_latency


def CHECK_PIPELINED_NATIVE_SIM_SUPPORTED(parser_state, main_latencies, ap_latencies=None):
    """Fail loudly (sys.exit) before native sim starts if a pipelined region
    uses global wires in a way the emulation cannot model, rather than
    silently producing cycle-wrong results (see pypeline_sim_DESIGN.md's
    "Pipelined native sim" Limitations).

    A pipelined region is a naturally pipelined pure @MAIN (total latency > 0)
    or an AUTO_PIPELINE call site with latency > 0. Hardware aligns a global
    wire with the arguments/return of the function that uses it, at whatever
    pipeline stage that function sits. Native sim evaluates the region's whole
    body at entry and publishes its global writes with its delayed return, so
    it is exact for non-VOLATILE wires used in the region root's own body only.
    Refused here: VOLATILE wires used by the root, and any global wire used by
    a function called inside the region. pypeline._sim_region_for is the
    runtime twin of this check (it also covers plain native runs with no
    build).
    """
    import AUTO

    roots = set()
    for hw_name, latency in (main_latencies or {}).items():
        if latency > 0:
            roots.add(hw_name)
    if ap_latencies:
        for logic in parser_state.FuncLogicLookupTable.values():
            for inst, key in getattr(logic, "sub_inst_to_auto_pipeline_key", {}).items():
                if ap_latencies.get(key, 0) > 0:
                    roots.add(logic.submodule_instances[inst])
    problems = []
    for root in sorted(roots):
        logic = parser_state.FuncLogicLookupTable.get(root)
        if logic is None:
            continue
        own = {
            **logic.read_only_global_wires,
            **logic.write_only_global_wires,
        }
        volatile = sorted(
            wire
            for wire, info in own.items()
            if AUTO_PIPELINE.GLOBAL_WIRE_TIMING(info) == "volatile"
            and wire not in logic.readback_global_wires.values()
        )
        if volatile:
            problems.append(f"'{root}' uses VOLATILE global wire(s) {', '.join(volatile)}")
        for path, ent, kind, detail in AUTO.FIND_EFFECTS(
            parser_state, root, include_self=False
        ):
            if kind == "global":
                problems.append(
                    f"'{ent}' (instance {C_TO_LOGIC.SUBMODULE_MARKER.join(path)} "
                    f"inside pipelined '{root}') uses global wire(s) {', '.join(detail)}"
                )
    if problems:
        sys.exit(
            "ERROR: native sim cannot model these global wire uses inside "
            "pipelined logic:\n  "
            + "\n  ".join(problems)
            + "\nHardware wires a global directly to the function that uses it "
            "and aligns it with that function's own arguments/return at the "
            "pipeline stage the function is placed (VOLATILE: per consumer "
            "stage). Native sim only models non-VOLATILE global wires used "
            "directly in the body of the pipelined @MAIN or AUTO_PIPELINE-tagged "
            "function itself. Simulate the generated hardware instead "
            "(--cocotb --ghdl), or move the wire access into the pipelined "
            "function and pass values as arguments/return values. See "
            "pypeline_guide.md 'Global wires in pipelined code'."
        )
