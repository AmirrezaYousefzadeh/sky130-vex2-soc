// Bridge VexRiscv DBusSimple <-> DMEM SRAM22 + tohost MMIO.
// Memory map:
//   0x1000_0000 .. 0x1000_1FFF : DMEM (8 KiB)  - read/write
//   0x2000_0000                : tohost        - write nonzero => halt
//
// IMEM is Harvard-only (iBus); put .text in IMEM and .data/.bss/.rodata in DMEM.
`timescale 1ns/1ps

module dbus_sram22_bridge (
  input  wire        clk,
  input  wire        reset,
  input  wire        enable,

  // VexRiscv dBus
  input  wire        dBus_cmd_valid,
  output wire        dBus_cmd_ready,
  input  wire        dBus_cmd_payload_wr,
  input  wire [3:0]  dBus_cmd_payload_mask,
  input  wire [31:0] dBus_cmd_payload_address,
  input  wire [31:0] dBus_cmd_payload_data,
  input  wire [1:0]  dBus_cmd_payload_size,
  output reg         dBus_rsp_ready,
  output wire        dBus_rsp_error,
  output reg  [31:0] dBus_rsp_data,

  // DMEM
  output wire        dmem_ce,
  output wire        dmem_we,
  output wire [3:0]  dmem_wmask,
  output wire [10:0] dmem_addr,
  output wire [31:0] dmem_din,
  input  wire [31:0] dmem_dout,

  // Halt / tohost
  output reg         halted,
  output reg  [31:0] tohost
);
  localparam [31:0] DMEM_BASE   = 32'h1000_0000;
  localparam [31:0] TOHOST_ADDR = 32'h2000_0000;
  localparam [31:0] MEM_MASK    = 32'hFFFF_E000; // 8 KiB window

  wire fire = dBus_cmd_valid && dBus_cmd_ready;

  wire sel_dmem   = (dBus_cmd_payload_address & MEM_MASK) == DMEM_BASE;
  wire sel_tohost = (dBus_cmd_payload_address == TOHOST_ADDR);

  reg busy;
  reg was_write;
  reg was_tohost;
  reg sel_dmem_r;

  assign dBus_cmd_ready = enable && !busy && !reset && !halted;
  assign dBus_rsp_error = 1'b0;

  assign dmem_ce    = fire && sel_dmem;
  assign dmem_we    = fire && sel_dmem && dBus_cmd_payload_wr;
  assign dmem_wmask = dBus_cmd_payload_mask;
  assign dmem_addr  = dBus_cmd_payload_address[12:2];
  assign dmem_din   = dBus_cmd_payload_data;

  always @(posedge clk) begin
    if (reset) begin
      busy           <= 1'b0;
      was_write      <= 1'b0;
      was_tohost     <= 1'b0;
      sel_dmem_r     <= 1'b0;
      dBus_rsp_ready <= 1'b0;
      dBus_rsp_data  <= 32'b0;
      halted         <= 1'b0;
      tohost         <= 32'b0;
    end else begin
      dBus_rsp_ready <= 1'b0;

      if (fire) begin
        busy       <= 1'b1;
        was_write  <= dBus_cmd_payload_wr;
        was_tohost <= sel_tohost;
        sel_dmem_r <= sel_dmem;

        if (sel_tohost && dBus_cmd_payload_wr) begin
          tohost <= dBus_cmd_payload_data;
          if (dBus_cmd_payload_data != 32'b0)
            halted <= 1'b1;
        end
      end else if (busy) begin
        busy <= 1'b0;
        // DBusSimple waits on rsp only for loads
        if (!was_write) begin
          dBus_rsp_ready <= 1'b1;
          if (was_tohost)
            dBus_rsp_data <= tohost;
          else if (sel_dmem_r)
            dBus_rsp_data <= dmem_dout;
          else
            dBus_rsp_data <= 32'hDEAD_BEEF;
        end
      end
    end
  end

  wire unused_size = &dBus_cmd_payload_size;
endmodule
