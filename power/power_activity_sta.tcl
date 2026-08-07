# Activity-based power for sky130_vex2_soc using MNIST MLP VCD-derived rates.
# Sourced vars: ::mnist_global_activity, ::mnist_design_period_ns, ::mnist_act(*)

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
set sdc     "$RUN/final/sdc/sky130_vex2_soc.sdc"

read_liberty $lib_sc
read_liberty $lib_sram
read_verilog $netlist
link_design sky130_vex2_soc
read_spef $spef

# Use design clock (hardened period), not the RTL sim 10 ns tick.
create_clock -name clk -period $::mnist_design_period_ns [get_ports clk]
set_propagated_clock [get_clocks clk]

# Default activity for unmatched pins (from RTL VCD median toggle density).
set_power_activity -global -activity $::mnist_global_activity -duty 0.5

# Top-level ports from TB.
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
report_power -digits 6 > $OUT/power_activity.rpt
report_power -instances [get_cells -hierarchical *] -digits 4 > $OUT/power_by_instance.rpt

puts "WROTE $OUT/power_activity.rpt"
puts "global_activity=$::mnist_global_activity period_ns=$::mnist_design_period_ns"
exit
