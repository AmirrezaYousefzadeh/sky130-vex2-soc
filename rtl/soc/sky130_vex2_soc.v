// sky130_vex2_soc
// VexRiscv 4-stage + two SRAM22 2048x32 macros (IMEM + DMEM)
//
// Memory map:
//   0x0000_0000 .. 0x0000_1FFF  IMEM  8 KiB
//   0x1000_0000 .. 0x1000_1FFF  DMEM  8 KiB
//   0x2000_0000                 tohost (write nonzero => halt)
//   0x2000_0004                 gpio   (bit0 = done)
//   0x2000_0008                 sleep  (write 1 => clock-gate sleep)
//   0x2000_000C                 status (bit0 = sleeping)
//
// Power-on: sleeping=1 (core_clk gated after reset). TB asserts `wake` to run.
`timescale 1ns/1ps

module sky130_vex2_soc (
`ifdef USE_POWER_PINS
  inout  wire        VPWR,
  inout  wire        VGND,
`endif
  input  wire        clk,
  input  wire        reset,
  input  wire        wake,
  output wire        halted,
  output wire [31:0] tohost,
  output wire        gpio_done,
  output wire        sleeping,
  output wire        sram_clk_en
);
  wire        core_clk;
  wire        core_clk_en;
  wire        sleep_req;
  wire        ext_irq;
  wire        halted_w;
  wire        sleeping_w;
  wire        gpio_done_w;

  assign halted      = halted_w;
  assign sleeping    = sleeping_w;
  assign gpio_done   = gpio_done_w;
  assign sram_clk_en = core_clk_en;

  sleep_ctrl u_sleep (
    .clk        (clk),
    .reset      (reset),
    .sleep_req  (sleep_req),
    .wake       (wake),
    .halted     (halted_w),
    .sleeping   (sleeping_w),
    .core_clk_en(core_clk_en),
    .core_clk   (core_clk),
    .ext_irq    (ext_irq)
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

  wire        sram_rstb = !reset;

  wire        imem_ce, imem_we;
  wire [3:0]  imem_wmask;
  wire [10:0] imem_addr;
  wire [31:0] imem_din, imem_dout;
  wire        imem_clk;

  wire        dmem_ce, dmem_we;
  wire [3:0]  dmem_wmask;
  wire [10:0] dmem_addr;
  wire [31:0] dmem_din, dmem_dout;
  wire        dmem_clk;

  // Per-macro ICG: stop SRAM clocks when chip-enable is idle (and when
  // core_clk is already gated in sleep). Same latch style as sleep_ctrl.
  clk_gate u_imem_icg (
    .clk  (core_clk),
    .en   (imem_ce),
    .gclk (imem_clk)
  );
  clk_gate u_dmem_icg (
    .clk  (core_clk),
    .en   (dmem_ce),
    .gclk (dmem_clk)
  );

  VexRiscv2 u_cpu (
    .clk                      (core_clk),
    .reset                    (reset),
    .timerInterrupt           (1'b0),
    .externalInterrupt        (ext_irq),
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
    .clk                   (core_clk),
    .reset                 (reset),
    .enable                (core_clk_en),
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
    .clk                      (core_clk),
    .reset                    (reset),
    .enable                   (core_clk_en),
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
    .tohost                   (tohost),
    .sleeping                 (sleeping_w),
    .gpio_done                (gpio_done_w),
    .sleep_req                (sleep_req)
  );

  sram22_2048x32m8w8 u_imem (
`ifdef USE_POWER_PINS
    .vdd   (VPWR),
    .vss   (VGND),
`endif
    .clk   (imem_clk),
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
    .clk   (dmem_clk),
    .rstb  (sram_rstb),
    .ce    (dmem_ce),
    .we    (dmem_we),
    .wmask (dmem_wmask),
    .addr  (dmem_addr),
    .din   (dmem_din),
    .dout  (dmem_dout)
  );
endmodule
