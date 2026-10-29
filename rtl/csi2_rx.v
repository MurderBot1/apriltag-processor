// MIPI CSI-2 packet layer for a 2-lane RAW8 sensor (OV9281 @ 1280x800).
// Input is what the CrossLink-NX hard D-PHY RX delivers after SoT sync: one byte per lane per
// byte-clock, byte0 on lane0, byte1 on lane1, ... `hs_valid` is high for the whole HS burst.
// Output is a 2-pixels-per-clock video stream.
//
//  * header ECC is checked; single-bit header errors are corrected, double errors drop the packet
//  * payload CRC-16 (CRC-16/MCRF4XX, x^16+x^12+x^5+1, init 0xFFFF) is checked per line
//  * frame_ok at fe tells downstream if the frame had exactly LINES good lines
`timescale 1ns/1ps
module csi2_rx #(
    parameter LINES = 800,
    parameter DT_RAW8 = 6'h2A
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        hs_valid,
    input  wire [7:0]  lane0,
    input  wire [7:0]  lane1,

    output reg         pix_valid,      // one beat = two pixels
    output reg  [7:0]  pix0,           // even pixel (lane0 byte)
    output reg  [7:0]  pix1,           // odd pixel
    output reg         line_first,     // first beat of a line
    output reg         line_last,      // last beat of a line
    output reg         fs,             // frame start pulse
    output reg         fe,             // frame end pulse
    output reg         pkt_end,        // pulse: current packet fully consumed / dropped (lets the D-PHY layer re-arm)
    output reg         frame_ok,       // valid with fe
    output reg  [15:0] ecc_corrected,  // statistics (saturating)
    output reg  [15:0] ecc_dropped,
    output reg  [15:0] crc_errors,
    output reg  [15:0] frames_bad
);
    // ---------------------------------------------------------------- ECC
    function [5:0] ecc6;
        input [23:0] d;
        begin
            ecc6[5] = d[10]^d[11]^d[12]^d[13]^d[14]^d[15]^d[16]^d[17]^d[18]^d[19]^d[21]^d[22]^d[23];
            ecc6[4] = d[4]^d[5]^d[6]^d[7]^d[8]^d[9]^d[16]^d[17]^d[18]^d[19]^d[20]^d[22]^d[23];
            ecc6[3] = d[1]^d[2]^d[3]^d[7]^d[8]^d[9]^d[13]^d[14]^d[15]^d[19]^d[20]^d[21]^d[23];
            ecc6[2] = d[0]^d[2]^d[3]^d[5]^d[6]^d[9]^d[11]^d[12]^d[15]^d[18]^d[20]^d[21]^d[22];
            ecc6[1] = d[0]^d[1]^d[3]^d[4]^d[6]^d[8]^d[10]^d[12]^d[14]^d[17]^d[20]^d[21]^d[22]^d[23];
            ecc6[0] = d[0]^d[1]^d[2]^d[4]^d[5]^d[7]^d[10]^d[11]^d[13]^d[16]^d[20]^d[21]^d[22]^d[23];
        end
    endfunction

    // syndrome -> index of the single flipped data bit (31 = none); table generated from the ECC definition
    function [4:0] sig_idx;
        input [5:0] sy;
        begin
            case (sy)
            6'b000111: sig_idx = 5'd0;
            6'b001011: sig_idx = 5'd1;
            6'b001101: sig_idx = 5'd2;
            6'b001110: sig_idx = 5'd3;
            6'b010011: sig_idx = 5'd4;
            6'b010101: sig_idx = 5'd5;
            6'b010110: sig_idx = 5'd6;
            6'b011001: sig_idx = 5'd7;
            6'b011010: sig_idx = 5'd8;
            6'b011100: sig_idx = 5'd9;
            6'b100011: sig_idx = 5'd10;
            6'b100101: sig_idx = 5'd11;
            6'b100110: sig_idx = 5'd12;
            6'b101001: sig_idx = 5'd13;
            6'b101010: sig_idx = 5'd14;
            6'b101100: sig_idx = 5'd15;
            6'b110001: sig_idx = 5'd16;
            6'b110010: sig_idx = 5'd17;
            6'b110100: sig_idx = 5'd18;
            6'b111000: sig_idx = 5'd19;
            6'b011111: sig_idx = 5'd20;
            6'b101111: sig_idx = 5'd21;
            6'b110111: sig_idx = 5'd22;
            6'b111011: sig_idx = 5'd23;
            default: sig_idx = 5'd31;
            endcase
        end
    endfunction
    function syndrome_is_data;
        input [5:0] sy;
        begin syndrome_is_data = (sig_idx(sy) != 5'd31); end
    endfunction
    function [23:0] correct24;
        input [23:0] d;
        input [5:0]  sy;
        reg [4:0] ix;
        begin
            ix = sig_idx(sy);
            correct24 = (ix == 5'd31) ? d : (d ^ (24'd1 << ix));
        end
    endfunction

    // ---------------------------------------------------------------- CRC16 (reflected 0x8408)
    function [15:0] crc8;
        input [15:0] c;
        input [7:0]  b;
        integer k;
        reg [15:0] x;
        begin
            x = c ^ {8'd0, b};
            for (k = 0; k < 8; k = k + 1)
                x = x[0] ? ((x >> 1) ^ 16'h8408) : (x >> 1);
            crc8 = x;
        end
    endfunction

    localparam S_IDLE = 3'd0, S_HDR1 = 3'd1, S_PAY = 3'd2, S_CRC = 3'd3, S_DROP = 3'd4, S_HDR2 = 3'd5;
    reg [2:0]  st;
    reg [7:0]  h_di, h_wc0, h_wc1, h_ecc;      // raw header bytes, captured on the incoming beats
    reg [15:0] beats_left;
    reg [15:0] crc;
    reg [15:0] lines;
    reg        line_err, frame_err, in_frame;
    reg        first_beat;
    // The payload is delayed by one beat so the header can be decoded from registers (S_HDR2) instead of from the
    // incoming lane bytes.  Packets must be separated by at least two idle beats (true for D-PHY bursts).
    reg [7:0]  l0_d, l1_d; reg hv_d;

    wire [23:0] hdr_raw  = {h_wc1, h_wc0, h_di};
    wire [5:0]  rx_ecc   = h_ecc[5:0];
    wire [5:0]  syn      = ecc6(hdr_raw) ^ rx_ecc;
    wire        hdr_ok0  = (syn == 6'd0) && (h_ecc[7:6] == 2'b00);
    wire        hdr_1bit = !hdr_ok0 && (syndrome_is_data(syn) || (syn != 0 && (syn & (syn - 1)) == 0));
    wire [23:0] hdr_fix  = correct24(hdr_raw, syn);
    wire [5:0]  di_fix   = hdr_fix[5:0];
    wire [15:0] wc_fix   = hdr_fix[23:8];

    wire [15:0] crc_nx   = crc8(crc8(crc, l0_d), l1_d);
    // burst-end detection: header states use the incoming strobe, payload states the delayed one
    wire        hsv = (st == S_PAY || st == S_CRC) ? hv_d : ((st == S_HDR2) ? 1'b1 : hs_valid);

    always @(posedge clk) begin
        l0_d <= lane0; l1_d <= lane1; hv_d <= hs_valid;
        if (rst) begin
            st <= S_IDLE; pix_valid <= 0; fs <= 0; fe <= 0; frame_ok <= 0; pkt_end <= 0;
            ecc_corrected <= 0; ecc_dropped <= 0; crc_errors <= 0; frames_bad <= 0;
            lines <= 0; frame_err <= 0; in_frame <= 0; line_first <= 0; line_last <= 0;
            crc <= 16'hFFFF; beats_left <= 0; line_err <= 0; first_beat <= 0;
            pix0 <= 0; pix1 <= 0; h_di <= 0; h_wc0 <= 0; h_wc1 <= 0; h_ecc <= 0; hv_d <= 0;
        end else begin
            pix_valid <= 0; fs <= 0; fe <= 0; line_first <= 0; line_last <= 0; pkt_end <= 0;
            if (!hsv) begin
                // burst ended: a long packet that did not complete is a line error
                if (st == S_PAY || st == S_CRC || st == S_HDR1) begin
                    if (in_frame) frame_err <= 1;
                end
                if (st != S_IDLE && st != S_DROP) pkt_end <= 1;
                st <= S_IDLE;
            end else begin
                case (st)
                    S_IDLE: begin
                        h_di <= lane0; h_wc0 <= lane1; st <= S_HDR1;
                    end
                    S_HDR1: begin
                        h_wc1 <= lane0; h_ecc <= lane1; st <= S_HDR2;
                    end
                    S_HDR2: begin
                        if (hdr_ok0 || hdr_1bit) begin
                            if (!hdr_ok0 && ecc_corrected != 16'hFFFF) ecc_corrected <= ecc_corrected + 1;
                            if (di_fix == 6'h00) begin                 // frame start
                                fs <= 1; in_frame <= 1; lines <= 0; frame_err <= 0; st <= S_DROP; pkt_end <= 1;
                            end else if (di_fix == 6'h01) begin        // frame end
                                fe <= 1; in_frame <= 0; st <= S_DROP; pkt_end <= 1;
                                frame_ok <= in_frame && !frame_err && (lines == LINES);
                                if (!(in_frame && !frame_err && lines == LINES) && frames_bad != 16'hFFFF)
                                    frames_bad <= frames_bad + 1;
                            end else if (di_fix == DT_RAW8 && wc_fix != 0 && !wc_fix[0]) begin
                                beats_left <= wc_fix[15:1]; crc <= 16'hFFFF; first_beat <= 1; line_err <= 0;
                                st <= S_PAY;
                            end else begin
                                st <= S_DROP; pkt_end <= 1;            // line start/end, embedded data, ...
                            end
                        end else begin
                            if (ecc_dropped != 16'hFFFF) ecc_dropped <= ecc_dropped + 1;
                            if (in_frame) frame_err <= 1;
                            st <= S_DROP; pkt_end <= 1;
                        end
                    end
                    S_PAY: begin
                        pix_valid <= 1; pix0 <= l0_d; pix1 <= l1_d;
                        line_first <= first_beat; first_beat <= 0;
                        line_last <= (beats_left == 16'd1);
                        crc <= crc_nx;
                        beats_left <= beats_left - 1;
                        if (beats_left == 16'd1) st <= S_CRC;
                    end
                    S_CRC: begin
                        if ({l1_d, l0_d} != crc) begin
                            if (crc_errors != 16'hFFFF) crc_errors <= crc_errors + 1;
                            if (in_frame) frame_err <= 1;
                        end
                        lines <= lines + 1;
                        st <= S_DROP; pkt_end <= 1;
                    end
                    default: ;  // S_DROP: ignore the rest of the burst
                endcase
            end
        end
    end
endmodule
