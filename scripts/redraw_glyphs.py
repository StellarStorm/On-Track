"""Redraw a few glyphs in the board's copy of the Doto font.

Doto draws ``0`` as a diamond and ``:`` ``;`` ``.`` ``,`` with plus-shaped
clusters of dots. This replaces them with the glyphs drawn below, made from
the font's own dot, and rewrites the font file in place. It also writes a
WOFF copy next to it for older iPads: Safari reads WOFF2 only from iOS 10.
Running it again gives the same result, so edit the drawings and rerun::

    uv run scripts/redraw_glyphs.py

Doto puts every glyph on a grid of dots 100 font units apart. A glyph is 5
dots wide; row 0 sits on the baseline, row 6 is the top of a capital, and
row -1 is below the baseline.

It then reshapes every dot in every glyph into a square filling the top-left
three quarters of its cell. Doto centers each dot in its cell, so on a
low-resolution screen, such as the iPad mini's, where a cell is 4 pixels,
both edges of every dot fall mid-pixel: the half-lit pixels fill in the
gaps and the dots smear into solid strokes. Squares on the cell edge cover
whole pixels (3 lit and 1 dark on a 4-pixel cell, 6 and 2 on 8) and keep the
gaps dark.
"""

from pathlib import Path

from fontTools.pens.recordingPen import DecomposingRecordingPen, RecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

FONT = (
    Path(__file__).resolve().parent.parent
    / 'static'
    / 'fonts'
    / 'doto-latin-700-normal.woff2'
)
GRID = 100
# Width of a reshaped dot, in font units. 75 keeps Doto's proportions and is
# a whole number of pixels when a cell is 4 or 8 pixels.
DOT = 75

# Each drawing lists its rows from top to bottom. The last row of a drawing
# sits on the row given with it: 0 for the baseline, -1 for a descender.
DRAWINGS = {
    '0': (
        0,
        [
            '.###.',
            '#...#',
            '#...#',
            '#...#',
            '#...#',
            '#...#',
            '.###.',
        ],
    ),
    ':': (
        2,
        [
            '..#..',
            '.....',
            '..#..',
        ],
    ),
    ';': (
        -1,
        [
            '..#..',
            '.....',
            '.....',
            '.....',
            '..#..',
            '.#...',
        ],
    ),
    '.': (0, ['..#..']),
    ',': (
        -1,
        [
            '..#..',
            '.#...',
        ],
    ),
}


def cells(bottom_row: int, rows: list[str]) -> list[tuple[int, int]]:
    """The (column, row) of every dot in a drawing."""
    top_row = bottom_row + len(rows) - 1
    return [
        (column, top_row - index)
        for index, row in enumerate(rows)
        for column, mark in enumerate(row)
        if mark == '#'
    ]


def contours(recording: RecordingPen) -> list[list[tuple]]:
    """Split a recorded glyph into its contours."""
    found, current = [], []
    for op, args in recording.value:
        current.append((op, args))
        if op in ('closePath', 'endPath'):
            found.append(current)
            current = []
    return found


def cell(contour: list[tuple]) -> tuple[int, int]:
    """The (column, row) a dot sits in."""
    points = [point for _, args in contour for point in args]
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return (
        int((min(xs) + max(xs)) / 2 // GRID),
        int((min(ys) + max(ys)) / 2 // GRID),
    )


def one_dot(font: TTFont) -> tuple[list[tuple], int, int]:
    """One dot from the font's period, and the cell it sits in.

    Takes the top dot of the period, so a font this script already changed
    yields the same dot as the original Doto.
    """
    recording = RecordingPen()
    font.getGlyphSet()[font.getBestCmap()[ord('.')]].draw(recording)
    dot = max(contours(recording), key=lambda contour: cell(contour)[1])
    column, row = cell(dot)
    return dot, column, row


def square_dots(font: TTFont) -> int:
    """Reshape every dot in the font into a square on its cell's edge.

    Returns the number of glyphs changed. A glyph made of anything but dots
    (none in Doto, apart from .notdef) is left alone.
    """
    glyph_set = font.getGlyphSet()
    glyf = font['glyf']
    hmtx = font['hmtx']
    changed = 0
    for name in font.getGlyphOrder():
        if name == '.notdef':
            continue
        recording = DecomposingRecordingPen(glyph_set)
        glyph_set[name].draw(recording)
        dots = contours(recording)
        if not dots:
            continue
        sizes = []
        for dot in dots:
            points = [point for _, args in dot for point in args]
            xs = [x for x, _ in points]
            ys = [y for _, y in points]
            sizes.append(max(max(xs) - min(xs), max(ys) - min(ys)))
        if max(sizes) > GRID:
            print(f'Left {name} alone: it is not made of dots')
            continue
        pen = TTGlyphPen(None)
        for column, row in sorted({cell(dot) for dot in dots}):
            left, top = column * GRID, (row + 1) * GRID
            # Clockwise, as TrueType expects for an outline.
            pen.moveTo((left, top - DOT))
            pen.lineTo((left, top))
            pen.lineTo((left + DOT, top))
            pen.lineTo((left + DOT, top - DOT))
            pen.closePath()
        glyph = pen.glyph()
        glyph.recalcBounds(glyf)
        glyf[name] = glyph
        width, _ = hmtx[name]
        hmtx[name] = (width, glyph.xMin)
        changed += 1
    return changed


def redraw(path: Path) -> None:
    # Keep the saved date, so rerunning leaves the files byte-for-byte the same.
    font = TTFont(path, recalcTimestamp=False)
    dot, dot_column, dot_row = one_dot(font)
    cmap = font.getBestCmap()
    glyf = font['glyf']
    hmtx = font['hmtx']
    for char, (bottom_row, rows) in DRAWINGS.items():
        pen = TTGlyphPen(None)
        for column, row in cells(bottom_row, rows):
            dx = (column - dot_column) * GRID
            dy = (row - dot_row) * GRID
            moved = TransformPen(pen, (1, 0, 0, 1, dx, dy))
            for op, args in dot:
                getattr(moved, op)(*args)
        glyph = pen.glyph()
        glyph.recalcBounds(glyf)
        name = cmap[ord(char)]
        glyf[name] = glyph
        width, _ = hmtx[name]
        hmtx[name] = (width, glyph.xMin)
    count = square_dots(font)
    font.save(path)
    print(f'Redrew {"".join(DRAWINGS)} and squared the dots of {count} glyphs')
    print(f'Wrote {path.name}')
    # The same font as WOFF, for browsers without WOFF2.
    copy = path.with_suffix('.woff')
    font.flavor = 'woff'
    font.save(copy)
    print(f'Wrote {copy.name}')


if __name__ == '__main__':
    redraw(FONT)
