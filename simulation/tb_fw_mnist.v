`timescale 1ns/1ps

// Single-inference MNIST with clock-gated sleep / TB wake.
// Schedule: init -> sleep 10k -> infer -> sleep 10k -> halt
// PASS: tohost = predicted_digit + 1 (1..10)
module tb_fw_mnist;
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
  localparam integer WAKE_PULSE_CYCLES = 8;
  localparam integer SLEEP_CYCLES = 10000; // free-running clk while core gated
  always #(CLK_PERIOD_NS / 2.0) clk = ~clk;

`ifdef GLS_PROGRESS
  `ifndef PROGRESS_EVERY
    `define PROGRESS_EVERY 2000
  `endif
  integer gls_cyc;
  initial gls_cyc = 0;
  always @(posedge clk) begin
    gls_cyc = gls_cyc + 1;
    if ((gls_cyc % `PROGRESS_EVERY) == 0)
      $display("GLS_PROGRESS cycle=%0d max=%0d", gls_cyc, `TIMEOUT_CYCLES);
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

`ifndef IMEM_HEX
  `define IMEM_HEX "imem.hex"
`endif
`ifndef DMEM_HEX
  `define DMEM_HEX "dmem.hex"
`endif
`ifndef TIMEOUT_CYCLES
  `define TIMEOUT_CYCLES 5000000
`endif

`ifdef DUMP_PATH
  `ifndef DUMP_LEVEL
    `define DUMP_LEVEL 0
  `endif
  `ifndef DUMP_MODULE
    `define DUMP_MODULE tb_fw_mnist
  `endif
`endif

  task automatic pulse_wake;
    integer k;
    begin
      wake = 1'b1;
      for (k = 0; k < WAKE_PULSE_CYCLES; k = k + 1)
        @(posedge clk);
      wake = 1'b0;
    end
  endtask

  task automatic wait_sleeping;
    integer guard;
    begin
      for (guard = 0; guard < `TIMEOUT_CYCLES; guard = guard + 1) begin
        @(posedge clk);
        if (sleeping === 1'b1)
          disable wait_sleeping;
      end
      $display("FAIL: timeout waiting for sleeping");
      $fatal(1);
    end
  endtask

  task automatic wait_done;
    integer guard;
    begin
      for (guard = 0; guard < `TIMEOUT_CYCLES; guard = guard + 1) begin
        @(posedge clk);
        if (gpio_done === 1'b1)
          disable wait_done;
      end
      $display("FAIL: timeout waiting for gpio_done");
      $fatal(1);
    end
  endtask

  task automatic hold_sleep;
    integer gap;
    begin
      for (gap = 0; gap < SLEEP_CYCLES; gap = gap + 1)
        @(posedge clk);
    end
  endtask

  integer i;
  initial begin
`ifdef SDF_ANNOTATE
    $sdf_annotate(`SDF_ANNOTATE, u_soc);
    $display("SDF: annotated %s onto u_soc", `SDF_ANNOTATE);
`endif

`ifdef DUMP_PATH
    $dumpfile(`DUMP_PATH);
    $dumpvars(`DUMP_LEVEL, `DUMP_MODULE);
    $display("WAVEFORM: dumping to %s (level=%0d)", `DUMP_PATH, `DUMP_LEVEL);
`endif
    $display("CLK: period=%0g ns  reset_cycles=%0d  sleep_cycles=%0d",
             CLK_PERIOD_NS, RESET_CYCLES, SLEEP_CYCLES);

    $readmemh(`IMEM_HEX, u_soc.u_imem.mem);
    $readmemh(`DMEM_HEX, u_soc.u_dmem.mem);
    $display("FW: loaded %s and %s", `IMEM_HEX, `DMEM_HEX);

    reset = 1'b1;
    wake  = 1'b0;
    repeat (RESET_CYCLES) @(posedge clk);
    @(negedge clk);
    reset = 1'b0;
    $display("TB: reset released at t=%0t", $time);

    // Power-on sleep -> wake so crt0/main can initialize, then FW sleeps again.
    wait_sleeping;
    $display("TB: power-on sleep — wake for init");
    pulse_wake;

    wait_sleeping;
    $display("TB: post-init sleep — hold %0d cycles", SLEEP_CYCLES);
    hold_sleep;
    $display("TB: wake for inference");
    pulse_wake;

    wait_done;
    $display("TB: inference done (gpio_done) at t=%0t", $time);

    wait_sleeping;
    $display("TB: post-infer sleep — hold %0d cycles", SLEEP_CYCLES);
    hold_sleep;
    $display("TB: wake for halt");
    pulse_wake;

    begin : wait_halt
      for (i = 0; i < `TIMEOUT_CYCLES; i = i + 1) begin
        @(posedge clk);
        if (halted === 1'b1) disable wait_halt;
      end
    end

    if (halted !== 1'b1) begin
      $display("FAIL: timeout after %0d cycles (tohost=%0h)", `TIMEOUT_CYCLES, tohost);
      $fatal(1);
    end

    if (tohost >= 32'd1 && tohost <= 32'd10 && sram_clk_en === 1'b0) begin
      $display("PASS: digit=%0d  tohost=%0d  cycles~%0d  sram_clk_en=%0d",
               tohost - 1, tohost, i, sram_clk_en);
      $finish;
    end else begin
      $display("FAIL: halted=%b tohost=%h sram_clk_en=%b sleeping=%b",
               halted, tohost, sram_clk_en, sleeping);
      $fatal(1);
    end
  end
endmodule
