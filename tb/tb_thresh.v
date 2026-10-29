// Feeds one 1280x800 frame (raw bytes from +img=file) at 120fps line timing (LINE=905 clk) into
// thresh_binarize and dumps the binary mask (+out=file, 1 byte/pixel 0/1) for comparison with golden.py.
`timescale 1ns/1ps
module tb_thresh;
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
    reg [7:0] mask [0:1280*800-1];
    integer fd, n, y, c, beats = 0, rows_seen = 0, bad_order = 0;
    reg [9:0] expect_y = 0; reg [9:0] expect_c = 0;
    reg got_fe = 0;
    always @(posedge clk) if (o_valid) begin
        mask[o_y*1280 + expect_c*2]     <= o_b0;
        mask[o_y*1280 + expect_c*2 + 1] <= o_b1;
        beats = beats + 1;
        if (o_y != expect_y) bad_order = bad_order + 1;
        if (o_last) begin expect_c <= 0; expect_y <= expect_y + 1; rows_seen = rows_seen + 1; end
        else expect_c <= expect_c + 1;
    end
    always @(posedge clk) if (o_fe) got_fe <= 1;
    reg [1023:0] imgf, outf;
    initial begin
        if (!$value$plusargs("img=%s", imgf)) begin $display("need +img"); $finish; end
        if (!$value$plusargs("out=%s", outf)) begin $display("need +out"); $finish; end
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
        end
        fe <= 1; @(posedge clk); fe <= 0;
        repeat (LINE * 20) @(posedge clk);
        fd = $fopen(outf, "wb");
        for (n = 0; n < 1280*800; n = n + 1) $fwrite(fd, "%c", mask[n] ? 8'd1 : 8'd0);
        $fclose(fd);
        $display("RESULT rows=%0d beats=%0d bad_order=%0d busy_err=%0d got_fe=%0d", rows_seen, beats, bad_order, o_err, got_fe);
        $finish;
    end
endmodule
