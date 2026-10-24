# UNDERTONE

A flicker piece for the MEGA65.

> **Warning.** The whole screen flashes 3 to 25 times a second for up to 30 minutes.
> Flashing light can trigger seizures, even in people who never had one.
> Do not watch if you or your family have a history of epilepsy.
> Stop at once if you feel dizzy, if your sight changes, or if any muscle twitches.
> Watch in a lit room, sit well back, and never when tired.
> Children only with an adult in the room.
> Any key stops the flicker at once.
>
> **At your own risk.** You watch and listen at your own risk. To the full extent the
> law allows, the author, Psinco and anyone who shares or shows this program accept no
> liability for physical or mental injury, or for any other harm or loss, caused by
> watching or hearing it.

## Run

Needs a MEGA65 in PAL (50 Hz).

1. Copy `UNDERTONE.D81` from the release to the SD card.
2. `MOUNT "UNDERTONE.D81"`
3. `LOAD"*",8,1`, then `RUN`

The program shows the full warning before anything flashes. Typing START on the next
screen confirms it. Any key or fire button stops the flicker; Q quits from every screen.

## What it is

The whole screen flashes on the MEGA65's 50 Hz grid, from 3 to 25 times a second. It
always speeds up and ends by itself. Four SID chips tick each time the screen changes and
hum at a pitch that rises with the flicker. Nothing is recorded: picture and sound are
worked out as it runs.

Settings: intensity (Soft or Full), tick, hum, palette (black and white, colour wheel, or
both in turns) and length (3, 10 or 30 minutes).

Inspired by Tony Conrad's *The Flicker* (1966). Nothing of the film is used.

## Source

| Path | What |
|---|---|
| `src/undertone.b65` | the program: readable BASIC 65 source |
| `src/engine.asm` | the flicker and sound engine (6502 code, called with `SYS`) |
| `build/undertone.bas` | the numbered BASIC 65 listing, also on the disk as `UNDERTONE.SRC` |
| `tools/` | assembler driver, transpiler, tokeniser, linter, disk writer, BASIC 65 simulator |
| `src/test_engine_v1.py` | tests the engine in a 6502 emulator |
| `src/sim_undertone.py` | tests the program in the BASIC 65 simulator |

`sh build.sh` rebuilds the disk and runs every test. It needs Python 3 with py65, d64
and Pillow.

## Credits

UNDERTONE 1.0, 2026, by Dawid Blachowski, with Claude, Anthropic's AI.
psinco. A Software Atelier from Luxembourg.

MIT licence: free to use, change and share, with the notice. See [LICENSE](LICENSE).
