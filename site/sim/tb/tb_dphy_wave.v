// Waveform scenario: D-PHY lane receive.  Same stimulus as tb/tb_dphy.v (+l0= +l1= bit-stream files, 32 UI/word),
// but only short windows around chosen packet bursts are dumped (+w0=, +w1=, +w2= : packet slot numbers).
`timescale 1ns/1ps
module tb;
    parameter LINES = 2;
    parameter SLOT = 6400;
    reg clk_p = 0; reg [1:0] d_p = 0;
    reg core_clk = 0, core_rst = 1;
    always #5 core_clk = ~core_clk;
    wire hs_valid; wire [7:0] lane0, lane1; wire [3:0] status; wire pkt_end;
    wire pv, lf, ll, fs, fe, fok; wire [7:0] p0, p1; wire [15:0] ec, ed, ce, fb;
    dphy_rx #(.USE_PRIM(0), .BEH_REVERSE(0)) rx(.clk_p(clk_p), .d_p(d_p), .core_clk(core_clk), .core_rst(core_rst), .pkt_end(pkt_end),
        .hs_valid(hs_valid), .lane0(lane0), .lane1(lane1), .status(status));
    csi2_rx #(.LINES(LINES)) csi(.clk(core_clk), .rst(core_rst), .hs_valid(hs_valid), .lane0(lane0), .lane1(lane1),
        .pix_valid(pv), .pix0(p0), .pix1(p1), .line_first(lf), .line_last(ll), .fs(fs), .fe(fe), .pkt_end(pkt_end),
        .frame_ok(fok), .ecc_corrected(ec), .ecc_dropped(ed), .crc_errors(ce), .frames_bad(fb));
    // ---- signals shown in the viewer
    wire clk_lane = clk_p;                     // sensor clock lane (400 MHz DDR, one edge per bit)
    wire data_lane0 = d_p[0], data_lane1 = d_p[1];
    wire sclk = rx.sclk;                       // divided byte-side clock in the receiver
    wire [3:0] gear_q0 = rx.q0, gear_q1 = rx.q1;   // 4:1 gearing outputs per lane
    wire [1:0] byte_valid = rx.bv;
    wire [1:0] lane_locked = rx.lock_any;
    wire [7:0] byte_l0 = rx.bd[0], byte_l1 = rx.bd[1];   // sync-aligned bytes before deskew FIFO
    wire [1:0] fifo_empty = rx.empty;
    wire [3:0] resyncs = rx.resyncs;
    wire [3:0] rx_status = status;
    wire core_clock = core_clk;
    wire pix_valid = pv; wire [7:0] pix0 = p0, pix1 = p1; wire line_first = lf, line_last = ll, frame_ok = fok;
    wire [2:0] csi_state = csi.st; wire [15:0] line_count = csi.lines;
    wire [15:0] ecc_corrected = ec, ecc_dropped = ed, crc_errors = ce, frames_bad = fb;
    reg [31:0] w0 [0:100000]; reg [31:0] w1 [0:100000];
    integer i, nui, k, s, a, b, c; reg [1023:0] f; integer ws0, ws1, ws2, ws3;
    task win; input integer slot; input integer ui; begin
        if (ui % SLOT == 150 && ui / SLOT == slot) $dumpon;
        if (ui % SLOT == 1400 && ui / SLOT == slot) $dumpoff;
    end endtask
    initial begin
        if (!$value$plusargs("vcd=%s", f)) $finish;
        $dumpfile(f); $dumpvars(1, tb); $dumpoff;
        if (!$value$plusargs("l0=%s", f)) $finish; $readmemh(f, w0);
        if (!$value$plusargs("l1=%s", f)) $finish; $readmemh(f, w1);
        if (!$value$plusargs("nui=%d", nui)) $finish;
        ws0 = -1; ws1 = -1; ws2 = -1; ws3 = -1;
        if ($value$plusargs("w0=%d", a)) ws0 = a;
        if ($value$plusargs("w1=%d", a)) ws1 = a;
        if ($value$plusargs("w2=%d", a)) ws2 = a;
        if ($value$plusargs("w3=%d", a)) ws3 = a;
        #100 core_rst = 0;
        #50;
        for (i = 0; i < nui; i = i + 1) begin
            d_p[0] = w0[i/32][i%32]; d_p[1] = w1[i/32][i%32];
            win(ws0, i); win(ws1, i); win(ws2, i); win(ws3, i);
            #0.625 clk_p = ~clk_p;
            #0.625;
        end
        #2000;
        $finish;
    end
endmodule
