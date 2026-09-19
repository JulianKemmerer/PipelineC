import os
import shlex
import subprocess
import sys

import C_TO_LOGIC
import SYN
import VHDL
from utilities import GET_TOOL_PATH

# Tool names
YOSYS_EXE = "yosys"
NEXT_PNR_EXE = "nextpnr-ecp5"
GHDL_EXE = "ghdl"

# Hard coded/default exe paths for simplest oss-cad-suite based install
# https://github.com/YosysHQ/oss-cad-suite-build/releases/
# Download, extract, set env var or path here
OSS_CAD_SUITE_ENV_PATH = os.environ.get("OSS_CAD_SUITE")
if OSS_CAD_SUITE_ENV_PATH:
    OSS_CAD_SUITE_PATH = OSS_CAD_SUITE_ENV_PATH
else:
    OSS_CAD_SUITE_PATH = "/media/1TB/Programs/Linux/oss-cad-suite"
YOSYS_BIN_PATH = None
GHDL_BIN_PATH = None
NEXTPNR_BIN_PATH = None
GHDL_PREFIX = None

if os.path.exists(OSS_CAD_SUITE_PATH):
    YOSYS_BIN_PATH = OSS_CAD_SUITE_PATH + "/bin"
    GHDL_BIN_PATH = OSS_CAD_SUITE_PATH + "/bin"
    GHDL_PREFIX = OSS_CAD_SUITE_PATH + "/lib/ghdl"
    NEXTPNR_BIN_PATH = OSS_CAD_SUITE_PATH + "/bin"

if YOSYS_BIN_PATH is None or not os.path.exists(YOSYS_BIN_PATH + "/" + YOSYS_EXE):
    YOSYS_EXE_PATH = GET_TOOL_PATH(YOSYS_EXE)
    if YOSYS_EXE_PATH is not None:
        YOSYS_BIN_PATH = os.path.abspath(os.path.dirname(YOSYS_EXE_PATH))

if GHDL_BIN_PATH is None or not os.path.exists(GHDL_BIN_PATH + "/" + GHDL_EXE):
    GHDL_EXE_PATH = GET_TOOL_PATH(GHDL_EXE)
    if GHDL_EXE_PATH is not None:
        GHDL_BIN_PATH = os.path.abspath(os.path.dirname(GHDL_EXE_PATH))
        GHDL_PREFIX = os.path.abspath(os.path.dirname(GHDL_EXE_PATH) + "/../lib/ghdl")

if NEXTPNR_BIN_PATH is None or not os.path.exists(
    NEXTPNR_BIN_PATH + "/" + NEXT_PNR_EXE
):
    NEXTPNR_EXE_PATH = GET_TOOL_PATH(NEXT_PNR_EXE)
    if NEXTPNR_EXE_PATH is not None:
        NEXTPNR_BIN_PATH = os.path.abspath(os.path.dirname(NEXTPNR_EXE_PATH))


# Part used when this tool is selected without a part (--syn_tool/SYN_TOOL()
# with no --part/PART()). See SYN.RESOLVE_PART_AND_TOOL.
DEFAULT_PART = "LFE5U-85F-6BG381C"


def _GHDL_PLUGIN_IS_BUILT_IN(yosys_bin_path):
    """Real probe (not a hardcoded guess) for whether this yosys build
    recognizes the `ghdl` command on its own, without the separate `-m ghdl`
    plugin flag some builds need to load it (e.g. oss-cad-suite's, which
    ships yosys and the ghdl plugin as separate pieces joined at runtime).

    Every yosys this codebase has been run against so far has needed
    `-m ghdl` -- that was previously just hardcoded, never actually checked.
    Tries `ghdl --help` with no `-m` flag and looks for yosys's specific
    "command not found" error, the one unambiguous signal that the plugin
    isn't loaded: any other ghdl-side error (e.g. an unrecognized ghdl flag)
    still proves the `ghdl` command itself is registered and just objected
    to `--help` -- that counts as built in. Fails safe to False (fall back
    to `-m ghdl`, today's universal case) on any doubt: stdin closed and a
    bounded timeout, same pattern as every other yosys invocation in this
    codebase, so a hung/misbehaving yosys can't stall startup.
    """
    if yosys_bin_path is None:
        return False
    yosys_exe = os.path.join(yosys_bin_path, YOSYS_EXE)
    if not os.path.exists(yosys_exe):
        return False
    try:
        result = subprocess.run(
            [yosys_exe, "-p", "ghdl --help"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
        )
        return b"No such command: ghdl" not in result.stdout
    except Exception:
        return False


GHDL_PLUGIN_BUILT_IN = _GHDL_PLUGIN_IS_BUILT_IN(YOSYS_BIN_PATH)


def GET_GHDL_PLUGIN_FLAGS():
    if GHDL_PLUGIN_BUILT_IN:
        return ""
    plugin = os.environ.get("PYPELINEC_YOSYS_GHDL_PLUGIN", "ghdl")
    return f"-m {shlex.quote(plugin)} "


def WRITE_YOSYS_SCRIPT(commands, script_path):
    """Write a list of yosys commands (one per line) to script_path and
    return the "-s <script_path>" argv fragment to use in place of
    "-p '<commands joined by ;>'".

    A design's full VHDL file list, inlined into a single `ghdl ... -e top`
    command passed via `-p`, can exceed Linux's MAX_ARG_STRLEN (any one
    argv/envp string is capped at PAGE_SIZE * 32 = 131072 bytes, independent
    of the much larger overall ARG_MAX) -- putting the same commands in a
    script file sidesteps that entirely, since the file's contents never
    become one shell/exec argument.
    """
    with open(script_path, "w") as f:
        f.write("\n".join(commands) + "\n")
    return f"-s {shlex.quote(script_path)}"


# yosys shells out to a SEPARATE abc executable for its `abc` pass -- it is not
# built into the yosys binary. It looks for `yosys-abc` next to its own exe
# (what oss-cad-suite and most distro packages ship), unless built with
# ABCEXTERNAL, in which case that compiled-in path (commonly a plain `abc` on
# PATH) is used instead. A yosys install missing abc runs `synth` fine and only
# fails once something actually reaches an `abc` pass -- which is why a plain
# "is yosys installed" check can pass while DEVICE_MODELS (the only SYN_TOOL
# here whose recipe calls `abc -liberty`) fails and PyRTL's own yosys use keeps
# working.
ABC_EXE = "yosys-abc"


def FIND_ABC_EXE(yosys_bin_path=None):
    """Best-effort locate the abc executable yosys would use. None if not found
    (which does NOT prove abc is unavailable -- an ABCEXTERNAL-built yosys can
    point anywhere -- so treat None as 'likely missing', not proof)."""
    yosys_bin_path = yosys_bin_path or YOSYS_BIN_PATH
    if yosys_bin_path is not None:
        beside_yosys = os.path.join(yosys_bin_path, ABC_EXE)
        if os.path.exists(beside_yosys):
            return beside_yosys
    for exe in (ABC_EXE, "abc"):
        found = GET_TOOL_PATH(exe)
        if found is not None:
            return found
    return None


def _RUNS_OK(argv, timeout=15):
    """True if argv executes at all (any exit code). False if it can't run --
    missing, not executable, wrong arch/ABI, hung."""
    try:
        subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return True
    except Exception:
        return False


def DIAGNOSE_TOOLS():
    """Static, cheap checks of the yosys/ghdl/abc install, returning a list of
    human-readable problem strings (empty == nothing obviously wrong).

    Exists because the real failure mode is a *partial* install: yosys present
    but abc missing, or ghdl present but GHDL_PREFIX pointing at a directory
    with no runtime libraries. Both produce failures deep inside a redirected
    yosys log rather than at any "is it installed" check, and both can leave
    other flows (PyRTL, plain elaboration) working perfectly. Intended for
    attaching to an error after a tool invocation has already failed, or for a
    manual pre-flight check -- not called on every build.
    """
    problems = []

    # --- yosys ---
    if YOSYS_BIN_PATH is None:
        problems.append(
            "yosys not found. Set the OSS_CAD_SUITE env var to an oss-cad-suite "
            "install, or put `yosys` on PATH."
        )
    else:
        yosys_exe = os.path.join(YOSYS_BIN_PATH, YOSYS_EXE)
        if not os.path.exists(yosys_exe):
            problems.append(f"yosys executable missing: {yosys_exe}")
        elif not _RUNS_OK([yosys_exe, "--version"]):
            problems.append(
                f"yosys found but will not run: {yosys_exe} "
                "(not executable, wrong architecture, or missing shared libraries?)"
            )

    # --- abc (yosys's separate technology-mapping executable) ---
    abc_exe = FIND_ABC_EXE()
    if abc_exe is None:
        problems.append(
            f"abc executable not found (looked for `{ABC_EXE}` next to yosys at "
            f"{YOSYS_BIN_PATH}, then `{ABC_EXE}`/`abc` on PATH). yosys shells out "
            "to abc for its `abc` pass, so `synth` succeeds and only liberty "
            "technology mapping (`abc -liberty ...`) fails -- this breaks the "
            "sky130 SYN_TOOL while leaving PyRTL's yosys use working. If this "
            "yosys was built with ABCEXTERNAL, abc may live elsewhere and this "
            "warning can be ignored."
        )
    elif not _RUNS_OK([abc_exe, "-h"]):
        problems.append(f"abc found but will not run: {abc_exe}")

    # --- ghdl ---
    if GHDL_BIN_PATH is None:
        problems.append("ghdl not found. Put `ghdl` on PATH or install oss-cad-suite.")
    else:
        ghdl_exe = os.path.join(GHDL_BIN_PATH, GHDL_EXE)
        if not os.path.exists(ghdl_exe):
            problems.append(f"ghdl executable missing: {ghdl_exe}")
        elif not _RUNS_OK([ghdl_exe, "--version"]):
            problems.append(f"ghdl found but will not run: {ghdl_exe}")

    # --- GHDL_PREFIX (ghdl's compiled runtime + analyzed std/ieee libraries) ---
    if GHDL_PREFIX is None:
        problems.append(
            "GHDL_PREFIX is unset and could not be derived. ghdl cannot find its "
            "analyzed `std`/`ieee` libraries without it, so every `ghdl` import "
            "inside yosys fails."
        )
    elif not os.path.isdir(GHDL_PREFIX):
        problems.append(
            f"GHDL_PREFIX points at a non-existent directory: {GHDL_PREFIX} "
            "(derived as <ghdl exe dir>/../lib/ghdl -- correct that path, or set "
            "the OSS_CAD_SUITE env var if using oss-cad-suite)."
        )
    else:
        missing_libs = [
            d for d in ("std", "ieee") if not os.path.isdir(os.path.join(GHDL_PREFIX, d))
        ]
        if missing_libs:
            problems.append(
                f"GHDL_PREFIX={GHDL_PREFIX} exists but is missing the "
                f"{'/'.join(missing_libs)} subdirector"
                f"{'y' if len(missing_libs) == 1 else 'ies'} ghdl needs -- this is "
                "probably the wrong directory (it should contain ghdl's analyzed "
                "standard libraries, e.g. oss-cad-suite's lib/ghdl)."
            )

    # --- the ghdl-yosys plugin bridge, however this install provides it ---
    if YOSYS_BIN_PATH is not None and os.path.exists(
        os.path.join(YOSYS_BIN_PATH, YOSYS_EXE)
    ):
        yosys_exe = os.path.join(YOSYS_BIN_PATH, YOSYS_EXE)
        argv = [yosys_exe] + shlex.split(GET_GHDL_PLUGIN_FLAGS())
        argv += ["-p", "ghdl --version"]
        try:
            result = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=15,
            )
            out = result.stdout.decode(errors="replace")
            if "No such command: ghdl" in out or "Can't load module" in out:
                problems.append(
                    "yosys cannot provide the `ghdl` command "
                    f"({'no -m flag needed per auto-detect' if GHDL_PLUGIN_BUILT_IN else 'tried `' + GET_GHDL_PLUGIN_FLAGS().strip() + '`'}): "
                    "the ghdl-yosys-plugin is missing, or was built against a "
                    "different yosys version than this one. Installing yosys and "
                    "ghdl from one coordinated source (e.g. a single oss-cad-suite "
                    "release) avoids this. yosys output:\n    "
                    + "\n    ".join(out.strip().splitlines()[-5:])
                )
        except Exception as e:
            problems.append(f"could not probe yosys's ghdl command support: {e}")

    return problems


# Flag to skip pnr
YOSYS_JSON_ONLY = False

# Xilinx 7-series open-source flow (Yosys + nextpnr-xilinx + Project X-Ray).
XC7_NEXTPNR_EXE = "nextpnr-xilinx"
XC7_FASM2FRAMES_EXE = "fasm2frames"
XC7_FRAMES2BIT_EXE = "xc7frames2bit"

# Optional root of a self-contained OpenXC7 install. Keep this separate from
# OSS_CAD_SUITE: it is useful (and common) to take Yosys/GHDL from OSS CAD
# Suite while taking nextpnr-xilinx, Project X-Ray and the matching chipdb from
# an OpenXC7/Apio bundle.
OPENXC7_PATH = os.environ.get("OPENXC7")

def IS_XC7_PART(part_str):
    return bool(part_str) and part_str.lower().startswith("xc7")


def _XC7_ARCH_CHIPDB_NAMES(part_str):
    """Return plausible nextpnr-xilinx architecture chipdb names."""
    package_part = part_str.lower().split("-", 1)[0]
    names = [package_part + ".bin"]
    for marker in ("xc7a35t", "xc7a50t", "xc7a100t", "xc7a200t"):
        if package_part.startswith(marker):
            names.append(marker + ".bin")
            break
    return names


def GET_XC7_TOOL_PATH(exe_name):
    """Find an XC7-specific executable, preferring the OpenXC7 root."""
    if OPENXC7_PATH:
        candidate = os.path.join(OPENXC7_PATH, "bin", exe_name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return GET_TOOL_PATH(exe_name)


def GET_XC7_CHIPDB_PATH(part_str):
    value = os.environ.get("OPENXC7_CHIPDB")
    search_paths = []
    if value:
        if os.path.isfile(value):
            return value
        search_paths.append(value)
    if OPENXC7_PATH:
        search_paths.extend(
            [
                os.path.join(OPENXC7_PATH, "chipdb"),
                os.path.join(OPENXC7_PATH, "share", "nextpnr", "chipdb"),
            ]
        )
    for directory in search_paths:
        if os.path.isdir(directory):
            for name in _XC7_ARCH_CHIPDB_NAMES(part_str):
                candidate = os.path.join(directory, name)
                if os.path.isfile(candidate):
                    return candidate
    return None


def _XC7_DATABASE_FAMILY(part_str):
    family_prefix = part_str.lower()[:4]
    return {
        "xc7a": "artix7",
        "xc7k": "kintex7",
        "xc7s": "spartan7",
        "xc7v": "virtex7",
        "xc7z": "zynq7",
    }.get(family_prefix)


def GET_XC7_PRJXRAY_DB_DIR(part_str):
    """Return the family database directory for a full XC7 part name."""
    family = _XC7_DATABASE_FAMILY(part_str)
    if family is None:
        return None

    roots = []
    env_root = os.environ.get("PRJXRAY_DB_DIR")
    if env_root:
        roots.append(env_root)
    if OPENXC7_PATH:
        # Apio/prebuilt layout, then the openXC7 source-installer layout.
        roots.extend(
            [
                os.path.join(
                    OPENXC7_PATH, "share", "nextpnr", "external", "prjxray-db"
                ),
                os.path.join(OPENXC7_PATH, "share", "nextpnr", "prjxray-db"),
            ]
        )

    for root in roots:
        candidate = os.path.join(root, family)
        if os.path.isdir(candidate):
            return candidate
    return None


def XC7_SYNTH_XILINX_COMMAND(top_entity_name, is_final_top):
    """Return the Yosys synth_xilinx command for an XC7 timing/final top."""
    iopad_arg = "" if is_final_top else " -noiopad"
    return (
        f"synth_xilinx -flatten -abc9 -arch xc7{iopad_arg} "
        f"-top {top_entity_name}"
    )


def GET_XC7_BITSTREAM_TOOLS_AND_DB(part_str):
    """Resolve all Project X-Ray inputs needed after XC7 place-and-route.

    Kept as one preflight so a --pins build can fail before spending time in
    synthesis/P&R, while GENERATE_BITSTREAM also calls it defensively for
    direct backend use.
    """
    fasm2frames = GET_XC7_TOOL_PATH(XC7_FASM2FRAMES_EXE)
    frames2bit = GET_XC7_TOOL_PATH(XC7_FRAMES2BIT_EXE)
    missing = []
    if fasm2frames is None:
        missing.append(XC7_FASM2FRAMES_EXE)
    if frames2bit is None:
        missing.append(XC7_FRAMES2BIT_EXE)

    architecture_db = GET_XC7_PRJXRAY_DB_DIR(part_str)
    if architecture_db is None:
        missing.append("Project X-Ray database")

    part_name = part_str.lower()
    part_yaml = None
    if architecture_db is not None:
        part_yaml = os.path.join(architecture_db, part_name, "part.yaml")
        if not os.path.isfile(part_yaml):
            missing.append("Project X-Ray part file " + part_yaml)

    if missing:
        raise Exception(
            "OpenXC7 bitstream prerequisites incomplete for "
            + part_str
            + ": missing "
            + ", ".join(missing)
            + ". Put the conversion tools/database below OPENXC7, or put the "
            + "tools on PATH and set PRJXRAY_DB_DIR."
        )
    return fasm2frames, frames2bit, architecture_db, part_yaml


# Derive cmd line options from part
def PART_TO_CMD_LINE_OPTS(part_str):
    opts = ""
    if part_str.lower().startswith("lfe5u"):
        # Ex. LFE5UM5G-85F-8BG756C
        toks = part_str.split("-")
        part = toks[0]
        size = toks[1]
        pkg = toks[2]
        """
    --12k                             set device type to LFE5U-12F
    --25k                             set device type to LFE5U-25F
    --45k                             set device type to LFE5U-45F
    --85k                             set device type to LFE5U-85F
    --um-25k                          set device type to LFE5UM-25F
    --um-45k                          set device type to LFE5UM-45F
    --um-85k                          set device type to LFE5UM-85F
    --um5g-25k                        set device type to LFE5UM5G-25F
    --um5g-45k                        set device type to LFE5UM5G-45F
    --um5g-85k                        set device type to LFE5UM5G-85F
    --package arg                     select device package (defaults to 
                                      CABGA381)
    --speed arg                       select device speedgrade (6, 7 or 8)
    """
        opts = ""
        opts += "--"
        if part == "LFE5UM":
            opts += "um-"
        elif part == "LFE5UM5G":
            opts += "um5g-"

        size_num = size.strip("F")
        opts += size_num + "k "

        speed_num = pkg[0]
        opts += "--speed " + speed_num + " "
        opts += "--out-of-context"

    elif part_str.lower().startswith("ice"):
        # Ex. ICE40UP5K-SG48
        toks = part_str.split("-")
        part = toks[0]
        pkg = toks[1]
        """
    --lp384                           set device type to iCE40LP384
    --lp1k                            set device type to iCE40LP1K
    --lp4k                            set device type to iCE40LP4K
    --lp8k                            set device type to iCE40LP8K
    --hx1k                            set device type to iCE40HX1K
    --hx4k                            set device type to iCE40HX4K
    --hx8k                            set device type to iCE40HX8K
    --up3k                            set device type to iCE40UP3K
    --up5k                            set device type to iCE40UP5K
    --u1k                             set device type to iCE5LP1K
    --u2k                             set device type to iCE5LP2K
    --u4k                             set device type to iCE5LP4K
    """
        if part_str.upper().startswith("ICE40LP384"):
            opts += "--lp384"
        elif part_str.upper().startswith("ICE40LP1K"):
            opts += "--lp1k"
        elif part_str.upper().startswith("ICE40LP4K"):
            opts += "--lp4k"
        elif part_str.upper().startswith("ICE40LP8K"):
            opts += "--lp8k"
        elif part_str.upper().startswith("ICE40HX1K"):
            opts += "--hx1k"
        elif part_str.upper().startswith("ICE40HX4K"):
            opts += "--hx4k"
        elif part_str.upper().startswith("ICE40HX8K"):
            opts += "--hx8k"
        elif part_str.upper().startswith("ICE40UP3K"):
            opts += "--up3k"
        elif part_str.upper().startswith("ICE40UP5K"):
            opts += "--up5k"
        elif part_str.upper().startswith("ICE5LP1K"):
            opts += "--u1k"
        elif part_str.upper().startswith("ICE5LP2K"):
            opts += "--u2k"
        elif part_str.upper().startswith("ICE5LP4K"):
            opts += "--u4k"

        opts += " --pcf-allow-unconstrained"

    return opts


# Convert nextpnr style paths with . /
def NODE_TO_ELEM(node_str):
    # Struct dot is "\."  ?
    node_str = node_str.replace("\\.", "|")
    # Regualr modules is .
    node_str = node_str.replace(".", "/")
    # Fix structs
    node_str = node_str.replace("|", ".")
    # print("node_str",node_str)
    return node_str


class ParsedTimingReport:
    def __init__(self, syn_output):
        self.orig_text = syn_output
        import re

        self.ram_resources = {
            name: int(count)
            for name, count in re.findall(
                r"Info:\s+(DP16KD|TRELLIS_SLICE|TRELLIS_FF|LUT4):\s+(\d+)/", syn_output
            )
        }
        for label, key in (("Total LUT4s", "LUT4"), ("Total DFFs", "DFF")):
            match = re.search(r"Info:\s+" + label + r":\s+(\d+)/", syn_output)
            if match:
                self.ram_resources[key] = int(match[1])
        # Clocks reported once at end
        clock_to_act_tar_mhz = {}
        tok1 = "Max frequency for clock"
        for line in syn_output.split("\n"):
            if tok1 in line:
                clk_str = line.split(tok1, 1)[1]
                # Synthesized clock net names may themselves contain colons
                # (for example Yosys auto names). The final colon is the
                # delimiter before nextpnr's frequency text.
                clk_name, freqs_str = clk_str.rsplit(":", 1)
                clk_name = clk_name.strip().strip("'")
                # print("clk_str",clk_str)
                # print("freqs_str",freqs_str)
                actual_mhz = float(freqs_str.split("MHz")[0])
                target_mhz = float(freqs_str.split("at ")[1].replace(" MHz)", ""))
                # print(clk_name, actual_mhz, target_mhz)
                clock_to_act_tar_mhz[clk_name] = (actual_mhz, target_mhz)

        self.path_reports = {}
        PATH_SPLIT = "Info: Critical path report for "
        maybe_path_texts = syn_output.split(PATH_SPLIT)
        for path_text in maybe_path_texts:
            if (
                "ns logic" in path_text and "(posedge -> posedge)" in path_text
            ):  # no async paths
                path_report = PathReport(path_text)
                # Set things only parsed once not per report
                path_report.path_delay_ns = (
                    1000.0 / clock_to_act_tar_mhz[path_report.path_group][0]
                )
                # Lolz really slow clocks come back as zero
                # nextpnr reports with two decimals 0.00 MHz
                tar_mhz = clock_to_act_tar_mhz[path_report.path_group][1]
                if tar_mhz < 0.01:
                    tar_mhz = 0.01
                path_report.source_ns_per_clock = 1000.0 / tar_mhz
                # Save in dict
                self.path_reports[path_report.path_group] = path_report

        if len(self.path_reports) == 0:
            print("Bad synthesis log?:", syn_output)
            sys.exit(-1)


class PathReport:
    def __init__(self, path_report_text):
        # print(path_report_text)
        self.path_delay_ns = None  # nanoseconds
        # self.slack_ns = None
        self.source_ns_per_clock = None  # From latch edge time
        self.path_group = None  # Clock name?
        self.netlist_resources = set()  # Set of strings
        self.start_reg_name = None
        self.end_reg_name = None

        prev_line = None
        in_netlist_resources = False
        is_first_net = True
        last_net_name = None
        for line in path_report_text.split("\n"):
            # Path delay ns
            tok1 = "Max frequency for clock"
            if tok1 in line:
                toks = line.split(tok1)
                toks = toks[1].split(":")
                toks = toks[1].split("MHz")
                mhz = float(toks[0])
                ns = 1000.0 / mhz
                self.path_delay_ns = ns
                # print("mhz",mhz)
                # print("ns",ns)

            # Clock name  /path group
            tok1 = "(posedge -> posedge)"
            if tok1 in line:
                self.path_group = line.split("'")[1]  # .strip().strip("'")
                # print("self.path_group",self.path_group)

            # Netlist resources + start and end
            if in_netlist_resources:
                tok1 = " Net "
                if tok1 in line:
                    net_str = line.split(tok1)[1].strip()
                    net = net_str.split(" ")[0]
                    net_name = NODE_TO_ELEM(net)
                    self.netlist_resources.add(net_name)
                    if is_first_net:
                        self.start_reg_name = net_name
                        is_first_net = False
                    last_net_name = net_name
            if "ns logic," in line and "ns routing" in line:
                in_netlist_resources = False
                self.end_reg_name = last_net_name
            tok1 = "Info:       type"
            if tok1 in line:
                in_netlist_resources = True


# Returns parsed timing report
def SYN_AND_REPORT_TIMING(
    inst_name,
    Logic,
    parser_state,
    TimingParamsLookupTable,
    total_latency=None,
    hash_ext=None,
    use_existing_log_file=True,
    is_final_top=False,
):
    import AUTO_PIPELINE

    multimain_timing_params = AUTO_PIPELINE.MultiMainTimingParams()
    multimain_timing_params.TimingParamsLookupTable = TimingParamsLookupTable
    return SYN_AND_REPORT_TIMING_NEW(
        parser_state,
        multimain_timing_params,
        inst_name,
        total_latency,
        hash_ext,
        use_existing_log_file,
        is_final_top,
    )


# Returns parsed timing report
def SYN_AND_REPORT_TIMING_MULTIMAIN(parser_state, multimain_timing_params):
    return SYN_AND_REPORT_TIMING_NEW(parser_state, multimain_timing_params)


def SYN_AND_REPORT_TIMING_FINAL_TOP(parser_state, multimain_timing_params):
    """Implement and time the already-written board-facing final top.

    SYN.WRITE_FINAL_FILES owns creation of final VHDL. This operation consumes
    those files, runs synthesis/place-and-route, and leaves the XC7 FASM
    implementation artifact on disk; bitstream-format conversion remains a
    separate backend step.
    """
    return SYN_AND_REPORT_TIMING_NEW(
        parser_state,
        multimain_timing_params,
        use_existing_log_file=False,
        is_final_top=True,
    )


# MULTIMAIN OR SINGLE INSTANCE
# Returns parsed timing report
def SYN_AND_REPORT_TIMING_NEW(
    parser_state,
    multimain_timing_params,
    inst_name=None,
    total_latency=None,
    hash_ext=None,
    use_existing_log_file=True,
    is_final_top=False,
):
    is_xc7 = IS_XC7_PART(parser_state.part)
    xc7_final_top = is_xc7 and is_final_top

    # Single inst
    if inst_name:
        Logic = parser_state.LogicInstLookupTable[inst_name]

        # Timing params for this logic
        timing_params = multimain_timing_params.TimingParamsLookupTable[inst_name]

        # First create syn/imp directory for this logic
        output_directory = SYN.GET_OUTPUT_DIRECTORY(Logic)

        # Set log path
        if hash_ext is None:
            hash_ext = timing_params.GET_HASH_EXT(
                multimain_timing_params.TimingParamsLookupTable, parser_state
            )
        if total_latency is None:
            total_latency = timing_params.GET_TOTAL_LATENCY(
                parser_state, multimain_timing_params.TimingParamsLookupTable
            )
        entity_file_ext = "_" + str(total_latency) + "CLK" + hash_ext
        log_file_name = "open_tools" + entity_file_ext + ".log"
    else:
        # Multimain
        # First create directory for this logic
        output_directory = SYN.SYN_OUTPUT_DIRECTORY + "/" + SYN.TOP_LEVEL_MODULE

        # Set log path
        # Hash for multi main is just hash of main pipes
        hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
        log_file_name = (
            "open_tools_final.log"
            if xc7_final_top
            else "open_tools" + hash_ext + ".log"
        )

    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    nextpnr_seed = int(os.environ.get("PIPELINEC_OPEN_TOOLS_SEED", "1"))
    if nextpnr_seed < 1:
        raise ValueError("PIPELINEC_OPEN_TOOLS_SEED must be a positive integer")
    if nextpnr_seed != 1:
        log_file_name = log_file_name[:-4] + f"_seed{nextpnr_seed}.log"
    log_path = output_directory + "/" + log_file_name

    # Use same configs based on to speed up run time?
    log_to_read = log_path

    # Final xc7 implementation produces the user bitstream and must not be
    # silently replaced by a cached characterization/multimain result.
    if not xc7_final_top and os.path.exists(log_to_read) and use_existing_log_file:
        # print "SKIPPED:", syn_imp_bash_cmd
        print("Reading log", log_to_read)
        f = open(log_path, "r")
        log_text = f.read()
        f.close()
    else:
        # Write top level vhdl for this module/multimain
        if inst_name:
            VHDL.WRITE_LOGIC_ENTITY(
                inst_name,
                Logic,
                output_directory,
                parser_state,
                multimain_timing_params.TimingParamsLookupTable,
            )
            VHDL.WRITE_LOGIC_TOP(
                inst_name,
                Logic,
                output_directory,
                parser_state,
                multimain_timing_params.TimingParamsLookupTable,
            )
        else:
            # Final XC7 implementation consumes the final top already emitted
            # by SYN.WRITE_FINAL_FILES. In particular this preserves edits made
            # by @final(syn) hooks between file emission and implementation.
            if not xc7_final_top:
                VHDL.WRITE_MULTIMAIN_TOP(
                    parser_state, multimain_timing_params, False
                )

        # Generate files for this SYN

        # Constraints
        # Write clock xdc and include it
        constraints_filepath = SYN.WRITE_CLK_CONSTRAINTS_FILE(
            multimain_timing_params, parser_state, inst_name
        )
        clk_to_mhz, constraints_filepath = SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(
            parser_state, inst_name
        )

        # Which vhdl files?
        vhdl_files_texts, top_entity_name = SYN.GET_VHDL_FILES_TCL_TEXT_AND_TOP(
            multimain_timing_params, parser_state, inst_name, xc7_final_top
        )

        if GHDL_PREFIX is None:
            raise Exception("ghdl not installed?")
        if YOSYS_BIN_PATH is None:
            raise Exception("yosys not installed?")
        if is_xc7:
            nextpnr_exe = GET_XC7_TOOL_PATH(XC7_NEXTPNR_EXE)
            chipdb_path = GET_XC7_CHIPDB_PATH(parser_state.part)
            if nextpnr_exe is None:
                raise Exception("nextpnr-xilinx not installed? Put it on PATH.")
            if chipdb_path is None:
                raise Exception(
                    "No nextpnr-xilinx chipdb for " + parser_state.part + ". Set "
                    "OPENXC7_CHIPDB to the chipdb file or containing directory."
                )
        elif NEXTPNR_BIN_PATH is None:
            raise Exception("nextpnr not installed?")

        # A single shell script build .sh
        m_ghdl = GET_GHDL_PLUGIN_FLAGS()
        optional_router2 = ""  # Always default router for now...
        # optional_router2 = "--router router2"
        # if inst_name:
        #    # Dont use router two for small single instances
        #    # Only use router two for multi main top level no inst_name
        #    optional_router2 = ""
        sh_file = top_entity_name + ".sh"
        sh_path = output_directory + "/" + sh_file
        f = open(sh_path, "w")
        # -v --debug
        if not YOSYS_JSON_ONLY:
            if is_xc7:
                # Characterization tops are synthetic register-to-register
                # timing shells, not physical board interfaces. Avoid inferred
                # I/O pads there; unconstrained synthetic ports can otherwise
                # land on unbonded package BELs. Final tops keep normal I/O.
                yosys_script_arg = WRITE_YOSYS_SCRIPT(
                    [
                        f"ghdl --std=08 -frelaxed {vhdl_files_texts} -e {top_entity_name}",
                        XC7_SYNTH_XILINX_COMMAND(top_entity_name, is_final_top),
                        f"write_json {top_entity_name}.json",
                    ],
                    output_directory + "/" + top_entity_name + "_yosys.ys",
                )
                f.write(
                    """
#!/usr/bin/env bash
set -e
export GHDL_PREFIX="""
                    + GHDL_PREFIX
                    + f"""
# Elab+Syn (json is output)
{YOSYS_BIN_PATH}/yosys {m_ghdl} {yosys_script_arg} &>> {shlex.quote(log_file_name)}
"""
                )

                xdc_arg = ""
                if is_final_top and SYN.PIN_CONSTRAINTS_FILE:
                    xdc_arg = " --xdc " + shlex.quote(SYN.PIN_CONSTRAINTS_FILE)
                elif not is_final_top:
                    characterization_netlist_helper = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        "openxc7_characterization_netlist.py",
                    )
                    f.write(
                        shlex.quote(sys.executable)
                        + " "
                        + shlex.quote(characterization_netlist_helper)
                        + " "
                        + shlex.quote(top_entity_name + ".json")
                        + " "
                        + shlex.quote(top_entity_name)
                        + "\n"
                    )

                fasm_arg = ""
                if is_final_top:
                    fasm_arg = " --fasm " + shlex.quote(top_entity_name + ".fasm")
                f.write(
                    shlex.quote(nextpnr_exe)
                    + " --chipdb "
                    + shlex.quote(chipdb_path)
                    + xdc_arg
                    + " --json "
                    + shlex.quote(top_entity_name + ".json")
                    + " --pre-pack "
                    + shlex.quote(constraints_filepath)
                    + " --timing-allow-fail --seed "
                    + str(nextpnr_seed)
                    + fasm_arg
                    + " &>> "
                    + shlex.quote(log_file_name)
                    + "\n"
                )

            else:
                # Existing ECP5/iCE40 open-tools flow.
                if parser_state.part.lower().startswith("ice"):
                    exe_ext = "ice40"
                    nowidelut = ""
                    dsp = "-dsp"
                else:
                    exe_ext = "ecp5"
                    nowidelut = "-nowidelut"
                    dsp = ""
                yosys_script_arg = WRITE_YOSYS_SCRIPT(
                    [
                        f"ghdl --std=08 -frelaxed {vhdl_files_texts} -e {top_entity_name}",
                        f"synth_{exe_ext} -abc9 {dsp} {nowidelut} -top {top_entity_name}"
                        f" -json {top_entity_name}.json",
                        f"write_edif -top {top_entity_name} {top_entity_name}.edf",
                    ],
                    output_directory + "/" + top_entity_name + "_yosys.ys",
                )
                f.write(
                    """
#!/usr/bin/env bash
export GHDL_PREFIX="""
                    + GHDL_PREFIX
                    + f"""
# Elab+Syn (json is output) $MODULE -g
{YOSYS_BIN_PATH}/yosys {m_ghdl} {yosys_script_arg} &>> """
                    + log_file_name
                    + f"""
# P&R
{NEXTPNR_BIN_PATH}/nextpnr-"""
                    + exe_ext
                    + " "
                    + PART_TO_CMD_LINE_OPTS(parser_state.part)
                    + " --json "
                    + top_entity_name
                    + ".json --pre-pack "
                    + constraints_filepath
                    + " --timing-allow-fail "
                    + f" --seed {nextpnr_seed} "
                    + optional_router2
                    + " &>> "
                    + log_file_name
                    + """
"""
                )
        else:
            # YOSYS_JSON_ONLY
            yosys_script_arg = WRITE_YOSYS_SCRIPT(
                [
                    f"ghdl --std=08 -frelaxed {vhdl_files_texts} -e {top_entity_name}",
                    f"synth -top {top_entity_name}",
                    f"write_json {top_entity_name}.json",
                ],
                output_directory + "/" + top_entity_name + "_yosys.ys",
            )
            f.write(
                """
# Only output yosys json
#!/usr/bin/env bash
export GHDL_PREFIX="""
                + GHDL_PREFIX
                + f"""
# Elab+Syn (json is output) $MODULE -g
{YOSYS_BIN_PATH}/yosys {m_ghdl} {yosys_script_arg} &>> """
                + log_file_name
                + """
"""
            )
        f.close()

        # Execute the command
        syn_imp_bash_cmd = "bash " + sh_file
        print("Running:", log_path, flush=True)
        C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd, cwd=output_directory)
        f = open(log_path, "r")
        log_text = f.read()
        f.close()

        # If just outputting json have to stop now?
        if YOSYS_JSON_ONLY:
            print("Stopping after json output in:", output_directory)
            sys.exit(0)

    return ParsedTimingReport(log_text)


def GENERATE_BITSTREAM(parser_state, multimain_timing_params):
    """Generate the final FPGA bitstream for the selected OPEN_TOOLS target.

    XC7 keeps physical implementation separate from bitstream-format
    conversion. Implement the final board-facing top after PipelineC's normal
    final-file pass, then convert the resulting FASM through Project X-Ray.
    """
    if not IS_XC7_PART(parser_state.part):
        return SYN_AND_REPORT_TIMING(
            None,
            None,
            parser_state,
            multimain_timing_params.TimingParamsLookupTable,
            is_final_top=True,
        )

    # Fail before an expensive final implementation when conversion cannot
    # possibly complete. The pipelinec driver performs the same preflight
    # earlier for --pins builds; this keeps direct backend calls safe too.
    fasm2frames, frames2bit, architecture_db, part_yaml = (
        GET_XC7_BITSTREAM_TOOLS_AND_DB(parser_state.part)
    )

    timing_report = SYN_AND_REPORT_TIMING_FINAL_TOP(
        parser_state, multimain_timing_params
    )

    output_directory = SYN.SYN_OUTPUT_DIRECTORY + "/" + SYN.TOP_LEVEL_MODULE
    top_entity_name = SYN.TOP_LEVEL_MODULE
    fasm_path = os.path.join(output_directory, top_entity_name + ".fasm")
    frames_path = os.path.join(output_directory, top_entity_name + ".frames")
    bit_path = os.path.join(output_directory, top_entity_name + ".bit")
    if not os.path.isfile(fasm_path):
        raise Exception("OpenXC7 final implementation did not produce: " + fasm_path)

    part_name = parser_state.part.lower()
    with open(frames_path, "w") as frames_file:
        subprocess.run(
            [
                fasm2frames,
                "--part",
                part_name,
                "--db-root",
                architecture_db,
                fasm_path,
            ],
            cwd=output_directory,
            stdout=frames_file,
            check=True,
        )
    subprocess.run(
        [
            frames2bit,
            "--part_file",
            part_yaml,
            "--part_name",
            part_name,
            "--frm_file",
            frames_path,
            "--output_file",
            bit_path,
        ],
        cwd=output_directory,
        check=True,
    )
    return timing_report


def RENDER_FINAL_TOP_VERILOG(multimain_timing_params, parser_state):
    output_dir = SYN.SYN_OUTPUT_DIRECTORY + "/" + SYN.TOP_LEVEL_MODULE
    out_file = f"{output_dir}/{SYN.TOP_LEVEL_MODULE}.v"
    print("Rendering top level Verilog...")
    # Identify tool versions
    if not os.path.exists(f"{GHDL_BIN_PATH}/ghdl"):
        raise Exception("ghdl executable not found!")
    if not os.path.exists(f"{YOSYS_BIN_PATH}/yosys"):
        raise Exception("yosys executable not found!")

    # Write a shell script to execute
    m_ghdl = GET_GHDL_PLUGIN_FLAGS()

    # GHDL --out=verilog produces duplicate wires
    # https://github.com/ghdl/ghdl/issues/2491
    """{GHDL_BIN_PATH}/ghdl synth --std=08 -frelaxed --out=verilog `cat ../vhdl_files.txt` -e {SYN.TOP_LEVEL_MODULE} > {SYN.TOP_LEVEL_MODULE}.v"""
    sh_text = f"""
{GHDL_BIN_PATH}/ghdl -i --std=08 -frelaxed @../vhdl_files.txt && \
{GHDL_BIN_PATH}/ghdl -m --std=08 -frelaxed {SYN.TOP_LEVEL_MODULE} && \
{YOSYS_BIN_PATH}/yosys -g {m_ghdl} -p "ghdl --std=08 -frelaxed {SYN.TOP_LEVEL_MODULE}; proc; opt; fsm; opt; memory; opt; write_verilog {SYN.TOP_LEVEL_MODULE}.v"
"""

    sh_path = output_dir + "/" + "convert_to_verilog.sh"
    f = open(sh_path, "w")
    f.write(sh_text)
    f.close()

    # Run command
    bash_cmd = f"bash {sh_path}"
    # print(bash_cmd, flush=True)
    log_text = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(bash_cmd, cwd=output_dir)
    # print(log_text)
    print(f"Top level Verilog file: {out_file}")


def FUNC_IS_PRIMITIVE(func_name):
    if func_name.startswith("ECP5_MUL"):
        return True
    return False


def GET_PRIMITIVE_MODULE_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
    if Logic.func_name.startswith("ECP5_MUL"):
        mul_size_strs = Logic.func_name.replace("ECP5_MUL", "").split("X")
    else:
        raise Exception("TODO other prims!")
    # Assume equal size for now
    if len(mul_size_strs) != 2 or mul_size_strs[0] != mul_size_strs[1]:
        raise Exception("Bad mult size", mul_size_strs)
    width = int(mul_size_strs[0])
    needs_clk = VHDL.LOGIC_NEEDS_CLOCK(
        inst_name, Logic, parser_state, TimingParamsLookupTable
    )
    timing_params = TimingParamsLookupTable[inst_name]

    # IO regs
    n_extra_input_regs = 0
    n_extra_output_regs = 0
    if timing_params._has_input_regs:
        n_extra_input_regs = 1
    if timing_params._has_output_regs:
        n_extra_output_regs = 1

    # Simple mapping of any slicing?
    in_reg = "NONE"
    pipe_reg = "NONE"
    out_reg = "NONE"
    # TODO UPDATE TO USE timing_params._has regs flags
    # 0 slices = comb
    if len(timing_params._slices) == 0:
        pass
    # 1 slice > 50% is output, < means input
    elif len(timing_params._slices) == 1:
        if timing_params._slices[0] > 0.5:
            out_reg = "CLK0"
        else:
            in_reg = "CLK0"
    # 2 slice is in and out
    elif len(timing_params._slices) == 2:
        out_reg = "CLK0"
        in_reg = "CLK0"
    # 3 slice is in,pipline,out regs
    elif len(timing_params._slices) == 3:
        out_reg = "CLK0"
        in_reg = "CLK0"
        pipe_reg = "CLK0"
    else:
        # 4+= determine additions to n_extra_input_regs n_extra_output_regs
        # Start with all 3 pipeline regs and do in,out extra regs evenly
        slice_latency = len(timing_params._slices)
        out_reg = "CLK0"
        in_reg = "CLK0"
        pipe_reg = "CLK0"
        slice_latency -= 3
        while slice_latency > 0:
            if slice_latency > 0:
                n_extra_input_regs += 1
                slice_latency -= 1
            if slice_latency > 0:
                n_extra_output_regs += 1
                slice_latency -= 1

    text = f"""
  component MULT{width}X{width}D is
  generic (
    REG_INPUTA_CLK : string := "NONE";
    REG_INPUTA_CE : string := "CE0";
    REG_INPUTA_RST : string := "RST0";
    --
    REG_INPUTB_CLK : string := "NONE";
    REG_INPUTB_CE : string := "CE0";
    REG_INPUTB_RST : string := "RST0";
    --
    REG_INPUTC_CLK : string := "NONE";
    --reg_inputc_ce : string := "CE0";
    --reg_inputc_rst : string := "RST0";
    --
    REG_PIPELINE_CLK : string := "NONE";
    REG_PIPELINE_CE : string := "CE0";
    REG_PIPELINE_RST : string := "RST0";
    --
    REG_OUTPUT_CLK : string := "NONE";
    --reg_output_ce : string := "CE0";
    --reg_output_rst : string := "RST0";
    --
    CLK0_DIV : string := "ENABLED";
    CLK1_DIV : string := "ENABLED";
    CLK2_DIV : string := "ENABLED";
    CLK3_DIV : string := "ENABLED";
    --
    --highspeed_clk : string := "NONE";
    GSR : string := "ENABLED";
    --Cas_match_reg : string := "FALSE";
    SOURCEB_MODE : string := "B_SHIFT";
    --mult_bypass : string := "DISABLED";
    RESETMODE : string := "SYNC"  );
  port ("""
    if width > 9:
        text += """
    A17 :   in  std_logic;
    A16 :   in  std_logic;
    A15 :   in  std_logic;
    A14 :   in  std_logic;
    A13 :   in  std_logic;
    A12 :   in  std_logic;
    A11 :   in  std_logic;
    A10 :   in  std_logic;
    A9 :   in  std_logic;"""
    text += """
    A8 :   in  std_logic;
    A7 :   in  std_logic;
    A6 :   in  std_logic;
    A5 :   in  std_logic;
    A4 :   in  std_logic;
    A3 :   in  std_logic;
    A2 :   in  std_logic;
    A1 :   in  std_logic;
    A0 :   in  std_logic;"""
    if width > 9:
        text += """
    B17 :   in  std_logic;
    B16 :   in  std_logic;
    B15 :   in  std_logic;
    B14 :   in  std_logic;
    B13 :   in  std_logic;
    B12 :   in  std_logic;
    B11 :   in  std_logic;
    B10 :   in  std_logic;
    B9 :   in  std_logic;"""
    text += """
    B8 :   in  std_logic;
    B7 :   in  std_logic;
    B6 :   in  std_logic;
    B5 :   in  std_logic;
    B4 :   in  std_logic;
    B3 :   in  std_logic;
    B2 :   in  std_logic;
    B1 :   in  std_logic;
    B0 :   in  std_logic;"""
    if width > 9:
        text += """
    C17 :   in  std_logic;
    C16 :   in  std_logic;
    C15 :   in  std_logic;
    C14 :   in  std_logic;
    C13 :   in  std_logic;
    C12 :   in  std_logic;
    C11 :   in  std_logic;
    C10 :   in  std_logic;
    C9 :   in  std_logic;"""
    text += """
    C8 :   in  std_logic;
    C7 :   in  std_logic;
    C6 :   in  std_logic;
    C5 :   in  std_logic;
    C4 :   in  std_logic;
    C3 :   in  std_logic;
    C2 :   in  std_logic;
    C1 :   in  std_logic;
    C0 :   in  std_logic;
    SIGNEDA :   in  std_logic;
    SIGNEDB :   in  std_logic;
    SOURCEA :   in  std_logic;
    SOURCEB :   in  std_logic;
    CLK3 :   in  std_logic;
    CLK2 :   in  std_logic;
    CLK1 :   in  std_logic;
    CLK0 :   in  std_logic;
    CE3 :   in  std_logic;
    CE2 :   in  std_logic;
    CE1 :   in  std_logic;
    CE0 :   in  std_logic;
    RST3 :   in  std_logic;
    RST2 :   in  std_logic;
    RST1 :   in  std_logic;
    RST0 :   in  std_logic;"""
    if width > 9:
        text += """
    --SRIA17 :   in  std_logic;
    --SRIA16 :   in  std_logic;
    --SRIA15 :   in  std_logic;
    --SRIA14 :   in  std_logic;
    --SRIA13 :   in  std_logic;
    --SRIA12 :   in  std_logic;
    --SRIA11 :   in  std_logic;
    --SRIA10 :   in  std_logic;
    --SRIA9 :   in  std_logic;"""
    text += """
    --SRIA8 :   in  std_logic;
    --SRIA7 :   in  std_logic;
    --SRIA6 :   in  std_logic;
    --SRIA5 :   in  std_logic;
    --SRIA4 :   in  std_logic;
    --SRIA3 :   in  std_logic;
    --SRIA2 :   in  std_logic;
    --SRIA1 :   in  std_logic;
    --SRIA0 :   in  std_logic;"""
    if width > 9:
        text += """
    --SRIB17 :   in  std_logic;
    --SRIB16 :   in  std_logic;
    --SRIB15 :   in  std_logic;
    --SRIB14 :   in  std_logic;
    --SRIB13 :   in  std_logic;
    --SRIB12 :   in  std_logic;
    --SRIB11 :   in  std_logic;
    --SRIB10 :   in  std_logic;
    --SRIB9 :   in  std_logic;"""
    text += """
    --SRIB8 :   in  std_logic;
    --SRIB7 :   in  std_logic;
    --SRIB6 :   in  std_logic;
    --SRIB5 :   in  std_logic;
    --SRIB4 :   in  std_logic;
    --SRIB3 :   in  std_logic;
    --SRIB2 :   in  std_logic;
    --SRIB1 :   in  std_logic;
    --SRIB0 :   in  std_logic;"""
    if width > 9:
        text += """
    SROA17 :   out  std_logic;
    SROA16 :   out  std_logic;
    SROA15 :   out  std_logic;
    SROA14 :   out  std_logic;
    SROA13 :   out  std_logic;
    SROA12 :   out  std_logic;
    SROA11 :   out  std_logic;
    SROA10 :   out  std_logic;
    SROA9 :   out  std_logic;"""
    text += """
    SROA8 :   out  std_logic;
    SROA7 :   out  std_logic;
    SROA6 :   out  std_logic;
    SROA5 :   out  std_logic;
    SROA4 :   out  std_logic;
    SROA3 :   out  std_logic;
    SROA2 :   out  std_logic;
    SROA1 :   out  std_logic;
    SROA0 :   out  std_logic;"""
    if width > 9:
        text += """
    SROB17 :   out  std_logic;
    SROB16 :   out  std_logic;
    SROB15 :   out  std_logic;
    SROB14 :   out  std_logic;
    SROB13 :   out  std_logic;
    SROB12 :   out  std_logic;
    SROB11 :   out  std_logic;
    SROB10 :   out  std_logic;
    SROB9 :   out  std_logic;"""
    text += """
    SROB8 :   out  std_logic;
    SROB7 :   out  std_logic;
    SROB6 :   out  std_logic;
    SROB5 :   out  std_logic;
    SROB4 :   out  std_logic;
    SROB3 :   out  std_logic;
    SROB2 :   out  std_logic;
    SROB1 :   out  std_logic;
    SROB0 :   out  std_logic;"""
    if width > 9:
        text += """
    ROA17 :   out  std_logic;
    ROA16 :   out  std_logic;
    ROA15 :   out  std_logic;
    ROA14 :   out  std_logic;
    ROA13 :   out  std_logic;
    ROA12 :   out  std_logic;
    ROA11 :   out  std_logic;
    ROA10 :   out  std_logic;
    ROA9 :   out  std_logic;"""
    text += """
    ROA8 :   out  std_logic;
    ROA7 :   out  std_logic;
    ROA6 :   out  std_logic;
    ROA5 :   out  std_logic;
    ROA4 :   out  std_logic;
    ROA3 :   out  std_logic;
    ROA2 :   out  std_logic;
    ROA1 :   out  std_logic;
    ROA0 :   out  std_logic;"""
    if width > 9:
        text += """
    ROB17 :   out  std_logic;
    ROB16 :   out  std_logic;
    ROB15 :   out  std_logic;
    ROB14 :   out  std_logic;
    ROB13 :   out  std_logic;
    ROB12 :   out  std_logic;
    ROB11 :   out  std_logic;
    ROB10 :   out  std_logic;
    ROB9 :   out  std_logic;"""
    text += """  
    ROB8 :   out  std_logic;
    ROB7 :   out  std_logic;
    ROB6 :   out  std_logic;
    ROB5 :   out  std_logic;
    ROB4 :   out  std_logic;
    ROB3 :   out  std_logic;
    ROB2 :   out  std_logic;
    ROB1 :   out  std_logic;
    ROB0 :   out  std_logic;"""
    if width > 9:
        text += """
    ROC17 :   out  std_logic;
    ROC16 :   out  std_logic;
    ROC15 :   out  std_logic;
    ROC14 :   out  std_logic;
    ROC13 :   out  std_logic;
    ROC12 :   out  std_logic;
    ROC11 :   out  std_logic;
    ROC10 :   out  std_logic;
    ROC9 :   out  std_logic;"""
    text += """
    ROC8 :   out  std_logic;
    ROC7 :   out  std_logic;
    ROC6 :   out  std_logic;
    ROC5 :   out  std_logic;
    ROC4 :   out  std_logic;
    ROC3 :   out  std_logic;
    ROC2 :   out  std_logic;
    ROC1 :   out  std_logic;
    ROC0 :   out  std_logic;"""
    if width > 9:
        text += """
    P35 :   out  std_logic;
    P34 :   out  std_logic;
    P33 :   out  std_logic;
    P32 :   out  std_logic;
    P31 :   out  std_logic;
    P30 :   out  std_logic;
    P29 :   out  std_logic;
    P28 :   out  std_logic;
    P27 :   out  std_logic;
    P26 :   out  std_logic;
    P25 :   out  std_logic;
    P24 :   out  std_logic;
    P23 :   out  std_logic;
    P22 :   out  std_logic;
    P21 :   out  std_logic;
    P20 :   out  std_logic;
    P19 :   out  std_logic;
    P18 :   out  std_logic;"""
    text += (
        """
    P17 :   out  std_logic;
    P16 :   out  std_logic;
    P15 :   out  std_logic;
    P14 :   out  std_logic;
    P13 :   out  std_logic;
    P12 :   out  std_logic;
    P11 :   out  std_logic;
    P10 :   out  std_logic;
    P9 :   out  std_logic;
    P8 :   out  std_logic;
    P7 :   out  std_logic;
    P6 :   out  std_logic;
    P5 :   out  std_logic;
    P4 :   out  std_logic;
    P3 :   out  std_logic;
    P2 :   out  std_logic;
    P1 :   out  std_logic;
    P0 :   out  std_logic;
    SIGNEDP :   out  std_logic  
    );
end component; 

  constant N_EXTRA_INPUT_REGS : integer := """
        + str(n_extra_input_regs)
        + """;
  constant N_EXTRA_OUTPUT_REGS : integer := """
        + str(n_extra_output_regs)
        + f""";
  type input_array_t is array(0 to N_EXTRA_INPUT_REGS-1) of unsigned({width-1} downto 0);
  type output_array_t is array(0 to N_EXTRA_OUTPUT_REGS-1) of unsigned({(width*2)-1} downto 0);

  signal a_in_r : input_array_t;
  signal b_in_r : input_array_t;
  signal p_out_r : output_array_t;

  -- Mult instance ports
  signal a_i : unsigned({width-1} downto 0);
  signal b_i : unsigned({width-1} downto 0);
  signal p_o : unsigned({(width*2)-1} downto 0);

  -- Maybe with extra io regs
  --signal a_c : unsigned({width-1} downto 0);
  --signal b_c : unsigned({width-1} downto 0);
  --signal return_output_c : unsigned({(width*2)-1} downto 0);

  begin

  """
    )

    if n_extra_input_regs > 0:
        text += """
    -- Delay regs
    process(clk) is
    begin
      if rising_edge(clk) then
        a_in_r(0) <= a;
        b_in_r(0) <= b;
        for i in 1 to N_EXTRA_INPUT_REGS-1 loop
          a_in_r(i) <= a_in_r(i-1);
          b_in_r(i) <= b_in_r(i-1);
        end loop;
      end if;
    end process;
    a_i <= a_in_r(N_EXTRA_INPUT_REGS-1);
    b_i <= b_in_r(N_EXTRA_INPUT_REGS-1);
    """
    else:
        text += """
    -- No extra regs
    a_i <= a;
    b_i <= b;
    """

    text += (
        f'''
  mult{width}x{width}d_inst : MULT{width}X{width}D
  generic map (
    REG_INPUTA_CLK => "'''
        + in_reg
        + '''",
    REG_INPUTA_CE => "CE0",
    REG_INPUTA_RST => "RST0",
    --
    REG_INPUTB_CLK => "'''
        + in_reg
        + '''",
    REG_INPUTB_CE => "CE0",
    REG_INPUTB_RST => "RST0",
    --
    REG_INPUTC_CLK => "NONE",
    --reg_inputc_ce => "CE0",
    --reg_inputc_rst => "RST0",
    --
    REG_PIPELINE_CLK => "'''
        + pipe_reg
        + '''",
    REG_PIPELINE_CE => "CE0",
    REG_PIPELINE_RST => "RST0",
    --
    REG_OUTPUT_CLK => "'''
        + out_reg
        + """",
    --reg_output_ce => "CE0",
    --reg_output_rst => "RST0",
    --
    CLK0_DIV => "DISABLED",
    CLK1_DIV => "DISABLED",
    CLK2_DIV => "DISABLED",
    CLK3_DIV => "DISABLED",
    --
    --highspeed_clk => "NONE",
    GSR => "DISABLED",
    --Cas_match_reg => "FALSE",
    --SOURCEB_MODE => "B_SHIFT",
    --mult_bypass => "DISABLED",
    RESETMODE => "ASYNC"  
  )
  port map("""
    )
    if width > 9:
        text += """
    A17 => a_i(17),
    A16 => a_i(16),
    A15 => a_i(15),
    A14 => a_i(14),
    A13 => a_i(13),
    A12 => a_i(12),
    A11 => a_i(11),
    A10 => a_i(10),
    A9 => a_i(9),"""
    text += """
    A8 => a_i(8),
    A7 => a_i(7),
    A6 => a_i(6),
    A5 => a_i(5),
    A4 => a_i(4),
    A3 => a_i(3),
    A2 => a_i(2),
    A1 => a_i(1),
    A0 => a_i(0),"""
    if width > 9:
        text += """
    B17 => b_i(17),
    B16 => b_i(16),
    B15 => b_i(15),
    B14 => b_i(14),
    B13 => b_i(13),
    B12 => b_i(12),
    B11 => b_i(11),
    B10 => b_i(10),
    B9 => b_i(9),"""
    text += """
    B8 => b_i(8),
    B7 => b_i(7),
    B6 => b_i(6),
    B5 => b_i(5),
    B4 => b_i(4),
    B3 => b_i(3),
    B2 => b_i(2),
    B1 => b_i(1),
    B0 => b_i(0),"""
    if width > 9:
        text += """
    C17 => '0',
    C16 => '0',
    C15 => '0',
    C14 => '0',
    C13 => '0',
    C12 => '0',
    C11 => '0',
    C10 => '0',
    C9 => '0',"""
    text += """
    C8 => '0',
    C7 => '0',
    C6 => '0',
    C5 => '0',
    C4 => '0',
    C3 => '0',
    C2 => '0',
    C1 => '0',
    C0 => '0',
    SIGNEDA => '0',
    SIGNEDB => '0',
    SOURCEA => '0',
    SOURCEB => '0',
    CLK3 => '0',
    CLK2 => '0',
    CLK1 => '0',
    """
    if needs_clk:
        text += """
    CLK0 => clk,
    """
    else:
        text += """
    CLK0 => '0',
    """
    text += """
    CE3 => '1',
    CE2 => '1',
    CE1 => '1',
    CE0 => '1',
    RST3 => '0',
    RST2 => '0',
    RST1 => '0',
    RST0 => '0',"""
    if width > 9:
        text += """
    --SRIA17 => '0',
    --SRIA16 => '0',
    --SRIA15 => '0',
    --SRIA14 => '0',
    --SRIA13 => '0',
    --SRIA12 => '0',
    --SRIA11 => '0',
    --SRIA10 => '0',
    --SRIA9 => '0',"""
    text += """
    --SRIA8 => '0',
    --SRIA7 => '0',
    --SRIA6 => '0',
    --SRIA5 => '0',
    --SRIA4 => '0',
    --SRIA3 => '0',
    --SRIA2 => '0',
    --SRIA1 => '0',
    --SRIA0 => '0',"""
    if width > 9:
        text += """
    --SRIB17 => '0',
    --SRIB16 => '0',
    --SRIB15 => '0',
    --SRIB14 => '0',
    --SRIB13 => '0',
    --SRIB12 => '0',
    --SRIB11 => '0',
    --SRIB10 => '0',
    --SRIB9 => '0',"""
    text += """
    --SRIB8 => '0',
    --SRIB7 => '0',
    --SRIB6 => '0',
    --SRIB5 => '0',
    --SRIB4 => '0',
    --SRIB3 => '0',
    --SRIB2 => '0',
    --SRIB1 => '0',
    --SRIB0 => '0',"""
    if width > 9:
        text += """
    SROA17 => open,
    SROA16 => open,
    SROA15 => open,
    SROA14 => open,
    SROA13 => open,
    SROA12 => open,
    SROA11 => open,
    SROA10 => open,
    SROA9 => open,"""
    text += """
    SROA8 => open,
    SROA7 => open,
    SROA6 => open,
    SROA5 => open,
    SROA4 => open,
    SROA3 => open,
    SROA2 => open,
    SROA1 => open,
    SROA0 => open,"""
    if width > 9:
        text += """
    SROB17 => open,
    SROB16 => open,
    SROB15 => open,
    SROB14 => open,
    SROB13 => open,
    SROB12 => open,
    SROB11 => open,
    SROB10 => open,
    SROB9 => open,"""
    text += """
    SROB8 => open,
    SROB7 => open,
    SROB6 => open,
    SROB5 => open,
    SROB4 => open,
    SROB3 => open,
    SROB2 => open,
    SROB1 => open,
    SROB0 => open,"""
    if width > 9:
        text += """
    ROA17 => open,
    ROA16 => open,
    ROA15 => open,
    ROA14 => open,
    ROA13 => open,
    ROA12 => open,
    ROA11 => open,
    ROA10 => open,
    ROA9 => open,"""
    text += """
    ROA8 => open,
    ROA7 => open,
    ROA6 => open,
    ROA5 => open,
    ROA4 => open,
    ROA3 => open,
    ROA2 => open,
    ROA1 => open,
    ROA0 => open,"""
    if width > 9:
        text += """
    ROB17 => open,
    ROB16 => open,
    ROB15 => open,
    ROB14 => open,
    ROB13 => open,
    ROB12 => open,
    ROB11 => open,
    ROB10 => open,
    ROB9 => open,
    ROB8 => open,"""
    text += """
    ROB7 => open,
    ROB6 => open,
    ROB5 => open,
    ROB4 => open,
    ROB3 => open,
    ROB2 => open,
    ROB1 => open,
    ROB0 => open,"""
    if width > 9:
        text += """
    ROC17 => open,
    ROC16 => open,
    ROC15 => open,
    ROC14 => open,
    ROC13 => open,
    ROC12 => open,
    ROC11 => open,
    ROC10 => open,
    ROC9 => open,
    """
    text += """
    ROC8 => open,
    ROC7 => open,
    ROC6 => open,
    ROC5 => open,
    ROC4 => open,
    ROC3 => open,
    ROC2 => open,
    ROC1 => open,
    ROC0 => open,"""
    if width > 9:
        text += """
    P35 => p_o(35),
    P34 => p_o(34),
    P33 => p_o(33),
    P32 => p_o(32),
    P31 => p_o(31),
    P30 => p_o(30),
    P29 => p_o(29),
    P28 => p_o(28),
    P27 => p_o(27),
    P26 => p_o(26),
    P25 => p_o(25),
    P24 => p_o(24),
    P23 => p_o(23),
    P22 => p_o(22),
    P21 => p_o(21),
    P20 => p_o(20),
    P19 => p_o(19),
    P18 => p_o(18),"""
    text += """
    P17 => p_o(17),
    P16 => p_o(16),
    P15 => p_o(15),
    P14 => p_o(14),
    P13 => p_o(13),
    P12 => p_o(12),
    P11 => p_o(11),
    P10 => p_o(10),
    P9 => p_o(9),
    P8 => p_o(8),
    P7 => p_o(7),
    P6 => p_o(6),
    P5 => p_o(5),
    P4 => p_o(4),
    P3 => p_o(3),
    P2 => p_o(2),
    P1 => p_o(1),
    P0 => p_o(0),
    SIGNEDP => open
  );
  """

    if n_extra_output_regs > 0:
        text += """
    -- Delay regs
    process(clk) is
    begin
      if rising_edge(clk) then
        p_out_r(0) <= p_o;
        for i in 1 to N_EXTRA_OUTPUT_REGS-1 loop
          p_out_r(i) <= p_out_r(i-1);
        end loop;
      end if;
    end process;
    return_output <= p_out_r(N_EXTRA_OUTPUT_REGS-1);
    """
    else:
        text += """
    -- No extra regs
    return_output <= p_o;
    """

    return text
