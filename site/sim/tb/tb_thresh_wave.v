// Waveform scenario: adaptive threshold / binarize on a real frame tile.  Same stimulus as tb/tb_thresh.v
// (+img= 1280x800 raw bytes, 120 fps line timing); dumps only a window of output row +wy, beats +wc0 .. +wc1.
`timescale 1ns/1ps
module tb;
    parameter LINE = 905;
    reg clk = 0, rst = 1;
    always #5 clk = ~clk;
    reg [7:0] img [0:1280*800-1];
    reg vin_valid = 0; reg [7:0] p0 = 0, p1 = 0; reg fs = 0, fe = 0;
    wire o_valid, o_b0, o_b1, o_first, o_last, o_fs, o_fe, o_err; wire [9:0] o_y;
    reg [7:0] dth = 24, dab = 64;
    thresh_binarize #(.LINE_CYC(LINE)) dut(.clk(clk), .rst(rst), .cfg_diff_min(dth), .cfg_abs_black(dab), .cfg_line_cyc(LINE[15:0]),
        .vin_valid(vin_valid), .vin_p0(p0), .vin_p1(p1), .vin_fs(fs), .vin_fe(fe),
        .o_valid(o_valid), .o_b0(o_b0), .o_b1(o_b1), .o_first(o_first), .o_last(o_last), .o_y(o_y),
        .o_frame_start(o_fs), .o_frame_end(o_fe), .o_busy_err(o_err));
    // ---- signals shown in the viewer
    wire        in_valid = vin_valid; wire [7:0] in_pix0 = p0, in_pix1 = p1;        // sensor stream (row y+17 in this window)
    wire        s2_valid = dut.p2_v;                                                // delayed pixel read from the 17-row ring
    wire [7:0]  delayed_pix0 = dut.ring_q2[7:0], delayed_pix1 = dut.ring_q2[15:8];
    wire [7:0]  tile_thr = dut.thr_q2[7:0];                                         // (min+max)/2 of the 3x3 tile neighbourhood
    wire        tile_contrasty = dut.thr_q2[8];                                     // contrast test passed
    wire        out_valid = o_valid, out_black0 = o_b0, out_black1 = o_b1, out_first = o_first, out_last = o_last;
    wire [9:0]  out_row = o_y;
    reg  [9:0]  out_beat = 0;
    always @(posedge clk) if (o_valid) out_beat <= o_last ? 0 : out_beat + 1;
    integer fd, n, y, c, wy, wc0, wc1; reg [1023:0] imgf, f;
    // window: dump while the output pipeline is inside [wc0-2, wc1+4] of row wy
    wire [9:0] ob_dut = dut.ob;
    reg won = 0;
    wire inwin = (dut.oy == wy) && dut.oact && (ob_dut >= wc0 - 2) && (ob_dut <= wc1 + 4);
    always @(posedge clk) begin
        if (inwin && !won) begin won <= 1; $dumpon; end
        if (!inwin && won) begin won <= 0; $dumpoff; end
    end
    initial begin
        if (!$value$plusargs("vcd=%s", f)) $finish;
        $dumpfile(f); $dumpvars(1, tb); $dumpoff;
        if (!$value$plusargs("img=%s", imgf)) begin $display("need +img"); $finish; end
        if (!$value$plusargs("wy=%d", wy)) wy = 400;
        if (!$value$plusargs("wc0=%d", wc0)) wc0 = 100;
        if (!$value$plusargs("wc1=%d", wc1)) wc1 = 130;
        if ($value$plusargs("dth=%d", n)) dth = n;
        if ($value$plusargs("dab=%d", n)) dab = n;
        fd = $fopen(imgf, "rb"); n = $fread(img, fd); $fclose(fd);
        repeat (20) @(posedge clk); rst <= 0; repeat (5) @(posedge clk);
        fs <= 1; @(posedge clk); fs <= 0; repeat (20) @(posedge clk);
        for (y = 0; y < 800; y = y + 1) begin
            for (c = 0; c < 640; c = c + 1) begin
                vin_valid <= 1; p0 <= img[y*1280 + 2*c]; p1 <= img[y*1280 + 2*c + 1]; @(posedge clk);
            end
            vin_valid <= 0; repeat (LINE - 640) @(posedge clk);
            if (y > wy + 17 + 2) begin $display("RESULT window done"); $finish; end
        end
        $finish;
    end
endmodule
