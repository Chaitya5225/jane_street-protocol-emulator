#!/usr/bin/env python3
"""Protocol Emulator ISA v0.1 assembler.

Word format (16 bits):
  [15:13] opcode   [12:10] delay = extra ticks after the 1 execution tick
  [9]  side-en     [8] side-val   (drives uo[1] when side-en=1)
  [7:0]  operand

Opcodes:
  0 JMP   op[7:6]=cond (00 always, 01 x--, 10 pin high, 11 pin low), op[5:0]=addr
  1 WAIT  op[7]=level, op[3:0]=pin index (0-7 = ui, 8-15 = uio)
  2 SET   op[7:5]=dest (000 pins, 001 pindirs, 010 x, 011 y), op[4:0]=imm
  3 IN    op[7:5]=src (000 pins, 010 x, 011 y), op[4:0]=n
  4 OUT   op[7:5]=dest (000 pins, 001 pindirs, 010 x, 011 y), op[4:0]=n
  5 MOV   op[7:5]=dest (000 osr,001 isr,010 x,011 y), op[4:3]=mod (00 -,01 ~,10 rev),
          op[2:0]=src (000 isr,001 osr,010 x,011 y)
  6 CAP   op[7:5]=dest (000 osr, 010 x, 011 y): dest <- ticks since last CAP, reset
  7 CFG   op[7:5]=field (000 jmppin, 001 inbase), op[4:0]=value

Syntax:
  label:  mnemonic args            ; comment
  delay suffix  [n]      (0-7 extra ticks)
  side-set suffix  side 0|1
  directive  .div N      (writes N as word 64 = tick divider, loaded by the loader)

Usage:
  python3 tools/asm.py programs/uart_tx.txt
Writes programs/uart_tx.hex: a 65-word loader image, one 16-bit word per line.
  lines 0-63  = program memory (zero-padded past the last instruction)
  line  64    = tick divider byte (.div), the loader's config word
A stray word is 0x0000 = 'jmp 0', so a runaway program parks at address 0.
"""
import re
import sys
from pathlib import Path

MEM_WORDS = 64          # program memory: 64 x 16 bits
DIV_ADDR = 64           # loader word 64 = tick divider byte

OPC = {"jmp": 0, "wait": 1, "set": 2, "in": 3, "out": 4, "mov": 5, "cap": 6, "cfg": 7}
SETD = {"pins": 0, "pindirs": 1, "x": 2, "y": 3}
INSD = {"pins": 0, "x": 2, "y": 3}
OUTD = {"pins": 0, "pindirs": 1, "x": 2, "y": 3}
MOVD = {"osr": 0, "isr": 1, "x": 2, "y": 3}
MOVS = {"isr": 0, "osr": 1, "x": 2, "y": 3}
CAPD = {"osr": 0, "x": 2, "y": 3}
CFGF = {"jmppin": 0, "inbase": 1}


class AsmError(Exception):
    pass


def _strip(line):
    line = line.split(";", 1)[0].strip()
    return line


def _take_suffixes(line, lineno):
    """Extract side-set and delay suffixes; return (line, side_en, side_val, delay)."""
    side_en = side_val = 0
    delay = 0
    m = re.search(r"\bside\s+([01])\b", line)
    if m:
        side_en, side_val = 1, int(m.group(1))
        line = line[: m.start()] + line[m.end():]
    m = re.search(r"\[(\d+)\]\s*$", line)
    if m:
        delay = int(m.group(1))
        if delay > 7:
            raise AsmError(f"line {lineno}: delay {delay} exceeds 3-bit field (max 7)")
        line = line[: m.start()] + line[m.end():]
    return line.strip(), side_en, side_val, delay


def _target(label, labels, lineno):
    if label not in labels:
        raise AsmError(f"line {lineno}: unknown label '{label}'")
    addr = labels[label]
    if addr > 63:
        raise AsmError(f"line {lineno}: label '{label}' out of jump range")
    return addr


def _encode(mnem, rest, labels, lineno):
    if mnem == "jmp":
        cond = 0
        if rest.startswith("x--"):
            cond, target = 1, rest[len("x--"):].lstrip(" ,")
        elif rest.startswith("!pin"):
            cond, target = 3, rest[len("!pin"):].lstrip(" ,")
        elif rest.startswith("pin"):
            cond, target = 2, rest[len("pin"):].lstrip(" ,")
        else:
            target = rest
        addr = _target(target, labels, lineno)
        op = (cond << 6) | addr
    elif mnem == "wait":
        m = re.match(r"^([01])\s+pin\s+(\d+)$", rest)
        if not m:
            raise AsmError(f"line {lineno}: wait syntax is 'wait <0|1> pin <0-15>'")
        pol, idx = int(m.group(1)), int(m.group(2))
        if idx > 15:
            raise AsmError(f"line {lineno}: pin index {idx} out of range 0-15")
        op = (pol << 7) | idx
    elif mnem == "set":
        m = re.match(r"^(\w+)\s*,\s*(\d+)$", rest)
        if not m or m.group(1) not in SETD:
            raise AsmError(f"line {lineno}: set syntax is 'set <pins|pindirs|x|y>, <0-31>'")
        dest, imm = SETD[m.group(1)], int(m.group(2))
        if imm > 31:
            raise AsmError(f"line {lineno}: immediate {imm} exceeds 5-bit field")
        op = (dest << 5) | imm
    elif mnem == "in":
        if rest in ("x", "y"):
            op = (INSD[rest] << 5) | 0
        else:
            m = re.match(r"^pins\s*,\s*(\d+)$", rest)
            if not m:
                raise AsmError(f"line {lineno}: in syntax is 'in pins, <1-16>' or 'in x' / 'in y'")
            n = int(m.group(1))
            if not 1 <= n <= 16:
                raise AsmError(f"line {lineno}: shift count {n} must be 1-16")
            op = (0 << 5) | n
    elif mnem == "out":
        m = re.match(r"^(\w+)\s*,\s*(\d+)$", rest)
        if not m or m.group(1) not in OUTD:
            raise AsmError(f"line {lineno}: out syntax is 'out <pins|pindirs|x|y>, <n>'")
        dest, n = OUTD[m.group(1)], int(m.group(2))
        lim = 8 if dest in (2, 3) else 16
        if not 1 <= n <= lim:
            raise AsmError(f"line {lineno}: shift count {n} must be 1-{lim} for '{m.group(1)}'")
        op = (dest << 5) | n
    elif mnem == "mov":
        m = re.match(r"^(\w+)\s*,\s*(~|rev)?\s*(\w+)$", rest)
        if not m or m.group(1) not in MOVD or m.group(3) not in MOVS:
            raise AsmError(f"line {lineno}: mov syntax is 'mov <dest>, [~|rev]<src>' "
                           "dest/src in osr,isr,x,y")
        mod = {"": 0, "~": 1, "rev": 2}[m.group(2) or ""]
        op = (MOVD[m.group(1)] << 5) | (mod << 3) | MOVS[m.group(3)]
    elif mnem == "cap":
        if rest not in CAPD:
            raise AsmError(f"line {lineno}: cap syntax is 'cap <osr|x|y>'")
        op = CAPD[rest] << 5
    elif mnem == "cfg":
        m = re.match(r"^(\w+)\s*,\s*(\d+)$", rest)
        if not m or m.group(1) not in CFGF:
            raise AsmError(f"line {lineno}: cfg syntax is 'cfg <jmppin|inbase>, <0-15>'")
        field, val = CFGF[m.group(1)], int(m.group(2))
        if val > 15:
            raise AsmError(f"line {lineno}: cfg value {val} out of range 0-15")
        op = (field << 5) | val
    else:
        raise AsmError(f"line {lineno}: unknown mnemonic '{mnem}'")
    return op


def assemble(text):
    """Return (words, listing). words includes the DIV word if a .div directive exists."""
    labels = {}
    instrs = []          # (lineno, addr, source)
    div = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = _strip(raw)
        if not line:
            continue
        if line.startswith("."):
            m = re.match(r"^\.div\s+(\d+)$", line)
            if not m:
                raise AsmError(f"line {lineno}: unknown directive (only .div N is supported)")
            div = int(m.group(1))
            if div > 255:
                raise AsmError(f"line {lineno}: .div must be 0-255")
            continue
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if m:
            if m.group(1) in labels:
                raise AsmError(f"line {lineno}: duplicate label '{m.group(1)}'")
            labels[m.group(1)] = len(instrs)
            line = m.group(2).strip()
        if not line:
            continue
        instrs.append((lineno, len(instrs), line))

    if len(instrs) > 64:
        raise AsmError(f"program has {len(instrs)} instructions, memory is 64 words")

    words, listing = [], []
    for lineno, addr, line in instrs:
        line, side_en, side_val, delay = _take_suffixes(line, lineno)
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise AsmError(f"line {lineno}: missing operands for '{parts[0]}'")
        mnem, rest = parts[0].lower(), parts[1].strip()
        if mnem not in OPC:
            raise AsmError(f"line {lineno}: unknown mnemonic '{mnem}'")
        op = _encode(mnem, rest, labels, lineno)
        word = (OPC[mnem] << 13) | (delay << 10) | (side_en << 9) | (side_val << 8) | op
        words.append(word)
        listing.append(f"{addr:3d}: 0x{word:04X}  {line}" +
                       (f"  side {side_val}" if side_en else "") +
                       (f"  [{delay}]" if delay else ""))

    if div is not None:
        listing.append(f" 64: 0x{div:04X}  .div {div}   (tick divider, loaded as word 64)")

    # Emit the full 65-word loader image: addresses 0-63 = program (zero-padded),
    # address 64 = DIV config byte. The image is exactly what the host pushes
    # through the parallel load port, one word per address, low byte first.
    padded = words + [0] * (MEM_WORDS - len(words))
    image = padded + ([div] if div is not None else [])
    if len(image) < MEM_WORDS + 1:
        image += [0] * (MEM_WORDS + 1 - len(image))
    return padded, listing, image, div


def write_image(image, out):
    out.write_text("".join(f"{w:04X}\n" for w in image))


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 tools/asm.py programs/<name>.txt")
    src = Path(sys.argv[1])
    out = src.with_suffix(".hex")
    try:
        _, listing, image, div = assemble(src.read_text())
    except AsmError as e:
        raise SystemExit(f"asm: FAILED\n{e}")
    write_image(image, out)
    print("\n".join(listing))
    n_instr = len(listing) - (1 if div is not None else 0)
    tail = f", DIV={div} at word 64" if div is not None else ", no .div directive"
    print(f"\nwrote {out}: {len(image)}-word loader image "
          f"({n_instr} program words, zero-padded{tail})")


if __name__ == "__main__":
    main()