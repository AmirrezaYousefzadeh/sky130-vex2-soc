# Per-pin activity power of sky130_vex2_soc from accumulated toggle counts (power/tools/vcd_toggles + toggles_to_activity.py).
# Every annotated pin/net gets its measured transition rate and duty; unannotated inputs get zero; the clock propagation stops
# at the outputs of the clock-gate cells so that gated subtrees are counted from the waveform, not from the clock definition.
# Env: RUN_DIR TOP LIB_SC LIB_SRAM PERIOD_NS OUT MACRO_INST ACT_TCL
set RUN $::env(RUN_DIR); set TOP $::env(TOP); set OUT $::env(OUT)
foreach l $::env(LIB_SC) { read_liberty $l }
if {[info exists ::env(LIB_SRAM)] && [file exists $::env(LIB_SRAM)]} { read_liberty $::env(LIB_SRAM) }
read_verilog "$RUN/final/nl/$TOP.nl.v"
link_design $TOP
read_spef "$RUN/final/spef/nom/$TOP.nom.spef"
set period $::env(PERIOD_NS); set half [expr {$period / 2.0}]
create_clock -name clk -period $period -waveform [list 0.0 $half] [get_ports clk]
set_propagated_clock [all_clocks]
# OpenSTA takes the activity of clock-network pins from the clock definition; stop the propagation at every clock-gate output
set __icg {}
foreach c [get_cells -hierarchical *] { set r [get_property $c ref_name]
  if {[string match {*dlclkp*} $r]} { foreach p [get_pins -of_objects $c] { if {[get_property $p direction] eq "output"} { lappend __icg $p } } } }
if {[llength $__icg]} { set_clock_sense -stop_propagation $__icg; puts "CLK_STOP_ICG: [llength $__icg] clock-gate outputs" }
file mkdir $OUT
set_power_activity -input -activity 0.0 -duty 0.0      ;# unannotated inputs: zero, never the tool default
puts "sourcing activities $::env(ACT_TCL)"
source $::env(ACT_TCL)
report_power -digits 6 > $OUT/power_pin.rpt
report_power -instances [get_cells -hierarchical *] -digits 4 > $OUT/power_pin_by_instance.rpt
foreach inst [split $::env(MACRO_INST) " "] {
  if {[llength [get_cells -quiet $inst]]} { report_power -instances [get_cells $inst] -digits 6 > $OUT/power_pin_$inst.rpt }
}
set ct {}
foreach cell [get_cells -quiet -hierarchical *] { set ref [get_property $cell ref_name]
  if {[string match {*clkbuf*} $ref] || [string match {*clkinv*} $ref] || [string match {*clkdly*} $ref] || [string match {*dlclkp*} $ref]} { lappend ct $cell } }
if {[llength $ct]} { report_power -instances $ct -digits 6 > $OUT/power_pin_clock_tree.rpt }
if {[catch {report_activity_annotation > $OUT/activity_annotation.rpt} err]} { puts "NOTE: $err" }
puts "WROTE $OUT/power_pin.rpt"
exit
