// sky130_vex2_soc
// VexRiscv 4-stage internal pipeline + two SRAM22 2048x32 macros (IMEM + DMEM)
//
// Memory map:
//   0x0000_0000 .. 0x0000_1FFF  IMEM  8 KiB  (instruction fetch only)
//   0x1000_0000 .. 0x1000_1FFF  DMEM  8 KiB  (data)
//   0x2000_0000                 tohost (write nonzero => halt)
`timescale 1ns/1ps

module sky130_vex2_soc (
`ifdef USE_POWER_PINS
  inout  wire        VPWR,
  inout  wire        VGND,
`endif
  input  wire        clk,
  input  wire        reset,
  output wire        halted,
  output wire [31:0] tohost,
  output wire        sram_clk_en
);
  wire        iBus_cmd_valid;
  wire        iBus_cmd_ready;
  wire [31:0] iBus_cmd_payload_pc;
  wire        iBus_rsp_valid;
  wire        iBus_rsp_payload_error;
  wire [31:0] iBus_rsp_payload_inst;

  wire        dBus_cmd_valid;
  wire        dBus_cmd_ready;
  wire        dBus_cmd_payload_wr;
  wire [3:0]  dBus_cmd_payload_mask;
  wire [31:0] dBus_cmd_payload_address;
  wire [31:0] dBus_cmd_payload_data;
  wire [1:0]  dBus_cmd_payload_size;
  wire        dBus_rsp_ready;
  wire        dBus_rsp_error;
  wire [31:0] dBus_rsp_data;

  wire        halted_w;
  assign halted      = halted_w;
  assign sram_clk_en  = !halted_w && !reset;

  // For ASIC: clock SRAMs from main clk; halt stops new CE via bridges.
  // (AND-gating clocks is hostile to CTS; use ICG later if needed.)
  wire        sram_clk = clk;
  wire        sram_rstb = !reset;

  wire        imem_ce, imem_we;
  wire [3:0]  imem_wmask;
  wire [10:0] imem_addr;
  wire [31:0] imem_din, imem_dout;

  wire        dmem_ce, dmem_we;
  wire [3:0]  dmem_wmask;
  wire [10:0] dmem_addr;
  wire [31:0] dmem_din, dmem_dout;

  VexRiscv2 u_cpu (
    .clk                      (clk),
    .reset                    (reset),
    .timerInterrupt           (1'b0),
    .externalInterrupt        (1'b0),
    .softwareInterrupt        (1'b0),
    .iBus_cmd_valid           (iBus_cmd_valid),
    .iBus_cmd_ready           (iBus_cmd_ready),
    .iBus_cmd_payload_pc      (iBus_cmd_payload_pc),
    .iBus_rsp_valid           (iBus_rsp_valid),
    .iBus_rsp_payload_error   (iBus_rsp_payload_error),
    .iBus_rsp_payload_inst    (iBus_rsp_payload_inst),
    .dBus_cmd_valid           (dBus_cmd_valid),
    .dBus_cmd_ready           (dBus_cmd_ready),
    .dBus_cmd_payload_wr      (dBus_cmd_payload_wr),
    .dBus_cmd_payload_mask    (dBus_cmd_payload_mask),
    .dBus_cmd_payload_address (dBus_cmd_payload_address),
    .dBus_cmd_payload_data    (dBus_cmd_payload_data),
    .dBus_cmd_payload_size    (dBus_cmd_payload_size),
    .dBus_rsp_ready           (dBus_rsp_ready),
    .dBus_rsp_error           (dBus_rsp_error),
    .dBus_rsp_data            (dBus_rsp_data)
  );

  ibus_sram22_bridge u_ibus (
    .clk                   (clk),
    .reset                 (reset),
    .enable                (sram_clk_en),
    .iBus_cmd_valid        (iBus_cmd_valid),
    .iBus_cmd_ready        (iBus_cmd_ready),
    .iBus_cmd_payload_pc   (iBus_cmd_payload_pc),
    .iBus_rsp_valid        (iBus_rsp_valid),
    .iBus_rsp_payload_error(iBus_rsp_payload_error),
    .iBus_rsp_payload_inst (iBus_rsp_payload_inst),
    .sram_ce               (imem_ce),
    .sram_we               (imem_we),
    .sram_wmask            (imem_wmask),
    .sram_addr             (imem_addr),
    .sram_din              (imem_din),
    .sram_dout             (imem_dout)
  );

  dbus_sram22_bridge u_dbus (
    .clk                      (clk),
    .reset                    (reset),
    .enable                   (sram_clk_en),
    .dBus_cmd_valid           (dBus_cmd_valid),
    .dBus_cmd_ready           (dBus_cmd_ready),
    .dBus_cmd_payload_wr      (dBus_cmd_payload_wr),
    .dBus_cmd_payload_mask    (dBus_cmd_payload_mask),
    .dBus_cmd_payload_address (dBus_cmd_payload_address),
    .dBus_cmd_payload_data    (dBus_cmd_payload_data),
    .dBus_cmd_payload_size    (dBus_cmd_payload_size),
    .dBus_rsp_ready           (dBus_rsp_ready),
    .dBus_rsp_error           (dBus_rsp_error),
    .dBus_rsp_data            (dBus_rsp_data),
    .dmem_ce                  (dmem_ce),
    .dmem_we                  (dmem_we),
    .dmem_wmask               (dmem_wmask),
    .dmem_addr                (dmem_addr),
    .dmem_din                 (dmem_din),
    .dmem_dout                (dmem_dout),
    .halted                   (halted_w),
    .tohost                   (tohost)
  );

  sram22_2048x32m8w8 u_imem (
`ifdef USE_POWER_PINS
    .vdd   (VPWR),
    .vss   (VGND),
`endif
    .clk   (sram_clk),
    .rstb  (sram_rstb),
    .ce    (imem_ce),
    .we    (imem_we),
    .wmask (imem_wmask),
    .addr  (imem_addr),
    .din   (imem_din),
    .dout  (imem_dout)
  );

  sram22_2048x32m8w8 u_dmem (
`ifdef USE_POWER_PINS
    .vdd   (VPWR),
    .vss   (VGND),
`endif
    .clk   (sram_clk),
    .rstb  (sram_rstb),
    .ce    (dmem_ce),
    .we    (dmem_we),
    .wmask (dmem_wmask),
    .addr  (dmem_addr),
    .din   (dmem_din),
    .dout  (dmem_dout)
  );
endmodule
