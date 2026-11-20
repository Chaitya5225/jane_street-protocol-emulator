#!/usr/bin/env python3
"""Tick-level functional model of the Protocol Emulator core, ISA v0.1.

Mirrors the RTL one-for-one so timing bugs are found on paper, before Verilog:
  - every instruction takes 1 + delay ticks (WAIT may stall longer)
  - side-set drives uo[1] on every tick of the instruction when enabled
  - the tick divider (word 64, 8-bit DIV) is loaded with the program

This model steps in TICKS, not chip clocks; DIV enters through the baud-rate
report. Clock-exact behaviour is verified later in cocotb against the RTL.

Usage:
  python3 tools/asm.py programs/uart_tx.txt      # first: assemble
  python3 tools/model.py programs/uart_tx.hex    # then: run + UART monitor check
"""
import sys
from pathlib import Path

CLK_HZ = 50_000_000
MEM_WORDS = 64          # program memory: 64 x 16 bits
DIV_ADDR = 64           # loader word 64 = tick divider byte


class Core:
    def __init__(self):
        self.mem = [0] * (MEM_WORDS + 1)
        self.pc = 0
        self.x = self.y = 0
        self.isr = self.osr = 0
        self.out = 0        # 16-bit output latch: pins 0-7 = uo, 8-15 = uio
        self.dir = 0        # pindirs: bits 8-15 = uio direction (1 = drive)
        self.div = 54
        self.jmppin = 0
        self.inbase = 0
        # external pin state (host side of the demo board)
        self.ext_ui = 0
        self.ext_uio = 0x04     # strobe (uio[2]) idle high; LOAD_EN (uio[0]) low
        # runtime
        self.cur = None
        self.tick = 0
        self.since_cap = 0
        self.tx_log = [(0, 0)]

    # ---- pins -------------------------------------------------------------
    def _pin(self, n):
        """Level of pin n (0-7 = ui, 8-15 = uio). uio reads own drive when dir=1."""
        if n < 8:
            return (self.ext_ui >> n) & 1
        if (self.dir >> n) & 1:
            return (self.out >> n) & 1
        return (self.ext_uio >> (n - 8)) & 1

    def _tx(self):
        return self.out & 1      # TX = uo[0]

    # ---- one instruction --------------------------------------------------
    def _start(self, w):
        op = (w >> 13) & 7
        delay = (w >> 10) & 7
        if (w >> 9) & 1:                       # side-set on uo[1]
            self.out = (self.out & ~0x2) | (((w >> 8) & 1) << 1)
        o = w & 0xFF
        c = {"op": op, "delay": delay, "waiting": False, "next": self.pc + 1}
        if op == 0:                            # JMP
            cond, addr = (o >> 6) & 3, o & 0x3F
            take = cond == 0
            if cond == 1:                      # x--: jump while X != 0
                if self.x != 0:
                    self.x = (self.x - 1) & 0xFF
                    take = True
            elif cond in (2, 3):               # jump-pin high / low
                lvl = self._pin(self.jmppin)
                take = lvl == (1 if cond == 2 else 0)
            c["next"] = addr if take else self.pc + 1
        elif op == 1:                          # WAIT
            c["waiting"] = True
            c["pol"] = (o >> 7) & 1
            c["pin"] = o & 0xF
        elif op == 2:                          # SET
            dest, imm = (o >> 5) & 7, o & 0x1F
            if dest == 0:
                self.out = (self.out & ~0x1F) | imm      # pins 0-4 only
            elif dest == 1:
                self.dir = (self.dir & ~0x1F) | imm
            elif dest == 2:
                self.x = imm & 0xFF
            else:
                self.y = imm & 0xFF
        elif op == 3:                          # IN
            src, n = (o >> 5) & 7, o & 0x1F
            if src == 0:
                field = 0
                for i in range(n):
                    field |= self._pin(self.inbase + i) << i
                self.isr = ((self.isr << n) | field) & 0xFFFF
            elif src == 2:
                self.isr = self.x
            elif src == 3:
                self.isr = self.y
        elif op == 4:                          # OUT
            dest, n = (o >> 5) & 7, o & 0x1F
            mask = (1 << n) - 1
            if dest == 0:
                self.out = (self.out & ~mask) | (self.osr & mask)
            elif dest == 1:
                self.dir = (self.dir & ~mask) | (self.osr & mask)
            elif dest == 2:
                self.x = self.osr & 0xFF
            else:
                self.y = self.osr & 0xFF
            self.osr = (self.osr >> n) & 0xFFFF
        elif op == 5:                          # MOV
            dest, mod, src = (o >> 5) & 7, (o >> 3) & 3, o & 7
            val = (self.isr, self.osr, self.x, self.y)[src]
            if mod == 1:
                val = ~val & 0xFFFF
            elif mod == 2:
                val = int(f"{val:016b}"[::-1], 2)
            if dest == 0:
                self.osr = val
            elif dest == 1:
                self.isr = val
            elif dest == 2:
                self.x = val & 0xFF
            else:
                self.y = val & 0xFF
        elif op == 6:                          # CAP
            dest = (o >> 5) & 7
            if dest == 0:
                self.osr = self.since_cap
            elif dest == 2:
                self.x = self.since_cap & 0xFF
            elif dest == 3:
                self.y = self.since_cap & 0xFF
            self.since_cap = 0
        elif op == 7:                          # CFG
            field, val = (o >> 5) & 7, o & 0x1F
            if field == 0:
                self.jmppin = val
            elif field == 1:
                self.inbase = val
        self.cur = c

    # ---- one tick ---------------------------------------------------------
    def step(self):
        self.tick += 1
        self.since_cap = (self.since_cap + 1) & 0xFFFF
        old = self._tx()
        if self.cur is None:
            self._start(self.mem[self.pc])
        c = self.cur
        if c["waiting"] and self._pin(c["pin"]) == c["pol"]:
            c["waiting"] = False
        if not c["waiting"]:
            if c["delay"] > 0:
                c["delay"] -= 1
            else:
                self.pc = c["next"] & 0x3F
                self.cur = None
        new = self._tx()
        if new != old:
            self.tx_log.append((self.tick, new))

    def run(self, ticks, events=()):
        """Run for `ticks` ticks; events = [(tick, fn), ...] applied before stepping."""
        ev = sorted(events)
        i = 0
        for t in range(1, ticks + 1):
            while i < len(ev) and ev[i][0] <= t:
                ev[i][1]()
                i += 1
            self.step()


# ---- software UART monitor (mirrors tb/uart_rx_monitor.v, CPB = 8) ---------
def uart_monitor_decode(tx_log, nframes):
    """Decode up to nframes bytes from the TX transition log.

    Mirrors the Verilog monitor's behaviour: after locking onto a start-bit
    falling edge it stays busy for the whole 80-tick frame (10 bits), so
    1->0 transitions inside the data bits are ignored.
    """
    edges = tx_log[:]
    frames = []
    busy_until = -1
    for idx in range(1, len(edges)):
        lvl_prev, lvl = edges[idx - 1][1], edges[idx][1]
        te = edges[idx][0]
        if lvl_prev == 1 and lvl == 0 and te >= busy_until:   # start bit edge
            bits = []
            for k in range(8):
                bits.append(_level_at(edges, te + 12 + 8 * k))   # centre of data bit k
            stop = _level_at(edges, te + 76)                     # centre of stop bit
            byte = sum(b << k for k, b in enumerate(bits))
            frames.append({"te": te, "byte": byte, "stop": stop, "bits": bits})
            busy_until = te + 80                                 # whole frame consumed
            if len(frames) == nframes:
                break
    return frames


def _level_at(edges, t):
    lvl = 0
    for tick, l in edges:
        if tick <= t:
            lvl = l
        else:
            break
    return lvl


# ---- test: assemble-time program x software UART ---------------------------
def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 tools/model.py programs/<name>.hex")
    hexf = Path(sys.argv[1])
    words = [int(l, 16) for l in hexf.read_text().split()]
    if len(words) < DIV_ADDR + 1:
        raise SystemExit(f"{hexf}: expected a {DIV_ADDR + 1}-word loader image "
                         f"(run tools/asm.py first), got {len(words)}")
    core = Core()
    core.mem[:MEM_WORDS] = words[:MEM_WORDS]
    core.div = words[DIV_ADDR] & 0xFF

    eff = core.div if core.div > 0 else 1        # DIV = 0 means one tick per clock
    tick_hz = CLK_HZ / eff
    baud = tick_hz / 8
    err = (baud - 115200) / 115200 * 100
    print(f"loaded {MEM_WORDS}-word image, DIV={core.div}")
    print(f"tick = {eff} clocks = {eff / CLK_HZ * 1e9:.0f} ns | "
          f"8 ticks/bit -> {baud:.0f} baud (target 115200, {err:+.2f}%)")

    # host: for each byte, drive data on ui[7:0], pulse the strobe on pin 10
    expected = [0xA5, 0x00, 0xFF, 0x3C]
    events, t = [], 5
    for b in expected:
        events.append((t, lambda b=b: setattr(core, "ext_ui", b)))
        events.append((t + 3, lambda: setattr(core, "ext_uio", core.ext_uio & ~0x04)))
        events.append((t + 8, lambda: setattr(core, "ext_uio", core.ext_uio | 0x04)))
        t += 100
    core.run(430, events)

    frames = uart_monitor_decode(core.tx_log, len(expected))
    ok = True
    for i, exp in enumerate(expected):
        if i < len(frames):
            f = frames[i]
            good = f["byte"] == exp and f["stop"] == 1
            ok &= good
            print(f"byte {i}: got 0x{f['byte']:02X} expected 0x{exp:02X} "
                  f"stop={f['stop']} start@tick {f['te']}  {'ok' if good else 'FAIL'}")
        else:
            ok = False
            print(f"byte {i}: MISSING (monitor saw {len(frames)} frames)")

    if len(core.tx_log) > 2:
        print(f"tx edges: {len(core.tx_log) - 1}, "
              f"tx busy ticks {core.tx_log[1][0]}..{core.tx_log[-1][0]}")
    if ok:
        print(f"PASS: {len(expected)} bytes decoded, 8 ticks per bit, "
              f"80-tick frames verified")
    else:
        print("FAIL: decode mismatch -- do not start RTL until this passes")
        sys.exit(1)


if __name__ == "__main__":
    main()