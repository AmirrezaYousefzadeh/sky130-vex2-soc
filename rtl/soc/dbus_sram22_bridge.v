// Bridge VexRiscv DBusSimple <-> DMEM SRAM22 + MMIO.
// Memory map:
//   0x1000_0000 .. 0x1000_1FFF : DMEM (8 KiB)
//   0x2000_0000                : tohost   - write nonzero => halt
//   0x2000_0004                : gpio     - bit0 = done (RW)
//   0x2000_0008                : sleep    - write 1 => request clock-gate sleep
//   0x2000_000C                : status   - bit0=sleeping (RO)
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
  output reg  [31:0] tohost,

  // Sleep / GPIO
  input  wire        sleeping,
  output reg         gpio_done,
  output reg         sleep_req
);
  localparam [31:0] DMEM_BASE   = 32'h1000_0000;
  localparam [31:0] TOHOST_ADDR = 32'h2000_0000;
  localparam [31:0] GPIO_ADDR   = 32'h2000_0004;
  localparam [31:0] SLEEP_ADDR  = 32'h2000_0008;
  localparam [31:0] STATUS_ADDR = 32'h2000_000C;
  localparam [31:0] MEM_MASK    = 32'hFFFF_E000; // 8 KiB window

  wire fire = dBus_cmd_valid && dBus_cmd_ready;

  wire sel_dmem   = (dBus_cmd_payload_address & MEM_MASK) == DMEM_BASE;
  wire sel_tohost = (dBus_cmd_payload_address == TOHOST_ADDR);
  wire sel_gpio   = (dBus_cmd_payload_address == GPIO_ADDR);
  wire sel_sleep  = (dBus_cmd_payload_address == SLEEP_ADDR);
  wire sel_status = (dBus_cmd_payload_address == STATUS_ADDR);

  reg busy;
  reg was_write;
  reg was_tohost;
  reg was_gpio;
  reg was_status;
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
      was_gpio       <= 1'b0;
      was_status     <= 1'b0;
      sel_dmem_r     <= 1'b0;
      dBus_rsp_ready <= 1'b0;
      dBus_rsp_data  <= 32'b0;
      halted         <= 1'b0;
      tohost         <= 32'b0;
      gpio_done      <= 1'b0;
      sleep_req      <= 1'b0;
    end else begin
      dBus_rsp_ready <= 1'b0;
      sleep_req      <= 1'b0;

      if (fire) begin
        busy       <= 1'b1;
        was_write  <= dBus_cmd_payload_wr;
        was_tohost <= sel_tohost;
        was_gpio   <= sel_gpio;
        was_status <= sel_status;
        sel_dmem_r <= sel_dmem;

        if (sel_tohost && dBus_cmd_payload_wr) begin
          tohost <= dBus_cmd_payload_data;
          if (dBus_cmd_payload_data != 32'b0)
            halted <= 1'b1;
        end
        if (sel_gpio && dBus_cmd_payload_wr)
          gpio_done <= dBus_cmd_payload_data[0];
        if (sel_sleep && dBus_cmd_payload_wr && dBus_cmd_payload_data[0])
          sleep_req <= 1'b1;
      end else if (busy) begin
        busy <= 1'b0;
        if (!was_write) begin
          dBus_rsp_ready <= 1'b1;
          if (was_tohost)
            dBus_rsp_data <= tohost;
          else if (was_gpio)
            dBus_rsp_data <= {31'b0, gpio_done};
          else if (was_status)
            dBus_rsp_data <= {31'b0, sleeping};
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
