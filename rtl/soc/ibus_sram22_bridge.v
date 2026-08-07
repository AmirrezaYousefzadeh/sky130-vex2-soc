// Bridge VexRiscv IBusSimple <-> SRAM22 synchronous 1RW macro (1-cycle read latency).
`timescale 1ns/1ps

module ibus_sram22_bridge (
  input  wire        clk,
  input  wire        reset,
  input  wire        enable,          // 0 => reject new fetches (halt / clock-gate path)

  // VexRiscv iBus
  input  wire        iBus_cmd_valid,
  output wire        iBus_cmd_ready,
  input  wire [31:0] iBus_cmd_payload_pc,
  output reg         iBus_rsp_valid,
  output wire        iBus_rsp_payload_error,
  output wire [31:0] iBus_rsp_payload_inst,

  // SRAM22 port
  output wire        sram_ce,
  output wire        sram_we,
  output wire [3:0]  sram_wmask,
  output wire [10:0] sram_addr,
  output wire [31:0] sram_din,
  input  wire [31:0] sram_dout
);
  reg pending;

  assign iBus_cmd_ready = enable && !pending && !reset;
  assign sram_ce        = iBus_cmd_valid && iBus_cmd_ready;
  assign sram_we        = 1'b0;
  assign sram_wmask     = 4'b0000;
  assign sram_addr      = iBus_cmd_payload_pc[12:2];
  assign sram_din       = 32'b0;

  assign iBus_rsp_payload_error = 1'b0;
  assign iBus_rsp_payload_inst  = sram_dout;

  always @(posedge clk) begin
    if (reset) begin
      pending        <= 1'b0;
      iBus_rsp_valid <= 1'b0;
    end else begin
      // Accept -> one-cycle SRAM latency -> response
      iBus_rsp_valid <= sram_ce;
      if (sram_ce)
        pending <= 1'b1;
      else if (iBus_rsp_valid)
        pending <= 1'b0;
    end
  end
endmodule
