/*
 * Protocol emulator, ISA v0.1 (see docs/isa.md).
 * One in-order core, one instruction per tick, tick = DIV chip clocks.
 * RTL mirrors tools/model.py step() line for line.
 */
`default_nettype none

module protocol_core (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] ui_in,
    input  wire [7:0] uio_in,
    output wire [7:0] uo_out,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe
);
    // ---------------------------------------------------------------- input sync
    reg [7:0] ui_a, ui_s, uio_a, uio_s;
    always @(posedge clk) begin
        ui_a  <= ui_in;   ui_s  <= ui_a;
        uio_a <= uio_in;  uio_s <= uio_a;
    end
    wire load = uio_s[0];                 // LOAD_EN
    wire wr   = uio_s[1];                 // WR strobe

    // ---------------------------------------------------------------- loader
    reg [15:0] mem [0:63];
    reg [7:0]  div;
    reg [6:0]  ptr;
    reg        hi, wr_d;
    reg [7:0]  lo;
    wire       wr_rise = wr & ~wr_d;

    always @(posedge clk) begin
        wr_d <= wr;
        if (!rst_n) begin
            ptr <= 7'd0; hi <= 1'b0; div <= 8'd54;
        end else if (!load) begin
            ptr <= 7'd0; hi <= 1'b0;
        end else if (wr_rise) begin
            if (!hi) begin
                lo <= ui_s; hi <= 1'b1;
            end else begin
                hi <= 1'b0;
                if (ptr < 7'd64)       mem[ptr[5:0]] <= {ui_s, lo};
                else if (ptr == 7'd64) div <= lo;          // word 64 = {8'h00, DIV}
                if (ptr < 7'd65) ptr <= ptr + 7'd1;
            end
        end
    end

    // ---------------------------------------------------------------- core state
    reg [5:0]  pc;
    reg [7:0]  x, y;
    reg [15:0] isr, osr, out_l, dir_l, cnt;
    reg [4:0]  jmppin, inbase;
    reg        active;                    // an instruction is in flight
    reg [2:0]  c_delay;
    reg        c_wait, c_pol;
    reg [3:0]  c_pin;
    reg [5:0]  c_next;

    // tick divider: DIV = 0 behaves as 1
    reg  [7:0] tcnt;
    wire [7:0] eff  = (div == 8'd0) ? 8'd1 : div;
    wire       tick = (tcnt == eff - 8'd1);
    always @(posedge clk)
        if (!rst_n || load) tcnt <= 8'd0;
        else                tcnt <= tick ? 8'd0 : tcnt + 8'd1;

    // pin view: pins 0-7 = ui, 8-15 = uio (reads own drive when dir=1)
    wire [15:0] pins16 = {(dir_l[15:8] & out_l[15:8]) | (~dir_l[15:8] & uio_s), ui_s};

    // ---------------------------------------------------------------- next state
    reg [5:0]  n_pc;
    reg [7:0]  n_x, n_y;
    reg [15:0] n_isr, n_osr, n_out, n_dir, n_cnt;
    reg [4:0]  n_jmppin, n_inbase;
    reg        n_active, n_cwait, n_cpol;
    reg [2:0]  n_cdelay;
    reg [3:0]  n_cpin;
    reg [5:0]  n_cnext;

    reg [15:0] w, field, mask, val, capv;
    reg [2:0]  l_delay;
    reg        l_wait, l_pol, take, lvl, match, still;
    reg [3:0]  l_pin;
    reg [5:0]  l_next, idx;
    reg [4:0]  n;
    integer    i;

    always @* begin
        n_pc = pc; n_x = x; n_y = y; n_isr = isr; n_osr = osr;
        n_out = out_l; n_dir = dir_l; n_cnt = cnt;
        n_jmppin = jmppin; n_inbase = inbase;
        n_active = active; n_cwait = c_wait; n_cpol = c_pol;
        n_cdelay = c_delay; n_cpin = c_pin; n_cnext = c_next;
        w = mem[pc];
        field = 16'd0; mask = 16'd0; val = 16'd0; capv = cnt + 16'd1;
        l_delay = c_delay; l_wait = c_wait; l_pol = c_pol;
        l_pin = c_pin; l_next = c_next;
        take = 1'b0; lvl = 1'b0; match = 1'b0; still = 1'b0;
        idx = 6'd0; n = 5'd0;

        if (tick) begin
            n_cnt = cnt + 16'd1;
            if (!active) begin
                // ---- start a new instruction
                l_delay = w[12:10]; l_wait = 1'b0; l_pol = 1'b0; l_pin = 4'd0;
                l_next  = pc + 6'd1;
                if (w[9]) n_out[1] = w[8];                    // side-set on uo[1]
                case (w[15:13])
                3'd0: begin                                   // JMP
                    take = (w[7:6] == 2'd0);
                    if (w[7:6] == 2'd1) begin
                        if (x != 8'd0) begin n_x = x - 8'd1; take = 1'b1; end
                    end else if (w[7:6] == 2'd2 || w[7:6] == 2'd3) begin
                        lvl  = (jmppin < 5'd16) ? pins16[jmppin[3:0]] : 1'b0;
                        take = (lvl == (w[7:6] == 2'd2));
                    end
                    if (take) l_next = w[5:0];
                end
                3'd1: begin                                   // WAIT
                    l_wait = 1'b1; l_pol = w[7]; l_pin = w[3:0];
                end
                3'd2: begin                                   // SET
                    case (w[7:5])
                    3'd0:    n_out[4:0] = w[4:0];
                    3'd1:    n_dir[4:0] = w[4:0];
                    3'd2:    n_x = {3'b000, w[4:0]};
                    default: n_y = {3'b000, w[4:0]};
                    endcase
                end
                3'd3: begin                                   // IN
                    n = w[4:0];
                    if (w[7:5] == 3'd0) begin
                        for (i = 0; i < 16; i = i + 1)
                            if (i < n) begin
                                idx = inbase + i[5:0];
                                field[i] = (idx < 6'd16) ? pins16[idx[3:0]] : 1'b0;
                            end
                        n_isr = (isr << n) | field;
                    end else if (w[7:5] == 3'd2) n_isr = {8'h00, x};
                    else if   (w[7:5] == 3'd3) n_isr = {8'h00, y};
                end
                3'd4: begin                                   // OUT
                    n = w[4:0];
                    mask = (n >= 5'd16) ? 16'hFFFF : ((16'd1 << n) - 16'd1);
                    case (w[7:5])
                    3'd0:    n_out = (n_out & ~mask) | (osr & mask);
                    3'd1:    n_dir = (dir_l & ~mask) | (osr & mask);
                    3'd2:    n_x = osr[7:0];
                    default: n_y = osr[7:0];
                    endcase
                    n_osr = (n >= 5'd16) ? 16'd0 : (osr >> n);
                end
                3'd5: begin                                   // MOV
                    case (w[1:0])
                    2'd0: val = isr;
                    2'd1: val = osr;
                    2'd2: val = {8'h00, x};
                    default: val = {8'h00, y};
                    endcase
                    if (w[4:3] == 2'd1) val = ~val;
                    else if (w[4:3] == 2'd2)
                        for (i = 0; i < 16; i = i + 1) field[i] = val[15 - i];
                    if (w[4:3] == 2'd2) val = field;
                    case (w[7:5])
                    3'd0:    n_osr = val;
                    3'd1:    n_isr = val;
                    3'd2:    n_x = val[7:0];
                    default: n_y = val[7:0];
                    endcase
                end
                3'd6: begin                                   // CAP
                    case (w[7:5])
                    3'd0: n_osr = capv;
                    3'd2: n_x = capv[7:0];
                    3'd3: n_y = capv[7:0];
                    default: ;
                    endcase
                    n_cnt = 16'd0;
                end
                3'd7: begin                                   // CFG
                    if (w[7:5] == 3'd0)      n_jmppin = w[4:0];
                    else if (w[7:5] == 3'd1) n_inbase = w[4:0];
                end
                endcase
            end
            // ---- advance: WAIT stall, delay, retire
            match = l_wait && (pins16[l_pin] == l_pol);
            still = l_wait && !match;
            if (!still) begin
                if (l_delay != 3'd0) begin n_cdelay = l_delay - 3'd1; n_active = 1'b1; end
                else begin n_pc = l_next; n_active = 1'b0; n_cdelay = 3'd0; end
            end else begin
                n_cdelay = l_delay; n_active = 1'b1;
            end
            n_cwait = still; n_cpol = l_pol; n_cpin = l_pin; n_cnext = l_next;
        end
    end

    always @(posedge clk) begin
        if (!rst_n || load) begin
            pc <= 6'd0; x <= 8'd0; y <= 8'd0; isr <= 16'd0; osr <= 16'd0;
            out_l <= 16'd0; dir_l <= 16'd0; cnt <= 16'd0;
            jmppin <= 5'd0; inbase <= 5'd0;
            active <= 1'b0; c_delay <= 3'd0; c_wait <= 1'b0; c_pol <= 1'b0;
            c_pin <= 4'd0; c_next <= 6'd0;
        end else begin
            pc <= n_pc; x <= n_x; y <= n_y; isr <= n_isr; osr <= n_osr;
            out_l <= n_out; dir_l <= n_dir; cnt <= n_cnt;
            jmppin <= n_jmppin; inbase <= n_inbase;
            active <= n_active; c_delay <= n_cdelay; c_wait <= n_cwait; c_pol <= n_cpol;
            c_pin <= n_cpin; c_next <= n_cnext;
        end
    end

    assign uo_out  = out_l[7:0];
    assign uio_out = out_l[15:8];
    assign uio_oe  = dir_l[15:8];
endmodule


module tt_um_example (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
    protocol_core core (
        .clk(clk), .rst_n(rst_n), .ui_in(ui_in), .uio_in(uio_in),
        .uo_out(uo_out), .uio_out(uio_out), .uio_oe(uio_oe)
    );
    wire _unused = &{ena, 1'b0};
endmodule

`default_nettype wire