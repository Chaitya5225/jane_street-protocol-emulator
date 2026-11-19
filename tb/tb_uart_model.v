`timescale 1ns/1ps
module tb_uart_model;
  localparam CPB = 16;
  reg clk = 0, tx = 1;
  wire [7:0] data; wire valid, ferr;
  integer errors = 0, got = 0;
  reg [7:0] exp [0:3];

  always #10 clk = ~clk;
  uart_rx_monitor #(.CPB(CPB)) mon (.clk(clk), .rx(tx), .data(data), .valid(valid), .frame_err(ferr));

  task send_byte(input [7:0] b);
    integer i;
    begin
      tx = 0; repeat (CPB) @(posedge clk);
      for (i = 0; i < 8; i = i + 1) begin tx = b[i]; repeat (CPB) @(posedge clk); end
      tx = 1; repeat (CPB) @(posedge clk);
    end
  endtask

  always @(posedge clk) if (valid) begin
    if (data !== exp[got] || ferr) begin
      errors = errors + 1;
      $display("FAIL byte %0d: got %h expected %h ferr=%b", got, data, exp[got], ferr);
    end
    got = got + 1;
  end

  initial begin
    exp[0] = 8'hA5; exp[1] = 8'h00; exp[2] = 8'hFF; exp[3] = 8'h3C;
    repeat (20) @(posedge clk);
    send_byte(8'hA5); send_byte(8'h00); send_byte(8'hFF); send_byte(8'h3C);
    repeat (40) @(posedge clk);
    if (got == 4 && errors == 0) $display("PASS: 4 bytes decoded");
    else $display("FAIL: got=%0d errors=%0d", got, errors);
    $finish;
  end
endmodule