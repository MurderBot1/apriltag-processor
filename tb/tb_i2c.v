// Sensor init over I2C against a behavioural OV9281-like slave (16-bit register space).
// Checks every init ROM entry landed, then does host-style write+read transactions (+ID register) and a NACK probe.
`timescale 1ns/1ps
module tb_i2c;
    reg clk = 0, rst = 1;
    always #5 clk = ~clk;
    wire scl_oe, sda_oe; wire sda_i_line;
    // open-drain bus
    wire scl = ~scl_oe;
    reg  slave_sda_oe = 0;
    wire sda = ~(sda_oe | slave_sda_oe);
    assign sda_i_line = sda;

    // ---- init sequencer + master
    wire go_i; wire [15:0] reg_i; wire [7:0] dat_i; wire [6:0] dev_i; wire init_done; wire [7:0] nack_count;
    reg  go_h = 0, rw_h = 0; reg [6:0] dev_h = 7'h60; reg [15:0] reg_h = 0; reg [7:0] dat_h = 0;
    wire go = init_done ? go_h : go_i;
    wire rw = init_done ? rw_h : 1'b0;
    wire [6:0] dev = init_done ? dev_h : dev_i;
    wire [15:0] rega = init_done ? reg_h : reg_i;
    wire [7:0] dat = init_done ? dat_h : dat_i;
    wire [7:0] rdata; wire busy, done, nack;
    i2c_master #(.QDIV(8)) m(.clk(clk), .rst(rst), .go(go), .rw(rw), .dev(dev), .reg_addr(rega), .wdata(dat),
        .rdata(rdata), .busy(busy), .done(done), .nack(nack), .scl_oe(scl_oe), .sda_oe(sda_oe), .sda_i(sda));
    sensor_init #(.POWERUP_CLKS(200), .MS_CLKS(50)) si(.clk(clk), .rst(rst), .i2c_done(done), .i2c_nack(nack),
        .i2c_busy(busy), .i2c_go(go_i), .i2c_reg(reg_i), .i2c_data(dat_i), .i2c_dev(dev_i), .init_done(init_done),
        .nack_count(nack_count));

    // ---- behavioural slave (address 0x60), ID registers at 0x300a/0x300b
    reg [7:0] regs [0:65535];
    integer wr_log_n = 0;
    reg [15:0] wr_log_a [0:255]; reg [7:0] wr_log_d [0:255];
    integer k;
    initial begin for (k = 0; k < 65536; k = k + 1) regs[k] = 0; regs[16'h300a] = 8'h92; regs[16'h300b] = 8'h81; end
    reg [15:0] ptr = 0; reg [7:0] sh = 0;
    // bit-level slave: n counts SCL rising edges inside the current byte (0..9)
    localparam M_IDLE = 0, M_ADDR = 1, M_PH = 2, M_PL = 3, M_DATA = 4, M_TX = 5;
    reg [2:0] mode = M_IDLE; reg [3:0] n = 0; reg ack_v;
    reg sda_q = 1, scl_q = 1;
    always @(posedge clk) begin sda_q <= sda; scl_q <= scl; end
    wire start_c = scl && scl_q && sda_q && !sda;
    wire stop_c  = scl && scl_q && !sda_q && sda;
    wire scl_rise = scl && !scl_q;
    wire scl_fall = !scl && scl_q;
    reg [7:0] txb;
    always @(posedge clk) begin
        if (start_c) begin mode <= M_ADDR; n <= 0; slave_sda_oe <= 0; end
        else if (stop_c) begin mode <= M_IDLE; slave_sda_oe <= 0; end
        else if (mode != M_IDLE) begin
            if (scl_rise) begin
                if (mode != M_TX && n < 8) sh <= {sh[6:0], sda};
                n <= n + 1;
            end
            if (scl_fall) begin
                if (mode == M_TX) begin
                    if (n < 8) slave_sda_oe <= ~txb[7 - n];
                    else begin slave_sda_oe <= 0; if (n == 9) begin mode <= M_IDLE; end end
                end else if (n == 8) begin
                    ack_v = (mode == M_ADDR) ? (sh[7:1] == 7'h60) : 1'b1;
                    slave_sda_oe <= ack_v; if (!ack_v) mode <= M_IDLE;
                end else if (n == 9) begin
                    slave_sda_oe <= 0; n <= 0;
                    case (mode)
                        M_ADDR: if (sh[0]) begin mode <= M_TX; txb <= regs[ptr]; slave_sda_oe <= ~regs[ptr][7]; end else mode <= M_PH;
                        M_PH:   begin ptr[15:8] <= sh; mode <= M_PL; end
                        M_PL:   begin ptr[7:0] <= sh; mode <= M_DATA; end
                        M_DATA: begin regs[ptr] <= sh; wr_log_a[wr_log_n] <= ptr; wr_log_d[wr_log_n] <= sh;
                                      wr_log_n <= wr_log_n + 1; mode <= M_IDLE; end
                        default: ;
                    endcase
                end
            end
        end
    end

    reg [31:0] expect_n;
    integer i, errors;
    reg [7:0] got;
    task host_xfer; input rwv; input [15:0] ra; input [7:0] d;
        begin
            @(posedge clk); rw_h <= rwv; reg_h <= ra; dat_h <= d; go_h <= 1; @(posedge clk); go_h <= 0;
            wait (done); @(posedge clk);
        end
    endtask
    reg [23:0] rom [0:255];
    initial begin
        $readmemh("rtl/sensor_init.hex", rom);
        errors = 0;
        repeat (10) @(posedge clk); rst <= 0;
        wait (init_done);
        repeat (50) @(posedge clk);
        // every non-delay ROM entry must be present in the slave write log (in order)
        i = 0;
        for (k = 0; k < 104; k = k + 1) begin
            if (rom[k][23:8] != 16'hFFFF) begin
                if (wr_log_a[i] !== rom[k][23:8] || wr_log_d[i] !== rom[k][7:0]) begin
                    errors = errors + 1; if (errors < 5) $display("ROM entry %0d mismatch: got %h=%h want %h=%h", k, wr_log_a[i], wr_log_d[i], rom[k][23:8], rom[k][7:0]);
                end
                i = i + 1;
            end
        end
        $display("INIT writes_logged=%0d expected=%0d nacks=%0d errors=%0d", wr_log_n, i, nack_count, errors);
        // host write / readback / ID read
        host_xfer(0, 16'h3509, 8'h55);
        host_xfer(1, 16'h3509, 8'h00); got = rdata; $display("READBACK 3509=%h", got);
        host_xfer(1, 16'h300a, 8'h00); got = rdata; $display("ID_HI=%h", got);
        host_xfer(1, 16'h300b, 8'h00); got = rdata; $display("ID_LO=%h", got);
        dev_h = 7'h33; host_xfer(0, 16'h0000, 8'h00); $display("NACK_PROBE nack=%0d", nack);
        $finish;
    end
    initial begin #400000000; $display("TIMEOUT"); $finish; end
endmodule
