`timescale 1ns/1ps

// Load firmware hex into IMEM/DMEM and run until tohost halt.
// PASS: halted && tohost in 1..10  (predicted digit = tohost-1)
module tb_fw_mnist;
  reg clk = 0;
  reg reset = 1;
  wire halted;
  wire [31:0] tohost;
  wire sram_clk_en;

  // SDF GLS: use >= hardened CLOCK_PERIOD
  localparam real CLK_PERIOD_NS = 20.0;
  localparam integer RESET_CYCLES = 64;
  always #(CLK_PERIOD_NS / 2.0) clk = ~clk;

  sky130_vex2_soc u_soc (
    .clk        (clk),
    .reset      (reset),
    .halted     (halted),
    .tohost     (tohost),
    .sram_clk_en(sram_clk_en)
  );

  // Gate-level: zero synthesized regfile (RTL used $readmemb zeros).
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
    $display("CLK: period=%0g ns  reset_cycles=%0d", CLK_PERIOD_NS, RESET_CYCLES);

    $readmemh(`IMEM_HEX, u_soc.u_imem.mem);
    $readmemh(`DMEM_HEX, u_soc.u_dmem.mem);
    $display("FW: loaded %s and %s", `IMEM_HEX, `DMEM_HEX);

    reset = 1'b1;
    repeat (RESET_CYCLES) @(posedge clk);
    @(negedge clk);
    reset = 1'b0;
    $display("TB: reset released at t=%0t", $time);

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

    // PASS codes: 1..10 mean predicted digit 0..9 matched expected label
    if (tohost >= 32'd1 && tohost <= 32'd10 && sram_clk_en === 1'b0) begin
      $display("PASS: digit=%0d  tohost=%0d  cycles~%0d  sram_clk_en=%0d",
               tohost - 1, tohost, i, sram_clk_en);
      $finish;
    end else begin
      $display("FAIL: halted=%b tohost=%h sram_clk_en=%b cycles~%0d",
               halted, tohost, sram_clk_en, i);
      $fatal(1);
    end
  end
endmodule
