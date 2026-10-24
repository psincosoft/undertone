"""bas65sim: run a BASIC 65 listing headlessly, for tests.

Not an emulator of the MEGA65 or of the BASIC 65 ROM. It interprets the subset of BASIC 65 the
UNDERTONE listings use, with the ROM's documented semantics as far as we know them, against a
model machine: a clock (each statement costs a fixed time; the frame counter $D7FA follows it),
a scripted keyboard and joystick, the text screen with T@& and C@&, four palette banks through
$D070, the SIDs, the audio mixer registers, the character set buffer at $FF7E000 and RAM.
The tokenizer finds keywords the way the ROM does, anywhere outside strings, so a keyword hidden
in a name is caught. Screens render to PNG with an approximate character set (c64font.py).

What it cannot tell: the real speed of BASIC 65, ROM quirks, anything about the VIC-IV, the SIDs
or the mixer beyond the register values written.
"""
import math
import random
import re
from pathlib import Path

from c64font import UPPER, LOWER

KEYWORDS = sorted(set("""ABS AND APPEND ASC ATN AUTO BACKGROUND BACKUP BANK BEGIN BEND BLOAD BOOT
BORDER BOX BSAVE BUMP BVERIFY CATALOG CHANGE CHAR CHDIR CHR$ CIRCLE CLOSE CLR CMD COLLECT COLLISION
COLOR CONCAT CONT COPY COS CURSOR CUT DATA DCLEAR DCLOSE DEC DEF DELETE DIM DIR DISK DLOAD DMA DMODE
DO DOPEN DPAT DSAVE DVERIFY EDIT EDMA ELLIPSE ELSE END ENVELOPE ERASE ERR$ EXIT EXP FAST FILTER FIND
FN FOR FOREGROUND FRE GCOPY GET GETKEY GO GOSUB GOTO GRAPHIC HEADER HELP HEX$ HIGHLIGHT IF IMPORT
INFO INPUT INSTR INT JOY KEY LEFT$ LEN LET LINE LIST LOAD LOCATE LOG LOOP LPEN MEM MERGE MID$ MKDIR
MOD MONITOR MOUNT MOUSE MOVSPR NEW NEXT NOT OFF ON OPEN OR PAINT PALETTE PASTE PEEK PEN PIXEL PLAY
POINTER POKE POLYGON POS POT PRINT RCOLOR READ RECORD REM RENAME RENUMBER RESTORE RESUME RETURN
RGRAPHIC RIGHT$ RMOUSE RND RPALETTE RPEN RPLAY RREG RSPCOLOR RSPPOS RSPRITE RUN RWINDOW SAVE SCNCLR
SCRATCH SCREEN SET SETBIT SGN SIN SLEEP SOUND SPC SPEED SPRCOLOR SPRITE SPRSAV SQR STEP STOP STR$
STRBIN$ SYS TAB TAN TEMPO THEN TO TRAP TROFF TRON TYPE UNTIL USING USR VAL VERIFY VIEWPORT VOL WAIT
WHILE WINDOW WPEEK WPOKE XOR""".split()), key=len, reverse=True)
ERRORS = {10: "NEXT WITHOUT FOR", 11: "SYNTAX", 12: "RETURN WITHOUT GOSUB", 13: "OUT OF DATA",
          14: "ILLEGAL QUANTITY", 15: "OVERFLOW", 17: "UNDEF'D STATEMENT", 18: "BAD SUBSCRIPT",
          19: "REDIM'D ARRAY", 20: "DIVISION BY ZERO", 22: "TYPE MISMATCH", 23: "STRING TOO LONG",
          30: "BREAK", 99: "NOT SIMULATED"}
FRAME_US = 20000
COLOUR_CODES = {144: 0, 5: 1, 28: 2, 159: 3, 156: 4, 30: 5, 31: 6, 158: 7, 129: 8, 149: 9, 150: 10,
                151: 11, 152: 12, 153: 13, 154: 14, 155: 15}
SYSTEM_PALETTE = [(0, 0, 0), (15, 15, 15), (15, 0, 0), (0, 15, 15), (15, 0, 15), (0, 15, 0), (0, 0, 15),
                  (15, 15, 0), (15, 6, 0), (10, 4, 0), (15, 7, 7), (5, 5, 5), (8, 8, 8), (9, 15, 9),
                  (9, 9, 15), (11, 11, 11)]


class BasicError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{ERRORS.get(code, code)} {detail}".strip())
        self.code = code


class Stop(Exception):
    pass


def swap(v):
    return ((v & 15) << 4) | (v >> 4)


# ---------------------------------------------------------------- tokens
def tokenize(text):
    toks, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == ' ':
            i += 1
            continue
        if ch == '"':
            j = text.find('"', i + 1)
            j = n if j < 0 else j
            toks.append(('str', text[i + 1:j]))
            i = j + 1
            continue
        if ch.isdigit() or (ch == '.' and i + 1 < n and text[i + 1].isdigit()):
            m = re.match(r'\d*\.?\d*(E[+-]?\d+)?', text[i:])
            toks.append(('num', float(m.group(0))))
            i += m.end()
            continue
        if ch == '$' and i + 1 < n and text[i + 1] in '0123456789ABCDEF':
            m = re.match(r'[0-9A-F]+', text[i + 1:])
            for k in KEYWORDS:
                if k in m.group(0):
                    raise ValueError(f"hex constant ${m.group(0)} contains keyword {k}")
            toks.append(('num', float(int(m.group(0), 16))))
            i += 1 + m.end()
            continue
        if ch.isalpha():
            kw = next((k for k in KEYWORDS if text.startswith(k, i)), None)
            if kw:
                toks.append(('kw', kw))
                i += len(kw)
                if kw in ('REM', 'DATA'):
                    toks.append(('raw', text[i:]))
                    break
                continue
            j = i + 1
            while j < n and text[j].isalnum() and not any(text.startswith(k, j) for k in KEYWORDS):
                j += 1
            name = text[i:j]
            if j < n and text[j] in '$%':
                name += text[j]
                j += 1
            if name in ('T', 'C') and text.startswith('@&', j):
                name += '@&'
                j += 2
            toks.append(('id', name))
            i = j
            continue
        if text.startswith(('<=', '>=', '<>', '=<', '=>', '><'), i):
            op = text[i:i + 2]
            toks.append(('op', {'=<': '<=', '=>': '>=', '><': '<>'}.get(op, op)))
            i += 2
            continue
        if ch == '^':
            toks.append(('op', '^'))
            i += 1
            continue
        toks.append(('op', ch))
        i += 1
    toks.append(('eol', None))
    return toks


def basic_name(name):
    """BASIC keeps only the first two characters of a name, plus its type."""
    if name.endswith('@&'):
        return name
    suffix = name[-1] if name[-1] in '$%' else ''
    base = name.rstrip('$%')
    return base[:2] + suffix


def fmt_num(v):
    if v == int(v) and abs(v) < 1e9:
        s = str(int(v))
    else:
        s = '%.9G' % v
        if 'E' not in s and '.' in s:
            s = s.rstrip('0').rstrip('.')
        if s.startswith('0.'):
            s = s[1:]
        elif s.startswith('-0.'):
            s = '-' + s[2:]
    return s if s.startswith('-') else ' ' + s


# ---------------------------------------------------------------- the machine
class Machine:
    def __init__(self, d070=0x00, pal_ntsc=False, width=80, height=25, seed=1):
        self.mem = {}
        self.time = 0                       # microseconds
        self.d070 = d070
        self.d020, self.d021 = 6, 6
        self.d06f = 0x80 if pal_ntsc else 0x00
        self.pal = [[[((b * 64 + c * 32 + e) * 37 + 11) & 255 for e in range(256)] for c in range(3)]
                    for b in range(4)]
        tb = (d070 >> 4) & 3
        for e, rgb in enumerate(SYSTEM_PALETTE):
            for c in range(3):
                self.pal[tb][c][e] = swap(rgb[c] * 17)
        self.pal_start = [[list(ch) for ch in bank] for bank in self.pal]
        self.mixer = [(i * 13 + 7) & 255 for i in range(256)]
        self.mixer_start = list(self.mixer)
        self.mix_sel = 0
        self.sid = [0] * 128
        self.sid_log = []
        self.chars = [0] * 4096
        for c in range(256):
            for r in range(8):
                self.chars[c * 8 + r] = UPPER[c][r]
                self.chars[2048 + c * 8 + r] = LOWER[c][r]
        self.chars_start = list(self.chars)
        self.cols, self.rows = width, height
        self.mode_start = (width, height)
        self.lowercase = False
        self.case_lock = False
        self.pen = 1
        self.reverse = False
        self.cx = self.cy = 0
        self.clear_screen()
        self.scrolls = 0
        self.esc = False
        self.keyq = []
        self.events = []
        self.shots = []
        self.fire_until = -1
        self.sound_clr = 0
        self.rng = random.Random(seed)
        self.sys_hook = None
        self.log = []

    # ---- time
    def frame(self):
        return self.time // FRAME_US

    # ---- screen
    def clear_screen(self):
        self.text = [[32] * self.cols for _ in range(self.rows)]
        self.colr = [[self.pen] * self.cols for _ in range(self.rows)]
        self.cx = self.cy = 0

    def set_mode(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.clear_screen()

    def put(self, ch):
        if self.esc:
            self.esc = False
            c = chr(ch)
            if c == '4':
                self.set_mode(40, 25)
            elif c == '8':
                self.set_mode(80, 25)
            elif c == '5':
                self.set_mode(80, 50)
            elif c == 'X':
                self.set_mode(40 if self.cols == 80 else 80, 25)
            return
        if ch == 27:
            self.esc = True
        elif ch == 13:
            self.cx = 0
            self.reverse = False
            self.down()
        elif ch == 147:
            self.clear_screen()
        elif ch == 19:
            self.cx = self.cy = 0
        elif ch == 14:
            self.lowercase = True
        elif ch == 142:
            self.lowercase = False
        elif ch in (11, 12):
            self.case_lock = ch == 11
        elif ch == 18:
            self.reverse = True
        elif ch == 146:
            self.reverse = False
        elif ch in COLOUR_CODES:
            self.pen = COLOUR_CODES[ch]
        elif ch == 17:
            self.down()
        elif ch == 145:
            self.cy = max(0, self.cy - 1)
        elif ch == 29:
            self.advance()
        elif ch == 157:
            self.cx = max(0, self.cx - 1)
        elif 32 <= ch <= 127 or 160 <= ch <= 255:
            if ch < 64:
                code = ch
            elif ch < 96:
                code = ch - 64
            elif ch < 128:
                code = ch - 32
            elif ch < 192:
                code = ch - 64
            elif ch < 255:
                code = ch - 128
            else:
                code = 94
            if self.reverse:
                code ^= 128
            self.text[self.cy][self.cx] = code
            self.colr[self.cy][self.cx] = self.pen
            self.advance()

    def advance(self):
        self.cx += 1
        if self.cx >= self.cols:
            self.cx = 0
            self.down()

    def down(self):
        self.cy += 1
        if self.cy >= self.rows:
            self.scrolls += 1
            self.text = self.text[1:] + [[32] * self.cols]
            self.colr = self.colr[1:] + [[self.pen] * self.cols]
            self.cy = self.rows - 1

    def row_text(self, y):
        out = []
        for code in self.text[y]:
            c = code & 127
            if 1 <= c <= 26:
                out.append(chr(c + (96 if self.lowercase else 64)))
            elif 32 <= c <= 63:
                out.append(chr(c))
            elif c == 0:
                out.append('@')
            else:
                out.append('#')
        return ''.join(out)

    def screen_text(self):
        return '\n'.join(self.row_text(y) for y in range(self.rows))

    # ---- memory and I/O
    def peek(self, a):
        a = int(a)
        if a < 0 or a > 0xFFFFFFF:
            raise BasicError(14, f"PEEK({a})")
        if 0xFFD3000 <= a <= 0xFFD3FFF:
            r = a - 0xFFD3000
            if r == 0x020:
                return self.d020
            if r == 0x021:
                return self.d021
            if r == 0x06F:
                return self.d06f
            if r == 0x070:
                return self.d070
            if 0x100 <= r <= 0x3FF:
                return self.pal[self.d070 >> 6][(r >> 8) - 1][r & 255]
            if 0x400 <= r <= 0x47F:
                return 0
            if r == 0x6F5:
                return self.mixer[self.mix_sel]
            if r == 0x7FA:
                return self.frame() & 255
            raise BasicError(99, f"PEEK ${a:07X}")
        if 0xFF7E000 <= a <= 0xFF7EFFF:
            return self.chars[a - 0xFF7E000]
        if a < 0x10000 and not (0x1800 <= a <= 0x1FFF):
            raise BasicError(99, f"PEEK ${a:04X}")
        return self.mem.get(a, 0)

    def poke(self, a, v):
        a, v = int(a), int(v)
        if not 0 <= v <= 255:
            raise BasicError(14, f"POKE {a},{v}")
        if 0xFFD3000 <= a <= 0xFFD3FFF:
            r = a - 0xFFD3000
            if r == 0x020:
                self.d020 = v
            elif r == 0x021:
                self.d021 = v
            elif r == 0x070:
                self.d070 = v
            elif 0x100 <= r <= 0x3FF:
                self.pal[self.d070 >> 6][(r >> 8) - 1][r & 255] = v
            elif 0x400 <= r <= 0x47F:
                self.sid[r - 0x400] = v
                self.sid_log.append((self.time, r - 0x400, v))
            elif r == 0x6F4:
                self.mix_sel = v
            elif r == 0x6F5:
                self.mixer[self.mix_sel] = v
            else:
                raise BasicError(99, f"POKE ${a:07X}")
            return
        if 0xFF7E000 <= a <= 0xFF7EFFF:
            self.chars[a - 0xFF7E000] = v
            return
        if a < 0x10000 and not (0x1800 <= a <= 0x1FFF):
            raise BasicError(99, f"POKE ${a:04X}")
        self.mem[a] = v

    # ---- input
    def poll_events(self):
        for shot in list(self.shots):
            if 'ready_at' not in shot:
                if shot['when'](self):
                    shot['ready_at'] = self.time + int(shot.get('delay', 0) * 1e6)
                continue
            if self.time >= shot['ready_at']:
                self.render(shot['path'])
                self.shots.remove(shot)
                self.log.append((self.time, 'shot ' + str(shot['path'])))
        while self.events:
            ev = self.events[0]
            if 'ready_at' not in ev:
                if ev['when'](self):
                    ev['ready_at'] = self.time + int(ev.get('delay', 0.3) * 1e6)
                else:
                    return
            if self.time < ev['ready_at']:
                return
            self.events.pop(0)
            if ev['key'] == 'FIRE':
                self.fire_until = self.time + 4 * FRAME_US
            elif ev['key'] == 'BREAK':
                raise BasicError(30)
            else:
                self.keyq.extend(ev['key'])
            self.log.append((self.time, ev.get('name', ev['key'])))

    def get_key(self):
        self.poll_events()
        if self.keyq:
            k = self.keyq.pop(0)
            return k if isinstance(k, str) else chr(k)
        return ""

    def joy(self, port):
        self.poll_events()
        return 128 if self.time < self.fire_until else 0

    # ---- rendering
    def rgb(self, entry):
        b = (self.d070 >> 4) & 3
        return tuple(swap(self.pal[b][c][entry]) for c in range(3))

    def render(self, path, scale=2):
        from PIL import Image
        cw = 8 * scale * (2 if self.cols == 40 else 1)
        ch = 8 * scale * (2 if self.rows == 25 else 1)
        bord = 24 * scale
        img = Image.new('RGB', (self.cols * cw + 2 * bord, self.rows * ch + 2 * bord), self.rgb(self.d020))
        px = img.load()
        bg = self.rgb(self.d021)
        base = 2048 if self.lowercase else 0
        for y in range(self.rows):
            for x in range(self.cols):
                code = self.text[y][x]
                fg = self.rgb(self.colr[y][x] & 15 if self.colr[y][x] < 16 else self.colr[y][x])
                for r in range(8):
                    bits = self.chars[base + code * 8 + r]
                    for c in range(8):
                        col = fg if bits & (0x80 >> c) else bg
                        x0, y0 = bord + x * cw + c * cw // 8, bord + y * ch + r * ch // 8
                        for dy in range(ch // 8):
                            for dx in range(cw // 8):
                                px[x0 + dx, y0 + dy] = col
        img.save(path)


# ---------------------------------------------------------------- the interpreter
class Interpreter:
    STMT_US = 50          # time per statement
    TOKEN_US = 2          # and per token

    def __init__(self, listing, machine):
        self.m = machine
        self.lines = {}
        for raw in Path(listing).read_text().splitlines() if isinstance(listing, (str, Path)) and \
                Path(listing).exists() else listing.splitlines():
            if raw.strip():
                no, text = raw.split(' ', 1)
                self.lines[int(no)] = text
        self.nums = sorted(self.lines)
        self.index = {n: i for i, n in enumerate(self.nums)}
        self.toks = [tokenize(self.lines[n]) for n in self.nums]
        self.vars, self.arrays = {}, {}
        self.stack = []
        self.trap = None
        self.er, self.el = 0, 0
        self.bank = 128
        self.data_ptr = (0, 0)
        self.data_items = []
        self.li, self.ti = 0, 0
        self.ended = False
        self.statements = 0
        self.rnd = random.Random(7)
        self.last_rnd = 0.5
        self.trace = []
        self.jumped = False

    # ---- token access
    def tok(self):
        return self.toks[self.li][self.ti]

    def take(self):
        t = self.toks[self.li][self.ti]
        self.ti += 1
        return t

    def peek_is(self, kind, value=None):
        t = self.tok()
        return t[0] == kind and (value is None or t[1] == value)

    def expect(self, kind, value=None):
        t = self.take()
        if t[0] != kind or (value is not None and t[1] != value):
            raise BasicError(11, f"expected {value or kind}, got {t[1]!r}")
        return t

    def line_no(self):
        return self.nums[self.li]

    # ---- variables
    def get_var(self, name):
        if name == 'ER':
            return self.er
        if name == 'EL':
            return self.el
        if name in ('ST', 'TI', 'DS'):
            raise BasicError(99, name)
        key = basic_name(name)
        return self.vars.get(key, "" if key.endswith('$') else 0)

    def set_var(self, name, value):
        key = basic_name(name)
        if key.rstrip('$%') in ('ER', 'EL', 'ST', 'TI', 'DS'):
            raise BasicError(11, f"assigns {key}")
        self.vars[key] = self.convert(key, value)

    def convert(self, key, value):
        if key.endswith('$'):
            if not isinstance(value, str):
                raise BasicError(22)
            if len(value) > 255:
                raise BasicError(23)
            return value
        if isinstance(value, str):
            raise BasicError(22)
        if key.endswith('%'):
            v = math.floor(value) if value >= 0 else -math.floor(-value)
            if not -32768 <= v <= 32767:
                raise BasicError(14)
            return v
        return float(value)

    def array(self, name, create=True):
        key = basic_name(name)
        if key not in self.arrays:
            if not create:
                return None
            self.arrays[key] = ([10], ["" if key.endswith('$') else 0] * 11)
        return key, self.arrays[key]

    def element(self, name, subs):
        key, (dims, data) = self.array(name)
        if len(subs) != len(dims):
            raise BasicError(18, name)
        idx = 0
        for s, d in zip(subs, dims):
            s = int(s)
            if s < 0 or s > d:
                raise BasicError(18, f"{name}({s})")
            idx = idx * (d + 1) + s
        return key, data, idx

    # ---- expressions
    def expr(self):
        return self.e_or()

    def e_or(self):
        v = self.e_and()
        while self.peek_is('kw', 'OR') or self.peek_is('kw', 'XOR'):
            op = self.take()[1]
            w = self.e_and()
            a, b = self.int16(v), self.int16(w)
            v = float(a | b if op == 'OR' else a ^ b)
        return v

    def e_and(self):
        v = self.e_not()
        while self.peek_is('kw', 'AND'):
            self.take()
            w = self.e_not()
            v = float(self.int16(v) & self.int16(w))
        return v

    def e_not(self):
        if self.peek_is('kw', 'NOT'):
            self.take()
            return float(~self.int16(self.e_not()))
        return self.e_rel()

    def int16(self, v):
        if isinstance(v, str):
            raise BasicError(22)
        v = math.floor(v)
        if not -32768 <= v <= 32767:
            raise BasicError(14, f"logic operand {v}")
        return v

    def e_rel(self):
        v = self.e_add()
        while self.tok()[0] == 'op' and self.tok()[1] in ('=', '<', '>', '<=', '>=', '<>'):
            op = self.take()[1]
            w = self.e_add()
            if isinstance(v, str) != isinstance(w, str):
                raise BasicError(22)
            r = {'=': v == w, '<': v < w, '>': v > w, '<=': v <= w, '>=': v >= w, '<>': v != w}[op]
            v = -1.0 if r else 0.0
        return v

    def e_add(self):
        v = self.e_mul()
        while self.tok()[0] == 'op' and self.tok()[1] in '+-':
            op = self.take()[1]
            w = self.e_mul()
            if op == '+':
                if isinstance(v, str) != isinstance(w, str):
                    raise BasicError(22)
                v = v + w
                if isinstance(v, str) and len(v) > 255:
                    raise BasicError(23)
            else:
                self.num(v), self.num(w)
                v = v - w
        return v

    def e_mul(self):
        v = self.e_unary()
        while self.tok()[0] == 'op' and self.tok()[1] in '*/':
            op = self.take()[1]
            w = self.e_unary()
            self.num(v), self.num(w)
            if op == '*':
                v = v * w
            else:
                if w == 0:
                    raise BasicError(20)
                v = v / w
        return v

    def e_unary(self):
        if self.peek_is('op', '-'):
            self.take()
            return -self.num(self.e_unary())
        if self.peek_is('op', '+'):
            self.take()
            return self.e_unary()
        return self.e_pow()

    def e_pow(self):
        v = self.e_atom()
        while self.peek_is('op', '^'):
            self.take()
            w = self.e_unary() if self.peek_is('op', '-') else self.e_atom()
            v = float(self.num(v) ** self.num(w))
        return v

    def num(self, v):
        if isinstance(v, str):
            raise BasicError(22)
        return v

    def args(self):
        self.expect('op', '(')
        out = [self.expr()]
        while self.peek_is('op', ','):
            self.take()
            out.append(self.expr())
        self.expect('op', ')')
        return out

    def e_atom(self):
        t = self.take()
        if t[0] == 'num':
            return t[1]
        if t[0] == 'str':
            return t[1]
        if t[0] == 'op' and t[1] == '(':
            v = self.expr()
            self.expect('op', ')')
            return v
        if t[0] == 'id':
            name = t[1]
            if name in ('T@&', 'C@&'):
                x, y = self.args()
                row, x = self.screen_cell(name, x, y)
                return float(row[x])
            if self.peek_is('op', '('):
                subs = [self.num(a) for a in self.args()]
                key, data, idx = self.element(name, subs)
                return data[idx]
            return self.get_var(name)
        if t[0] == 'kw':
            return self.function(t[1])
        raise BasicError(11, f"unexpected {t[1]!r}")

    def function(self, kw):
        if kw == 'RND':
            (x,) = self.args()
            if x < 0:
                self.rnd.seed(x)
            if x != 0 or True:
                self.last_rnd = self.rnd.random()
            return self.last_rnd
        a = self.args()
        n = lambda i: self.num(a[i])
        s = lambda i: a[i] if isinstance(a[i], str) else (_ for _ in ()).throw(BasicError(22))
        if kw == 'PEEK':
            return float(self.m.peek(n(0)))
        if kw == 'INT':
            return float(math.floor(n(0)))
        if kw == 'ABS':
            return abs(n(0))
        if kw == 'SGN':
            return float((n(0) > 0) - (n(0) < 0))
        if kw == 'SQR':
            return math.sqrt(n(0))
        if kw == 'LEN':
            return float(len(s(0)))
        if kw == 'ASC':
            return float(ord(s(0)[0])) if s(0) else 0.0
        if kw == 'CHR$':
            v = int(n(0))
            if not 0 <= v <= 255:
                raise BasicError(14)
            return chr(v)
        if kw == 'STR$':
            return fmt_num(n(0))
        if kw == 'VAL':
            m = re.match(r'\s*[-+]?\d*\.?\d*', s(0))
            try:
                return float(m.group(0))
            except ValueError:
                return 0.0
        if kw == 'MID$':
            st = int(n(1))
            if st < 1 or st > 255:
                raise BasicError(14)
            ln = int(n(2)) if len(a) > 2 else 255
            return s(0)[st - 1:st - 1 + ln]
        if kw == 'LEFT$':
            return s(0)[:max(0, int(n(1)))]
        if kw == 'RIGHT$':
            k = int(n(1))
            return s(0)[-k:] if k > 0 else ""
        if kw == 'INSTR':
            h, nd = s(0), s(1)
            if not h or not nd:
                return 0.0
            st = int(n(2)) if len(a) > 2 else 1
            return float(h.find(nd, st - 1) + 1)
        if kw == 'MOD':
            if n(1) == 0:
                raise BasicError(20)
            return float(math.fmod(n(0), n(1)))
        if kw == 'JOY':
            return float(self.m.joy(int(n(0))))
        if kw == 'RWINDOW':
            k = int(n(0))
            return float({0: self.m.cols, 1: self.m.rows, 2: self.m.cols, 3: self.m.rows}[k])
        if kw == 'ERR$':
            return ERRORS.get(int(n(0)), "?")
        raise BasicError(99, kw)

    def screen_cell(self, name, x, y):
        x, y = int(self.num(x)), int(self.num(y))
        if not (0 <= x < self.m.cols and 0 <= y < self.m.rows):
            raise BasicError(18, f"{name}({x},{y})")
        arr = self.m.text if name == 'T@&' else self.m.colr
        return arr[y], x

    # ---- statements
    def run(self, max_us=None, start=None):
        if start is not None:
            self.li, self.ti = self.index[start], 0
        limit = None if max_us is None else self.m.time + max_us
        while not self.ended:
            if limit is not None and self.m.time > limit:
                return False
            try:
                self.step()
            except BasicError as e:
                if self.trap is not None and e.code != 99:
                    self.er, self.el = e.code, self.line_no()
                    self.trace.append(('trap', e.code, self.line_no(), str(e)))
                    self.stack = []
                    self.li, self.ti = self.index[self.trap], 0
                    continue
                raise BasicError(e.code, f"{e} in line {self.line_no()}")
        return True

    def next_line(self):
        self.li += 1
        self.ti = 0
        if self.li >= len(self.nums):
            self.ended = True

    def goto(self, n):
        n = int(n)
        if n not in self.index:
            raise BasicError(17, str(n))
        self.li, self.ti = self.index[n], 0
        self.jumped = True

    def step(self):
        t = self.tok()
        if t[0] == 'eol':
            self.next_line()
            return
        if t[0] == 'op' and t[1] == ':':
            self.take()
            return
        self.statements += 1
        self.m.time += self.STMT_US
        self.jumped = False
        self.statement()
        if self.jumped or self.ended:
            return
        t = self.tok()
        if t[0] == 'op' and t[1] == ':':
            self.take()
        elif t[0] == 'kw' and t[1] == 'ELSE':
            self.next_line()
        elif t[0] != 'eol' and not self.ended:
            raise BasicError(11, f"after statement: {t[1]!r}")

    def statement(self):
        t = self.take()
        self.m.time += self.TOKEN_US * len(self.toks[self.li])
        if t[0] == 'id':
            self.assign(t[1])
            return
        if t[0] != 'kw':
            raise BasicError(11, f"statement starts with {t[1]!r}")
        k = t[1]
        f = getattr(self, 's_' + k.replace('$', 'S'), None)
        if f is None:
            raise BasicError(99, k)
        f()

    def assign(self, name):
        if name in ('T@&', 'C@&'):
            x, y = self.args()
            self.expect('op', '=')
            v = self.num(self.expr())
            row, x = self.screen_cell(name, x, y)
            v = int(v)
            if not 0 <= v <= 255:
                raise BasicError(14, f"{name}={v}")
            row[x] = v
            return
        if self.peek_is('op', '('):
            subs = [self.num(a) for a in self.args()]
            key, data, idx = self.element(name, subs)
            self.expect('op', '=')
            data[idx] = self.convert(key, self.expr())
            return
        self.expect('op', '=')
        self.set_var(name, self.expr())

    def s_LET(self):
        self.assign(self.expect('id')[1])

    def s_REM(self):
        self.ti = len(self.toks[self.li]) - 1

    def s_DATA(self):
        self.ti = len(self.toks[self.li]) - 1

    def s_BANK(self):
        self.bank = int(self.expr())

    def s_TRAP(self):
        if self.peek_is('num'):
            self.trap = int(self.take()[1])
            if self.trap not in self.index:
                raise BasicError(17)
        else:
            self.trap = None

    def s_END(self):
        self.ended = True

    def s_STOP(self):
        raise BasicError(30)

    def s_PRINT(self):
        newline = True
        while True:
            t = self.tok()
            if t[0] == 'eol' or (t[0] == 'op' and t[1] == ':') or (t[0] == 'kw' and t[1] == 'ELSE'):
                break
            if t[0] == 'op' and t[1] in ';,':
                self.take()
                newline = False
                continue
            v = self.expr()
            newline = True
            text = v if isinstance(v, str) else fmt_num(v) + ' '
            for ch in text:
                self.m.put(ord(ch))
        if newline:
            self.m.put(13)

    def s_POKE(self):
        a = self.num(self.expr())
        k = 0
        while self.peek_is('op', ','):
            self.take()
            self.m.poke(a + k, self.num(self.expr()))
            k += 1
        if k == 0:
            raise BasicError(11, "POKE needs a value")

    def s_IF(self):
        c = self.expr()
        self.expect('kw', 'THEN')
        self.jumped = True
        if isinstance(c, str):
            raise BasicError(22, "IF on a string")
        if c != 0:
            if self.peek_is('num'):
                self.goto(self.take()[1])
            return
        # false: find ELSE on this line
        toks = self.toks[self.li]
        depth = 0
        for j in range(self.ti, len(toks)):
            if toks[j] == ('kw', 'IF'):
                depth += 1
            if toks[j] == ('kw', 'ELSE'):
                if depth == 0:
                    self.ti = j + 1
                    if self.peek_is('num'):
                        self.goto(self.take()[1])
                    return
                depth -= 1
        self.ti = len(toks) - 1      # skip the rest of the line

    def s_GOTO(self):
        self.goto(self.expect('num')[1])

    def s_GO(self):
        self.expect('kw', 'TO')
        self.s_GOTO()

    def s_GOSUB(self):
        n = self.expect('num')[1]
        self.stack.append(('gosub', self.li, self.ti))
        self.goto(n)

    def s_RETURN(self):
        while self.stack and self.stack[-1][0] != 'gosub':
            self.stack.pop()
        if not self.stack:
            raise BasicError(12)
        _, self.li, self.ti = self.stack.pop()
        self.jumped = True

    def s_ELSE(self):
        self.ti = len(self.toks[self.li]) - 1

    def s_ON(self):
        v = int(self.num(self.expr()))
        kind = self.take()
        if kind not in (('kw', 'GOSUB'), ('kw', 'GOTO')):
            raise BasicError(11, "ON without GOTO/GOSUB")
        targets = [self.expect('num')[1]]
        while self.peek_is('op', ','):
            self.take()
            targets.append(self.expect('num')[1])
        if v < 0 or v > 255:
            raise BasicError(14)
        if 1 <= v <= len(targets):
            if kind[1] == 'GOSUB':
                self.stack.append(('gosub', self.li, self.ti))
            self.goto(targets[v - 1])

    def s_FOR(self):
        name = self.expect('id')[1]
        self.expect('op', '=')
        start = self.num(self.expr())
        self.expect('kw', 'TO')
        limit = self.num(self.expr())
        step = 1.0
        if self.peek_is('kw', 'STEP'):
            self.take()
            step = self.num(self.expr())
        if name.endswith(('$', '%')):
            raise BasicError(22, "FOR needs a real variable")
        self.set_var(name, start)
        key = basic_name(name)
        for i in range(len(self.stack) - 1, -1, -1):
            fr = self.stack[i]
            if fr[0] == 'gosub':
                break
            if fr[0] == 'for' and fr[1] == key:
                del self.stack[i:]
                break
        self.stack.append(('for', key, limit, step, self.li, self.ti))

    def s_NEXT(self):
        names = []
        if self.peek_is('id'):
            names.append(self.take()[1])
            while self.peek_is('op', ','):
                self.take()
                names.append(self.expect('id')[1])
        for name in names or [None]:
            key = basic_name(name) if name else None
            idx = None
            for i in range(len(self.stack) - 1, -1, -1):
                fr = self.stack[i]
                if fr[0] == 'gosub':
                    break
                if fr[0] == 'for' and (key is None or fr[1] == key):
                    idx = i
                    break
            if idx is None:
                raise BasicError(10, name or "")
            del self.stack[idx + 1:]
            _, k, limit, step, li, ti = self.stack[idx]
            v = self.vars[k] + step
            self.vars[k] = v
            if (step >= 0 and v <= limit) or (step < 0 and v >= limit):
                self.li, self.ti = li, ti
                self.jumped = True
                return
            self.stack.pop()

    def loop_cond(self):
        """Optional WHILE/UNTIL condition: returns True to keep looping, None if absent."""
        if self.peek_is('kw', 'WHILE'):
            self.take()
            return self.expr() != 0
        if self.peek_is('kw', 'UNTIL'):
            self.take()
            return self.expr() == 0
        return None

    def s_DO(self):
        here = (self.li, self.ti - 1)
        keep = self.loop_cond()
        if keep is False:
            self.skip_to_loop_end()
            self.jumped = True
            return
        self.stack.append(('do',) + here)

    def skip_to_loop_end(self):
        depth = 1
        li, ti = self.li, self.ti
        while li < len(self.nums):
            toks = self.toks[li]
            while ti < len(toks):
                t = toks[ti]
                if t == ('kw', 'DO'):
                    depth += 1
                elif t == ('kw', 'LOOP'):
                    depth -= 1
                    if depth == 0:
                        self.li, self.ti = li, ti + 1
                        if self.peek_is('kw', 'WHILE') or self.peek_is('kw', 'UNTIL'):
                            self.take()
                            self.expr()
                        return
                ti += 1
            li, ti = li + 1, 0
        raise BasicError(11, "DO without LOOP")

    def s_LOOP(self):
        while self.stack and self.stack[-1][0] == 'for':
            self.stack.pop()
        if not self.stack or self.stack[-1][0] != 'do':
            raise BasicError(11, "LOOP without DO")
        keep = self.loop_cond()
        _, li, ti = self.stack.pop()
        if keep is False:
            return
        self.li, self.ti = li, ti
        self.jumped = True

    def s_EXIT(self):
        while self.stack and self.stack[-1][0] == 'for':
            self.stack.pop()
        if not self.stack or self.stack[-1][0] != 'do':
            raise BasicError(11, "EXIT outside DO")
        _, li, ti = self.stack.pop()
        self.li, self.ti = li, ti + 1
        self.skip_to_loop_end()
        self.jumped = True

    def s_DIM(self):
        while True:
            name = self.expect('id')[1]
            dims = [int(self.num(a)) for a in self.args()]
            key = basic_name(name)
            if key in self.arrays:
                raise BasicError(19, key)
            size = 1
            for d in dims:
                size *= d + 1
            self.arrays[key] = (dims, ["" if key.endswith('$') else 0] * size)
            if not self.peek_is('op', ','):
                break
            self.take()

    def s_GET(self):
        name = self.expect('id')[1]
        k = self.m.get_key()
        if name.endswith('$'):
            self.set_var(name, k)
        else:
            self.set_var(name, float(ord(k)) if k else 0.0)

    def s_CURSOR(self):
        if self.peek_is('kw', 'ON') or self.peek_is('kw', 'OFF'):
            self.take()
            return
        x = None if self.peek_is('op', ',') else self.num(self.expr())
        y = None
        if self.peek_is('op', ','):
            self.take()
            y = self.num(self.expr())
        if x is not None:
            self.m.cx = int(x)
        if y is not None:
            self.m.cy = int(y)

    def s_SOUND(self):
        self.expect('kw', 'CLR')
        self.m.sound_clr += 1
        self.m.sid = [0] * 128

    def s_SYS(self):
        a = int(self.num(self.expr()))
        if self.m.sys_hook is None:
            raise BasicError(99, f"SYS {a}")
        self.m.sys_hook(self.m, a)

    def s_RESTORE(self):
        n = int(self.take()[1]) if self.peek_is('num') else self.nums[0]
        if n not in self.index:
            raise BasicError(17)
        self.data_ptr = (self.index[n], 0)
        self.data_items = []

    def next_data_item(self):
        while not self.data_items:
            li, _ = self.data_ptr
            while li < len(self.nums) and self.toks[li][0] != ('kw', 'DATA'):
                li += 1
            if li >= len(self.nums):
                raise BasicError(13)
            raw = self.toks[li][1][1]
            self.data_items = self.split_data(raw)
            self.data_ptr = (li + 1, 0)
        return self.data_items.pop(0)

    @staticmethod
    def split_data(raw):
        items, cur, inq, quoted = [], '', False, False
        for ch in raw:
            if ch == '"':
                if not inq and not cur.strip():
                    cur = ''
                inq = not inq
                quoted = True
                continue
            if ch == ',' and not inq:
                items.append((cur if quoted else cur.strip(), quoted))
                cur, quoted = '', False
                continue
            cur += ch
        items.append((cur if quoted else cur.strip(), quoted))
        return items

    def s_READ(self):
        while True:
            name = self.expect('id')[1]
            subs = [self.num(a) for a in self.args()] if self.peek_is('op', '(') else None
            text, quoted = self.next_data_item()
            if name.endswith('$'):
                v = text
            else:
                if quoted:
                    raise BasicError(22, "string in numeric DATA")
                try:
                    v = float(text) if text else 0.0
                except ValueError:
                    raise BasicError(22, f"DATA {text!r}")
            if subs is None:
                self.set_var(name, v)
            else:
                key, data, idx = self.element(name, subs)
                data[idx] = self.convert(key, v)
            if not self.peek_is('op', ','):
                break
            self.take()
