// Device clock test: the 1 MHz tick generator must be exact for both the 100 MHz (1/100) and 85.714 MHz (7/600) cores.
`timescale 1ns/1ps
module tb_clock;
    reg clk = 0, rst = 1;
    always #5 clk = ~clk;
    wire a_miso, a_oe, a_scl, a_sda, a_irq, b_miso, b_oe, b_scl, b_sda, b_irq; wire [3:0] a_led, b_led;
    cam_core #(.POWERUP_CLKS(100), .MS_CLKS(10), .I2C_QDIV(2), .US_NUM(1), .US_DEN(100)) a(.clk(clk), .rst(rst), .hs_valid(1'b0),
        .lane0(8'd0), .lane1(8'd0), .sck(1'b0), .cs_n(1'b1), .mosi(1'b0), .miso(a_miso), .miso_oe(a_oe), .scl_oe(a_scl),
        .sda_oe(a_sda), .sda_i(1'b1), .irq(a_irq), .leds(a_led));
    cam_core #(.POWERUP_CLKS(100), .MS_CLKS(10), .I2C_QDIV(2), .US_NUM(7), .US_DEN(600)) b(.clk(clk), .rst(rst), .hs_valid(1'b0),
        .lane0(8'd0), .lane1(8'd0), .sck(1'b0), .cs_n(1'b1), .mosi(1'b0), .miso(b_miso), .miso_oe(b_oe), .scl_oe(b_scl),
        .sda_oe(b_sda), .sda_i(1'b1), .irq(b_irq), .leds(b_led));
    integer fails = 0;
    initial begin
        repeat (4) @(posedge clk); rst = 0;
        repeat (600000) @(posedge clk);
        #1;
        $display("a.time_us=%0d (want 6000) b.time_us=%0d (want 7000)", a.time_us, b.time_us);
        if (a.time_us !== 64'd6000) fails = fails + 1;
        if (b.time_us !== 64'd7000) fails = fails + 1;
        // 64-bit rollover carries into the high word
        a.time_us = 64'h0000_0001_FFFF_FFFF;
        repeat (101) @(posedge clk); #1;
        $display("a.time_us after carry = %h", a.time_us);
        if (a.time_us[63:32] !== 32'd2) fails = fails + 1;
        if (fails == 0) $display("CLOCK PASS"); else $display("CLOCK FAIL");
        $finish;
    end
endmodule
