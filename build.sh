#!/bin/sh
# UNDERTONE 1.0: rebuild the release disk from source and run every test.
# Needs Python 3 with py65, d64 and Pillow (pip install py65 d64 pillow).
# Usage: sh build.sh        Output: build/UNDERTONE.D81 and its SHA-256.
set -e
cd "$(dirname "$0")"
mkdir -p build

echo "engine: assemble, then test it in a 6502 emulator"
python3 tools/asm6502.py src/engine.asm src/engine.bin src/engine.lst
python3 src/test_engine_v1.py src/engine.bin > build/engine-tests.txt
tail -n 1 build/engine-tests.txt

echo "program: readable source to numbered BASIC 65 listing, lint"
python3 tools/bas65pp.py src/undertone.b65 build/undertone.bas
python3 tools/lint_basic.py build/undertone.bas | tail -n 1

echo "program: run it in the BASIC 65 simulator"
python3 src/sim_undertone.py build/undertone.bas src/engine.bin build/screens > build/simulator.txt
tail -n 1 build/simulator.txt

echo "release: tokenise, write the disk"
python3 tools/bas65tok.py build/undertone.bas build/UNDERTONE.prg
python3 tools/make_d81.py --disk build/UNDERTONE.D81 "UNDERTONE 1.0" PS \
    UNDERTONE=build/UNDERTONE.prg:prg AUTOBOOT.C65=build/UNDERTONE.prg:prg \
    UNDERTONE.SRC=build/undertone.bas:listing LICENSE=LICENSE:text
sha256sum build/UNDERTONE.D81
