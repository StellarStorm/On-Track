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
"""

from pathlib import Path

from fontTools.pens.recordingPen import RecordingPen
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
    font.save(path)
    print(f'Redrew {"".join(DRAWINGS)} in {path.name}')
    # The same font as WOFF, for browsers without WOFF2.
    copy = path.with_suffix('.woff')
    font.flavor = 'woff'
    font.save(copy)
    print(f'Wrote {copy.name}')


if __name__ == '__main__':
    redraw(FONT)
