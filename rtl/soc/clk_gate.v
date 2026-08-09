// Integrated clock gate.
// ASIC / OpenLane: sky130_fd_sc_ms__dlclkp (proper liberty clock-gate arcs).
// RTL sim: behavioral stub in simulation/sky130_dlclkp_stub.v
`timescale 1ns/1ps

module clk_gate (
  input  wire clk,
  input  wire en,
  output wire gclk
);
  // Drive-2 is enough for mem ICGs; core_clk is buffered by CTS after GCLK.
  sky130_fd_sc_ms__dlclkp_2 u_icg (
    .CLK  (clk),
    .GATE (en),
    .GCLK (gclk)
  );
endmodule
