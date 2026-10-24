"""Static checks for a BASIC 65 listing meant for IMPORT.

Checks: line format and ascending numbers, line length, characters that are identical in
ASCII and PETSCII, and variable names (no keyword inside a name, no reserved variable
assigned). Usage: python3 lint_basic.py LISTING.bas
"""
import re
import sys

KEYWORDS = """ABS AND APPEND ASC ATN AUTO BACKGROUND BACKUP BANK BEGIN BEND BLOAD BOOT BORDER BOX BSAVE
BUMP BVERIFY CATALOG CHANGE CHAR CHDIR CHR$ CIRCLE CLOSE CLR CMD COLLECT COLLISION COLOR CONCAT
CONT COPY COS CURSOR CUT DATA DCLEAR DCLOSE DEC DEF DELETE DIM DIR DISK DLOAD DMA DMODE DO DOPEN
DPAT DSAVE DVERIFY EDIT EDMA ELLIPSE ELSE END ENVELOPE ERASE ERR$ EXIT EXP FAST FILTER FIND FN FOR
FOREGROUND FRE GCOPY GET GETKEY GO GOSUB GOTO GRAPHIC HEADER HELP HEX$ HIGHLIGHT IF IMPORT INFO INPUT
INSTR INT JOY KEY LEFT$ LEN LET LINE LIST LOAD LOCATE LOG LOOP LPEN MEM MERGE MID$ MKDIR MOD MONITOR
MOUNT MOUSE MOVSPR NEW NEXT NOT OFF ON OPEN OR PAINT PALETTE PASTE PEEK PEN PIXEL PLAY POINTER POKE
POLYGON POS POT PRINT RCOLOR READ RECORD REM RENAME RENUMBER RESTORE RESUME RETURN RGRAPHIC RIGHT$
RMOUSE RND RPALETTE RPEN RPLAY RREG RSPCOLOR RSPPOS RSPRITE RUN RWINDOW SAVE SCNCLR SCRATCH SCREEN
SET SETBIT SGN SIN SLEEP SOUND SPC SPEED SPRCOLOR SPRITE SPRSAV SQR STEP STOP STR$ STRBIN$ SYS TAB
TAN TEMPO THEN TO TRAP TROFF TRON TYPE UNTIL USING USR VAL VERIFY VIEWPORT VOL WAIT WHILE WINDOW
WPEEK WPOKE XOR""".split()
RESERVED = {'ST', 'TI', 'DS', 'ER', 'EL'}
ALLOWED = set(" !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^")  # ^ is PETSCII 94, the power operator


def lint(path):
    problems, names = [], set()
    prev = -1
    lines = open(path).read().splitlines()
    for ln in lines:
        m = re.match(r'^(\d+) (.*)$', ln)
        if not m:
            problems.append(f"bad line format: {ln!r}")
            continue
        n, body = int(m.group(1)), m.group(2)
        if n <= prev:
            problems.append(f"{n}: line number not ascending")
        prev = n
        if len(ln) > 80:
            problems.append(f"{n}: {len(ln)} characters")
        bad = sorted({c for c in ln if c not in ALLOWED})
        if bad:
            problems.append(f"{n}: characters {bad}")
        if body.startswith(('REM', 'DATA')):
            continue
        code = re.sub(r'"[^"]*"', '""', body)
        code = re.sub(r'\$[0-9A-F]+', '0', code)
        code = code.split('REM', 1)[0]
        for w in re.findall(r'[A-Z][A-Z0-9]*\$?', code):
            if w in KEYWORDS:
                continue
            hits = [k for k in KEYWORDS if k in w]
            if hits:
                problems.append(f"{n}: name {w} contains keyword {hits}")
            names.add(w)
        for w in re.findall(r'(?:^|:)\s*([A-Z][A-Z0-9]*)\s*=', code):
            if w[:2] in RESERVED:
                problems.append(f"{n}: assigns reserved variable {w}")
    short = {}
    for w in names:
        key = w.rstrip('$')[:2] + ('$' if w.endswith('$') else '')
        short.setdefault(key, set()).add(w)
    clashes = {k: v for k, v in short.items() if len(v) > 1}
    for k, v in clashes.items():
        problems.append(f"names {sorted(v)} share their first two characters")
    return len(lines), max(len(l) for l in lines), sorted(names), problems


if __name__ == '__main__':
    count, longest, names, problems = lint(sys.argv[1])
    print(f"lines {count}, longest {longest}")
    print("names:", ' '.join(names))
    print("problems:", problems or "none")
    sys.exit(1 if problems else 0)
