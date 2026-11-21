#!/usr/bin/env python3
"""Random-program lockstep: run N random programs through tools/model.py and the RTL, compare every tick."""
import os, random, subprocess, sys
sys.path.insert(0, os.path.dirname(__file__))
from model import Core

def rnd_word(r):
    op = r.randrange(8)
    delay = r.choice([0, 0, 0, 1, 2, 3, 7])
    side = (1 << 9) | (r.randrange(2) << 8) if r.random() < 0.25 else 0
    if op == 0:   o = (r.randrange(4) << 6) | r.randrange(64)
    elif op == 1: o = (r.randrange(2) << 7) | (r.randrange(8) << 4) | r.randrange(16)
    elif op == 5: o = (r.randrange(8) << 5) | (r.randrange(4) << 3) | r.randrange(4)
    else:         o = (r.randrange(8) << 5) | r.randrange(32)
    return (op << 13) | (delay << 10) | side | o

def main(ncases, nt):
    fails = 0
    for seed in range(ncases):
        r = random.Random(seed)
        words = [rnd_word(r) for _ in range(64)]
        ui, uio = r.randrange(256), r.randrange(256) & 0xFE
        m = Core(); m.mem[:64] = words; m.ext_ui = ui; m.ext_uio = uio
        lines = []
        for _ in range(nt):
            m.step()
            lines.append(f"{m.pc:04x} {m.x:04x} {m.y:04x} {m.isr:04x} {m.osr:04x} {m.out:04x} {m.dir:04x}")
        open('/tmp/ls.hex', 'w').write('\n'.join(f'{w:04x}' for w in words + [1]) + '\n')
        open('/tmp/ls.trace', 'w').write('\n'.join(lines) + '\n')
        res = subprocess.run(['vvp', '/tmp/ls_sim', '+hex=/tmp/ls.hex', '+trace=/tmp/ls.trace',
                              f'+ui={ui}', f'+uio={uio}', f'+nt={nt}'], capture_output=True, text=True).stdout
        if 'PASS' not in res:
            fails += 1
            print(f'seed {seed}:', res.strip()[:600])
    print(f'{ncases - fails}/{ncases} random programs matched the model for {nt} ticks each')
    return fails

if __name__ == '__main__':
    sys.exit(1 if main(int(sys.argv[1]), int(sys.argv[2])) else 0)