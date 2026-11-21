`timescale 1ns/1ps
// Loads programs/uart_tx.hex through the parallel loader, sends 4 bytes, decodes TX with the reference monitor.
module tb_core_uart;
    localparam DIV = 54, CPB = 8 * DIV;
    reg clk = 0, rst_n = 0;
    reg [7:0] ui_in = 8'h00, uio_in = 8'h05;      // LOAD_EN=1, strobe (uio[2]) idle high
    wire [7:0] uo_out, uio_out, uio_oe;
    tt_um_example uut (.ui_in(ui_in), .uo_out(uo_out), .uio_in(uio_in), .uio_out(uio_out),
                       .uio_oe(uio_oe), .ena(1'b1), .clk(clk), .rst_n(rst_n));
    always #10 clk = ~clk;

    reg [15:0] img [0:64];
    wire [7:0] mdata; wire mvalid, mferr;
    reg armed = 0;   // TX is low while the loader holds the core in reset; ignore it until the program drives TX high
    wire rx_g = uo_out[0] | ~armed;
    uart_rx_monitor #(.CPB(CPB)) mon (.clk(clk), .rx(rx_g), .data(mdata), .valid(mvalid), .frame_err(mferr));

    reg [7:0] exp [0:3];
    integer got = 0, errors = 0, i, b, clkn = 0, t0 = 0;
    reg started = 0;
    reg last_tx = 1;

    task wr_byte(input [7:0] v);
        begin
            @(posedge clk); #1 ui_in = v; uio_in = uio_in | 8'h02;
            repeat (4) @(posedge clk);
            #1 uio_in = uio_in & ~8'h02;
            repeat (4) @(posedge clk);
        end
    endtask

    // print TX edges as (clock since load released) for comparison with the model's tick log
    always @(posedge clk) begin
        if (started) begin
            clkn <= clkn + 1;
            if (uo_out[0] !== last_tx) $display("EDGE %0d %0d", clkn, uo_out[0]);
            last_tx <= uo_out[0];
        end
    end

    always @(posedge clk) if (mvalid) begin
        if (mdata !== exp[got] || mferr) begin errors = errors + 1; $display("FAIL byte %0d got %h exp %h ferr=%b", got, mdata, exp[got], mferr); end
        got = got + 1;
    end

    initial begin
        exp[0] = 8'hA5; exp[1] = 8'h00; exp[2] = 8'hFF; exp[3] = 8'h3C;
        $readmemh("programs/uart_tx.hex", img);
        repeat (6) @(posedge clk); #1 rst_n = 1; repeat (4) @(posedge clk);
        for (i = 0; i < 65; i = i + 1) begin wr_byte(img[i][7:0]); wr_byte(img[i][15:8]); end
        @(posedge clk); #1 uio_in = 8'h04;            // LOAD_EN low: start; strobe high
        wait (uut.core.load == 1'b0);
        started = 1; clkn = 0;
        repeat (DIV * 3) @(posedge clk); armed = 1;
        for (b = 0; b < 4; b = b + 1) begin
            // same host schedule as tools/model.py: data at tick t, strobe low t+3, high t+8, next byte +100
            repeat (DIV * ((b == 0) ? 2 : 92) - 5) @(posedge clk);
            #1 ui_in = exp[b];
            repeat (DIV * 3) @(posedge clk);
            #1 uio_in = 8'h00;
            repeat (DIV * 5) @(posedge clk);
            #1 uio_in = 8'h04;
        end
        repeat (DIV * 100) @(posedge clk);
        if (got == 4 && errors == 0) $display("PASS: 4 bytes decoded by the reference monitor"); else $display("FAIL: got=%0d errors=%0d", got, errors);
        $finish;
    end
endmodule