`timescale 1ns/1ps

// Smoke test: tiny program writes tohost and halts.
// SoC powers on asleep — TB pulses wake so the program can run.
module tb_sky130_vex2_soc;
  reg clk = 0;
  reg reset = 1;
  reg wake = 0;
  wire halted;
  wire [31:0] tohost;
  wire gpio_done;
  wire sleeping;
  wire sram_clk_en;

  localparam real CLK_PERIOD_NS = 20.0;
  localparam integer RESET_CYCLES = 64;
  localparam integer TIMEOUT_CYCLES = 10000;
  always #(CLK_PERIOD_NS / 2.0) clk = ~clk;

`ifdef GLS_PROGRESS
  `ifndef PROGRESS_EVERY
    `define PROGRESS_EVERY 500
  `endif
  integer gls_cyc;
  initial gls_cyc = 0;
  always @(posedge clk) begin
    gls_cyc = gls_cyc + 1;
    if ((gls_cyc % `PROGRESS_EVERY) == 0)
      $display("GLS_PROGRESS cycle=%0d max=%0d", gls_cyc, TIMEOUT_CYCLES);
  end
`endif

  sky130_vex2_soc u_soc (
    .clk        (clk),
    .reset      (reset),
    .wake       (wake),
    .halted     (halted),
    .tohost     (tohost),
    .gpio_done  (gpio_done),
    .sleeping   (sleeping),
    .sram_clk_en(sram_clk_en)
  );

`ifdef GLS_RF_INIT
  `include "gls_regfile_init.vh"
`endif

`ifndef DUMP_PATH
  `define DUMP_PATH "waveform.vcd"
`endif

  `ifndef DUMP_LEVEL
    `define DUMP_LEVEL 0
  `endif
  `ifndef DUMP_MODULE
    `define DUMP_MODULE tb_sky130_vex2_soc
  `endif

  initial begin
`ifdef SDF_ANNOTATE
    $sdf_annotate(`SDF_ANNOTATE, u_soc);
    $display("SDF: annotated %s onto u_soc", `SDF_ANNOTATE);
`endif

    $dumpfile(`DUMP_PATH);
    $dumpvars(`DUMP_LEVEL, `DUMP_MODULE);
    $display("WAVEFORM: dumping to %s (level=%0d)", `DUMP_PATH, `DUMP_LEVEL);
    $display("CLK: period=%0g ns  reset_cycles=%0d", CLK_PERIOD_NS, RESET_CYCLES);

    u_soc.u_imem.mem[0] = 32'h00100513;
    u_soc.u_imem.mem[1] = 32'h200005b7;
    u_soc.u_imem.mem[2] = 32'h00a5a023;
    u_soc.u_imem.mem[3] = 32'h00000013;

    reset = 1'b1;
    wake  = 1'b0;
    repeat (RESET_CYCLES) @(posedge clk);
    @(negedge clk);
    reset = 1'b0;
    $display("TB: reset released at t=%0t (sleeping=%0d)", $time, sleeping);

    // Power-on sleep: pulse wake so the smoke program can fetch.
    repeat (4) @(posedge clk);
    wake = 1'b1;
    repeat (8) @(posedge clk);
    wake = 1'b0;
    $display("TB: wake pulsed");

    begin : wait_halt
      integer i;
      for (i = 0; i < TIMEOUT_CYCLES; i = i + 1) begin
        @(posedge clk);
        if (halted === 1'b1) disable wait_halt;
      end
    end

    if (halted === 1'b1 && tohost === 32'd1 && sram_clk_en === 1'b0) begin
      $display("PASS: halted=%0d tohost=%0d sram_clk_en=%0d", halted, tohost, sram_clk_en);
      $finish;
    end else begin
      $display("FAIL: halted=%b tohost=%h sram_clk_en=%b sleeping=%b",
               halted, tohost, sram_clk_en, sleeping);
      $fatal(1);
    end
  end
endmodule
