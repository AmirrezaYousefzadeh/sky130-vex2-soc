# Time-windowed activity-based power for sky130_vex2_soc.
# Expects ACTIVITY_TCL with ::tp_n, ::tp_global(i), ::tp_act(i,name), ::tp_duty(i,name)
# and ::mnist_design_period_ns.
#
# Prints parseable markers to stdout for the Python emitter / progress UI:
#   ===WINDOW i===
#   ... report_power ...
#   ===INST u_imem===
#   ...
#   ===INST u_dmem===
#   ...
#   ===ENDWINDOW i===

if {![info exists ::env(ROOT)]} {
  puts "ERROR: ROOT not set"
  exit 1
}
set ROOT $::env(ROOT)
set RUN  $::env(RUN_DIR)
set OUT  $::env(POWER_OUT)
set ACT  $::env(ACTIVITY_TCL)

source $ACT

set lib_sc  $::env(LIB_SC)
set lib_sram $::env(LIB_SRAM)
set netlist "$RUN/final/nl/sky130_vex2_soc.nl.v"
set spef    "$RUN/final/spef/nom/sky130_vex2_soc.nom.spef"

read_liberty $lib_sc
read_liberty $lib_sram
read_verilog $netlist
link_design sky130_vex2_soc
read_spef $spef

set period $::mnist_design_period_ns
set half   [expr {$period / 2.0}]
create_clock -name clk -period $period -waveform [list 0.0 $half] [get_ports clk]
set_propagated_clock [get_clocks clk]

# Sleep: case-analyze core ICG GATE from VCD sram_clk_en duty (see power_icg_utils.tcl).
source [file join $::env(ROOT) power power_icg_utils.tcl]
set ::power_core_icg_gate [power_find_core_icg_gate]
if {$::power_core_icg_gate eq ""} {
  puts "WARNING: core ICG GATE not found; time-power will not derate sleep"
} else {
  puts "core_icg_gate=$::power_core_icg_gate"
}

file mkdir $OUT

set has_imem [llength [get_cells -quiet u_imem]]
set has_dmem [llength [get_cells -quiet u_dmem]]

proc apply_window_activity {i} {
  set_power_activity -global -activity $::tp_global($i) -duty 0.5

  if {[info exists ::tp_act($i,reset)]} {
    set_power_activity -input_ports [get_ports reset] \
      -activity $::tp_act($i,reset) -duty $::tp_duty($i,reset)
  }

  foreach {inst key_ce key_we} {u_imem imem_ce imem_we u_dmem dmem_ce dmem_we} {
    if {[llength [get_cells -quiet $inst]] == 0} {
      continue
    }
    if {[llength [get_pins -quiet $inst/ce]] && [info exists ::tp_act($i,$key_ce)]} {
      set_power_activity -pins [get_pins $inst/ce] \
        -activity $::tp_act($i,$key_ce) -duty 0.5
    }
    if {[llength [get_pins -quiet $inst/we]] && [info exists ::tp_act($i,$key_we)]} {
      set_power_activity -pins [get_pins $inst/we] \
        -activity $::tp_act($i,$key_we) -duty 0.5
    }
  }

  # Derate gated core_clk tree for sleep windows (OpenSTA ignores GATE activity).
  set en_duty [power_core_enable_duty_from_window $i]
  set awake [power_apply_core_clk_enable $en_duty]
  puts "core_clk_en_duty=$en_duty awake=$awake"
}

set n $::tp_n
puts "TIME_POWER_WINDOWS $n"
flush stdout

for {set i 0} {$i < $n} {incr i} {
  apply_window_activity $i

  puts "===WINDOW $i==="
  flush stdout
  report_power -digits 6

  puts "===INST u_imem==="
  flush stdout
  if {$has_imem} {
    report_power -instances [get_cells u_imem] -digits 6
  } else {
    puts "MISSING u_imem"
  }

  puts "===INST u_dmem==="
  flush stdout
  if {$has_dmem} {
    report_power -instances [get_cells u_dmem] -digits 6
  } else {
    puts "MISSING u_dmem"
  }

  puts "===ENDWINDOW $i==="
  flush stdout
}

puts "TIME_POWER_DONE"
flush stdout
exit
