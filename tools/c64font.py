"""An approximate Commodore-style 8x8 character set for previews.

Drawn for this project from memory of the look, not copied from a ROM. Only the characters the
UNDERTONE screens use are exact enough to judge layout; everything else is a placeholder box.
upper[code] and lower[code] give 8 row bytes for screen codes 0-255 of each set; codes 128-255
are the inverse of 0-127, as in the built-in sets.
"""

H = lambda s: [int(b, 16) for b in s.split()]

LETTERS = {
    'A': "18 3C 66 7E 66 66 66 00", 'B': "7C 66 66 7C 66 66 7C 00", 'C': "3C 66 60 60 60 66 3C 00",
    'D': "78 6C 66 66 66 6C 78 00", 'E': "7E 60 60 78 60 60 7E 00", 'F': "7E 60 60 78 60 60 60 00",
    'G': "3C 66 60 6E 66 66 3C 00", 'H': "66 66 66 7E 66 66 66 00", 'I': "3C 18 18 18 18 18 3C 00",
    'J': "1E 0C 0C 0C 0C 6C 38 00", 'K': "66 6C 78 70 78 6C 66 00", 'L': "60 60 60 60 60 60 7E 00",
    'M': "63 77 7F 6B 63 63 63 00", 'N': "66 76 7E 7E 6E 66 66 00", 'O': "3C 66 66 66 66 66 3C 00",
    'P': "7C 66 66 7C 60 60 60 00", 'Q': "3C 66 66 66 66 3C 0E 00", 'R': "7C 66 66 7C 78 6C 66 00",
    'S': "3C 66 60 3C 06 66 3C 00", 'T': "7E 18 18 18 18 18 18 00", 'U': "66 66 66 66 66 66 3C 00",
    'V': "66 66 66 66 66 3C 18 00", 'W': "63 63 63 6B 7F 77 63 00", 'X': "66 66 3C 18 3C 66 66 00",
    'Y': "66 66 66 3C 18 18 18 00", 'Z': "7E 06 0C 18 30 60 7E 00",
}
SMALL = {
    'a': "00 00 3C 06 3E 66 3E 00", 'b': "00 60 60 7C 66 66 7C 00", 'c': "00 00 3C 60 60 60 3C 00",
    'd': "00 06 06 3E 66 66 3E 00", 'e': "00 00 3C 66 7E 60 3C 00", 'f': "00 0E 18 3E 18 18 18 00",
    'g': "00 00 3E 66 66 3E 06 7C", 'h': "00 60 60 7C 66 66 66 00", 'i': "00 18 00 38 18 18 3C 00",
    'j': "00 06 00 06 06 06 06 3C", 'k': "00 60 60 6C 78 6C 66 00", 'l': "00 38 18 18 18 18 3C 00",
    'm': "00 00 66 7F 7F 6B 63 00", 'n': "00 00 7C 66 66 66 66 00", 'o': "00 00 3C 66 66 66 3C 00",
    'p': "00 00 7C 66 66 7C 60 60", 'q': "00 00 3E 66 66 3E 06 06", 'r': "00 00 7C 66 60 60 60 00",
    's': "00 00 3E 60 3C 06 7C 00", 't': "00 18 7E 18 18 18 0E 00", 'u': "00 00 66 66 66 66 3E 00",
    'v': "00 00 66 66 66 3C 18 00", 'w': "00 00 63 6B 7F 3E 36 00", 'x': "00 00 66 3C 18 3C 66 00",
    'y': "00 00 66 66 66 3E 0C 78", 'z': "00 00 7E 0C 18 30 7E 00",
}
COMMON = {   # screen codes 0, 27-63, the same in both sets except where noted
    0: "3C 66 6E 6E 60 62 3C 00", 27: "3C 30 30 30 30 30 3C 00", 28: "0C 12 30 7C 30 62 FC 00",
    29: "3C 0C 0C 0C 0C 0C 3C 00", 30: "00 18 3C 7E 18 18 18 18", 31: "00 10 30 7F 7F 30 10 00",
    32: "00 00 00 00 00 00 00 00", 33: "18 18 18 18 00 00 18 00", 34: "66 66 66 00 00 00 00 00",
    35: "66 66 FF 66 FF 66 66 00", 36: "18 3E 60 3C 06 7C 18 00", 37: "62 66 0C 18 30 66 46 00",
    38: "3C 66 3C 38 67 66 3F 00", 39: "06 0C 18 00 00 00 00 00", 40: "0C 18 30 30 30 18 0C 00",
    41: "30 18 0C 0C 0C 18 30 00", 42: "00 66 3C FF 3C 66 00 00", 43: "00 18 18 7E 18 18 00 00",
    44: "00 00 00 00 00 18 18 30", 45: "00 00 00 7E 00 00 00 00", 46: "00 00 00 00 00 18 18 00",
    47: "00 03 06 0C 18 30 60 00", 48: "3C 66 6E 76 66 66 3C 00", 49: "18 18 38 18 18 18 7E 00",
    50: "3C 66 06 0C 30 60 7E 00", 51: "3C 66 06 1C 06 66 3C 00", 52: "06 0E 1E 66 7F 06 06 00",
    53: "7E 60 7C 06 06 66 3C 00", 54: "3C 66 60 7C 66 66 3C 00", 55: "7E 66 0C 18 18 18 18 00",
    56: "3C 66 66 3C 66 66 3C 00", 57: "3C 66 66 3E 06 66 3C 00", 58: "00 00 18 00 00 18 00 00",
    59: "00 00 18 00 00 18 18 30", 60: "0E 18 30 60 30 18 0E 00", 61: "00 00 7E 00 7E 00 00 00",
    62: "70 18 0C 06 0C 18 70 00", 63: "3C 66 06 0C 18 00 18 00",
}
GRAPHICS = {  # upper-case set only
    64: "00 00 00 FF FF 00 00 00", 93: "18 18 18 18 18 18 18 18",
    85: "00 00 00 07 0F 1C 18 18", 73: "00 00 00 E0 F0 38 18 18",
    74: "18 18 1C 0F 07 00 00 00", 75: "18 18 38 F0 E0 00 00 00",
    100: "00 00 00 00 00 00 00 FF",
}
BOTH_GRAPHICS = {64: "00 00 00 FF FF 00 00 00", 93: "18 18 18 18 18 18 18 18", 100: "00 00 00 00 00 00 00 FF"}
QUAD = {97: 5, 98: 12, 108: 8, 123: 4, 124: 2, 126: 1, 127: 9}   # code: TL 1, TR 2, BL 4, BR 8


def quad(mask):
    top = (0xF0 if mask & 1 else 0) | (0x0F if mask & 2 else 0)
    bot = (0xF0 if mask & 4 else 0) | (0x0F if mask & 8 else 0)
    return [top] * 4 + [bot] * 4


def box():
    return [0xFF, 0x81, 0x81, 0x81, 0x81, 0x81, 0x81, 0xFF]


def build():
    upper, lower = [box() for _ in range(256)], [box() for _ in range(256)]
    for code, rows in COMMON.items():
        upper[code] = H(rows)
        lower[code] = H(rows)
    for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        upper[1 + i] = H(LETTERS[ch])
        lower[1 + i] = H(SMALL[ch.lower()])
        lower[65 + i] = H(LETTERS[ch])
    for code, rows in GRAPHICS.items():
        upper[code] = H(rows)
    for code, rows in BOTH_GRAPHICS.items():
        lower[code] = H(rows)
    upper[96] = lower[96] = [0] * 8
    for code, mask in QUAD.items():
        upper[code] = quad(mask)
        lower[code] = quad(mask)
    for s in (upper, lower):
        for c in range(128):
            s[128 + c] = [b ^ 0xFF for b in s[c]]
    return upper, lower


UPPER, LOWER = build()
