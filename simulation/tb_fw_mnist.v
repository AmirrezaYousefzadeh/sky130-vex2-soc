`timescale 1ns/1ps

// Load firmware hex into IMEM/DMEM and run until tohost halt.
// PASS: halted && tohost in 1..10  (predicted digit = tohost-1)
module tb_fw_mnist;
  reg clk = 0;
  reg reset = 1;
  wire halted;
  wire [31:0] tohost;
  wire sram_clk_en;

  always #5 clk = ~clk;

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
  // DUMP_LEVEL / DUMP_MODULE let GLS dump SoC nets only (level 1) without
  // descending into every stdcell / SRAM mem[] (keeps VCD size usable).
  `ifndef DUMP_LEVEL
    `define DUMP_LEVEL 0
  `endif
  `ifndef DUMP_MODULE
    `define DUMP_MODULE tb_fw_mnist
  `endif
  initial begin
    $dumpfile(`DUMP_PATH);
    $dumpvars(`DUMP_LEVEL, `DUMP_MODULE);
    $display("WAVEFORM: dumping to %s (level=%0d)", `DUMP_PATH, `DUMP_LEVEL);
  end
`endif

  integer i;
  initial begin
    $readmemh(`IMEM_HEX, u_soc.u_imem.mem);
    $readmemh(`DMEM_HEX, u_soc.u_dmem.mem);
    $display("FW: loaded %s and %s", `IMEM_HEX, `DMEM_HEX);

    repeat (5) @(posedge clk);
    reset = 0;

    begin : wait_halt
      for (i = 0; i < `TIMEOUT_CYCLES; i = i + 1) begin
        @(posedge clk);
        if (halted) disable wait_halt;
      end
    end

    if (!halted) begin
      $display("FAIL: timeout after %0d cycles (tohost=%0h)", `TIMEOUT_CYCLES, tohost);
      $fatal(1);
    end

    // PASS codes: 1..10 mean predicted digit 0..9 matched expected label
    if (tohost >= 32'd1 && tohost <= 32'd10 && sram_clk_en == 1'b0) begin
      $display("PASS: digit=%0d  tohost=%0d  cycles~%0d  sram_clk_en=%0d",
               tohost - 1, tohost, i, sram_clk_en);
      $finish;
    end else begin
      $display("FAIL: halted=%0d tohost=%0h sram_clk_en=%0d cycles~%0d",
               halted, tohost, sram_clk_en, i);
      $fatal(1);
    end
  end
endmodule
