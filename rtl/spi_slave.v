// SPI mode-0 slave bridge to a 24-bit byte-addressed bus.
//   read : 0x03 a2 a1 a0  <dummy byte>  d0 d1 d2 ...   (auto-increment, bytes of little-endian words)
//   write: 0x02 a2 a1 a0  w0b0 w0b1 w0b2 w0b3 w1b0 ...   (word aligned, little-endian, one bus_we per 4 bytes)
// SCK is sampled by the core clock, so SCK must be <= clk/6 (16 MHz at 100 MHz).
`timescale 1ns/1ps
module spi_slave (
    input  wire        clk,
    input  wire        rst,
    input  wire        sck,
    input  wire        cs_n,
    input  wire        mosi,
    output reg         miso,
    output wire        miso_oe,
    output reg  [23:0] bus_addr,
    output reg         bus_re,
    input  wire [31:0] bus_rdata,       // valid <= 8 clocks after bus_re
    output reg         bus_we,
    output reg  [31:0] bus_wdata
);
    reg [2:0] sck_s; reg [1:0] cs_s, mo_s;
    always @(posedge clk) begin sck_s <= {sck_s[1:0], sck}; cs_s <= {cs_s[0], cs_n}; mo_s <= {mo_s[0], mosi}; end
    wire active = ~cs_s[1];
    wire rise = sck_s[1] & ~sck_s[2];
    wire fall = ~sck_s[1] & sck_s[2];
    assign miso_oe = active;

    reg [2:0]  bitc;
    reg [7:0]  shin;
    reg [23:0] bytec;                   // bytes received after the header (payload index), header handled by hdr
    reg [2:0]  hdr;                     // 0 cmd, 1..3 address bytes, 4 = payload
    reg [7:0]  cmd;
    reg [23:0] paddr;                   // address of the next payload byte
    reg [7:0]  out_sh, next_byte;
    reg        load_pending;
    reg [3:0]  fwait;
    reg [1:0]  fsel;
    reg        dummy_done;
    reg [31:0] wacc; reg [1:0] wcnt; reg [23:0] waddr_q;

    wire [7:0] cur_byte = {shin[6:0], mo_s[1]};

    always @(posedge clk) begin
        bus_re <= 0; bus_we <= 0;
        if (rst || !active) begin
            bitc <= 0; hdr <= 0; load_pending <= 0; fwait <= 0; dummy_done <= 0; wcnt <= 0; miso <= 0; bytec <= 0;
        end else begin
            // fetch result capture
            if (fwait != 0) begin
                fwait <= fwait - 1;
                if (fwait == 1) next_byte <= bus_rdata >> {fsel, 3'b000};
            end
            if (rise) begin
                shin <= cur_byte;
                bitc <= bitc + 1;
                // prefetch the next byte at bit 2 of the dummy byte / every data byte
                if (bitc == 3'd2 && hdr == 3'd4 && cmd == 8'h03) begin
                    bus_addr <= paddr; bus_re <= 1; fwait <= 4'd10; fsel <= paddr[1:0];
                    paddr <= paddr + 1;
                end
                if (bitc == 3'd7) begin
                    case (hdr)
                        3'd0: begin cmd <= cur_byte; hdr <= 1; end
                        3'd1: begin paddr[23:16] <= cur_byte; hdr <= 2; end
                        3'd2: begin paddr[15:8] <= cur_byte; hdr <= 3; end
                        3'd3: begin paddr[7:0] <= cur_byte; hdr <= 4; waddr_q <= {paddr[23:8], cur_byte}; end
                        default: begin
                            if (cmd == 8'h03) load_pending <= 1;      // next fall shifts the prefetched byte out
                            else if (cmd == 8'h02) begin
                                case (wcnt)
                                    2'd0: wacc[7:0] <= cur_byte;
                                    2'd1: wacc[15:8] <= cur_byte;
                                    2'd2: wacc[23:16] <= cur_byte;
                                    default: begin
                                        bus_wdata <= {cur_byte, wacc[23:0]}; bus_addr <= waddr_q; bus_we <= 1;
                                        waddr_q <= waddr_q + 4;
                                    end
                                endcase
                                wcnt <= wcnt + 1;
                            end
                        end
                    endcase
                end
            end
            if (fall) begin
                if (load_pending) begin
                    load_pending <= 0; out_sh <= {next_byte[6:0], 1'b0}; miso <= next_byte[7];
                end else begin
                    out_sh <= {out_sh[6:0], 1'b0}; miso <= out_sh[7];
                end
            end
        end
    end
endmodule
