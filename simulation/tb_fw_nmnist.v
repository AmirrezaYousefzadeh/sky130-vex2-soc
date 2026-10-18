`timescale 1ns/1ps

// Event-driven N-MNIST firmware testbench with clock-gated sleep / TB wake per event.
// The TB replays the test sample's event times (events.hex, clock cycles after the start of the stream):
//   reset -> wake (init) -> firmware sleeps -> for each event i: wait until its time, wait for the core to be
//   asleep, pulse wake -> firmware processes the event and sleeps again -> after the last event: wake -> halt.
// Reports: decision time (gpio_done edge) and event index, awake cycles per event, late deliveries (an event that
// falls due while the previous one is still being processed is delivered when the core sleeps again).
// PASS: tohost = decided digit + 1 (1..10); the firmware also checks its outputs against the Python reference.
module tb_fw_nmnist;
  reg clk = 0;
  reg reset = 1;
  reg wake = 0;
  wire halted;
  wire [31:0] tohost;
  wire gpio_done;
  wire sleeping;
  wire sram_clk_en;

`ifndef CLK_PERIOD_NS
  `define CLK_PERIOD_NS 20.0
`endif
  localparam real CLK_PERIOD_NS = `CLK_PERIOD_NS;   // overridable (-DCLK_PERIOD_NS=200 for the 5 MHz hardening)
  localparam integer RESET_CYCLES = 64;
  localparam integer WAKE_PULSE_CYCLES = 8;
  localparam integer TAIL_SLEEP_CYCLES = 2000;      // free-running clk after the last event before the halt wake
  always #(CLK_PERIOD_NS / 2.0) clk = ~clk;

`include "events.vh"                                // localparam integer N_EV (written by train_export.py)
`ifndef EVENTS_HEX
  `define EVENTS_HEX "events.hex"
`endif
`ifndef IMEM_HEX
  `define IMEM_HEX "imem.hex"
`endif
`ifndef DMEM_HEX
  `define DMEM_HEX "dmem.hex"
`endif
`ifndef TIMEOUT_CYCLES
  `define TIMEOUT_CYCLES 20000000
`endif
`ifndef DUMP_FROM_EV
  `define DUMP_FROM_EV 0                             // VCD only between these event indices (inclusive)
`endif
`ifndef DUMP_TO_EV
  `define DUMP_TO_EV (N_EV - 1)
`endif

`ifdef GLS_PROGRESS
  `ifndef PROGRESS_EVERY
    `define PROGRESS_EVERY 20000
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

`ifdef DUMP_PATH
  `ifndef DUMP_LEVEL
    `define DUMP_LEVEL 0
  `endif
  `ifndef DUMP_MODULE
    `define DUMP_MODULE tb_fw_nmnist
  `endif
`endif

  reg [31:0] ev_cyc [0:N_EV-1];
  integer cyc;                      // free-running cycle counter
  initial cyc = 0;
  always @(posedge clk) cyc <= cyc + 1;

  // decision: first rising edge of gpio_done
  integer dec_cyc, dec_ev, ev_index;
  reg decided;
  initial begin dec_cyc = -1; dec_ev = -1; ev_index = -1; decided = 1'b0; end
  always @(posedge clk) begin
    if (gpio_done === 1'b1 && !decided && ev_index >= 0) begin
      decided <= 1'b1; dec_cyc <= cyc; dec_ev <= ev_index;
    end
  end

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

  integer i, t0, due, deliver, awake, awake_sum, awake_max, late, late_n, late_max, t_last;
  initial begin
`ifdef SDF_ANNOTATE
    $sdf_annotate(`SDF_ANNOTATE, u_soc);
    $display("SDF: annotated %s onto u_soc", `SDF_ANNOTATE);
`endif
`ifdef DUMP_PATH
    $dumpfile(`DUMP_PATH);
    $dumpvars(`DUMP_LEVEL, `DUMP_MODULE);
    $display("WAVEFORM: dumping to %s (level=%0d, events %0d..%0d)", `DUMP_PATH, `DUMP_LEVEL, `DUMP_FROM_EV, `DUMP_TO_EV);
    if (`DUMP_FROM_EV > 0) $dumpoff;
`endif
    $display("CLK: period=%0g ns  reset_cycles=%0d  events=%0d", CLK_PERIOD_NS, RESET_CYCLES, N_EV);
    $readmemh(`IMEM_HEX, u_soc.u_imem.mem);
    $readmemh(`DMEM_HEX, u_soc.u_dmem.mem);
    $readmemh(`EVENTS_HEX, ev_cyc);
    $display("FW: loaded %s, %s and %s", `IMEM_HEX, `DMEM_HEX, `EVENTS_HEX);

    reset = 1'b1;
    wake  = 1'b0;
    repeat (RESET_CYCLES) @(posedge clk);
    @(negedge clk);
    reset = 1'b0;
    $display("TB: reset released at t=%0t", $time);

    wait_sleeping;                      // power-on sleep -> wake so crt0/main initialise
    $display("TB: power-on sleep - wake for init");
    pulse_wake;
    wait_sleeping;                      // firmware is ready: the event stream starts now
    t0 = cyc;
    $display("TB: stream starts at cycle %0d (t=%0t)", t0, $time);

    awake_sum = 0; awake_max = 0; late_n = 0; late_max = 0;
    for (i = 0; i < N_EV; i = i + 1) begin
      due = t0 + ev_cyc[i];
      while (cyc < due) @(posedge clk);
      wait_sleeping;                    // the previous event may still be in flight
      late = cyc - due;
      if (late > 1) begin late_n = late_n + 1; if (late > late_max) late_max = late; end
`ifdef DUMP_PATH
      if (i == `DUMP_FROM_EV && `DUMP_FROM_EV > 0) $dumpon;
`endif
      deliver = cyc; ev_index = i;
      pulse_wake;
      wait_sleeping;                    // the core processed the event and went back to sleep
      awake = cyc - deliver;
      awake_sum = awake_sum + awake;
      if (awake > awake_max) awake_max = awake;
`ifdef DUMP_PATH
      if (i == `DUMP_TO_EV && `DUMP_TO_EV < N_EV - 1) $dumpoff;
`endif
    end
    t_last = cyc;
    $display("TB: %0d events delivered; awake cycles per event mean %0d max %0d; late deliveries %0d (max %0d cycles)",
             N_EV, awake_sum / N_EV, awake_max, late_n, late_max);
    if (dec_ev >= 0)
      $display("TB: DECISION at event %0d, t=%0d ns after stream start (%0d cycles); event time %0d ns",
               dec_ev, (dec_cyc - t0) * CLK_PERIOD_NS, dec_cyc - t0, ev_cyc[dec_ev] * CLK_PERIOD_NS);
    else
      $display("TB: no decision within the stream");

    repeat (TAIL_SLEEP_CYCLES) @(posedge clk);
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
      $display("PASS: digit=%0d  tohost=%0d  decision_event=%0d  decision_ns=%0d  stream_cycles=%0d  awake_cycles=%0d",
               tohost - 1, tohost, dec_ev, (dec_cyc - t0) * CLK_PERIOD_NS, t_last - t0, awake_sum);
      $finish;
    end else if (tohost >= 32'd11 && tohost <= 32'd20 && sram_clk_en === 1'b0) begin
      // short stream: outputs bit-exact with the reference, no decision reached (as in the reference)
      $display("PASS: undecided (expected for this short stream), argmax=%0d  tohost=%0d  stream_cycles=%0d  awake_cycles=%0d",
               tohost - 11, tohost, t_last - t0, awake_sum);
      $finish;
    end else begin
      $display("FAIL: halted=%b tohost=%h sram_clk_en=%b sleeping=%b", halted, tohost, sram_clk_en, sleeping);
      $fatal(1);
    end
  end
endmodule
