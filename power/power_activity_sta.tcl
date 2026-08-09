# Activity-based power for sky130_vex2_soc using VCD-derived rates.
# Sourced vars: ::mnist_global_activity, ::mnist_design_period_ns, ::mnist_act(*)
#
# Clock tree: OpenSTA forbids set_power_activity on clock ports. Activity for
# the clock network comes from create_clock + set_propagated_clock (density
# = 2/period for both edges). Matching liberty + SPEF + propagated clock are
# what make clkbuf / clock-pin power accurate.

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

# Design clock (not the TB tick). 50% duty waveform so clockDuty() is correct.
set period $::mnist_design_period_ns
set half   [expr {$period / 2.0}]
create_clock -name clk -period $period -waveform [list 0.0 $half] [get_ports clk]
# Propagated → OpenSTA walks the CTS network; clkbufs count in the Clock group
# instead of getting data-path median activity as plain combo cells.
set_propagated_clock [get_clocks clk]

# Sleep derating via core ICG case analysis (see power_icg_utils.tcl).
source [file join $::env(ROOT) power power_icg_utils.tcl]
set ::power_core_icg_gate [power_find_core_icg_gate]
set en_duty [power_core_enable_duty_from_avg]
puts "core_icg_gate=$::power_core_icg_gate core_clk_en_duty=$en_duty"

# Default activity for unmatched *data* pins (from VCD median).
# Clock pins / clock-network cells keep origin=clock (baked in by OpenSTA).
set_power_activity -global -activity $::mnist_global_activity -duty 0.5

# Top-level ports from TB (not the clock — OpenSTA rejects activity on clk).
if {[info exists ::mnist_act(reset)]} {
  set_power_activity -input_ports [get_ports reset] \
    -activity $::mnist_act(reset) -duty $::mnist_duty(reset)
}

# SRAM macro pin activities (RTL names match instance pins on blackbox).
foreach inst {u_imem u_dmem} {
  if {[llength [get_pins -quiet $inst/ce]]} {
    if {[info exists ::mnist_act(imem_ce)] && $inst eq "u_imem"} {
      set_power_activity -pins [get_pins $inst/ce] -activity $::mnist_act(imem_ce) -duty 0.5
    }
    if {[info exists ::mnist_act(dmem_ce)] && $inst eq "u_dmem"} {
      set_power_activity -pins [get_pins $inst/ce] -activity $::mnist_act(dmem_ce) -duty 0.5
    }
  }
  if {[llength [get_pins -quiet $inst/we]]} {
    if {[info exists ::mnist_act(imem_we)] && $inst eq "u_imem"} {
      set_power_activity -pins [get_pins $inst/we] -activity $::mnist_act(imem_we) -duty 0.5
    }
    if {[info exists ::mnist_act(dmem_we)] && $inst eq "u_dmem"} {
      set_power_activity -pins [get_pins $inst/we] -activity $::mnist_act(dmem_we) -duty 0.5
    }
  }
}

file mkdir $OUT

# Always-on root clk vs gated core_clk: OpenSTA cannot take fractional GATE
# activity for power. Report awake (GATE=1) and sleep (GATE=0); Python blends
# by VCD sram_clk_en duty → power_activity.rpt / energy summary.
power_apply_core_clk_enable 1.0
report_power -digits 6 > $OUT/power_awake.rpt
report_power -instances [get_cells -hierarchical *] -digits 4 > $OUT/power_by_instance_awake.rpt

power_apply_core_clk_enable 0.0
report_power -digits 6 > $OUT/power_sleep.rpt

# Keep primary report as awake (legacy consumers); summarize_energy blends.
file copy -force $OUT/power_awake.rpt $OUT/power_activity.rpt
file copy -force $OUT/power_by_instance_awake.rpt $OUT/power_by_instance.rpt

# CTS cells are often named _NNNN_ in the flat netlist; match by liberty ref_name.
# Report with core awake so clock-tree power is meaningful.
power_apply_core_clk_enable 1.0
set clk_tree_cells {}
foreach cell [get_cells -quiet -hierarchical *] {
  set ref [get_property $cell ref_name]
  if {[string match {*clkbuf*} $ref] \
      || [string match {*clkinv*} $ref] \
      || [string match {*clkdly*} $ref] \
      || [string match {*clkbt*} $ref]} {
    lappend clk_tree_cells $cell
  }
}
if {[llength $clk_tree_cells] > 0} {
  report_power -instances $clk_tree_cells -digits 6 > $OUT/power_clock_tree.rpt
  puts "clock_tree_named_cells=[llength $clk_tree_cells]"
} else {
  set fp [open $OUT/power_clock_tree.rpt w]
  puts $fp "No liberty cells matched *clkbuf*/clkinv/clkdly/clkbt*."
  puts $fp "Rely on the Clock group in power_activity.rpt (propagated clock network)."
  close $fp
  puts "clock_tree_named_cells=0"
}

# Optional annotation coverage (helps debug wrong/missing clock activity).
if {[catch {report_activity_annotation > $OUT/activity_annotation.rpt} err]} {
  puts "NOTE: report_activity_annotation skipped ($err)"
}

puts "WROTE $OUT/power_activity.rpt"
puts "WROTE $OUT/power_awake.rpt"
puts "WROTE $OUT/power_sleep.rpt"
puts "WROTE $OUT/power_clock_tree.rpt"
puts "global_activity=$::mnist_global_activity period_ns=$period"
puts "core_clk_en_duty=$en_duty"
puts "clock: propagated, waveform={0 $half}, period=$period ns"
puts "sleep: blended in summarize_energy.py as duty*P_awake+(1-duty)*P_sleep"
exit
