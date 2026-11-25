"""Turn the SEPTA logo into LED dots for the board's title bar.

Samples ``septa-logo.svg`` onto a grid of dots and writes the result into
``templates/board.html``, between the ``LOGO START`` and ``LOGO END``
comments. Each dot takes the color that covers most of it. Rerun after
changing the size or the colors::

    uv run scripts/logo_dots.py

The SVG is SEPTA's logo from Wikimedia Commons
(https://commons.wikimedia.org/wiki/File:SEPTA.svg). Only what that file
uses is supported: ``rect`` and ``path`` elements filled with a flat color,
and the path commands M, L, H, V, C and Z.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / 'scripts' / 'septa-logo.svg'
BOARD = ROOT / 'templates' / 'board.html'

# The title bar is 13 dots tall; this leaves a dot above and below.
ROWS = 11
# Samples per dot along each side.
SAMPLES = 6
# The SVG's fills, the letter each gets in the drawing, and the LED color it
# lights. The blue is darker than the logo's so it shows on the blue bar.
COLORS = {
    '#FFFFFF': ('w', '#f2f7ff'),
    '#F14728': ('r', '#ff4a2a'),
    '#1F4FA3': ('b', '#1d2a6b'),
}
CURVE_STEPS = 24

Point = tuple[float, float]


def path_outlines(d: str) -> list[list[Point]]:
    """The closed outlines of an SVG path, with curves cut into lines."""
    tokens = re.findall(r'[A-Za-z]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?', d)
    outlines: list[list[Point]] = []
    points: list[Point] = []
    x = y = 0.0
    command = ''
    i = 0

    def numbers(count: int) -> list[float]:
        nonlocal i
        values = [float(v) for v in tokens[i : i + count]]
        i += count
        return values

    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
        relative = command.islower()
        kind = command.upper()
        if kind == 'Z':
            if points:
                outlines.append(points)
            points = []
            continue
        if kind == 'M':
            if points:
                outlines.append(points)
            dx, dy = numbers(2)
            x, y = (x + dx, y + dy) if relative else (dx, dy)
            points = [(x, y)]
            # Further pairs after a move are lines.
            command = 'l' if relative else 'L'
        elif kind == 'L':
            dx, dy = numbers(2)
            x, y = (x + dx, y + dy) if relative else (dx, dy)
            points.append((x, y))
        elif kind == 'H':
            (dx,) = numbers(1)
            x = x + dx if relative else dx
            points.append((x, y))
        elif kind == 'V':
            (dy,) = numbers(1)
            y = y + dy if relative else dy
            points.append((x, y))
        elif kind == 'C':
            values = numbers(6)
            if relative:
                values = [
                    v + (x if n % 2 == 0 else y) for n, v in enumerate(values)
                ]
            x1, y1, x2, y2, x3, y3 = values
            for step in range(1, CURVE_STEPS + 1):
                t = step / CURVE_STEPS
                u = 1 - t
                points.append(
                    (
                        u**3 * x
                        + 3 * u * u * t * x1
                        + 3 * u * t * t * x2
                        + t**3 * x3,
                        u**3 * y
                        + 3 * u * u * t * y1
                        + 3 * u * t * t * y2
                        + t**3 * y3,
                    )
                )
            x, y = x3, y3
        else:
            raise ValueError(f'Unsupported path command: {command}')
    if points:
        outlines.append(points)
    return outlines


def inside(point: Point, outlines: list[list[Point]]) -> bool:
    """Even-odd test: does a ray from the point cross an odd number of edges?"""
    px, py = point
    crossings = 0
    for outline in outlines:
        for (x1, y1), (x2, y2) in zip(outline, outline[1:] + outline[:1]):
            straddles = (y1 > py) != (y2 > py)
            if straddles and px < x1 + (py - y1) * (x2 - x1) / (y2 - y1):
                crossings += 1
    return crossings % 2 == 1


def read_shapes() -> list[tuple[str, list[list[Point]]]]:
    """Each filled shape in drawing order, as its letter and outlines."""
    shapes = []
    for element in ET.parse(SVG).getroot().iter():
        tag = element.tag.rsplit('}', 1)[-1]
        if tag == 'rect':
            x, y, w, h = (
                float(element.get(name))
                for name in ('x', 'y', 'width', 'height')
            )
            outlines = [[(x, y), (x + w, y), (x + w, y + h), (x, y + h)]]
        elif tag == 'path':
            outlines = path_outlines(element.get('d'))
        else:
            continue
        letter, _ = COLORS[element.get('fill').upper()]
        shapes.append((letter, outlines))
    return shapes


def bounds(shapes) -> tuple[float, float, float, float]:
    xs = [x for _, outlines in shapes for o in outlines for x, _ in o]
    ys = [y for _, outlines in shapes for o in outlines for _, y in o]
    return min(xs), min(ys), max(xs), max(ys)


def draw(shapes) -> list[str]:
    left, top, right, bottom = bounds(shapes)
    columns = round(ROWS * (right - left) / (bottom - top))
    rows = []
    for row in range(ROWS):
        line = ''
        for column in range(columns):
            votes: dict[str, int] = {}
            for i in range(SAMPLES):
                for j in range(SAMPLES):
                    point = (
                        left
                        + (column + (i + 0.5) / SAMPLES)
                        / columns
                        * (right - left),
                        top
                        + (row + (j + 0.5) / SAMPLES) / ROWS * (bottom - top),
                    )
                    letter = '.'
                    for shape_letter, outlines in shapes:
                        if inside(point, outlines):
                            letter = shape_letter
                    votes[letter] = votes.get(letter, 0) + 1
            line += max(votes, key=votes.get)
        rows.append(line)
    return rows


def write(rows: list[str]) -> None:
    indent = ' ' * 6
    colors = ', '.join(f'{letter}: "{led}"' for letter, led in COLORS.values())
    block = (
        f'{indent}// LOGO START: written by scripts/logo_dots.py\n'
        f'{indent}var LOGO = [\n'
        + ''.join(f'{indent}  "{row}",\n' for row in rows)
        + f'{indent}];\n'
        f'{indent}var LOGO_COLORS = {{ {colors} }};\n'
        f'{indent}// LOGO END'
    )
    html = BOARD.read_text()
    pattern = re.compile(r' *// LOGO START.*?// LOGO END', re.DOTALL)
    if not pattern.search(html):
        raise SystemExit(f'No LOGO START/END comments in {BOARD}')
    BOARD.write_text(pattern.sub(lambda _: block, html))


if __name__ == '__main__':
    logo = draw(read_shapes())
    print('\n'.join(logo))
    write(logo)
    print(f'Wrote {len(logo)}x{len(logo[0])} dots to {BOARD.name}')
