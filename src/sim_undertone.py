"""Run the UNDERTONE 1.0 listing in the BASIC 65 subset interpreter (tools/bas65sim.py), from
RUN to the return to READY, with scripted keys and fire buttons, the real engine run in a 6502
emulator for one short run, and every screen rendered to PNG.

Checks the program's logic only: flow, the START gate, settings reaching the engine, texts,
layout (nothing scrolls, nothing outside the frame), Q quitting from every stage, and that
everything the program changes is put back on quit. It does not check BASIC 65 itself, its
speed, or how the screens really look.
Usage: python3 sim_undertone.py undertone.bas engine.bin OUTDIR
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'tools'))
sys.path.insert(0, str(HERE))
import bas65sim as B                    # noqa: E402
import test_engine_v1 as TE             # noqa: E402

FAILED = []


def check(cond, msg):
    print(('  PASS ' if cond else '  FAIL ') + msg)
    if not cond:
        FAILED.append(msg)


def has(text):
    return lambda m: text in m.screen_text()


def after(pred, *more):
    return lambda m: pred(m) and all(p(m) for p in more)


def ev(when, key, delay=0.3, name=None):
    return dict(when=when, key=key, delay=delay, name=name or repr(key))


def shot(when, path, delay=0.0):
    return dict(when=when, path=path, delay=delay)


def row(m, y):
    """Row y between the frame columns, without the spaces at either end."""
    return m.row_text(y)[1:39].strip()


def rows_are(**want):
    """Every given row (r4=..., r12=...) reads exactly so."""
    return lambda m: all(row(m, int(k[1:])) == v for k, v in want.items())


P0 = dict(r4="NOTHING BUT WHITE AGAINST BLACK.", r5="ANY COLOUR YOU SEE IS YOURS.")
P1 = dict(r4="WHITE AGAINST BLACK, THEN ONE TURN", r5="OF THE COLOUR WHEEL, IN TURNS.")
P2 = dict(r4="EACH COLOUR AGAINST ITS OPPOSITE,", r5="ROUND AND ROUND THE COLOUR WHEEL.")
FIXED = dict(r2="H O W   I T   R U N S", r6="IT STARTS SLOW, SPEEDS UP AND ENDS",
             r7="ON ITS OWN. LOOK AT THE CENTRE.", r17="PRESS 1 TO 5 TO CHANGE A SETTING.",
             r18="ANY KEY STOPS THE FLICKER AT ONCE.", r19="TYPE START TO BEGIN. TYPING IT MEANS",
             r20="YOU ACCEPT THE WARNING.")
NOTE = {(1, 0): "LIGHT GREY AGAINST DARK GREY", (0, 0): "PURE WHITE AGAINST PURE BLACK",
        (1, 1): "SOFTER CONTRAST, NO SATURATED RED", (0, 1): "FULL CONTRAST, FULL COLOUR"}
PALNAME = ("BLACK AND WHITE", "B&W AND COLOUR WHEEL", "COLOUR WHEEL")   # by engine code
LENGTH = ("3 MIN", "10 MIN", "30 MIN")


def settings(soft=1, tick=1, hum=1, pal=0, length=0, typed=''):
    """The How it runs screen, every line of it, for these settings."""
    want = dict(FIXED, **(P0, P1, P2)[pal])
    want.update(r9="1   INTENSITY   " + ("SOFT" if soft else "FULL"),
                r10="2   TICK        " + ("ON" if tick else "OFF"),
                r11="3   HUM         " + ("ON" if hum else "OFF"),
                r12="4   PALETTE     " + PALNAME[pal],
                r13="5   LENGTH      " + LENGTH[length],
                r15=NOTE[soft, min(pal, 1)],
                r22="> " + typed + "#")
    return rows_are(**want)


def title_on(m):
    return m.text[8][0] == 85 and m.text[16][38] == 75


def card_on(m):
    return 'p s i n c o' in m.screen_text()


class Engine:
    """SYS $1800: the real engine in the 6502 emulator, or a stand-in for a whole 30-minute run."""

    def __init__(self, code_len):
        self.code_len = code_len
        self.calls = []
        self.plan = []          # per call: ('real', stop_frame, key) or ('ended',)

    def __call__(self, m, addr):
        check(addr == 0x1800, f"SYS ${addr:04X}")
        params = {k: m.mem.get(a, 0) for k, a in TE.P.items()}
        self.calls.append(dict(params, d020=m.d020, d021=m.d021, d070=m.d070,
                               mixer=[m.mixer[r] for r in (2, 3, 32, 33, 194, 195, 224, 225)]))
        kind = self.plan.pop(0)
        if kind[0] == 'real':
            code = bytes(m.mem.get(0x1800 + i, 0) for i in range(self.code_len))
            em = TE.Machine(code, m.d070, keys=[(kind[1], kind[2])])
            em.pal = m.pal
            em.border, em.screen = m.d020, m.d021
            for a in range(0x1E80, 0x1F00):
                em.mem[a] = m.mem.get(a, 0)
            r = em.run({}, max_frames=kind[1] + 50)
            for a in range(0x1E80, 0x1F00):
                m.mem[a] = em.mem[a]
            m.d070, m.d020, m.d021 = em.d070, em.border, em.screen
            frames = r['FR0'] + 256 * r['FR1'] + 65536 * r['FR2']
            self.calls[-1]['result'] = r
            self.calls[-1]['shown'] = len(em.shown)
            m.sid = [em.sidreg.get(0xD400 + i, 0) for i in range(128)]
        else:
            frames = 91429
            m.mem[TE.P['EXIT']] = 0
            m.mem[TE.P['INCL']], m.mem[TE.P['INCH']] = 0, 0x80
            for i, k in enumerate(('FR0', 'FR1', 'FR2')):
                m.mem[TE.P[k]] = (frames >> (8 * i)) & 255
            m.mem[TE.P['MISS']] = 0
            m.pal[(m.d070 >> 4) & 3][0][254] = 0xFF
        m.time += frames * B.FRAME_US


def expected_tables():
    MR, MG, MB, PT, GL, SG = TE.build_tables()
    return (MR, MG, MB), (PT, GL, SG)


def restored(m):
    ok = True
    for b in range(4):
        for c in range(3):
            if m.pal[b][c] != m.pal_start[b][c]:
                bad = [e for e in range(256) if m.pal[b][c][e] != m.pal_start[b][c][e]]
                print(f"    palette bank {b} channel {c} differs at {bad[:8]}")
                ok = False
    return ok


def run_flow(listing, code, out, d070, stmt_us=50, name='flow'):
    print(f"--- {name}: $D070 = ${d070:02X}, {stmt_us} us per statement")
    m = B.Machine(d070=d070)
    it = B.Interpreter(listing, m)
    it.STMT_US = stmt_us
    eng = Engine(len(code))
    eng.plan = [('real', 300, 0x20), ('ended',)]
    m.sys_hook = eng
    o = lambda s: str(out / f"{name}-{s}.png")
    m.shots = [
        shot(card_on, o('01-card'), 2.6),
        shot(title_on, o('02-title-strike'), 0.32),
        shot(title_on, o('03-title-glow'), 4.0),
    ]
    m.events = [ev(has('1/5'), ' ', 1.2, 'story 1')]
    m.shots.append(shot(has('1/5'), o('04-story-1'), 1.0))
    for p in (2, 3, 4, 5):
        m.events.append(ev(has(f'{p}/5'), 'FIRE' if p == 3 else ' ', 1.2, f'story {p}'))
        m.shots.append(shot(has(f'{p}/5'), o(f'05-story-{p}'), 1.0))
    m.events += [
        ev(has('1/2'), 'X', 0.5, 'early key on the warning'),
        ev(after(has('1/2'), has('PRESS A KEY')), ' ', 0.5, 'warning 1'),
        ev(has('2/2'), 'FIRE', 0.5, 'early fire on the warning'),
        ev(after(has('2/2'), has('PRESS A KEY')), ' ', 0.5, 'warning 2'),
        ev(settings(), '1', 0.5, 'FULL'),
        ev(settings(soft=0), '4', 0.3, 'palette: colour wheel'),
        ev(settings(soft=0, pal=2), '4', 0.3, 'palette: B&W and colour wheel'),
        ev(settings(soft=0, pal=1), '5', 0.3, 'length 10'),
        ev(settings(soft=0, pal=1, length=1), 'ST', 0.3, 'ST'),
        ev(settings(soft=0, pal=1, length=1, typed='ST'), 'X', 0.3, 'X: the word starts again'),
        ev(settings(soft=0, pal=1, length=1), 'START', 0.5, 'START'),
        ev(has('R AGAIN'), 'R', 1.5, 'again'),
        ev(settings(pal=1, length=1), '234', 0.5, 'tick off, hum off, palette round to black and white'),
        ev(settings(tick=0, hum=0, pal=0, length=1), '4', 0.3, 'colour wheel'),
        ev(settings(tick=0, hum=0, pal=2, length=1), '4', 0.3, 'B&W and colour wheel'),
        ev(settings(tick=0, hum=0, pal=1, length=1), '4', 0.3, 'black and white'),
        ev(settings(tick=0, hum=0, pal=0, length=1), '4', 0.3, 'colour wheel'),
        ev(settings(tick=0, hum=0, pal=2, length=1), '5', 0.3, 'length 30'),
        ev(settings(tick=0, hum=0, pal=2, length=2), '5', 0.3, 'length round to 3'),
        ev(settings(tick=0, hum=0, pal=2, length=0), '5', 0.3, 'length 10'),
        ev(settings(tick=0, hum=0, pal=2, length=1), '5', 0.3, 'length 30'),
        ev(settings(tick=0, hum=0, pal=2, length=2), 'START', 0.5, 'START'),
        ev(has('IT REACHED 25 HZ'), 'Q', 1.5, 'quit'),
    ]
    m.shots += [
        shot(after(has('1/2'), has('PRESS A KEY')), o('06-warning-1'), 0.1),
        shot(after(has('2/2'), has('PRESS A KEY')), o('07-warning-2'), 0.1),
        shot(settings(), o('08-settings-default'), 0.2),
        shot(settings(soft=0, pal=1, length=1, typed='ST'), o('09-settings-full-both'), 0.1),
        shot(has('YOU STOPPED IT'), o('10-end-stopped'), 1.0),
        shot(settings(tick=0, hum=0, pal=2, length=2), o('11-settings-colour-wheel'), 0.1),
        shot(has('IT REACHED 25 HZ'), o('12-end-ended'), 1.0),
    ]
    snaps = {}
    watch = [('warning-1', has('1/2')), ('settings', settings()), ('end', has('YOU STOPPED IT')),
             ('typed', settings(soft=0, pal=1, length=1, typed='ST')),
             ('story-5', after(has('5/5'), has('THE REST IS YOU')))]

    def track():
        for key, pred in watch:
            if key not in snaps and pred(m):
                tb = (m.d070 >> 4) & 3
                col15 = tuple(B.swap(m.pal[tb][c][15]) for c in range(3))
                snaps[key] = (m.time, m.screen_text(), [list(r) for r in m.colr], [list(r) for r in m.text],
                              col15)

    # run, watching a few moments
    max_stack = 0
    while not it.ended:
        it.run(max_us=200000)
        max_stack = max(max_stack, len(it.stack))
        track()
        if m.time > 3600e6:
            check(False, "still running after an hour of simulated time")
            break
    log = [n for t, n in m.log if not str(n).startswith('shot')]
    print("    events:", ', '.join(str(n) for n in log))
    check(not m.events, f"every scripted input was used (left: {[e['name'] for e in m.events]})")
    check(not m.shots, f"every screen was captured (left: {[s['path'] for s in m.shots]})")
    check(m.scrolls == 0, "the screen never scrolled")
    check(max_stack <= 6, f"stack depth stayed small (at most {max_stack})")
    check(len(eng.calls) == 2, f"the engine ran twice ({len(eng.calls)})")
    check(not it.trace, f"no error was trapped: {it.trace}")
    if len(eng.calls) == 2:
        c1, c2 = eng.calls
        bt = [b for b in range(4) if b != (d070 >> 4) & 3][:2]
        check(c1['SOFT'] == 0 and c1['SOUND'] == 3 and c1['PAL'] == 1 and c1['K'] == 56,
              f"run 1 gets Full, tick and hum, both in turns, 10 min: {c1['SOFT'], c1['SOUND'], c1['PAL'], c1['K']}")
        check(c2['SOFT'] == 1 and c2['SOUND'] == 0 and c2['PAL'] == 2 and c2['K'] == 169,
              f"run 2 gets Soft again, no sound, colour wheel, 30 min: {c2['SOFT'], c2['SOUND'], c2['PAL'], c2['K']}")
        check(all(c[k] == v for c in (c1, c2) for k, v in
                  dict(INCL=0, INCH=16, ECHO=1, MOD=1, KFL=27270 & 255, KFH=27270 >> 8, VS=10, VT=8,
                       EDLY=3, BT1=bt[0], BT2=bt[1]).items()),
              "fixed parameters: 3.125 Hz start, echo, tick pitch by lightness, tone factor, volumes, banks")
        check(all(v == 0 for v in c1['mixer']) and all(v == 0 for v in c2['mixer']),
              "hard panning: the four cross-feed coefficients are 0 during each run")
        check(c1['d020'] == 0 and c1['d021'] == 0, "border and background black (entry 0) when the engine starts")
        check(c1['d070'] & 0xC0 == (d070 & 0x30) << 2, "the text bank is mapped when the engine starts")
        r = c1['result']
        check(r['EXIT'] == 0x20 and r['FR0'] + 256 * r['FR1'] == 300 and c1['shown'] == 301,
              "run 1: the real engine, loaded from the DATA lines, ran 300 frames and stopped on the key")
    if 'settings' in snaps:
        cr = snaps['settings'][2]
        start_cols = [cr[19][x] for x in range(7, 12)]
        rest = [cr[19][x] for x in list(range(2, 7)) + list(range(12, 38)) if snaps['settings'][3][19][x] != 32]
        check(start_cols == [15] * 5 and set(rest) == {1},
              f"START in colour 15, the rest of the line in white: {start_cols}, {sorted(set(rest))}")
        yellow = snaps['settings'][4]
        check(yellow == (255, 220, 0), f"colour 15 on How it runs is yellow {yellow}")
    if 'typed' in snaps:
        cr = snaps['typed'][2]
        check(cr[22][4] == 15 and cr[22][5] == 15, "the typed letters are yellow too")
        tx = snaps['typed'][3]
        check(tx[12][37] != 32 and tx[12][38] == 32,
              "B&W AND COLOUR WHEEL ends in column 37: one blank column before the frame")
    if 'story-5' in snaps:
        lines = snaps['story-5'][1].split('\n')
        y = next((i for i, l in enumerate(lines) if 'BUILT ANEW ON THE MEGA65:' in l), None)
        ok = False
        if y is not None:
            x0 = lines[y].index('MEGA65')
            cr, tx = snaps['story-5'][2], snaps['story-5'][3]
            word = [cr[y][x] for x in range(x0, x0 + 6)]
            rest = {cr[y][x] for x in range(1, 39) if tx[y][x] != 32 and not x0 <= x < x0 + 6}
            ok = word == [15] * 6 and rest == {14}
        check(ok, "story 5/5: MEGA65 in the highlight colour (15), the rest of its line in 14")
    tb, tt = expected_tables()
    bt = [b for b in range(4) if b != (d070 >> 4) & 3][:2]
    if 'end' in snaps and eng.calls:
        t = snaps['end'][1]
        r = eng.calls[0]['result']
        hz = int(500 * (r['INCL'] + 256 * r['INCH']) / 65536 + .5) / 10
        want = f"YOU STOPPED IT AT {hz:g} HZ,"
        check(want in t and 'AFTER 6 S.' in t, f"THE END after the stop: '{want}' and 'AFTER 6 S.'")
        check('MISSED' not in t, "no missed frames reported")
    check(it.ended and m.sound_clr >= 1, "quit: SOUND CLR, program ended")
    check(restored(m), "quit: every palette entry of all four banks is back")
    check(m.d070 == d070 and m.d020 == 6 and m.d021 == 6, "quit: $D070, border, background back")
    check(m.chars == m.chars_start, "quit: the character set is back")
    check(m.mixer == m.mixer_start, "quit: the mixer is back")
    check((m.cols, m.rows) == (80, 25) and not m.lowercase and not m.case_lock,
          "quit: 80 x 25, upper case, case switch enabled")
    return m, it, snaps


def tables_check(listing, code, d070):
    """Stop right after the set-up and compare the table banks with the engine test's model."""
    m = B.Machine(d070=d070)
    it = B.Interpreter(listing, m)
    while not card_on(m):
        it.run(max_us=100000)
    (mr, mg, mb), (pt, gl, sg) = expected_tables()
    bt = [b for b in range(4) if b != (d070 >> 4) & 3][:2]
    ok = (m.pal[bt[0]] == [mr, mg, mb] and m.pal[bt[1]] == [pt, gl, sg])
    check(ok, f"$D070 = ${d070:02X}: BASIC builds the table banks {bt} exactly as the engine test's model")
    eng = bytes(m.mem.get(0x1800 + i, 0) for i in range(len(code)))
    check(eng == code, "the engine in memory equals engine.bin (DATA lines, checksum)")
    tbk = (d070 >> 4) & 3
    others = [b for b in range(4) if b not in bt and b != tbk]
    check(all(m.pal[b] == m.pal_start[b] for b in others), "the fourth bank is never touched")


def skip_flow(listing, code, out):
    print("--- RETURN skips the intro; RUN/STOP on the settings screen")
    m = B.Machine(d070=0x1B)
    it = B.Interpreter(listing, m)
    m.sys_hook = Engine(len(code))
    m.events = [
        ev(card_on, '\r', 0.5, 'RETURN on the card'),
        ev(has('1/2'), '\r', 0.2, 'RETURN early on the warning'),
        ev(after(has('1/2'), has('PRESS A KEY')), '\r', 0.2, 'warning 1'),
        ev(after(has('2/2'), has('PRESS A KEY')), '\r', 0.2, 'warning 2'),
        ev(has('H O W'), 'BREAK', 0.5, 'RUN/STOP'),
    ]
    seen_title = False
    while not it.ended and m.time < 600e6:
        it.run(max_us=100000)
        seen_title |= title_on(m)
    check(not m.events, f"all inputs used (left: {[e['name'] for e in m.events]})")
    check(not seen_title, "RETURN on the card goes straight to the warning: no title, no story")
    check(any(t[0] == 'trap' and t[1] == 30 for t in it.trace), "RUN/STOP is caught by TRAP")
    check(restored(m) and m.d070 == 0x1B and m.chars == m.chars_start and (m.cols, m.rows) == (80, 25),
          "after RUN/STOP: palettes, $D070, character set and screen mode are back")


def long_wait(listing, code):
    print("--- THE END left alone for 40 minutes, BASIC very slow (2 ms per statement)")
    m = B.Machine(d070=0x00)
    it = B.Interpreter(listing, m)
    it.STMT_US = 2000
    eng = Engine(len(code))
    eng.plan = [('real', 100, 0x0D)]
    m.sys_hook = eng
    m.events = [
        ev(card_on, '\r', 0.5, 'RETURN on the card'),
        ev(after(has('1/2'), has('PRESS A KEY')), ' ', 0.2, 'warning 1'),
        ev(after(has('2/2'), has('PRESS A KEY')), ' ', 0.2, 'warning 2'),
        ev(settings(), 'START', 0.5, 'START with the defaults'),
        ev(has('R AGAIN'), 'Q', 2400, 'Q after 40 minutes'),
    ]
    while not it.ended and m.time < 3000e6:
        it.run(max_us=1000000)
    check(not m.events and not it.trace and it.ended,
          f"no error after 40 minutes on THE END; Q quits (traps: {it.trace}, left: {[e['name'] for e in m.events]})")
    check(restored(m) and (m.cols, m.rows) == (80, 25), "everything back after Q")
    c = eng.calls[0] if eng.calls else {}
    check(c.get('SOFT') == 1 and c.get('SOUND') == 3 and c.get('PAL') == 0 and c.get('K') == 17,
          f"the defaults reach the engine: Soft, tick and hum, black and white, 3 min "
          f"{c.get('SOFT'), c.get('SOUND'), c.get('PAL'), c.get('K')}")


def blank(m):
    return not m.screen_text().strip()


def quit_case(listing, code, name, events, plan=(), never=None, d070=0x1B):
    """Q at one stage of the program: it ends at once and puts everything back."""
    print(f"--- Q: {name}")
    m = B.Machine(d070=d070)
    it = B.Interpreter(listing, m)
    eng = Engine(len(code))
    eng.plan = list(plan)
    m.sys_hook = eng
    m.events = events
    seen = False
    while not it.ended and m.time < 900e6:
        it.run(max_us=100000)
        seen |= bool(never and never(m))
    qt = next((t for t, n in m.log if str(n).startswith('Q') or str(n).startswith('SHIFT+Q')), None)
    check(not m.events, f"{name}: every input used (left: {[e['name'] for e in m.events]})")
    check(it.ended and not it.trace, f"{name}: the program ends, nothing trapped ({it.trace})")
    if qt is not None:
        check(m.time - qt < 2e6, f"{name}: ended {(m.time - qt) / 1e6:.2f} s after the key")
    # after the last input BASIC writes the SIDs only on its way out
    last = qt if qt is not None else max(t for t, n in m.log if not str(n).startswith('shot'))
    cleared = {r for t, r, v in m.sid_log if t >= last and v == 0}
    check(set(range(0x20, 0x39)) | set(range(0x60, 0x79)) <= cleared,
          f"{name}: SID 2 and SID 4 cleared on the way out")
    check(restored(m) and m.d070 == d070 and m.d020 == 6 and m.d021 == 6 and m.chars == m.chars_start
          and m.mixer == m.mixer_start and (m.cols, m.rows) == (80, 25) and not m.lowercase,
          f"{name}: palettes, $D070, border, characters, mixer and screen mode back")
    if never:
        check(not seen, f"{name}: the screen that must not come never came")
    return m, it, eng


def quit_flows(listing, code):
    to_warn = [ev(card_on, '\r', 0.5, 'RETURN on the card')]
    w1 = ev(after(has('1/2'), has('PRESS A KEY')), ' ', 0.2, 'warning 1')
    w2 = ev(after(has('2/2'), has('PRESS A KEY')), ' ', 0.2, 'warning 2')
    to_set = to_warn + [w1, w2]
    quit_case(listing, code, "the card", [ev(card_on, 'Q', 1.0, 'Q on the card')], never=title_on)
    m, it, eng = quit_case(listing, code, "the title, hum on",
                           [ev(title_on, 'Q', 4.0, 'Q on the title')], never=has('1/5'))
    qt = next(t for t, n in m.log if n == 'Q on the title')
    check(any(r == 0x2B and v == 65 and t < qt for t, r, v in m.sid_log),
          "the title's hum was sounding when Q came")
    quit_case(listing, code, "story page 2",
              [ev(has('1/5'), ' ', 1.0, 'story 1'), ev(has('2/5'), 'Q', 1.0, 'Q on story 2')], never=has('3/5'))
    quit_case(listing, code, "story page 1, shifted",
              [ev(has('1/5'), chr(209), 1.0, 'SHIFT+Q on story 1')], never=has('2/5'))
    quit_case(listing, code, "warning 1 while it still ignores keys",
              to_warn + [ev(has('1/2'), 'Q', 0.5, 'Q on warning 1, locked')], never=has('PRESS A KEY'))
    quit_case(listing, code, "warning 2",
              to_warn + [w1, ev(has('2/2'), 'Q', 2.5, 'Q on warning 2')], never=has('H O W'))
    quit_case(listing, code, "How it runs", to_set + [ev(settings(), 'Q', 0.5, 'Q on How it runs')])
    quit_case(listing, code, "How it runs, half of START typed",
              to_set + [ev(settings(), 'STA', 0.5, 'STA'), ev(settings(typed='STA'), 'Q', 0.3, 'Q after STA')])
    m, it, eng = quit_case(listing, code, "the second before the flicker",
                           to_set + [ev(settings(), 'START', 0.5, 'START'), ev(blank, 'Q', 0.3, 'Q in the pause')])
    check(not eng.calls, "the engine never ran")
    for key in (0x71, 0x51):
        m, it, eng = quit_case(listing, code, f"the flicker, stopped with ${key:02X}",
                               to_set + [ev(settings(), 'START', 0.5, 'START')], plan=[('real', 150, key)],
                               never=has('YOU STOPPED IT'))
        check(len(eng.calls) == 1 and eng.calls[0]['result']['EXIT'] == key,
              f"the engine stopped on ${key:02X} and the program quit without THE END")
    quit_case(listing, code, "How it runs again, after R",
              to_set + [ev(settings(), 'START', 0.5, 'START'), ev(has('R AGAIN'), 'R', 1.0, 'R'),
                        ev(settings(), 'Q', 0.5, 'Q on How it runs after R')], plan=[('real', 100, 0x20)])


def ntsc_flow(listing):
    print("--- NTSC")
    m = B.Machine(d070=0x00, pal_ntsc=True)
    it = B.Interpreter(listing, m)
    it.run(max_us=10e6)
    check(it.ended and 'NEEDS PAL' in m.screen_text() and (m.cols, m.rows) == (80, 25) and restored(m),
          "NTSC: says it needs PAL and ends without touching anything")


def main():
    listing, binfile, outdir = sys.argv[1:4]
    code = Path(binfile).read_bytes()
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    for d070 in (0x00, 0x55, 0xFF):
        tables_check(listing, code, d070)
    run_flow(listing, code, out, 0x55, name='flow')
    skip_flow(listing, code, out)
    quit_flows(listing, code)
    ntsc_flow(listing)
    long_wait(listing, code)
    run_flow(listing, code, out, 0xFF, stmt_us=150, name='slow')
    print("failures:", len(FAILED))
    for f in FAILED:
        print("  -", f)
    sys.exit(1 if FAILED else 0)


if __name__ == '__main__':
    main()
