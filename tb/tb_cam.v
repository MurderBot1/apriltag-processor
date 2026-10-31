// Full-chain testbench: plays a CSI-2 stream at 120 fps timing into cam_core and records what leaves on the MCU frame bus (mask + candidate
// packets, sampled on the rising edge of mcu_clk like the RP2350 PIO), then reads the statistics registers through the SPI slave.
//   +frames=hex +plen=hex +npk=<packets> +nframes=<expected packets> +out=file [+pkt=prefix : packet n is written to prefix.n.hex as 33032 words]
// +out= gets one "PACKET n bytes=.. cyc=.." line per packet and a final STATS line.
`timescale 1ns/1ps
module tb_cam;
    reg clk = 0, rst = 1;
    always #5 clk = ~clk;                      // 100 MHz
    reg hs = 0; reg [7:0] l0 = 0, l1 = 0;
    reg sck = 0, cs_n = 1, mosi = 0; wire miso, miso_oe;
    wire scl_oe, sda_oe, irq; wire [3:0] leds;
    wire [7:0] mcu_d; wire mcu_clk, mcu_fs;
    cam_core #(.POWERUP_CLKS(100), .MS_CLKS(10), .I2C_QDIV(2)) dut(.clk(clk), .rst(rst), .hs_valid(hs), .lane0(l0),
        .lane1(l1), .sck(sck), .cs_n(cs_n), .mosi(mosi), .miso(miso), .miso_oe(miso_oe), .scl_oe(scl_oe),
        .sda_oe(sda_oe), .sda_i(1'b1), .mcu_d(mcu_d), .mcu_clk(mcu_clk), .mcu_fs(mcu_fs), .irq(irq), .leds(leds));

    reg [15:0] beats [0:3000000];
    reg [31:0] plen [0:4000];
    integer npk, nframes, nres = 0;
    reg [1023:0] f;
    integer fd, k, i, b, maxcyc;
    integer fs_count = 0, last_fs = 0, cyc = 0, min_period = 999999999, max_period = 0;
    always @(posedge clk) begin
        cyc <= cyc + 1;
        if (dut.csi_fs) begin
            if (fs_count > 0) begin
                if (cyc - last_fs < min_period) min_period = cyc - last_fs;
                if (cyc - last_fs > max_period) max_period = cyc - last_fs;
            end
            last_fs <= cyc; fs_count <= fs_count + 1;
        end
    end

`ifdef TRACE
    // per-frame CCL trace (step-0 diagnostics): build with -DTRACE
    always @(posedge clk) begin
        if (dut.ccl_done) $display("TRACE t=%0d ccl_done flags=%b(cand,lab,run,row) count=%0d max_row_cycles=%0d nlab=%0d cancel=%b stream_busy=%b",
            cyc, dut.ccl_flags, dut.ccl_count, dut.ccl_maxrow, dut.ccl.nlab, dut.cancel, dut.stream_busy);
        if (dut.csi_fe) $display("TRACE t=%0d csi_fe frame_ok=%b cancel=%b ovf_row=%b ovf_run=%b ovf_lab=%b ovf_cand=%b ccl.S=%0d pend=%0d", cyc, dut.csi_frame_ok, dut.cancel, dut.ccl.ovf_row, dut.ccl.ovf_run, dut.ccl.ovf_lab, dut.ccl.ovf_cand, dut.ccl.S, dut.ccl.pend);
    end
    integer rowdrop = 0;
    always @(posedge clk) if (dut.ccl.tail_cyc && dut.ccl.pend >= 2) rowdrop <= rowdrop + 1;
    always @(posedge clk) if (dut.csi_fe) $display("TRACE rows_dropped_for_backpressure=%0d", rowdrop);
`endif

    // ------------------------------------------------------------ SPI master (SCK = clk/8 -> 12.5 MHz)
    reg [31:0] rd_words [0:1023];
    task spi_byte; input [7:0] tx; output [7:0] rx;
        integer q;
        begin
            rx = 0;
            for (q = 7; q >= 0; q = q - 1) begin
                mosi = tx[q]; repeat (4) @(posedge clk); sck = 1; rx = {rx[6:0], miso}; repeat (4) @(posedge clk); sck = 0;
            end
        end
    endtask
    reg [7:0] rxb;
    reg spi_lock = 0;
    task spi_read; input [23:0] addr; input integer nwords;
        integer w, bb;
        begin
            wait (!spi_lock); spi_lock = 1;
            cs_n = 0; repeat (8) @(posedge clk);
            spi_byte(8'h03, rxb); spi_byte(addr[23:16], rxb); spi_byte(addr[15:8], rxb); spi_byte(addr[7:0], rxb);
            spi_byte(8'h00, rxb);                              // dummy
            for (w = 0; w < nwords; w = w + 1) begin
                rd_words[w] = 0;
                for (bb = 0; bb < 4; bb = bb + 1) begin spi_byte(8'h00, rxb); rd_words[w][8*bb +: 8] = rxb; end
            end
            repeat (8) @(posedge clk); cs_n = 1; repeat (16) @(posedge clk); spi_lock = 0;
        end
    endtask
    task spi_write; input [23:0] addr; input [31:0] data;
        integer bb;
        begin
            wait (!spi_lock); spi_lock = 1;
            cs_n = 0; repeat (8) @(posedge clk);
            spi_byte(8'h02, rxb); spi_byte(addr[23:16], rxb); spi_byte(addr[15:8], rxb); spi_byte(addr[7:0], rxb);
            for (bb = 0; bb < 4; bb = bb + 1) spi_byte(data[8*bb +: 8], rxb);
            repeat (8) @(posedge clk); cs_n = 1; repeat (16) @(posedge clk); spi_lock = 0;
        end
    endtask

    // ------------------------------------------------------------ sensor model
    task play;
        integer p, nb, ty, bi, off, slots, frame_slot;
        begin
            off = 0; frame_slot = 0;
            for (p = 0; p < npk; p = p + 1) begin
                nb = plen[p][23:0]; ty = plen[p][31:24];
                for (bi = 0; bi < nb; bi = bi + 1) begin
                    hs <= 1; l0 <= beats[off + bi][7:0]; l1 <= beats[off + bi][15:8]; @(posedge clk);
                end
                off = off + nb;
                hs <= 0; repeat (800 - nb) @(posedge clk);
                frame_slot = frame_slot + 1;
                if (ty == 2) begin repeat ((1041 - frame_slot) * 800) @(posedge clk); frame_slot = 0; end
            end
        end
    endtask

    // ------------------------------------------------------------ MCU bus recorder (what the PIO + DMA of the RP2350 would capture)
    reg [7:0] pbuf [0:140000]; integer nb = 0; reg fs_q = 0; integer pk_cyc = 0; reg [1023:0] pktpre; reg have_pkt = 0;
    integer bad_packets = 0, pfd, pi; reg [31:0] pw; reg [8*200-1:0] pname;
    always @(posedge mcu_clk) begin pbuf[nb] = mcu_d; nb = nb + 1; end
    always @(posedge clk) begin
        fs_q <= mcu_fs;
        if (mcu_fs && !fs_q) pk_cyc = cyc;
        if (!mcu_fs && fs_q) begin
            fd = $fopen(f, "a");
            $fdisplay(fd, "PACKET %0d bytes=%0d start=%0d end=%0d", nres, nb, pk_cyc, cyc);
            $fclose(fd);
            if (nb != 132128) bad_packets = bad_packets + 1;
            else if (have_pkt) begin
                $sformat(pname, "%0s.%0d.hex", pktpre, nres);
                pfd = $fopen(pname, "w");
                for (pi = 0; pi < 33032; pi = pi + 1) begin
                    pw = {pbuf[4 * pi + 3], pbuf[4 * pi + 2], pbuf[4 * pi + 1], pbuf[4 * pi]};
                    $fdisplay(pfd, "%08x", pw);
                end
                $fclose(pfd);
            end
            nres = nres + 1; nb = 0;
        end
    end

    initial begin
        if (!$value$plusargs("frames=%s", f)) $finish; $readmemh(f, beats);
        if (!$value$plusargs("plen=%s", f)) $finish; $readmemh(f, plen);
        if (!$value$plusargs("npk=%d", npk)) $finish;
        if (!$value$plusargs("nframes=%d", nframes)) $finish;
        if (!$value$plusargs("out=%s", f)) $finish;
        have_pkt = $value$plusargs("pkt=%s", pktpre);
        fd = $fopen(f, "w"); $fclose(fd);
        repeat (10) @(posedge clk); rst <= 0; repeat (5) @(posedge clk);
        // register write/read check
        spi_write(24'h000058, 32'hCAFEF00D); spi_read(24'h000000, 1);
        spi_read(24'h000058, 1);
        $display("REGTEST id_ok=%0d scratch=%h", 1, rd_words[0]);
        spi_read(24'h000000, 2); $display("ID=%h VER=%h", rd_words[0], rd_words[1]);
        play;
        repeat (100000) @(posedge clk);
        maxcyc = 400000000; if ($value$plusargs("maxcyc=%d", maxcyc)) maxcyc = maxcyc;
        wait (nres >= nframes || cyc > maxcyc);
        if (nres < nframes) $display("NO_RESULT ccl.S=%0d pend=%0d stream_busy=%b ws=%0d cancel=%b gate=%b tf=%0d oact=%b", dut.ccl.S, dut.ccl.pend, dut.stream_busy, dut.ms.ws, dut.cancel, dut.gate, dut.th.tf, dut.th.oact);
        repeat (2000) @(posedge clk);
        fd = $fopen(f, "a");
        spi_read(24'h000018, 20);
        $fdisplay(fd, "STATS status=%08x frame=%0d ecc=%08x crc=%08x ccl=%08x stream=%08x dropped=%0d total=%0d processed=%0d fsperiod_min=%0d fsperiod_max=%0d bad_packets=%0d",
            rd_words[0], rd_words[1], rd_words[2], rd_words[3], rd_words[4], rd_words[5], rd_words[6], rd_words[7], rd_words[8], min_period, max_period, bad_packets);
        $fclose(fd);
        $display("DONE results=%0d fs=%0d", nres, fs_count);
        $finish;
    end
    initial begin #20000000000; $display("TIMEOUT"); $finish; end
endmodule
