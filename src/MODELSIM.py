#!/usr/bin/env python

import sys
import os
import subprocess
import math
import hashlib
import copy

import SIM
import C_TO_LOGIC
import VHDL
import SW_LIB
import SYN
import VIVADO



# Default to env if there
TOOL_EXE = "vsim"
ENV_TOOL_PATH = C_TO_LOGIC.GET_TOOL_PATH(TOOL_EXE)
if ENV_TOOL_PATH:
  MODELSIM_PATH = ENV_TOOL_PATH
else:
  #MODELSIM_PATH="/media/1TB/Programs/Linux/Modelsim/modelsim_ase/bin/vsim"
  MODELSIM_PATH="/media/1TB/Programs/Linux/Modelsim18.0.0.219/modelsim_ase/bin/vsim"

MODEL_SIM_INI_TEXT='''
; Copyright 1991-2017 Mentor Graphics Corporation
;
; All Rights Reserved.
;
; THIS WORK CONTAINS TRADE SECRET AND PROPRIETARY INFORMATION WHICH IS THE PROPERTY OF 
; MENTOR GRAPHICS CORPORATION OR ITS LICENSORS AND IS SUBJECT TO LICENSE TERMS.
;   

[Library]
std = $MODEL_TECH/../std
ieee = $MODEL_TECH/../ieee
vital2000 = $MODEL_TECH/../vital2000
;
; VITAL concerns:
;
; The library ieee contains (among other packages) the packages of the
; VITAL 2000 standard.  When a design uses VITAL 2000 exclusively, it should use
; the physical library ieee (recommended), or use the physical library
; vital2000, but not both.  The design can use logical library ieee and/or
; vital2000 as long as each of these maps to the same physical library, either
; ieee or vital2000.
;
; A design using the 1995 version of the VITAL packages, whether or not
; it also uses the 2000 version of the VITAL packages, must have logical library
; name ieee mapped to physical library vital1995.  (A design cannot use library
; vital1995 directly because some packages in this library use logical name ieee
; when referring to the other packages in the library.)  The design source
; should use logical name ieee when referring to any packages there except the
; VITAL 2000 packages.  Any VITAL 2000 present in the design must use logical
; name vital2000 (mapped to physical library vital2000) to refer to those
; packages.
; ieee = $MODEL_TECH/../vital1995
;
; For compatiblity with previous releases, logical library name vital2000 maps
; to library vital2000 (a different library than library ieee, containing the
; same packages).
; A design should not reference VITAL from both the ieee library and the
; vital2000 library because the vital packages are effectively different.
; A design that references both the ieee and vital2000 libraries must have
; both logical names ieee and vital2000 mapped to the same library, either of
; these:
;   $MODEL_TECH/../ieee
;   $MODEL_TECH/../vital2000
;
verilog = $MODEL_TECH/../verilog
std_developerskit = $MODEL_TECH/../std_developerskit
synopsys = $MODEL_TECH/../synopsys
modelsim_lib = $MODEL_TECH/../modelsim_lib
sv_std = $MODEL_TECH/../sv_std
floatfixlib = $MODEL_TECH/../floatfixlib
osvvm = $MODEL_TECH/../osvvm

; Altera Primitive libraries
;
; VHDL Section
;
altera_mf = $MODEL_TECH/../altera/vhdl/altera_mf
altera = $MODEL_TECH/../altera/vhdl/altera
altera_lnsim = $MODEL_TECH/../altera/vhdl/altera_lnsim
lpm = $MODEL_TECH/../altera/vhdl/220model
220model = $MODEL_TECH/../altera/vhdl/220model
sgate = $MODEL_TECH/../altera/vhdl/sgate
twentynm = $MODEL_TECH/../altera/vhdl/twentynm
twentynm_hssi = $MODEL_TECH/../altera/vhdl/twentynm_hssi
twentynm_hip = $MODEL_TECH/../altera/vhdl/twentynm_hip
fourteennm = $MODEL_TECH/../altera/vhdl/fourteennm
fourteennm_ct1 = $MODEL_TECH/../altera/vhdl/fourteennm_ct1
cyclone10gx = $MODEL_TECH/../altera/vhdl/cyclone10gx
cyclone10gx_hssi = $MODEL_TECH/../altera/vhdl/cyclone10gx_hssi
cyclone10gx_hip = $MODEL_TECH/../altera/vhdl/cyclone10gx_hip
;
; Verilog Section
;
altera_mf_ver = $MODEL_TECH/../altera/verilog/altera_mf
altera_ver = $MODEL_TECH/../altera/verilog/altera
altera_lnsim_ver = $MODEL_TECH/../altera/verilog/altera_lnsim
lpm_ver = $MODEL_TECH/../altera/verilog/220model
220model_ver = $MODEL_TECH/../altera/verilog/220model
sgate_ver = $MODEL_TECH/../altera/verilog/sgate
twentynm_ver = $MODEL_TECH/../altera/verilog/twentynm
twentynm_hssi_ver = $MODEL_TECH/../altera/verilog/twentynm_hssi
twentynm_hip_ver = $MODEL_TECH/../altera/verilog/twentynm_hip
fourteennm_ver = $MODEL_TECH/../altera/verilog/fourteennm
fourteennm_ct1_ver = $MODEL_TECH/../altera/verilog/fourteennm_ct1
cyclone10gx_ver = $MODEL_TECH/../altera/verilog/cyclone10gx
cyclone10gx_hssi_ver = $MODEL_TECH/../altera/verilog/cyclone10gx_hssi
cyclone10gx_hip_ver = $MODEL_TECH/../altera/verilog/cyclone10gx_hip

[vcom]
; VHDL93 variable selects language version as the default. 
; Default is VHDL-2002.
; Value of 0 or 1987 for VHDL-1987.
; Value of 1 or 1993 for VHDL-1993.
; Default or value of 2 or 2002 for VHDL-2002.
; Value of 3 or 2008 for VHDL-2008
VHDL93 = 2008

; Show source line containing error. Default is off.
; Show_source = 1

; Turn off unbound-component warnings. Default is on.
; Show_Warning1 = 0

; Turn off process-without-a-wait-statement warnings. Default is on.
; Show_Warning2 = 0

; Turn off null-range warnings. Default is on.
; Show_Warning3 = 0

; Turn off no-space-in-time-literal warnings. Default is on.
; Show_Warning4 = 0

; Turn off multiple-drivers-on-unresolved-signal warnings. Default is on.
; Show_Warning5 = 0

; Turn off optimization for IEEE std_logic_1164 package. Default is on.
; Optimize_1164 = 0

; Turn on resolving of ambiguous function overloading in favor of the
; "explicit" function declaration (not the one automatically created by
; the compiler for each type declaration). Default is off.
; The .ini file has Explicit enabled so that std_logic_signed/unsigned
; will match the behavior of synthesis tools.
Explicit = 1

; Turn off acceleration of the VITAL packages. Default is to accelerate.
; NoVital = 1

; Turn off VITAL compliance checking. Default is checking on.
; NoVitalCheck = 1

; Ignore VITAL compliance checking errors. Default is to not ignore.
; IgnoreVitalErrors = 1

; Turn off VITAL compliance checking warnings. Default is to show warnings.
; Show_VitalChecksWarnings = 0

; Keep silent about case statement static warnings.
; Default is to give a warning.
; NoCaseStaticError = 1

; Keep silent about warnings caused by aggregates that are not locally static.
; Default is to give a warning.
; NoOthersStaticError = 1

; Treat as errors:
;   case statement static warnings
;   warnings caused by aggregates that are not locally static
; Overrides NoCaseStaticError, NoOthersStaticError settings.
; PedanticErrors = 1

; Turn off inclusion of debugging info within design units.
; Default is to include debugging info.
; NoDebug = 1

; Turn off "Loading..." messages. Default is messages on.
; Quiet = 1

; Turn on some limited synthesis rule compliance checking. Checks only:
;    -- signals used (read) by a process must be in the sensitivity list
; CheckSynthesis = 1

; Activate optimizations on expressions that do not involve signals,
; waits, or function/procedure/task invocations. Default is off.
; ScalarOpts = 1

; Turns on lint-style checking.
; Show_Lint = 1

; Require the user to specify a configuration for all bindings,
; and do not generate a compile time default binding for the
; component. This will result in an elaboration error of
; 'component not bound' if the user fails to do so. Avoids the rare
; issue of a false dependency upon the unused default binding.
; RequireConfigForAllDefaultBinding = 1

; Perform default binding at compile time.
; Default is to do default binding at load time.
; BindAtCompile = 1;

; Inhibit range checking on subscripts of arrays. Range checking on
; scalars defined with subtypes is inhibited by default.
; NoIndexCheck = 1

; Inhibit range checks on all (implicit and explicit) assignments to
; scalar objects defined with subtypes.
; NoRangeCheck = 1

; Use this directory for compiler temporary files instead of "work/_temp"
; CompilerTempDir = /tmp

; Set this to cause the compilers to force data to be committed to disk
; when the files are closed.
; SyncCompilerFiles = 1

; Range and length checking will be performed on array indices and discrete
; ranges, and when violations are found within subprograms, errors will be
; reported. Default is to issue warnings for violations, because subprograms
; may not be invoked.
; NoDeferSubpgmCheck = 0

;Controls if VHDL identifiers are store lower case or left in the
;case of the declaration. Does not make the langauge case sensitive.
;Only effect how identifiers are printed. Default is to preserve the
;users case.  Value of 0 indicates lower case identifers
; PreserveCase = 1

;In Configuraiton, Controls the visibility of use clause in the design
;units being configurated.  If 1, then pre-6.7 behavior. Extends the visibility
;of objects made visible through use clauses into nested component configurations
; OldVHDLConfigurationVisibility = 0

[vlog]

; Turn off inclusion of debugging info within design units.
; Default is to include debugging info.
; NoDebug = 1

; Turn on `protect compiler directive processing.
; Default is to ignore `protect directives.
; Protect = 1

; Turn off "loading..." messages. Default is messages on.
; Quiet = 1

; Turn on Verilog hazard checking (order-dependent accessing of global vars).
; Default is off.
; Hazard = 1

; Turn on converting regular Verilog identifiers to uppercase. Allows case
; insensitivity for module names. Default is no conversion.
; UpCase = 1

; Turn on incremental compilation of modules. Default is off.
; Incremental = 1

; Turns on lint-style checking.

; Show_Lint = 1

; Turn on bad option warning. Default is off.
; Show_BadOptionWarning = 1

; Revert back to IEEE 1364-1995 syntax, default is 0 (off).
; vlog95compat = 1

[vsim]

; Automatic SDF compilation
; Disables automatic compilation of SDF files in flows that support it.
; Default is on, uncomment to turn off.
; NoAutoSDFCompile = 1

; Simulator resolution
; Set to fs, ps, ns, us, ms, or sec with optional prefix of 1, 10, or 100.
Resolution = ps

; User time unit for run commands
; Set to default, fs, ps, ns, us, ms, or sec. The default is to use the
; unit specified for Resolution. For example, if Resolution is 100ps,
; then UserTimeUnit defaults to ps.
; Should generally be set to default.
UserTimeUnit = default

; Default run length
RunLength = 100

; Maximum iterations that can be run without advancing simulation time
IterationLimit = 5000

; Directive to license manager:
; vhdl          Immediately reserve a VHDL license
; vlog          Immediately reserve a Verilog license
; plus          Immediately reserve a VHDL and Verilog license
; nomgc         Do not look for Mentor Graphics Licenses
; nomti         Do not look for Model Technology Licenses
; noqueue       Do not wait in the license queue when a license isn't available
; viewsim	Try for viewer license but accept simulator license(s) instead
;		of queuing for viewer license
; License = plus

; Stop the simulator after a VHDL/Verilog assertion message
; 0 = Note  1 = Warning  2 = Error  3 = Failure  4 = Fatal
BreakOnAssertion = 3

; Message Format conversion specifications:
; %S - Severity Level of message/assertion
; %R - Text of message
; %T - Time of message
; %D - Delta value (iteration number) of Time
; %K - Kind of path: Instance/Region/Signal/Process/Foreign Process/Unknown/Protected
; %i - Instance/Region/Signal pathname with Process name (if available)
; %I - shorthand for one of these:
;      "  %K: %i"
;      "  %K: %i File: %F" (when path is not Process or Signal)
;      except that the %i in this case does not report the Process name
; %O - Process name
; %P - Instance/Region path without leaf process
; %F - File name
; %L - Line number; if assertion message, then line number of assertion or, if
;      assertion is in a subprogram, line from which the call is made
; %u - Design unit name in form library.primary
; %U - Design unit name in form library.primary(secondary)
; %% - The '%' character itself
;
; If specific format for Severity Level is defined, use that format.
; Else, for a message that occurs during elaboration:
;   -- Failure/Fatal message in VHDL region that is not a Process, and in
;      certain non-VHDL regions, uses MessageFormatBreakLine;
;   -- Failure/Fatal message otherwise uses MessageFormatBreak;
;   -- Note/Warning/Error message uses MessageFormat.
; Else, for a message that occurs during runtime and triggers a breakpoint because
; of the BreakOnAssertion setting:
;   -- if in a VHDL region that is not a Process, uses MessageFormatBreakLine;
;   -- otherwise uses MessageFormatBreak.
; Else (a runtime message that does not trigger a breakpoint) uses MessageFormat.
;
; MessageFormatNote      = "** %S: %R\n   Time: %T  Iteration: %D%I\n"
; MessageFormatWarning   = "** %S: %R\n   Time: %T  Iteration: %D%I\n"
; MessageFormatError     = "** %S: %R\n   Time: %T  Iteration: %D  %K: %i File: %F\n"
; MessageFormatFail      = "** %S: %R\n   Time: %T  Iteration: %D  %K: %i File: %F\n"
; MessageFormatFatal     = "** %S: %R\n   Time: %T  Iteration: %D  %K: %i File: %F\n"
; MessageFormatBreakLine = "** %S: %R\n   Time: %T  Iteration: %D  %K: %i File: %F Line: %L\n"
; MessageFormatBreak     = "** %S: %R\n   Time: %T  Iteration: %D  %K: %i File: %F\n"
; MessageFormat          = "** %S: %R\n   Time: %T  Iteration: %D%I\n"
; Assertion Message Format
; %S - Severity Level 
; %R - Report Message
; %T - Time of assertion
; %D - Delta
; %I - Instance or Region pathname (if available)
; %% - print '%' character
; AssertionFormat = "** %S: %R\n   Time: %T  Iteration: %D%I\n"

; Assertion File - alternate file for storing VHDL/Verilog assertion messages
; AssertFile = assert.log

; Default radix for all windows and commands...
; Set to symbolic, ascii, binary, octal, decimal, hex, unsigned
DefaultRadix = symbolic

; VSIM Startup command
; Startup = do startup.do

; File for saving command transcript
TranscriptFile = transcript

; File for saving command history
; CommandHistory = cmdhist.log

; Specify whether paths in simulator commands should be described
; in VHDL or Verilog format.
; For VHDL, PathSeparator = /
; For Verilog, PathSeparator = .
; Must not be the same character as DatasetSeparator.
PathSeparator = /

; Specify the dataset separator for fully rooted contexts.
; The default is ':'. For example, sim:/top
; Must not be the same character as PathSeparator.
DatasetSeparator = :

; Disable VHDL assertion messages
; IgnoreNote = 1
; IgnoreWarning = 1
; IgnoreError = 1
; IgnoreFailure = 1

; Default force kind. May be freeze, drive, deposit, or default
; or in other terms, fixed, wired, or charged.
; A value of "default" will use the signal kind to determine the
; force kind, drive for resolved signals, freeze for unresolved signals
; DefaultForceKind = freeze

; If zero, open files when elaborated; otherwise, open files on
; first read or write.  Default is 0.
; DelayFileOpen = 1

; Control VHDL files opened for write.
;   0 = Buffered, 1 = Unbuffered
UnbufferedOutput = 0

; Control the number of VHDL files open concurrently.
; This number should always be less than the current ulimit
; setting for max file descriptors.
;   0 = unlimited
ConcurrentFileLimit = 40

; Control the number of hierarchical regions displayed as
; part of a signal name shown in the Wave window.
; A value of zero tells VSIM to display the full name.
; The default is 0.
; WaveSignalNameWidth = 0

; Turn off warnings from the std_logic_arith, std_logic_unsigned
; and std_logic_signed packages.
; StdArithNoWarnings = 1

; Turn off warnings from the IEEE numeric_std and numeric_bit packages.
; NumericStdNoWarnings = 1

; Use old-style (pre-6.6) VHDL FOR generate statement iteration names
; in the design hierarchy.
; This style is controlled by the value of the GenerateFormat
; value described next.  Default is to use new-style names, which
; comprise the generate statement label, '(', the value of the generate
; parameter, and a closing ')'.
; Uncomment this to use old-style names.
; OldVhdlForGenNames = 1

; Control the format of the (VHDL) FOR generate statement label
; for each iteration.  Do not quote it.
; The format string here must contain the conversion codes %s and %d,
; in that order, and no other conversion codes.  The %s represents
; the generate_label; the %d represents the generate parameter value
; at a particular generate iteration (this is the position number if
; the generate parameter is of an enumeration type).  Embedded whitespace
; is allowed (but discouraged); leading and trailing whitespace is ignored.
; Application of the format must result in a unique scope name over all
; such names in the design so that name lookup can function properly.
; GenerateFormat = %s__%d

; Enable changes in VHDL elaboration to allow for Variable Logging
; This trades off simulation performance for the ability to log variables
; efficiently.  By default this is disable for maximum simulation performance
; VhdlVariableLogging = 1

; Specify whether checkpoint files should be compressed.
; The default is 1 (compressed).
; CheckpointCompressMode = 0

; List of dynamically loaded objects for Verilog PLI applications
; Veriuser = veriuser.sl

; Specify default options for the restart command. Options can be one
; or more of: -force -nobreakpoint -nolist -nolog -nowave
; DefaultRestartOptions = -force

; HP-UX 10.20 ONLY - Enable memory locking to speed up large designs
; (> 500 megabyte memory footprint). Default is disabled.
; Specify number of megabytes to lock.
; LockedMemory = 1000

; Turn on (1) or off (0) WLF file compression.
; The default is 1 (compress WLF file).
; WLFCompress = 0

; Specify whether to save all design hierarchy (1) in the WLF file
; or only regions containing logged signals (0).
; The default is 0 (save only regions with logged signals).
; WLFSaveAllRegions = 1

; WLF file time limit.  Limit WLF file by time, as closely as possible,
; to the specified amount of simulation time.  When the limit is exceeded
; the earliest times get truncated from the file.
; If both time and size limits are specified the most restrictive is used.
; UserTimeUnits are used if time units are not specified.
; The default is 0 (no limit).  Example: WLFTimeLimit = {100 ms}
; WLFTimeLimit = 0

; WLF file size limit.  Limit WLF file size, as closely as possible,
; to the specified number of megabytes.  If both time and size limits
; are specified then the most restrictive is used.
; The default is 0 (no limit).
; WLFSizeLimit = 1000

; Specify whether or not a WLF file should be deleted when the
; simulation ends.  A value of 1 will cause the WLF file to be deleted.
; The default is 0 (do not delete WLF file when simulation ends).
; WLFDeleteOnQuit = 1

; Specify whether or not a WLF file should be indexed during 
; simulation.  If set to 0, the WLF file will not be indexed.
; The default is 1, indexed the WLF file.
; WLFIndex = 0

; Specify whether or not a WLF file should be optimized during 
; simulation.  If set to 0, the WLF file will not be optimized.
; The default is 1, optimize the WLF file.
; WLFOptimize = 0

; Specify the name of the WLF file.
; The default is vsim.wlf
; WLFFilename = vsim.wlf

; Specify whether to lock the WLF file.
; Locking the file prevents other invocations of ModelSim/Questa tools from
; inadvertently overwriting the WLF file.
; The default is 1, lock the WLF file.
; WLFFileLock = 0

; Specify the WLF reader cache size limit for each open WLF file.  
; The size is giving in megabytes.  A value of 0 turns off the
; WLF cache. 
; WLFSimCacheSize allows a different cache size to be set for 
; simulation WLF file independent of post-simulation WLF file 
; viewing.  If WLFSimCacheSize is not set it defaults to the
; WLFCacheSize setting.
; The default WLFCacheSize setting is enabled to 256M per open WLF file.
; WLFCacheSize = 2000
; WLFSimCacheSize = 500

; Specify the WLF file event collapse mode.
; 0 = Preserve all events and event order. (same as -wlfnocollapse)
; 1 = Only record values of logged objects at the end of a simulator iteration. 
;     (same as -wlfcollapsedelta)
; 2 = Only record values of logged objects at the end of a simulator time step. 
;     (same as -wlfcollapsetime)
; The default is 1.
; WLFCollapseMode = 0

; Specify whether WLF file logging can use threads on multi-processor machines
; if 0, no threads will be used, if 1, threads will be used if the system has
; more than one processor
; WLFUseThreads = 1

; Customize the vsim kernel shutdown behavior at the end of the simulation.
; Some common causes of the end of simulation are $finish (implicit or explicit), 
; sc_stop(), tf_dofinish(), and assertion failures. 
; This should be set to "ask", "exit", or "stop". The default is "ask".
; "ask"   -- In batch mode, the vsim kernel will abruptly exit.  
;            In GUI mode, a dialog box will pop up and ask for user confirmation 
;            whether or not to quit the simulation.
; "stop"  -- Cause the simulation to stay loaded in memory. This can make some 
;            post-simulation tasks easier.
; "exit"  -- The simulation will abruptly exit without asking for any confirmation.
; "final" -- Run SystemVerilog final blocks then behave as "stop".
; Note: This variable can be overridden with the vsim "-onfinish" command line switch.
OnFinish = ask

; Check vsim plusargs.  Default is 0 (off).
; 0 = Don't check plusargs
; 1 = Warning on unrecognized plusarg
; 2 = Error and exit on unrecognized plusarg
; CheckPlusargs = 1

; Environment variable expansion of command line arguments has been depricated 
; in favor shell level expansion.  Universal environment variable expansion 
; inside -f files is support and continued support for MGC Location Maps provide
; alternative methods for handling flexible pathnames.
; The following line may be uncommented and the value set to 1 to re-enable this 
; deprecated behavior.  The default value is 0.
; DeprecatedEnvironmentVariableExpansion = 0

; Turn on/off collapsing of bus ports in VCD dumpports output
DumpportsCollapse = 1

[lmc]

[msg_system]
; Change a message severity or suppress a message.
; The format is: <msg directive> = <msg number>[,<msg number>...]
; Examples:
;   note = 3009
;   warning = 3033
;   error = 3010,3016
;   fatal = 3016,3033
;   suppress = 3009,3016,3043
; The command verror <msg number> can be used to get the complete
; description of a message.

; Control transcripting of elaboration/runtime messages.
; The default is to have messages appear in the transcript and 
; recorded in the wlf file (messages that are recorded in the
; wlf file can be viewed in the MsgViewer).  The other settings
; are to send messages only to the transcript or only to the 
; wlf file.  The valid values are
;    both  {default}
;    tran  {transcript only}
;    wlf   {wlf file only}
; msgmode = both
'''


def DO_OPTIONAL_DEBUG(do_debug=False, latency=0):
  # DO DEBUG PROJECT?
  if not do_debug:
    return
  
  print("================== Doing Optional Modelsim Debug ================================", flush=True)
  # #######################################################################################################
  
  # Get all vhd files in syn output
  vhd_files = SIM.GET_SIM_FILES(latency=0)
  
  # .do FILE to execute:
  proj_name = "pipelinc_proj"
  proj_dir = SYN.SYN_OUTPUT_DIRECTORY + "/"
  text = ""
  text += '''
  project new {''' + proj_dir + '''} ''' + proj_name + '''
  '''
    
  # Compile ieee_proposed in fixed/float support?
  if SYN.SYN_TOOL is VIVADO:
    text += '''vcom -work ieee_proposed -2002 -explicit -stats=none ''' + VIVADO.VIVADO_DIR + "/scripts/rt/data/fixed_pkg_c.vhd" + "\n"
    text += '''vcom -work ieee_proposed -2002 -explicit -stats=none ''' + VIVADO.VIVADO_DIR + "/scripts/rt/data/float_pkg_c.vhd" + "\n" 
  
  # Add all files
  for vhd_file in vhd_files:
    text += '''
  project addfile {''' + vhd_file + '''}
  '''
  
  # Compile to work library?
  text += '''
  project calculateorder
  project compileall
  vlib work
  vmap work work
  '''
  # Do vsim too?
  # vsim work.main_bin_op_sl_main_c_7_top

  # Identify tool versions
  if os.path.exists(MODELSIM_PATH):
    print(MODELSIM_PATH, flush=True)
  else:
    raise Exception("vsim executable not found!")
  
  ini_filepath = proj_dir + "pipelinec_modelsim.ini"
  f=open(ini_filepath,"w")
  f.write(MODEL_SIM_INI_TEXT)
  f.close()
  do_filename = proj_name + ".do"
  do_filepath = proj_dir + do_filename
  f=open(do_filepath,"w")
  f.write(text)
  f.close()
  
  # Run modelsim
  bash_cmd = (
    MODELSIM_PATH + " " + "-modelsimini " + ini_filepath + " " + "-do 'source {" + do_filepath + "}' " )
  print(bash_cmd, flush=True)  
  
  log_text = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(bash_cmd)
  print(log_text, flush=True)
  sys.exit(-1)
  
