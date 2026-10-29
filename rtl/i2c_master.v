// I2C / SCCB master with 16-bit register addressing (OV9281): one transaction =
//   write: S dev|W rh rl data P          read: S dev|W rh rl Sr dev|R data(NACK) P
// Open-drain: scl_oe / sda_oe = 1 pulls the line low.  No clock stretching.  nack is sticky until the next go.
`timescale 1ns/1ps
module i2c_master #(
    parameter QDIV = 62                 // clk cycles per quarter SCL period (100 MHz / (4*62) ~ 400 kHz)
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        go,
    input  wire        rw,              // 1 = read
    input  wire [6:0]  dev,
    input  wire [15:0] reg_addr,
    input  wire [7:0]  wdata,
    output reg  [7:0]  rdata,
    output reg         busy,
    output reg         done,            // pulse
    output reg         nack,
    output reg         scl_oe,
    output reg         sda_oe,
    input  wire        sda_i
);
    // op codes of the micro sequence
    localparam OP_START = 0, OP_BYTE = 1, OP_RSTART = 2, OP_RBYTE = 3, OP_STOP = 4;
    reg [3:0]  step;
    reg [7:0]  cur;
    reg [3:0]  bitn;
    reg [1:0]  ph;
    reg [7:0]  qcnt;
    reg [2:0]  op;
    reg        active, is_rd;
    reg [6:0]  dev_q; reg [15:0] ra_q; reg [7:0] wd_q;

    // sequence tables --------------------------------------------------------
    // returns op and byte for step index
    reg [2:0] seq_op; reg [7:0] seq_byte; reg seq_last;
    always @* begin
        seq_last = 0; seq_op = OP_STOP; seq_byte = 8'h00;
        case (step)
            4'd0: begin seq_op = OP_START; end
            4'd1: begin seq_op = OP_BYTE; seq_byte = {dev_q, 1'b0}; end
            4'd2: begin seq_op = OP_BYTE; seq_byte = ra_q[15:8]; end
            4'd3: begin seq_op = OP_BYTE; seq_byte = ra_q[7:0]; end
            4'd4: begin
                if (is_rd) seq_op = OP_RSTART; else begin seq_op = OP_BYTE; seq_byte = wd_q; end
            end
            4'd5: begin
                if (is_rd) begin seq_op = OP_BYTE; seq_byte = {dev_q, 1'b1}; end
                else begin seq_op = OP_STOP; seq_last = 1; end
            end
            4'd6: begin seq_op = OP_RBYTE; end
            default: begin seq_op = OP_STOP; seq_last = 1; end
        endcase
    end

    always @(posedge clk) begin
        done <= 0;
        if (rst) begin
            busy <= 0; scl_oe <= 0; sda_oe <= 0; active <= 0; nack <= 0; step <= 0; ph <= 0; qcnt <= 0; rdata <= 0;
        end else if (!active) begin
            scl_oe <= 0; sda_oe <= 0;
            if (go) begin
                active <= 1; busy <= 1; nack <= 0; step <= 0; ph <= 0; qcnt <= 0; bitn <= 0;
                dev_q <= dev; ra_q <= reg_addr; wd_q <= wdata; is_rd <= rw;
            end
        end else begin
            if (qcnt != QDIV - 1) qcnt <= qcnt + 1;
            else begin
                qcnt <= 0;
                case (seq_op)
                    OP_START: begin
                        // phases: 0: SDA=1,SCL=1  1: SDA low  2: SCL low  3: next
                        case (ph)
                            2'd0: begin sda_oe <= 0; scl_oe <= 0; ph <= 1; end
                            2'd1: begin sda_oe <= 1; ph <= 2; end
                            2'd2: begin scl_oe <= 1; ph <= 3; end
                            default: begin ph <= 0; step <= step + 1; bitn <= 0; cur <= 0; end
                        endcase
                    end
                    OP_RSTART: begin
                        // SDA high while SCL low, SCL high, SDA low, SCL low
                        case (ph)
                            2'd0: begin sda_oe <= 0; scl_oe <= 1; ph <= 1; end
                            2'd1: begin scl_oe <= 0; ph <= 2; end
                            2'd2: begin sda_oe <= 1; ph <= 3; end
                            default: begin scl_oe <= 1; ph <= 0; step <= step + 1; bitn <= 0; end
                        endcase
                    end
                    OP_BYTE: begin
                        // bits 0..7 data (MSB first) then bit 8 = ACK sampled from slave
                        case (ph)
                            2'd0: begin
                                scl_oe <= 1;
                                if (bitn < 8) sda_oe <= ~seq_byte[7 - bitn]; else sda_oe <= 0;
                                ph <= 1;
                            end
                            2'd1: begin scl_oe <= 0; ph <= 2; end
                            2'd2: begin
                                if (bitn == 8 && sda_i) nack <= 1;
                                ph <= 3;
                            end
                            default: begin
                                scl_oe <= 1; ph <= 0;
                                if (bitn == 8) begin bitn <= 0; step <= step + 1; end else bitn <= bitn + 1;
                            end
                        endcase
                    end
                    OP_RBYTE: begin
                        // 8 data bits from slave, then we NACK (SDA released) to end the read
                        case (ph)
                            2'd0: begin scl_oe <= 1; sda_oe <= (bitn == 8) ? 1'b0 : 1'b0; ph <= 1; end
                            2'd1: begin scl_oe <= 0; ph <= 2; end
                            2'd2: begin
                                if (bitn < 8) cur <= {cur[6:0], sda_i};
                                ph <= 3;
                            end
                            default: begin
                                scl_oe <= 1; ph <= 0;
                                if (bitn == 8) begin bitn <= 0; rdata <= cur; step <= 4'd7; end else bitn <= bitn + 1;
                            end
                        endcase
                    end
                    default: begin   // OP_STOP: SDA low, SCL high, SDA high
                        case (ph)
                            2'd0: begin scl_oe <= 1; sda_oe <= 1; ph <= 1; end
                            2'd1: begin scl_oe <= 0; ph <= 2; end
                            2'd2: begin sda_oe <= 0; ph <= 3; end
                            default: begin active <= 0; busy <= 0; done <= 1; ph <= 0; end
                        endcase
                    end
                endcase
            end
        end
    end
endmodule
