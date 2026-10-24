"""Build a D81 image.

Two forms:

  python3 make_d81.py LISTING.bas OUT.d81 "DISK NAME" ID FILENAME [NAME=TEXTFILE ...]
      The test-bench form: the listing as a SEQ file (for MOUNT / IMPORT / DSAVE / RUN),
      then optional text files.

  python3 make_d81.py --disk OUT.d81 "DISK NAME" ID NAME=PATH:KIND [NAME=PATH:KIND ...]
      Files in the order given; the first PRG is what LOAD"*" and RUN"*" (SHIFT+RUN/STOP) load.
      KIND is prg (the file's bytes as they are, load address included), listing (a BASIC
      listing as SEQ) or text (a text file as SEQ).

Listings must use only ASCII 0x20-0x5E (upper-case letters, digits, punctuation); those bytes
are identical in PETSCII. Lines end with CR (0x0D). Text files are converted to upper case,
joined into paragraphs and wrapped at 38 columns, so TYPE shows them in either character set.
"""
import sys
import textwrap
from pathlib import Path

from d64 import DiskImage

ALLOWED = set(range(0x20, 0x5F))  # 0x5E: PETSCII up-arrow, the power operator


def petscii_lines(lines, where):
    out = bytearray()
    for n, line in enumerate(lines, 1):
        raw = line.rstrip().encode('ascii')
        bad = [chr(b) for b in raw if b not in ALLOWED]
        if bad:
            sys.exit(f"{where} line {n}: characters outside the safe PETSCII range: {bad}")
        out += raw + b'\r'
    return bytes(out)


def petscii_listing(path):
    return petscii_lines([l for l in Path(path).read_text().splitlines() if l.strip()], path)


def petscii_text(path, width=38):
    """Paragraphs (separated by blank lines) are joined and wrapped at 38 columns."""
    lines = []
    for para in Path(path).read_text().upper().split('\n\n'):
        words = ' '.join(para.split())
        if lines:
            lines.append('')
        lines += textwrap.wrap(words, width) if words else ['']
    return petscii_lines(lines, path)


def write_disk(out, disk_name, disk_id, files):
    """files: list of (name, bytes, 'PRG' or 'SEQ')."""
    out_path = Path(out)
    if out_path.exists():
        out_path.unlink()
    DiskImage.create('d81', out_path, disk_name.encode(), disk_id.encode())
    with DiskImage(out_path, mode='w') as image:
        for name, data, ftype in files:
            with image.path(name.encode()).open('w', ftype=ftype) as f:
                f.write(data)
    for name, data, ftype in files:
        print(f"{out}: {name} {ftype}, {len(data)} bytes")


def main():
    args = sys.argv[1:]
    if args and args[0] == '--disk':
        out, disk_name, disk_id = args[1:4]
        files = []
        for spec in args[4:]:
            name, rest = spec.split('=', 1)
            path, kind = rest.rsplit(':', 1)
            if kind == 'prg':
                files.append((name, Path(path).read_bytes(), 'PRG'))
            elif kind == 'listing':
                files.append((name, petscii_listing(path), 'SEQ'))
            elif kind == 'text':
                files.append((name, petscii_text(path), 'SEQ'))
            else:
                sys.exit(f"unknown kind {kind!r} in {spec!r}")
        write_disk(out, disk_name, disk_id, files)
        return
    src, out, disk_name, disk_id, fname = args[0:5]
    files = [(fname, petscii_listing(src), 'SEQ')]
    for extra in args[5:]:
        name, path = extra.split('=', 1)
        files.append((name, petscii_text(path), 'SEQ'))
    write_disk(out, disk_name, disk_id, files)


if __name__ == '__main__':
    main()
