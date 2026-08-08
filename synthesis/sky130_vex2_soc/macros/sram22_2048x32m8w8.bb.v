// Blackbox header for OpenLane synthesis (not for functional sim).
// Behavioral model: third_party/sram22_sky130_macros/.../sram22_2048x32m8w8.v
`timescale 1ns/1ps

(* blackbox *)
module sram22_2048x32m8w8 (
`ifdef USE_POWER_PINS
  inout  wire        vdd,
  inout  wire        vss,
`endif
  input  wire        clk,
  input  wire        rstb,
  input  wire        ce,
  input  wire        we,
  input  wire [3:0]  wmask,
  input  wire [10:0] addr,
  input  wire [31:0] din,
  output wire [31:0] dout
);
endmodule
