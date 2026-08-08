import os
import sys

import COCOTB
import CXXRTL
import EDAPLAY
import MODELSIM
import pypeline_sim
import SYN
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
    through to the full build (sweep + AUTOPIPELINE pin-and-confirm), and the sim
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
            # per-MAIN latencies and the converged AUTOPIPELINE harvest so it
            # emulates the built pipeline latencies. Harvesting here (not
            # reusing pypeline's cache) also covers designs whose AP .latency
            # was never read -- the pin-and-confirm loop never ran for those,
            # so the cache is still empty. Harvest divergences are already a
            # fatal driver error for every non---comb .py build
            # (SYN.AUTOPIPELINE_DIVERGENCE_EXIT), so ignore them here.
            main_latencies = None
            ap_latencies = None
            autofsm_schedules = None
            if parser_state is not None:
                main_latencies = GET_MAIN_FUNC_LATENCIES(
                    parser_state, multimain_timing_params
                )
                # Fail loudly (rather than silently mis-model) if the design
                # uses a pipelined-native-sim construct the emulation can't
                # represent accurately -- see CHECK_PIPELINED_NATIVE_SIM_SUPPORTED.
                CHECK_PIPELINED_NATIVE_SIM_SUPPORTED(parser_state, main_latencies)
                if multimain_timing_params is not None:
                    ap_latencies, _divergences = SYN.HARVEST_AUTOPIPELINE_LATENCIES(
                        parser_state, multimain_timing_params.TimingParamsLookupTable
                    )
                # The AUTOFSM schedules the build actually used. Taken from
                # pypeline's installed cache rather than re-derived: the schedule
                # in force is by definition the one the final elaboration read,
                # and re-scheduling here could disagree with what was built.
                import pypeline

                autofsm_schedules = pypeline.AUTOFSM_SCHEDULE_CACHE() or None
            pypeline_sim.run_sim(
                source_file,
                args.run,
                main_latencies=main_latencies,
                autopipeline_latencies=ap_latencies,
                autofsm_schedules=autofsm_schedules,
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


def CHECK_PIPELINED_NATIVE_SIM_SUPPORTED(parser_state, main_latencies):
    """Fail loudly (sys.exit) if the design relies on a pipelined-native-sim
    construct the emulation cannot model accurately, rather than silently
    producing cycle-wrong results (see pypeline_sim_DESIGN.md's "Pipelined
    native sim" Limitations subsection).

    Currently enforced: a naturally-pipelined *pure* @MAIN (total latency > 0,
    i.e. the sweep sliced the MAIN itself -- distinct from an AUTOPIPELINE
    child inside a stateful MAIN, which reports 0 to its container) must write
    at most ONE global wire. The native sim delays every wire such a MAIN
    writes by that MAIN's single total latency N, but the generated VHDL
    emerges each *separate* write-only global wire at its own "fully driven
    last" pipeline stage -- its own cone depth -- so a MAIN writing two wires
    of different depth (e.g. a deep result wire and a shallow passthrough) is
    cycle-wrong on the shallower one. Fields carried in ONE struct wire are
    fine: VHDL registers the whole struct together to its deepest field's
    stage, so they stay aligned in both sims. The fix is therefore to bundle
    the MAIN's co-timed outputs into a single struct wire (which also aligns
    them in hardware). This is intentionally conservative -- two separate
    equal-depth wires would match, but native sim has no per-wire stage
    information at sim time to prove that, so it refuses rather than guess.
    """
    if not main_latencies:
        return
    for hw_name, latency in main_latencies.items():
        if latency <= 0:
            continue
        logic = parser_state.FuncLogicLookupTable.get(hw_name)
        if logic is None:
            continue
        written = sorted(getattr(logic, "write_only_global_wires", {}).keys())
        if len(written) > 1:
            sys.exit(
                "ERROR: pipelined native sim cannot accurately model MAIN "
                f"'{hw_name}': it is pipelined ({latency} clks) and writes "
                f"{len(written)} separate global wires ({', '.join(written)}). "
                "Native sim delays every wire a pipelined MAIN writes by the "
                "MAIN's total latency, but each separate wire emerges at its "
                "own pipeline depth in the generated VHDL, so wires of "
                "differing depth would be cycle-wrong. Bundle these outputs "
                "into a SINGLE struct wire (which also aligns them in "
                "hardware), or build/simulate with --comb (zero latency)."
            )
