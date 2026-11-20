Protocol Emulator ISA v0.1 — FROZEN 2026-11-21
A 16-bit, tick-deterministic instruction set for a pin-timing core. The protocol
lives in the program, not in the silicon. Anything below is binding for RTL v0.1;
changes go through the assembler, this document, and the tick model together.

Word format
text
[15:13] opcode      8 opcodes
[12:10] delay       extra ticks after the 1 execution tick (0-7)
[9]     side-en     1 = drive side-val on uo[1] for every tick of this instruction
[8]     side-val    value driven on uo[1] when side-en = 1
[7:0]   operand     meaning depends on opcode
Timing rule
Every instruction takes exactly 1 + delay ticks. WAIT takes 1 + delay or
longer (it stalls until the pin matches). Pin effects land on the instruction's
first tick; side-set applies on every tick of the instruction. One tick =
DIV chip clocks (8-bit divider, word 64 of the loader image; DIV=0 means one
tick per clock). At 50 MHz with DIV=54, 8 ticks/bit = 115740 baud (+0.47% vs 115200).

Opcodes
Op
Mnemonic
Operand
Action
000	JMP	cond[7:6], addr[5:0]	cond: 00 always, 01 while X!=0 (decrement X, jump), 10 jump-pin high, 11 jump-pin low. X=0: no jump, no decrement.
001	WAIT	pol[7], 0[6:4], pin[3:0]	Stall until pin pin (0-15) reads pol. Checked once per tick.
010	SET	dest[7:5], imm[4:0]	dest: 000 pins (drives pins 0-4), 001 pindirs (pins 0-4), 010 X, 011 Y.
011	IN	src[7:5], n[4:0]	Shift into ISR (left, LSB enters first). src: 000 pins (n bits from inbase), 010 X, 011 Y (full copy, n ignored).
100	OUT	dest[7:5], n[4:0]	Shift n bits out of OSR (LSB first). dest: 000 pins, 001 pindirs, 010 X, 011 Y (X/Y: n<=8, field copy).
101	MOV	dest[7:5], mod[4:3], src[2:0]	dest: 000 OSR, 001 ISR, 010 X, 011 Y. mod: 00 none, 01 invert, 10 bit-reverse. src: 000 ISR, 001 OSR, 010 X, 011 Y.
110	CAP	dest[7:5]	dest <- ticks since last CAP, then reset the counter. dest: 000 OSR, 010 X, 011 Y.
111	CFG	field[7:5], value[4:0]	field: 000 jmppin (0-15), 001 inbase (0-15).

Architectural state
Register
Width
Reset
Notes
PC	6	0	64 x 16 program memory; wraps 63 -> 0
X, Y	8	undef	must be initialised with SET after reset (ASIC flops do not start at 0)
ISR, OSR	16	undef	explicit IN/OUT only; no auto-push/pull in v0.1
OUT latch	16	0	pins 0-7 = uo (always driven), 8-15 = uio (visible only where pindir = 1)
pindirs	16	0	bits 8-15 = uio direction (1 = drive, 0 = release/high-Z); open-drain is done by releasing on 1 and driving on 0
DIV	8	54	loaded as word 64 by the loader
jmppin, inbase	5	0	set with CFG

Pin map
text
pins 0-7   = ui[7:0]    core input only (host data port at runtime)
pins 8-15  = uio[7:0]   bidirectional, pindir-controlled
uo[0]      = TX / MOSI (first OUT/SET pin target)
uo[1]      = SCK / SCL  (side-set target)
Loader (parallel, frozen)
The RP2350 host drives the load port before every run:

Signal
Pin
Role
LOAD_EN	uio[0]	high = loading: PC held in reset, write pointer = 0
WR	uio[1]	one rising edge per byte; low byte first, then high byte latches one 16-bit word and advances the pointer
data	ui[7:0]	byte written at the current pointer

Addresses 0-63 = program words, address 64 = {8'h00, DIV}. LOAD_EN falling
starts the core at PC=0. The image format is exactly programs/*.hex (65 lines).
A deselected design loses state, so the program is reloaded on every selection.

v0.1 deltas from the 2026-11-18 chat draft
Side-set is enable + value on uo[1] (not unconditional 2-bit drive).
Program memory frozen at 64 x 16 to match the 6-bit JMP address (the 128-word
sketch would have made half of it unreachable).
Open-drain I2C needs no special mode: pindirs release/drive does it.
CAP measures ticks since the last CAP (pin-edge capture is deferred to v0.2).
jmp x-- at X=0 does not decrement (no PIO-style wrap).
Verification status
Encoding table: assembler tools/asm.py is the single source of truth.
Behaviour + timing: tick model tools/model.py; UART TX program verified
(4 bytes, every TX edge on the exact 8-tick lattice, 115741 baud, +0.47%).
Next: RTL implements this spec; cocotb runs the same hex image and the same
monitor (tb/uart_rx_monitor.v) against the RTL.