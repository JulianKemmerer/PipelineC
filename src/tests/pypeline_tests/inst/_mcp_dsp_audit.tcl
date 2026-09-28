# Sourced by mcp_dsp_packing_test.py after opening a freshly built checkpoint.
proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} { error $message }
}
proc check_bank {cells expected label} {
    require {[llength $cells] == $expected} "$label: expected $expected bits, found [llength $cells]"
    foreach cell $cells {
        require {[string match FD* [get_property REF_NAME $cell]]} "$label: not a fabric register: $cell"
        require {[get_property DONT_TOUCH $cell]} "$label: missing DONT_TOUCH: $cell"
    }
}
proc check_requirements {paths expected label} {
    require {[llength $paths] > 0} "$label: no timing paths"
    foreach path $paths {
        set actual [get_property REQUIREMENT $path]
        require {abs($actual - $expected) < 0.01} "$label: expected $expected ns, got $actual ns"
    }
}
proc check_launch_control {launches} {
    # Vivado can implement the enable either on CE or in a feedback mux at D.
    # Restrict sources to the actual controller registers so a data/self-feedback
    # path cannot hide a missing or incorrectly relaxed controller path. Controllers
    # may be shared between identical wrappers, so do not require local ownership.
    set controllers [get_cells -hier -filter {NAME =~ *cycles_since_launch_reg* && IS_SEQUENTIAL}]
    set from [get_pins -of_objects $controllers -filter {REF_PIN_NAME == C}]
    require {[llength $from] > 0} "missing launch controller registers"
    foreach launch $launches {
        set to [get_pins -of_objects $launch -filter {REF_PIN_NAME == CE || REF_PIN_NAME == D}]
        check_requirements [get_timing_paths -quiet -from $from -to $to -max_paths 2 -delay_type max] 12.5 "launch control setup at $launch"
        check_requirements [get_timing_paths -quiet -from $from -to $to -max_paths 2 -delay_type min] 0.0 "launch control hold at $launch"
    }
}
proc check_pair {n start end} {
    set launches [get_cells -quiet $start]
    set captures [get_cells -quiet $end]
    check_bank $launches 64 launch
    check_bank $captures 32 capture
    # Independently enumerate the expected aggregate bit names. A wildcard
    # matching some surviving bits does not establish endpoint preservation.
    set prefix [string range $start 0 end-3]
    foreach suffix {{[a]} {[b]} {[salt][0]} {[salt][1]}} {
        # Vivado flattens record fields and array dimensions as separate brackets.
        for {set bit 0} {$bit < 16} {incr bit} {
            set name [format {%s%s[%d]} $prefix $suffix $bit]
            require {[lsearch -exact $launches $name] >= 0} "missing launch bit $name"
        }
    }
    set prefix [string range $end 0 end-3]
    for {set bit 0} {$bit < 32} {incr bit} {
        set name [format {%s[%d]} $prefix $bit]
        require {[lsearch -exact $captures $name] >= 0} "missing capture bit $name"
    }
    set from [get_pins -of_objects $launches -filter {REF_PIN_NAME == C}]
    set to [get_pins -of_objects $captures -filter {REF_PIN_NAME == D}]
    require {[llength $from] == 64 && [llength $to] == 32} "incomplete endpoint pin collections"
    foreach pin $from {
        check_requirements [get_timing_paths -from $pin -to $to -max_paths 32 -delay_type max] [expr {$n * 12.5}] "setup from $pin"
        check_requirements [get_timing_paths -from $pin -to $to -delay_type min] 0.0 "hold from $pin"
    }
    foreach pin $to {
        check_requirements [get_timing_paths -from $from -to $pin -delay_type max] [expr {$n * 12.5}] "setup to $pin"
    }
    # MCP exceptions target capture D, not the launch control logic.
    check_launch_control $launches
    set holder [file dirname $start]
    set dsps {}
    foreach dsp [get_cells -hier -filter {REF_NAME == DSP48E1}] {
        if {[string first "$holder/" $dsp] == 0} { lappend dsps $dsp }
    }
    require {[llength $dsps] > 0} "no inferred DSPs in $holder"
    foreach dsp $dsps {
        foreach reg {AREG BREG MREG PREG} {
            require {[get_property $reg $dsp] == 0} "$dsp absorbed a register ($reg)"
        }
    }
}
proc audit_mcps {pairs phase} {
    foreach pair $pairs { check_pair {*}$pair }
    set control [get_cells -hier -filter {NAME =~ *control_reg* && IS_SEQUENTIAL}]
    set control_d [get_pins -of_objects $control -filter {REF_PIN_NAME == D}]
    check_requirements [get_timing_paths -to $control_d -max_paths 16] 12.5 "neighboring counter"
    puts "MCP_DSP_AUDIT_PASS $phase"
}
proc negative_checks {pairs} {
    lassign [lindex $pairs 0] n start end
    set launches [get_cells $start]
    set code [catch {check_bank [lrange $launches 1 end] 64 launch} message]
    require {$code && [string first "expected 64 bits" $message] >= 0} "partial endpoint loss was accepted"
    # Mutate only the disposable in-memory test design, never the checkpoint.
    set from [get_pins -of_objects $launches -filter {REF_PIN_NAME == C}]
    set to [get_pins -of_objects [get_cells $end] -filter {REF_PIN_NAME == D}]
    set_multicycle_path [expr {$n + 1}] -setup -from $from -to $to
    set code [catch {check_pair $n $start $end} message]
    require {$code && [string first "ns, got" $message] >= 0} "wrong MCP requirement was accepted: $message"
    # Deliberately relax controller timing too: the audit must reject this
    # whether Vivado chose a physical CE or a mux driving the launch D pin.
    set controllers [get_cells -hier -filter {NAME =~ *cycles_since_launch_reg* && IS_SEQUENTIAL}]
    set control_from [get_pins -of_objects $controllers -filter {REF_PIN_NAME == C}]
    set control_to [get_pins -of_objects $launches -filter {REF_PIN_NAME == CE || REF_PIN_NAME == D}]
    set_multicycle_path 2 -setup -from $control_from -to $control_to
    set code [catch {check_launch_control $launches} message]
    require {$code && [string first "launch control setup" $message] >= 0 && [string first "ns, got" $message] >= 0} "relaxed launch control was accepted: $message"
    puts "MCP_DSP_NEGATIVE_CHECKS_PASS"
}
