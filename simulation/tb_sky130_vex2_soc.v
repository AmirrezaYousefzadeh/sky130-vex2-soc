`timescale 1ns/1ps

// Smoke test: tiny program writes tohost and halts.
module tb_sky130_vex2_soc;
  reg clk = 0;
  reg reset = 1;
  wire halted;
  wire [31:0] tohost;
  wire sram_clk_en;

  // SDF GLS: use >= hardened CLOCK_PERIOD
  localparam real CLK_PERIOD_NS = 20.0;
  // Most CPU flops are dfxtp (no async reset); sync reset needs many cycles
  // to flush X through delayed combo before release — especially with SDF.
  localparam integer RESET_CYCLES = 64;
  localparam integer TIMEOUT_CYCLES = 10000;
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

  // Machine code in IMEM (little-endian words):
  //   addi a0, x0, 1          -> 0x00100513
  //   lui  a1, 0x20000        -> 0x200005b7   (a1 = 0x20000000)
  //   sw   a0, 0(a1)          -> 0x00a5a023
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
    // Must finish before time advances / reset is released.
    $sdf_annotate(`SDF_ANNOTATE, u_soc);
    $display("SDF: annotated %s onto u_soc", `SDF_ANNOTATE);
`endif

    $dumpfile(`DUMP_PATH);
    $dumpvars(`DUMP_LEVEL, `DUMP_MODULE);
    $display("WAVEFORM: dumping to %s (level=%0d)", `DUMP_PATH, `DUMP_LEVEL);
    $display("CLK: period=%0g ns  reset_cycles=%0d", CLK_PERIOD_NS, RESET_CYCLES);

    // Backdoor load into SRAM behavioral model
    u_soc.u_imem.mem[0] = 32'h00100513;
    u_soc.u_imem.mem[1] = 32'h200005b7;
    u_soc.u_imem.mem[2] = 32'h00a5a023;
    u_soc.u_imem.mem[3] = 32'h00000013;

    // Hold reset while clocking so sync-reset logic can clear dfxtp X state.
    reset = 1'b1;
    repeat (RESET_CYCLES) @(posedge clk);
    // Deassert away from the rising edge (SDF clock skew / recovery).
    @(negedge clk);
    reset = 1'b0;
    $display("TB: reset released at t=%0t", $time);

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
      $display("FAIL: halted=%b tohost=%h sram_clk_en=%b", halted, tohost, sram_clk_en);
      $fatal(1);
    end
  end
endmodule
