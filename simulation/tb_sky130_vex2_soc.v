`timescale 1ns/1ps

// Smoke test: tiny program writes tohost and halts.
module tb_sky130_vex2_soc;
  reg clk = 0;
  reg reset = 1;
  wire halted;
  wire [31:0] tohost;
  wire sram_clk_en;

  always #5 clk = ~clk; // 100 MHz sim clock

  sky130_vex2_soc u_soc (
    .clk        (clk),
    .reset      (reset),
    .halted     (halted),
    .tohost     (tohost),
    .sram_clk_en(sram_clk_en)
  );

  // Machine code in IMEM (little-endian words):
  //   addi a0, x0, 1          -> 0x00100513
  //   lui  a1, 0x20000        -> 0x200005b7   (a1 = 0x20000000)
  //   sw   a0, 0(a1)          -> 0x00a5a023
  // DUMP_PATH is set by scripts/sim_smoke.sh (-DDUMP_PATH=...).
  // Default keeps waveforms under waves/ for one-click open in Cursor
  // (Surfer / VaporView extensions — open the .vcd file).
`ifndef DUMP_PATH
  `define DUMP_PATH "sky130_vex2_soc.vcd"
`endif

  initial begin
    $dumpfile(`DUMP_PATH);
    $dumpvars(0, tb_sky130_vex2_soc);
    $display("WAVEFORM: dumping to %s", `DUMP_PATH);

    // Backdoor load into SRAM behavioral model
    u_soc.u_imem.mem[0] = 32'h00100513;
    u_soc.u_imem.mem[1] = 32'h200005b7;
    u_soc.u_imem.mem[2] = 32'h00a5a023;
    // NOP pad
    u_soc.u_imem.mem[3] = 32'h00000013;

    repeat (5) @(posedge clk);
    reset = 0;

    // Wait for halt or timeout
    begin : wait_halt
      integer i;
      for (i = 0; i < 2000; i = i + 1) begin
        @(posedge clk);
        if (halted) disable wait_halt;
      end
    end

    if (halted && tohost == 32'd1 && sram_clk_en == 1'b0) begin
      $display("PASS: halted=%0d tohost=%0d sram_clk_en=%0d", halted, tohost, sram_clk_en);
      $finish;
    end else begin
      $display("FAIL: halted=%0d tohost=%0h sram_clk_en=%0d", halted, tohost, sram_clk_en);
      $fatal(1);
    end
  end
endmodule
