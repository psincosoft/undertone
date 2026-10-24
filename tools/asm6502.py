"""Two-pass driver around the py65 assembler for the small 6502 dialect used in this project.

Syntax: 'label:' lines, 'NAME = $1234' equates, '* = $1800' origin, '.byte a,b,...',
one instruction per line, ';' comments. Symbols are replaced by their values before each
instruction is handed to py65's assembler, so only plain NMOS 6502 opcodes are produced.
Usage: python3 asm6502.py SOURCE.asm OUT.bin [LISTING.txt]
"""
import re
import sys

from py65.assembler import Assembler
from py65.devices.mpu6502 import MPU

BRANCHES = {'BCC', 'BCS', 'BEQ', 'BMI', 'BNE', 'BPL', 'BVC', 'BVS'}
SYM = re.compile(r'(?<![$\w])([A-Za-z_][A-Za-z0-9_]*)')


def parse_num(tok):
    tok = tok.strip()
    if tok.startswith('$'):
        return int(tok[1:], 16)
    if tok.startswith('%'):
        return int(tok[1:], 2)
    return int(tok)


def read_lines(path):
    for n, raw in enumerate(open(path), 1):
        line = raw.split(';', 1)[0].rstrip()
        if line.strip():
            yield n, line


def assemble(path):
    asm = Assembler(MPU())
    equ, labels = {}, {}
    for npass in (1, 2):
        pc, out, origin, listing = None, bytearray(), None, []
        for n, line in read_lines(path):
            s = line.strip()
            m = re.match(r'^\*\s*=\s*(\S+)$', s)
            if m:
                pc = origin = parse_num(m.group(1))
                continue
            m = re.match(r'^([A-Za-z_]\w*)\s*=\s*(\S+)$', s)
            if m:
                equ[m.group(1)] = parse_num(m.group(2))
                continue
            m = re.match(r'^([A-Za-z_]\w*):\s*(.*)$', s)
            if m:
                if npass == 1:
                    if m.group(1) in labels or m.group(1) in equ:
                        sys.exit(f"line {n}: duplicate symbol {m.group(1)}")
                    labels[m.group(1)] = pc
                elif labels[m.group(1)] != pc:
                    sys.exit(f"line {n}: label {m.group(1)} moved between passes")
                s = m.group(2).strip()
                if not s:
                    continue
            if s.lower().startswith('.byte'):
                data = bytes(parse_num(t) for t in s[5:].split(','))
                listing.append((pc, data, s))
                out += data
                pc += len(data)
                continue
            mnem = s.split()[0].upper()

            def value(match):
                name = match.group(1)
                if name.upper() in ('A', 'X', 'Y'):
                    return name
                if name in equ:
                    return f"${equ[name]:04X}"
                if name in labels:
                    return f"${labels[name]:04X}"
                if npass == 1:  # forward reference: any address that keeps the size right
                    return f"${pc:04X}" if mnem in BRANCHES else "$1800"
                sys.exit(f"line {n}: unknown symbol {name}")

            parts = s.split(None, 1)
            stmt = parts[0] + (' ' + SYM.sub(value, parts[1]) if len(parts) > 1 else '')
            code = asm.assemble(stmt, pc)
            if not code:
                sys.exit(f"line {n}: cannot assemble '{stmt}'")
            listing.append((pc, bytes(code), s))
            out += bytes(code)
            pc += len(code)
    return origin, bytes(out), listing, labels, equ


def main():
    src, binpath = sys.argv[1], sys.argv[2]
    origin, code, listing, labels, equ = assemble(src)
    open(binpath, 'wb').write(code)
    if len(sys.argv) > 3:
        with open(sys.argv[3], 'w') as f:
            for pc, data, text in listing:
                f.write(f"{pc:04X}  {' '.join(f'{b:02X}' for b in data):<9}  {text}\n")
    print(f"{binpath}: ${origin:04X}-${origin + len(code) - 1:04X}, {len(code)} bytes")


if __name__ == '__main__':
    main()
