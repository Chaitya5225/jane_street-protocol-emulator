module uart_rx_monitor #(parameter CPB = 16) (
  input  wire       clk,
  input  wire       rx,
  output reg  [7:0] data      = 8'h00,
  output reg        valid     = 1'b0,
  output reg        frame_err = 1'b0
);
  localparam IDLE = 0, START = 1, DATA = 2, STOP = 3;
  reg [1:0] st = IDLE;
  integer   cnt = 0;
  integer   bit_i = 0;
  reg [7:0] sh = 8'h00;

  always @(posedge clk) begin
    valid <= 1'b0;
    case (st)
      IDLE: if (!rx) begin st <= START; cnt <= 0; end
      START: if (cnt == CPB/2 - 1) begin
               if (!rx) begin st <= DATA; cnt <= 0; bit_i <= 0; end
               else st <= IDLE;
             end else cnt <= cnt + 1;
      DATA: if (cnt == CPB - 1) begin
              cnt <= 0;
              sh[bit_i] <= rx;
              if (bit_i == 7) st <= STOP; else bit_i <= bit_i + 1;
            end else cnt <= cnt + 1;
      STOP: if (cnt == CPB - 1) begin
              data <= sh; valid <= 1'b1; frame_err <= !rx;
              st <= IDLE; cnt <= 0;
            end else cnt <= cnt + 1;
    endcase
  end
endmodule