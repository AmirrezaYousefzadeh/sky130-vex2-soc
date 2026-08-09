# Shared helpers: model sleep by case-analyzing the core ICG GATE.
#
# OpenSTA ignores set_power_activity on integrated clock-gate GATE pins for
# power (clock origin wins). set_case_analysis 0/1 on the core dlclkp GATE
# does propagate and derates the core_clk tree + sequential clock-pin power.
#
# Enable duty comes from VCD (sram_clk_en == core_clk_en in RTL).

proc power_find_core_icg_gate {} {
  foreach c [get_cells -quiet -hierarchical *] {
    set ref [get_property $c ref_name]
    if {![string match {*dlclkp*} $ref]} {
      continue
    }
    set gclk_pin ""
    set gate_pin ""
    foreach p [get_pins -of_objects $c] {
      set pn [get_property $p name]
      if {$pn eq "GCLK"} { set gclk_pin $p }
      if {$pn eq "GATE"} { set gate_pin $p }
    }
    if {$gclk_pin eq "" || $gate_pin eq ""} {
      continue
    }
    set net [get_nets -quiet -of_objects $gclk_pin]
    if {[llength $net] == 0} {
      continue
    }
    set nname [get_property $net name]
    if {$nname eq "core_clk"} {
      return $gate_pin
    }
  }
  return ""
}

# Apply enable: duty in [0,1] from VCD. Threshold keeps partial wake/sleep
# windows on the dominant side (almost all windows are ~0 or ~1).
proc power_apply_core_clk_enable {duty {threshold 0.5}} {
  if {![info exists ::power_core_icg_gate] || $::power_core_icg_gate eq ""} {
    set ::power_core_icg_gate [power_find_core_icg_gate]
  }
  set gate $::power_core_icg_gate
  if {$gate eq ""} {
    puts "WARNING: core ICG GATE not found; sleep derating disabled"
    return 0
  }
  if {$duty < $threshold} {
    set_case_analysis 0 $gate
    return 0
  }
  set_case_analysis 1 $gate
  return 1
}

proc power_core_enable_duty_from_avg {} {
  # Prefer sram_clk_en (SoC port); fall back to core_clk_en alias if present.
  foreach key {sram_clk_en core_clk_en} {
    if {[info exists ::mnist_duty($key)]} {
      return $::mnist_duty($key)
    }
  }
  return 1.0
}

proc power_core_enable_duty_from_window {i} {
  foreach key {sram_clk_en core_clk_en} {
    if {[info exists ::tp_duty($i,$key)]} {
      return $::tp_duty($i,$key)
    }
  }
  return 1.0
}
