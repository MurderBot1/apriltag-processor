// Full-chain testbench: plays a CSI-2 stream at 120 fps timing into cam_core and, on every result interrupt,
// reads status + result records back through the SPI slave.  Dumps one block per result set to +out=.
//   +frames=hex +plen=hex +npk=<packets> +nframes=<expected results> +out=file
`timescale 1ns/1ps
module tb_cam;
    reg clk = 0, rst = 1;
    always #5 clk = ~clk;                      // 100 MHz
    reg hs = 0; reg [7:0] l0 = 0, l1 = 0;
    reg sck = 0, cs_n = 1, mosi = 0; wire miso, miso_oe;
    wire scl_oe, sda_oe, irq; wire [3:0] leds;
    cam_core #(.POWERUP_CLKS(100), .MS_CLKS(10), .I2C_QDIV(2)) dut(.clk(clk), .rst(rst), .hs_valid(hs), .lane0(l0),
        .lane1(l1), .sck(sck), .cs_n(cs_n), .mosi(mosi), .miso(miso), .miso_oe(miso_oe), .scl_oe(scl_oe),
        .sda_oe(sda_oe), .sda_i(1'b1), .irq(irq), .leds(leds));

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
    // per-frame CCL / TPU-start trace (step-0 diagnostics): build with -DTRACE
    always @(posedge clk) begin
        if (dut.ccl_done) $display("TRACE t=%0d ccl_done flags=%b(cand,lab,run,row) count=%0d max_row_cycles=%0d nlab=%0d cancel=%b tpu_busy=%b",
            cyc, dut.ccl_flags, dut.ccl_count, dut.ccl_maxrow, dut.ccl.nlab, dut.cancel, dut.tpu_busy);
        if (dut.tpu_start) $display("TRACE t=%0d tpu_start count=%0d", cyc, dut.tpu_count);
        if (dut.tpu_done) $display("TRACE t=%0d tpu_done cycles=%0d", cyc, dut.t_cycles);
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

    // ------------------------------------------------------------ result reader
    reg [31:0] st; integer nt, rec;
    always @(posedge irq) begin
        spi_read(24'h000018, 1); st = rd_words[0];
        nt = st[15:8];
        fd = $fopen(f, "a");
        $fdisplay(fd, "RESULT seq=%0d bank=%0d tags=%0d cyc=%0d", st[31:16], st[1], nt, cyc);
        if (nt > 31) nt = 31;                                   // result RAM holds 31 records; the MCU reads exactly `count` of them
        spi_read(st[1] ? 24'h002000 : 24'h001000, 16 + 16 * nt);
        for (i = 0; i < 16 + 16 * 31; i = i + 1) $fdisplay(fd, "%08x", (i < 16 + 16 * nt) ? rd_words[i] : 32'd0);
        $fclose(fd);
        nres = nres + 1;
    end

    initial begin
        if (!$value$plusargs("frames=%s", f)) $finish; $readmemh(f, beats);
        if (!$value$plusargs("plen=%s", f)) $finish; $readmemh(f, plen);
        if (!$value$plusargs("npk=%d", npk)) $finish;
        if (!$value$plusargs("nframes=%d", nframes)) $finish;
        if (!$value$plusargs("out=%s", f)) $finish;
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
        if (nres < nframes) $display("NO_RESULT ccl.S=%0d pend=%0d tpu.st=%0d tpu_busy=%b cancel=%b gate=%b ccl_done_cnt? tf=%0d oact=%b", dut.ccl.S, dut.ccl.pend, dut.tpu.st, dut.tpu_busy, dut.cancel, dut.gate, dut.th.tf, dut.th.oact);
        repeat (2000) @(posedge clk);
        fd = $fopen(f, "a");
        spi_read(24'h000018, 20);
        $fdisplay(fd, "STATS status=%08x frame=%0d ecc=%08x crc=%08x ccl=%08x tpucyc=%0d dropped=%0d total=%0d processed=%0d fsperiod_min=%0d fsperiod_max=%0d",
            rd_words[0], rd_words[1], rd_words[2], rd_words[3], rd_words[4], rd_words[5], rd_words[6], rd_words[7], rd_words[8], min_period, max_period);
        $fclose(fd);
        if ($value$plusargs("fbdump=%s", f)) begin
            fd = $fopen(f, "w");
            for (i = 0; i < 32000; i = i + 1) $fdisplay(fd, "%08x", dut.cur_bank ? dut.fb1[i] : dut.fb0[i]);
            $fclose(fd);
        end
        $display("DONE results=%0d fs=%0d", nres, fs_count);
        $finish;
    end
    initial begin #20000000000; $display("TIMEOUT"); $finish; end
endmodule
