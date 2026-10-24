"""bas65pp: readable BASIC 65 source -> numbered BASIC 65 listing for IMPORT.

Source rules
- One source line is one BASIC line. Leading whitespace is ignored.
- A line starting with '#' and a space (or '#' alone) is a comment and is dropped.
  A trailing comment is two spaces, '#', a space, outside strings: 'PRINT A  # note'.
- Directives:
    #include FILE        insert another source file (path relative to this one)
    #var NAME SHORT      long variable name -> BASIC name (one or two letters or a letter and a
                         digit, optional $ or %); arrays use the same name with '('
    #define NAME TEXT    constant: NAME -> TEXT
    #import FILE.asm     every 'NAME = $hex' equate of an assembler file becomes a #define
    #line N              the next line gets number N (default 10, then steps of #step)
    #step N              step between line numbers (default 10)
    #engine FILE.bin N   the binary as DATA lines from line N, 16 bytes each; defines
                         ENGINE_BYTES, ENGINE_SUM and ENGINE_LINE
- '@name' alone on a line labels the next line; '@name' in code is that line's number.
- Names with a lower-case letter or an underscore belong to the transpiler and must be
  declared. BASIC keywords and plain BASIC names are written in upper case and pass through.
  Strings, and everything after REM or DATA, pass through untouched.
Checks: undeclared names, undefined or duplicate labels, ascending numbers, line length,
characters, short names that clash or contain a keyword, jump targets that do not exist.
Writes OUT.bas and OUT.map (labels with their line numbers, variables with their BASIC names).
Usage: python3 bas65pp.py SOURCE.b65 OUT.bas [--width 80]
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lint_basic import KEYWORDS, RESERVED, ALLOWED  # noqa: E402

NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*[$%]?')
LABEL = re.compile(r'@([a-z_][a-z0-9_]*)')
SHORT = re.compile(r'^[A-Z][A-Z0-9]?[$%]?$')
JUMP = re.compile(r'\b(GOTO|GOSUB|THEN|ELSE|TRAP|RESTORE|RESUME)\s*(\d+)')
ONJUMP = re.compile(r'\bON\b[^:]*?\b(?:GOTO|GOSUB)\s*([\d\s,]+)')


class Error(Exception):
    pass


def split_comment(text):
    """Remove a trailing '  # ' comment that is outside strings."""
    inside = False
    for i, ch in enumerate(text):
        if ch == '"':
            inside = not inside
        elif not inside and text.startswith('  # ', i):
            return text[:i].rstrip()
    return text.rstrip()


class Source:
    def __init__(self):
        self.names = {}        # long name -> replacement text
        self.kinds = {}        # long name -> 'var' or 'def'
        self.labels = {}       # label -> line number
        self.lines = []        # (number, text, where)
        self.next_no = 10
        self.step = 10
        self.pending = []      # labels waiting for the next line
        self.last_no = 0

    def define(self, name, value, kind, where):
        if name in self.names and self.names[name] != value:
            raise Error(f"{where}: {name} defined twice")
        if not re.search(r'[a-z_]', name):
            raise Error(f"{where}: {name} must contain a lower-case letter or an underscore")
        if kind == 'var':
            if not SHORT.match(value):
                raise Error(f"{where}: {value} is not a BASIC variable name")
            base = value.rstrip('$%')
            if base in RESERVED or any(k in base for k in KEYWORDS):
                raise Error(f"{where}: {value} is reserved or contains a keyword")
            if (name[-1] in '$%') != (value[-1] in '$%') or (name[-1] in '$%' and name[-1] != value[-1]):
                raise Error(f"{where}: {name} and {value} differ in type")
            for other, v in self.names.items():
                if self.kinds[other] == 'var' and v == value and other != name:
                    raise Error(f"{where}: {name} and {other} both map to {value}")
        self.names[name] = value
        self.kinds[name] = kind

    def add_line(self, text, where):
        no = self.next_no
        if no <= self.last_no:
            raise Error(f"{where}: line {no} does not follow {self.last_no}")
        if no > 63999:
            raise Error(f"{where}: line number {no} too big")
        for lab in self.pending:
            self.labels[lab] = no
        self.pending = []
        self.lines.append((no, text, where))
        self.last_no = no
        self.next_no = no + self.step

    def read(self, path, depth=0):
        path = Path(path)
        if depth > 8:
            raise Error(f"{path}: includes nested too deep")
        for n, raw in enumerate(path.read_text().splitlines(), 1):
            where = f"{path.name}:{n}"
            s = raw.strip()
            if not s:
                continue
            if s == '#' or s.startswith('# '):
                continue
            if s.startswith('#'):
                self.directive(s, path, where, depth)
                continue
            s = split_comment(s)
            m = re.match(r'^@([a-z_][a-z0-9_]*)$', s)
            if m:
                lab = m.group(1)
                if lab in self.labels or lab in self.pending:
                    raise Error(f"{where}: label @{lab} defined twice")
                self.pending.append(lab)
                continue
            self.add_line(s, where)

    def directive(self, s, path, where, depth):
        parts = s.split(None, 2)
        word = parts[0]
        if word == '#include':
            self.read(path.parent / parts[1].strip('"'), depth + 1)
        elif word == '#var':
            self.define(parts[1], parts[2].strip(), 'var', where)
        elif word == '#define':
            self.define(parts[1], parts[2].strip(), 'def', where)
        elif word == '#import':
            for n, raw in enumerate((path.parent / parts[1]).read_text().splitlines(), 1):
                m = re.match(r'^([A-Za-z_]\w*)\s*=\s*(\$[0-9A-Fa-f]+)\s*(;.*)?$', raw.strip())
                if m and '_' in m.group(1):
                    self.define(m.group(1), m.group(2).upper(), 'def', f"{parts[1]}:{n}")
        elif word == '#line':
            no = int(parts[1])
            if no <= self.last_no:
                raise Error(f"{where}: #line {no} does not follow {self.last_no}")
            self.next_no = no
        elif word == '#step':
            self.step = int(parts[1])
        elif word == '#engine':
            binfile, start = parts[1], int(parts[2])
            code = (path.parent / binfile).read_bytes()
            self.define('ENGINE_BYTES', str(len(code)), 'def', where)
            self.define('ENGINE_SUM', str(sum(code)), 'def', where)
            self.define('ENGINE_LINE', str(start), 'def', where)
            self.engine = (code, start, where)
        else:
            raise Error(f"{where}: unknown directive {word}")

    def emit_engine(self):
        if not hasattr(self, 'engine'):
            return
        code, start, where = self.engine
        if self.pending:
            raise Error(f"{where}: labels {self.pending} before the engine data")
        self.next_no = start
        old_step, self.step = self.step, 10
        for i in range(0, len(code), 16):
            self.add_line("DATA " + ",".join(str(b) for b in code[i:i + 16]), where)
        self.step = old_step

    def substitute(self, text, where):
        out, i, n = [], 0, len(text)
        while i < n:
            ch = text[i]
            if ch == '"':
                j = text.find('"', i + 1)
                j = n if j < 0 else j + 1
                out.append(text[i:j])
                i = j
                continue
            if ch == '@':
                m = LABEL.match(text, i)
                if m:
                    lab = m.group(1)
                    if lab not in self.labels:
                        raise Error(f"{where}: label @{lab} not defined")
                    out.append(str(self.labels[lab]))
                    i = m.end()
                    continue
                out.append(ch)
                i += 1
                continue
            if ch.isdigit():
                m = re.match(r'[0-9A-F.]+', text[i:])
                out.append(m.group(0))
                i += m.end()
                continue
            m = NAME.match(text, i)
            if m:
                word = m.group(0)
                if word in ('REM', 'DATA') or (word.startswith('REM') and word.isupper()):
                    out.append(text[i:])
                    break
                if re.search(r'[a-z_]', word):
                    key = word if word in self.names else word.rstrip('$%')
                    if key not in self.names or (key != word and self.kinds[key] == 'var'):
                        raise Error(f"{where}: {word} is not declared")
                    out.append(self.names[key] + (word[len(key):] if key != word else ''))
                else:
                    out.append(word)
                i = m.end()
                continue
            out.append(ch)
            i += 1
        return ''.join(out)


def check_output(lines, width):
    numbers = {no for no, _, _ in lines}
    problems = []
    for no, text, where in lines:
        full = f"{no} {text}"
        if len(full) > width:
            problems.append(f"{where}: line {no} has {len(full)} characters")
        bad = sorted({c for c in full if c not in ALLOWED})
        if bad:
            problems.append(f"{where}: line {no} has characters {bad}")
        if text.startswith(('REM', 'DATA')):
            continue
        code = re.sub(r'"[^"]*("|$)', '""', text).split('REM', 1)[0]
        for m in JUMP.finditer(code):
            if int(m.group(2)) not in numbers:
                problems.append(f"{where}: line {no} jumps to {m.group(2)}, which does not exist")
        for m in ONJUMP.finditer(code):
            for t in m.group(1).split(','):
                if t.strip() and int(t) not in numbers:
                    problems.append(f"{where}: line {no} jumps to {t.strip()}, which does not exist")
    return problems


def build(src_path, width=80):
    src = Source()
    src.read(src_path)
    if src.pending:
        raise Error(f"labels {src.pending} at the end of the source")
    src.emit_engine()
    out = [(no, src.substitute(text, where), where) for no, text, where in src.lines]
    return src, out, check_output(out, width)


def main():
    args = sys.argv[1:]
    width = 80
    if '--width' in args:
        k = args.index('--width')
        width = int(args[k + 1])
        del args[k:k + 2]
    src_path, out_path = args
    try:
        src, out, problems = build(src_path, width)
    except Error as e:
        sys.exit(f"error: {e}")
    if problems:
        sys.exit("problems:\n  " + "\n  ".join(problems))
    Path(out_path).write_text(''.join(f"{no} {text}\n" for no, text, _ in out))
    with open(Path(out_path).with_suffix('.map'), 'w') as f:
        f.write("# labels\n")
        for lab, no in sorted(src.labels.items(), key=lambda t: t[1]):
            f.write(f"{no:>6}  @{lab}\n")
        f.write("# variables\n")
        for name, value in sorted(src.names.items(), key=lambda t: t[1]):
            if src.kinds[name] == 'var':
                f.write(f"{value:>6}  {name}\n")
        f.write("# source lines\n")
        for no, _, where in out:
            f.write(f"{no:>6}  {where}\n")
    longest = max(len(f"{no} {t}") for no, t, _ in out)
    print(f"{out_path}: {len(out)} lines, longest {longest}, {len(src.labels)} labels, "
          f"{sum(1 for k in src.kinds.values() if k == 'var')} variables")


if __name__ == '__main__':
    main()
