"""Run the UNDERTONE 1.0 engine in a 6502 emulator (py65) against a simulated MEGA65 I/O map,
and compare every frame, picture and sound, with a reference model written independently
in Python.

The piece: three palettes. White against black only; in turns, 256 flashes of white against
black and one turn of the colour wheel from entry 43 (yellow against blue); or the colour wheel
alone from entry 43. The accelerando always runs and the piece ends when it reaches 25 Hz.
Sound: tick (pitch from the lightness of the colour it marks), echo, tone.
Stops: any key (hardware queue $D610), or a fire button going down on either port (CIA 1).

Simulated: frame counter $D7FA, key queue $D610, CIA 1 ports $DC00/$DC01 with joystick fire
lines and one keyboard key held in a row, $D030 (colour RAM at $DC00), four palette banks
through $D070 (MAPEDPAL for access, BTPALSEL for display), SID writes, every RAM write.
Tables are built exactly as the BASIC program builds them. Every scenario runs with the text
palette in bank 0 and in bank 3. This checks program logic only, not the real chips, the
sound they make, or the timing of the real machine.
Usage: python3 test_engine_v1.py engine.bin
"""
import sys

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

ORG = 0x1800
STUB = 0x1700
CPF = 12000           # emulated CPU cycles per video frame
KF = 27270            # tone factor for a SID clock of 984375 Hz
P = dict(INCL=0x1E80, INCH=0x1E81, SOFT=0x1E82, SOUND=0x1E83, PAL=0x1E84, K=0x1E85, BT1=0x1E86,
         BT2=0x1E87, ECHO=0x1E88, MOD=0x1E89, KFL=0x1E8A, KFH=0x1E8B, VS=0x1E8C, VT=0x1E8D,
         EDLY=0x1E8E, EXIT=0x1E8F, FR0=0x1E90, FR1=0x1E91, FR2=0x1E92, MISS=0x1E93,
         SEG=0x1E94, CNT=0x1E95)
VARS = range(0x1E80, 0x1F00)     # the only RAM the engine may write, besides the stack
WEIGHTS = (54, 183, 18)          # luminance of R, G, B in 255ths


def swap(v):
    return ((v & 15) << 4) | (v >> 4)


# ---------------- tables, as the BASIC program computes them ----------------
def hexcone(i):
    x = i * 6 / 256
    s = int(x)
    f = x - s
    return [(1, f, 0), (1 - f, 1, 0), (0, 1, f), (0, 1 - f, 1), (f, 0, 1), (1, 0, 1 - f)][s]


def build_tables():
    MR, MG, MB, PT, GL, SG = ([0] * 256 for _ in range(6))
    for h in range(256):
        c = hexcone(h)
        MR[h], MG[h], MB[h] = [min(128, int(256 * abs(v - .5) + .5)) for v in c]
        SG[h] = (c[0] < .5) * 1 + (c[1] < .5) * 2 + (c[2] < .5) * 4
        lightness = (h / 255) ** (1 / 2.2)
        PT[h] = int(16 * 2 ** (3 * lightness) + .5)
        GL[h] = swap(int(255 * lightness + .5))
    return MR, MG, MB, PT, GL, SG


MR, MG, MB, PT, GL, SG = build_tables()
WHITE, BLACK = (GL[255],) * 3, (GL[0],) * 3


# ---------------- reference model of the engine ----------------
class Model:
    def __init__(self, inc, soft, k, sound=3, echo=1, mod=1, vs=10, vt=8, edly=3, pal=1,
                 fire=lambda f: False):
        self.inc, self.soft, self.k, self.pal, self.fire = inc, soft, k, pal, fire
        self.sound, self.echo, self.mod, self.vs, self.vt_max, self.edly = sound, echo, mod, vs, vt, edly
        self.phase = 0
        self.seg = self.cnt = self.hh = 0
        if pal == 2:                 # the colour wheel alone starts at entry 43
            self.seg, self.hh = 1, 43
        self.kc = self.stp = 0
        self.fc = 64
        self.frames = self.top = self.cycles = 0
        self.st = 1
        self.history = []
        self.log = []                # per frame: (cycle number, segment, hue index)
        self.amp = 102 if soft else 256
        self.fprev = fire(0)         # read once while starting
        self.exit = 0
        self.colours()
        self.nst = self.state()

    def state(self):
        return 1 if self.phase & 0x8000 else 0

    def chan(self, m, neg, w):
        p = m if self.amp >= 256 else (self.amp * m) >> 8
        hi, lo = min(255, 128 + p), 128 - p
        a, b = (lo, hi) if neg else (hi, lo)
        return GL[a], GL[b], w * a, w * b

    def colours(self):
        if self.seg == 0:
            ms, negs = (128, 128, 128), (False, False, False)
        else:
            i = self.hh
            ms = (MR[i], MG[i], MB[i])
            negs = (bool(SG[i] & 1), bool(SG[i] & 2), bool(SG[i] & 4))
        res = [self.chan(m, n, w) for m, n, w in zip(ms, negs, WEIGHTS)]
        self.A = tuple(r[0] for r in res)
        self.B = tuple(r[1] for r in res)
        self.pa = PT[sum(r[2] for r in res) >> 8]
        self.pb = PT[sum(r[3] for r in res) >> 8]
        self.vt = self.vt_max if self.amp >= 256 else (self.amp * self.vt_max + 128) >> 8

    def flash(self):
        self.cycles += 1
        self.cnt = (self.cnt + 1) & 255
        if self.cnt == 0 and self.pal == 1:
            self.seg ^= 1
            if self.seg:
                self.hh = 43
            self.colours()
        elif self.seg:
            self.hh = (self.hh + 1) & 255
            self.colours()

    def accel(self):
        self.kc += 1
        if self.kc < self.k:
            return False
        self.kc = 0
        self.stp += 1
        if self.stp & 3 == 0:
            self.fc += 1
        self.inc += self.inc >> 8
        if self.inc >= 0x8000:
            self.inc = 0x8000
            self.top = self.frames
            return True
        return False

    def sound_writes(self, changed):
        """The SID registers the engine writes at the start of this frame."""
        w = {}
        tick = self.sound & 1
        ticks = (1 if self.nst == 0 else 2) if (changed and tick) else 0
        self.history.append(ticks)
        old = self.history[-1 - self.edly] if len(self.history) > self.edly else 0
        echo = old if self.echo else 0
        w[0xD401] = self.pa if self.mod else 0x40
        w[0xD441] = self.pb if self.mod else 0x40
        w[0xD404] = 0x81 if ticks & 1 else 0x80
        w[0xD444] = 0x81 if ticks & 2 else 0x80
        w[0xD44B] = 0x81 if echo & 1 else 0x80
        w[0xD40B] = 0x81 if echo & 2 else 0x80
        w[0xD418] = w[0xD458] = 0x10 | (self.vs if tick else 0)
        if self.sound & 2:
            fn = (self.inc * KF) >> 16
            gn = fn + (fn >> 5)
            for base in (0xD420, 0xD460):
                w[base], w[base + 1] = fn & 255, fn >> 8
                w[base + 7], w[base + 8] = gn & 255, gn >> 8
                w[base + 4] = w[base + 11] = 0x41
                w[base + 0x16] = self.fc
                w[base + 0x18] = 0x10 | self.vt
        else:
            for base in (0xD420, 0xD460):
                w[base + 4] = w[base + 11] = 0x40
                w[base + 0x18] = 0x10
        return w

    def frame(self, key=None):
        shown = self.A if self.nst == 0 else self.B
        self.log.append((self.cycles, self.seg, self.hh))
        changed = self.nst != self.st
        writes = self.sound_writes(changed)
        self.frames += 1
        self.st = self.nst
        if key is not None:
            self.exit = key
            return shown, writes, True
        now = self.fire(self.frames)     # the engine's frame n is emulator frame n
        if now != self.fprev:
            self.fprev = now
            if now:
                self.exit = 0xFF
                return shown, writes, True
        if self.accel():
            return shown, writes, True
        self.phase += self.inc
        if self.phase >= 0x10000:
            self.phase -= 0x10000
            self.flash()
        self.nst = self.state()
        return shown, writes, False


# ---------------- emulated machine ----------------
class Machine:
    def __init__(self, code, d070, keys=(), stall_at=None, fire=lambda f: (False, False),
                 cram=False, dc00=0x7F, held_key_row=7):
        self.mem = ObservableMemory()
        self.mpu = MPU(memory=self.mem)
        for i, b in enumerate(code):
            self.mem[ORG + i] = b
        for i, b in enumerate([0x20, ORG & 255, ORG >> 8, 0xEA]):
            self.mem[STUB + i] = b
        self.keys = list(keys)
        self.stall_at = stall_at
        self.d070 = self.d070_start = d070
        self.disp = (d070 >> 4) & 3
        self.bt1, self.bt2 = [b for b in range(4) if b != self.disp][:2]
        self.pal = [[[0x77] * 256 for _ in range(3)] for _ in range(4)]
        for i in range(256):
            self.pal[self.bt1][0][i], self.pal[self.bt1][1][i], self.pal[self.bt1][2][i] = MR[i], MG[i], MB[i]
            self.pal[self.bt2][0][i], self.pal[self.bt2][1][i], self.pal[self.bt2][2][i] = PT[i], GL[i], SG[i]
        self.border = self.screen = 6
        self.shown, self.stray, self.table_writes, self.sid, self.knock = [], [], 0, {}, []
        self.sidreg = {}
        self.fire, self.cram = fire, cram
        self.dc00 = self.dc00_start = dc00
        self.held_key_row = held_key_row      # a key in this row, column 4, is held all the time
        self.cia_touched = False
        self.bad_writes = []
        m = self.mem
        m.subscribe_to_read([0xD7FA], lambda a: self.frame() & 255)
        m.subscribe_to_read([0xD610], self.key_read)
        m.subscribe_to_write([0xD610], self.key_write)
        m.subscribe_to_read([0xD070], lambda a: self.d070)
        m.subscribe_to_write([0xD070], lambda a, v: setattr(self, 'd070', v))
        m.subscribe_to_read([0xD020], lambda a: self.border)
        m.subscribe_to_read([0xD021], lambda a: self.screen)
        m.subscribe_to_write([0xD020], lambda a, v: setattr(self, 'border', v))
        m.subscribe_to_write([0xD021], lambda a, v: setattr(self, 'screen', v))
        m.subscribe_to_write([0xD02F], lambda a, v: self.knock.append(v))
        m.subscribe_to_read([0xD030], lambda a: 0x65 if cram else 0x64)
        m.subscribe_to_read([0xDC00], self.porta)
        m.subscribe_to_read([0xDC01], self.portb)
        m.subscribe_to_write([0xDC00], self.porta_write)
        m.subscribe_to_write([0xDC01], self.cia_bad)
        m.subscribe_to_read(range(0xD100, 0xD400), self.pal_read)
        m.subscribe_to_write(range(0xD100, 0xD400), self.pal_write)
        m.subscribe_to_write(range(0xD400, 0xD480), self.sid_write)
        m.subscribe_to_write(range(0x0000, 0x0100), self.ram_write)
        m.subscribe_to_write(range(0x0200, 0xD000), self.ram_write)

    def frame(self):
        return self.mpu.processorCycles // CPF

    def ram_write(self, a, v):
        if a not in VARS:
            self.bad_writes.append(a)

    # CIA 1: port A drives the keyboard rows and reads joystick 2; port B reads the columns
    # and joystick 1. Fire is bit 4, low when down.
    def porta(self, a):
        if self.cram:
            self.cia_touched = True
        j1, j2 = self.fire(self.frame())
        return self.dc00 & (0xEF if j2 else 0xFF)

    def portb(self, a):
        if self.cram:
            self.cia_touched = True
        j1, j2 = self.fire(self.frame())
        v = 0xEF if j1 else 0xFF
        if not (self.dc00 >> self.held_key_row) & 1:   # the held key's row is selected
            v &= 0xEF
        return v

    def porta_write(self, a, v):
        if self.cram:
            self.cia_touched = True
        self.dc00 = v

    def cia_bad(self, a, v):
        self.cia_touched = True

    def key_read(self, a):
        return self.keys[0][1] if self.keys and self.keys[0][0] <= self.frame() else 0

    def key_write(self, a, v):
        if self.keys and self.keys[0][0] <= self.frame():
            self.keys.pop(0)

    def pal_read(self, a):
        return self.pal[self.d070 >> 6][(a - 0xD100) >> 8][a & 255]

    def pal_write(self, a, v):
        bank, ch, ent = self.d070 >> 6, (a - 0xD100) >> 8, a & 255
        if bank != self.disp:
            self.table_writes += 1
        elif ent != 254:
            self.stray.append((a, v))
        self.pal[bank][ch][ent] = v
        if ent == 254 and ch == 2 and bank == self.disp:
            self.shown.append(tuple(self.pal[bank][c][254] for c in range(3)))

    def sid_write(self, a, v):
        # the first write of a register in a frame is the engine's frame-start write;
        # on the last frame, the exit writes come after it
        self.sid.setdefault(self.frame(), {}).setdefault(a, v)
        self.sidreg[a] = v

    def run(self, params, max_frames=6000):
        params = dict(params, BT1=self.bt1, BT2=self.bt2)
        for k, v in params.items():
            self.mem[P[k]] = v
        mpu = self.mpu
        mpu.pc, mpu.sp = STUB, 0xFF
        mpu.p &= ~mpu.INTERRUPT
        stalled = False
        while mpu.pc != STUB + 3:
            mpu.step()
            if self.stall_at and not stalled and self.frame() == self.stall_at:
                mpu.processorCycles += 3 * CPF
                stalled = True
            if self.frame() > max_frames:
                raise RuntimeError("engine did not return")
        self.sp_end = mpu.sp
        return {k: self.mem[a] for k, a in P.items()}


def check(cond, msg):
    print(('  PASS ' if cond else '  FAIL ') + msg)
    if not cond:
        check.failed += 1


check.failed = 0


def params(inc, soft, k, sound, echo=1, mod=1, pal=1, vs=10, vt=8, edly=3):
    return dict(INCL=inc & 255, INCH=inc >> 8, SOFT=soft, K=k, SOUND=sound, ECHO=echo, MOD=mod,
                PAL=pal, KFL=KF & 255, KFH=KF >> 8, VS=vs, VT=vt, EDLY=edly)


def scenario(code, d070, name, inc, soft, k, keys=(), max_frames=6000, sound=3, echo=1, mod=1,
             pal=1, fire=lambda f: (False, False), cram=False):
    m = Machine(code, d070, keys=keys, fire=fire, cram=cram)
    r = m.run(params(inc, soft, k, sound, echo, mod, pal), max_frames=max_frames)
    readable = (lambda f: any(fire(f))) if not cram else (lambda f: False)
    model = Model(inc, soft, k, sound, echo, mod, pal=pal, fire=readable)
    exp_cols, exp_snd = [], []
    frame_keys = {}
    for kf, ch in keys:
        frame_keys.setdefault(kf, []).append(ch)
    f, stopped = 0, False
    while not stopped and f <= max_frames:
        # model frame f is the engine's frame after the f-th counter change (emulator frame f + 1)
        shown, writes, stopped = model.frame(frame_keys.get(f + 1, [None])[0])
        exp_cols.append(shown)
        exp_snd.append(writes)
        f += 1
    got = m.shown[1:]
    n = min(len(got), len(exp_cols))
    first_bad = next((i for i in range(n) if got[i] != exp_cols[i]), None)
    check(first_bad is None and len(got) == len(exp_cols),
          f"{name}: picture, {len(got)} frames match the model ({len(exp_cols)})"
          + ("" if first_bad is None else f" (first mismatch at frame {first_bad})"))
    bad = None
    for i, w in enumerate(exp_snd):
        g = m.sid.get(i + 1, {})
        diff = {a: (g.get(a), v) for a, v in w.items() if g.get(a) != v}
        if diff:
            bad = (i, {f"${a:04X}": f"got {x} want {y}" for a, (x, y) in list(diff.items())[:4]})
            break
    check(bad is None, f"{name}: sound, {len(exp_snd)} frames of SID writes match the model"
          + ("" if bad is None else f" (first mismatch at frame {bad[0]}: {bad[1]})"))
    check(r['EXIT'] == model.exit, f"{name}: exit code {r['EXIT']} (model {model.exit})")
    check(not m.bad_writes and m.sp_end == 0xFF,
          f"{name}: RAM writes only in $1E80-$1EFF and the stack; stack balanced"
          + (f" (stray writes at {sorted({f'${a:04X}' for a in m.bad_writes})[:5]})" if m.bad_writes else ""))
    return m, r, model, [m.sid.get(i + 1, {}) for i in range(len(exp_snd))], got


def suite(code, d070):
    # in turns, near the top: one whole white/black segment, one turn of the wheel, white/black again
    m, r, md, snd, shown = scenario(code, d070, "in turns, full, from 24.2 Hz", 0x7C00, 0, 150,
                                    max_frames=4000)
    check(not m.stray and m.table_writes == 0, "only entry 254 of the text bank written, tables untouched")
    check(m.border == 6 and m.screen == 6 and m.d070 == m.d070_start, "border, background, $D070 restored")
    check(not (m.mpu.p & m.mpu.INTERRUPT) and m.knock[:2] == [0x47, 0x53], "interrupts on again; VIC-IV knock")
    check(m.dc00 == m.dc00_start, f"CIA 1 port A put back to ${m.dc00_start:02X}")
    check(r['MISS'] == 0, "no missed frames")
    check(r['EXIT'] == 0 and len(shown) == md.top, f"ends by itself at 25 Hz, frame {md.top}")
    frames = r['FR0'] + 256 * r['FR1'] + 65536 * r['FR2']
    check(frames == len(shown), f"frame count {frames} reported")
    check(shown[0] == WHITE, "the first frame is white")
    bw = [s for s, (cyc, seg, hh) in zip(shown, md.log) if seg == 0]
    check(set(bw) == {WHITE, BLACK}, "white against black shows nothing but full white and full black")
    first_colour = next(i for i, (cyc, seg, hh) in enumerate(md.log) if seg == 1)
    yellow = Model(0x1000, 0, 6)
    yellow.seg, yellow.hh = 1, 43
    yellow.colours()
    check(md.log[first_colour][0] == 256 and shown[first_colour] == yellow.A,
          f"after 256 flashes the wheel starts at entry 43, yellow {yellow.A} against blue {yellow.B}")
    back = next(i for i in range(first_colour, len(md.log)) if md.log[i][1] == 0)
    check(md.log[back][0] == 512 and shown[back] == WHITE and md.log[back - 1][2] == 42,
          "after one whole turn (256 flashes, back round to entry 42) white against black returns")
    pitches = {(w[0xD401], w[0xD441]) for w, (cyc, seg, hh) in zip(snd, md.log) if seg == 0}
    check(pitches == {(128, 16)}, f"tick pitch: white {sorted(pitches)[0][0]}, black {sorted(pitches)[0][1]}")
    col = [(w[0xD401], w[0xD441]) for w, (cyc, seg, hh) in zip(snd, md.log) if seg == 1]
    check(any(abs(a - b) <= 1 for a, b in col) and max(a - b for a, b in col) > 60,
          f"colour ticks: up to {max(a - b for a, b in col)} apart, the same where both colours are equally light")
    fns = [w[0xD420] + 256 * w[0xD421] for w in snd]
    fcs = [w[0xD436] for w in snd]
    check(all(b >= a for a, b in zip(fns, fns[1:])) and all(b >= a for a, b in zip(fcs, fcs[1:])),
          "tone pitch and filter only rise")
    off = all(m.sidreg.get(a) == 0 for a in (0xD418, 0xD438, 0xD458, 0xD478)) and \
        all(m.sidreg.get(a) in (0x80, 0x40) for a in (0xD404, 0xD40B, 0xD444, 0xD44B, 0xD424, 0xD42B, 0xD464, 0xD46B))
    check(off, "on exit: all gates off, all four SID volumes 0")
    # soft, near the top
    m, r, md, snd, shown = scenario(code, d070, "in turns, soft, from 24.2 Hz", 0x7C00, 1, 150,
                                    max_frames=4000)
    bw = {s for s, (cyc, seg, hh) in zip(shown, md.log) if seg == 0}
    check(bw == {(GL[179],) * 3, (GL[77],) * 3}, f"soft white against black: {sorted(bw)}")
    # white against black only: past flash 256 and 512 nothing changes
    m, r, md, snd, shown = scenario(code, d070, "white against black, full", 0x7C00, 0, 150,
                                    max_frames=4000, pal=0)
    check(md.cycles > 512 and set(shown) == {WHITE, BLACK} and {seg for c, seg, h in md.log} == {0}
          and m.shown[0] == WHITE,
          f"white against black: {md.cycles} flashes, nothing but full white and full black")
    # the colour wheel alone: from entry 43, one step a flash, on through flash 256 and 512
    m, r, md, snd, shown = scenario(code, d070, "colour wheel, full", 0x7C00, 0, 150,
                                    max_frames=4000, pal=2)
    yellow = Model(0x1000, 0, 6, pal=2)
    hues = [h for c, seg, h in md.log]
    steps = all((b - a) & 255 == (cb - ca) & 255 for (ca, sa, a), (cb, sb, b) in zip(md.log, md.log[1:]))
    check(m.shown[0] == yellow.A and shown[0] == yellow.A and {seg for c, seg, h in md.log} == {1},
          f"colour wheel: the first frame is entry 43, yellow {yellow.A}, before and after the screen points at it")
    check(md.cycles > 512 and steps and hues[0] == 43 and len(set(hues)) == 256
          and WHITE not in shown and BLACK not in shown,
          f"colour wheel: {md.cycles} flashes, one step each, all 256 entries, never white or black")
    at256 = next(i for i, (c, seg, h) in enumerate(md.log) if c == 256)
    check(md.log[at256][2] == 43 and md.log[at256 - 1][2] == 42, "colour wheel: flash 256 is entry 43 again")
    # the colour wheel alone at Soft: every channel stays within 0.5 +- 0.2 in linear light
    m, r, md, snd, shown = scenario(code, d070, "colour wheel, soft", 0x7C00, 1, 150,
                                    max_frames=4000, pal=2)
    soft = {GL[v] for v in range(77, 180)}
    check(all(ch in soft for s in shown for ch in s), "colour wheel, soft: no channel beyond 77..179 of 255")
    # the whole accelerando at its fastest setting, from 3.125 Hz
    m, r, md, snd, shown = scenario(code, d070, "whole run, K = 1", 0x1000, 0, 1, max_frames=4000)
    f0, f1 = snd[0][0xD420] + 256 * snd[0][0xD421], snd[-1][0xD420] + 256 * snd[-1][0xD421]
    hz = lambda fn: fn * 984375 / 2 ** 24
    check(r['EXIT'] == 0 and len(shown) == md.top == 541 and abs(hz(f0) - 100) < .1 and hz(f1) > 795,
          f"541 steps, ends by itself; tone from {hz(f0):.1f} Hz to {hz(f1):.1f} Hz")
    # echo: a tick at frame t sounds again on the other side at frame t + 3
    ok = all((snd[i][0xD44B] == 0x81) == (snd[i - 3][0xD404] == 0x81) and
             (snd[i][0xD40B] == 0x81) == (snd[i - 3][0xD444] == 0x81) for i in range(3, len(snd)))
    check(ok and any(w[0xD44B] == 0x81 for w in snd), "echo: each tick again 3 refreshes later on the other side")
    # sound layers: tick only, tone only, off
    for layer, name in ((1, "tick only"), (2, "tone only"), (0, "sound off")):
        m, r, md, snd, shown = scenario(code, d070, name, 0x2000, 0, 3, sound=layer, max_frames=4000)
        ticks = any(w[0xD404] == 0x81 or w[0xD444] == 0x81 for w in snd)
        tone = any(w[0xD424] == 0x41 for w in snd)
        check(ticks == bool(layer & 1) and tone == bool(layer & 2), f"{name}: ticks {ticks}, tone {tone}")
    # any key stops: the first key in the queue, whatever it is
    for ch in (0x20, 0x73, 0x0D, 0x03):
        m, r, md, snd, shown = scenario(code, d070, f"key ${ch:02X}", 0x2000, 0, 50, keys=[(100, ch)])
        check(len(shown) == 100, f"key ${ch:02X} stops it in the frame it arrives ({len(shown)} frames)")
    # a key left in the queue before the start does not stop it
    m = Machine(code, d070, keys=[(0, 0x0D), (0, 0x54)])
    r = m.run(params(0x7C00, 0, 150, 3), max_frames=4000)
    check(r['EXIT'] == 0, "keys already queued at the start are dropped, not taken as a stop")
    # fire on port 2, then on port 1
    for port in (0, 1):
        fire = (lambda f, p=port: (f >= 200, False) if p else (False, f >= 200))
        m, r, md, snd, shown = scenario(code, d070, f"fire on port {2 - port}", 0x2000, 0, 50, fire=fire)
        check(r["EXIT"] == 0xFF and len(shown) == 200, f"fire on port {2 - port} stops it ({len(shown)} frames)")
    # a button held at the start must be let go first; it then stops the piece when pressed again
    fire = lambda f: (False, f < 50 or f >= 300)
    m, r, md, snd, shown = scenario(code, d070, "fire held at the start", 0x2000, 0, 50, fire=fire)
    check(r["EXIT"] == 0xFF and len(shown) == 300, f"held at the start: ignored, the next press stops it "
          f"({len(shown)} frames)")
    # a held keyboard key in the selected row looks like fire on port 1 unless no row is selected
    m, r, md, snd, shown = scenario(code, d070, "row 7 key held", 0x7C00, 0, 150, max_frames=4000)
    check(r['EXIT'] == 0, "a key held in the row selected before the start is not taken for fire")
    # colour RAM at $DC00: the CIA is not touched at all, keys still stop it
    m, r, md, snd, shown = scenario(code, d070, "colour RAM at $DC00", 0x2000, 0, 50, keys=[(150, 0x20)],
                                    fire=lambda f: (f >= 100, f >= 100), cram=True)
    check(not m.cia_touched and r['EXIT'] == 0x20 and len(shown) == 150,
          "colour RAM at $DC00: no CIA access, fire ignored, the key stops it")
    # a stall of three frames is counted
    m = Machine(code, d070, keys=[(60, 0x20)], stall_at=20)
    r = m.run(params(0x2000, 1, 50, 0))
    check(r['MISS'] == 3, f"stall of 3 frames reported as {r['MISS']} missed")


def main():
    code = open(sys.argv[1], 'rb').read()
    end = ORG + len(code)
    check(end <= 0x1E80, f"engine ${ORG:04X}-${end - 1:04X}, {len(code)} bytes, below the variables at $1E80")
    for d070 in (0x01, 0xFF):
        print(f"$D070 = ${d070:02X}: text palette in bank {(d070 >> 4) & 3}")
        suite(code, d070)
    print("failures:", check.failed)
    sys.exit(1 if check.failed else 0)


if __name__ == '__main__':
    main()
