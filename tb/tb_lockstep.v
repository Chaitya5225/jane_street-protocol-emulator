`timescale 1ns/1ps
// Lockstep RTL vs Python model: same 65-word image, compare architectural state after every tick.
module tb_lockstep;
    reg clk = 0, rst_n = 0;
    reg [7:0] ui_in = 8'h00, uio_in = 8'h01;      // LOAD_EN high during reset/load
    wire [7:0] uo_out, uio_out, uio_oe;
    tt_um_example uut (.ui_in(ui_in), .uo_out(uo_out), .uio_in(uio_in), .uio_out(uio_out),
                       .uio_oe(uio_oe), .ena(1'b1), .clk(clk), .rst_n(rst_n));
    always #10 clk = ~clk;

    reg [15:0] img [0:64];
    reg [15:0] tr  [0:65535];
    reg [8*200-1:0] hexf, trf;
    integer ui_v, uio_v, nt, k, bad, i;
    reg tk;

    task wr_byte(input [7:0] b);
        begin
            @(posedge clk); #1 ui_in = b; uio_in = uio_in | 8'h02;
            repeat (4) @(posedge clk);
            #1 uio_in = uio_in & ~8'h02;
            repeat (4) @(posedge clk);
        end
    endtask

    always @(posedge clk) tk <= uut.core.tick && !uut.core.load && rst_n;
    always @(negedge clk) if (tk && k < nt) begin
        if (tr[k*7+0] !== {10'd0, uut.core.pc} || tr[k*7+1] !== {8'd0, uut.core.x} ||
            tr[k*7+2] !== {8'd0, uut.core.y}   || tr[k*7+3] !== uut.core.isr ||
            tr[k*7+4] !== uut.core.osr         || tr[k*7+5] !== uut.core.out_l ||
            tr[k*7+6] !== uut.core.dir_l) begin
            if (bad < 3)
                $display("MISMATCH tick %0d: model pc=%0h x=%0h y=%0h isr=%0h osr=%0h out=%0h dir=%0h | rtl pc=%0h x=%0h y=%0h isr=%0h osr=%0h out=%0h dir=%0h",
                    k+1, tr[k*7+0], tr[k*7+1], tr[k*7+2], tr[k*7+3], tr[k*7+4], tr[k*7+5], tr[k*7+6],
                    uut.core.pc, uut.core.x, uut.core.y, uut.core.isr, uut.core.osr, uut.core.out_l, uut.core.dir_l);
            bad = bad + 1;
        end
        k = k + 1;
    end

    initial begin
        bad = 0; k = 0;
        if (!$value$plusargs("hex=%s", hexf)) $fatal(1, "need +hex=");
        if (!$value$plusargs("trace=%s", trf)) $fatal(1, "need +trace=");
        if (!$value$plusargs("ui=%d", ui_v)) ui_v = 0;
        if (!$value$plusargs("uio=%d", uio_v)) uio_v = 0;
        if (!$value$plusargs("nt=%d", nt)) nt = 1000;
        $readmemh(hexf, img);
        $readmemh(trf, tr);
        repeat (6) @(posedge clk);
        #1 rst_n = 1;
        repeat (4) @(posedge clk);
        for (i = 0; i < 65; i = i + 1) begin wr_byte(img[i][7:0]); wr_byte(img[i][15:8]); end
        @(posedge clk); #1 ui_in = ui_v[7:0]; uio_in = uio_v[7:0] & 8'hFE;   // LOAD_EN low: run
        wait (k >= nt);
        @(posedge clk);
        if (bad == 0) $display("PASS lockstep: %0d ticks", nt); else $display("FAIL lockstep: %0d bad of %0d", bad, nt);
        $finish;
    end
    initial begin #200000000; $display("TIMEOUT k=%0d", k); $finish; end
endmodule