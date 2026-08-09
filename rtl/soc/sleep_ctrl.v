// Sleep / wake controller: gates core_clk while sleeping or halted.
// Free-running `clk` runs the sleep FSM; CPU/SRAM/bridges use `core_clk`.
//
// Wake = ungate core_clk only (no MEIP). Firmware resumes after the SLEEP store
// once clocks return — avoids clk→core_clk hold paths on an IRQ pulse.
`timescale 1ns/1ps

module sleep_ctrl (
  input  wire clk,
  input  wire reset,
  input  wire sleep_req,   // 1-cycle pulse from MMIO (core domain, while clocks on)
  input  wire wake,        // async TB wake request (level)
  input  wire halted,
  output reg  sleeping,
  output wire core_clk_en,
  output wire core_clk,
  output wire ext_irq
);
  assign ext_irq = 1'b0;

  // Sync wake (2FF) on always-on clk
  reg wake_meta, wake_sync, wake_sync_d;
  always @(posedge clk) begin
    if (reset) begin
      wake_meta   <= 1'b0;
      wake_sync   <= 1'b0;
      wake_sync_d <= 1'b0;
    end else begin
      wake_meta   <= wake;
      wake_sync   <= wake_meta;
      wake_sync_d <= wake_sync;
    end
  end
  wire wake_rise = wake_sync & ~wake_sync_d;

  reg sleep_req_d;
  always @(posedge clk) begin
    if (reset)
      sleep_req_d <= 1'b0;
    else
      sleep_req_d <= sleep_req;
  end
  wire sleep_rise = sleep_req & ~sleep_req_d;

  always @(posedge clk) begin
    if (reset) begin
      sleeping <= 1'b1; // power-on sleep after reset release
    end else begin
      if (sleep_rise && !halted)
        sleeping <= 1'b1;
      if (wake_rise && sleeping && !halted)
        sleeping <= 1'b0;
      if (halted)
        sleeping <= 1'b1;
    end
  end

  assign core_clk_en = reset | (!sleeping && !halted);

  clk_gate u_core_icg (
    .clk  (clk),
    .en   (core_clk_en),
    .gclk (core_clk)
  );
endmodule
