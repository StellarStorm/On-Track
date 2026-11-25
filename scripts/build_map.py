"""Build the Regional Rail map and station list from SEPTA's data.

Downloads SEPTA's latest GTFS release from GitHub (or reads a zip you
already have), takes each line's stations in order, lays them out on the
schematic described in LAYOUT below, and writes ``static/map.json``. Run it
again when SEPTA publishes new data::

    uv run scripts/build_map.py
    uv run scripts/build_map.py --zip ~/Downloads/gtfs_public.zip

Only the small rail feed inside the release is used, and nothing is kept
but the JSON.

It also saves SEPTA's list of Regional Rail stations, with the exact name
its departures API expects for each, to ``static/stations.json`` for the
control page's station picker.

The layout is a grid where one unit is the usual gap between stations; x
grows to the right and y grows downward. Each line lists the points its
track passes through, starting at a station already on the map: stations
pinned to a position, and bare corners. The line's other stations are
spaced evenly along the track between the pinned ones.

Station names are placed automatically: each tries the line's preferred
side first, then the others, and takes the first spot that doesn't run into
another name, a track or a station.
"""

import argparse
import csv
import html
import io
import json
import math
import re
import urllib.request
import zipfile
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'static' / 'map.json'
STATIONS_OUTPUT = ROOT / 'static' / 'stations.json'
# SEPTA's table of station names and the name its API expects for each.
STATION_LIST = 'https://www3.septa.org/VIRegionalRail.html'
RELEASES = 'https://api.github.com/repos/septadev/GTFS/releases/latest'
USER_AGENT = 'on-track-map-builder'

Point = tuple[float, float]

# Center City, drawn first. Every station here is pinned.
TRUNK = [
    ('Penn Medicine Station', -4, 3),
    ('Gray 30th St Station', -4, 0),
    ('Suburban Station', -2, 0),
    ('Jefferson Station', 0, 0),
    ('Temple University', 2, -2),
]

# Each line, in the order they're placed: its color, the side its station
# names prefer, and its track.
#
# The colors are what a lit station shows on screen, so they are bright and
# chosen to stay apart from each other, with neighboring lines given
# clearly different hues. A track starts at a station already placed
# (a 1-tuple), then lists pinned stations (name, x, y) and corners (x, y).
# Its last point must be the end of the line.
#
# 'side' is for stations on upright or slanted track: 'left' or 'right'.
# 'level' is for stations on level track: 'above' or 'below', where the
# name is angled up or down to the right.
LAYOUT = {
    'LAN': {
        'color': '#ff3b30',
        'side': 'left',
        'level': 'above',
        'track': [
            ('Temple University',),
            ('North Broad', 2, -5),
            ('Wayne Junction', 2, -8),
            ('Fern Rock Transit Center', 2, -10),
            ('Glenside', 2, -16),
            ('Lansdale', 2, -26),
            (2, -28),
            ('Doylestown', 8, -28),
        ],
    },
    'WAR': {
        'color': '#ff9500',
        'side': 'right',
        'track': [('Glenside',), ('Warminster', 8, -22)],
    },
    'WTR': {
        'color': '#9d5cff',
        'side': 'right',
        'level': 'above',
        'track': [
            ('Jenkintown-Wyncote',),
            (5.5, -14.5),
            ('West Trenton', 15, -24),
        ],
    },
    'FOX': {
        'color': '#00c3ff',
        'side': 'right',
        'level': 'above',
        'track': [('Wayne Junction',), (3.5, -9.5), ('Fox Chase', 9, -9.5)],
    },
    'CHE': {
        'color': '#1fd65f',
        'side': 'left',
        'level': 'below',
        'track': [
            ('Wayne Junction',),
            (-3.5, -8),
            ('Chestnut Hill East', -3.5, -20),
        ],
    },
    'NOR': {
        'color': '#ff3fd0',
        'side': 'right',
        'level': 'below',
        'track': [
            ('North Broad',),
            (-5, -5),
            ('Norristown Elm Street', -15, -15),
        ],
    },
    'TRE': {
        'color': '#3d6bff',
        'side': 'right',
        'level': 'below',
        'track': [
            ('Gray 30th St Station',),
            ('North Philadelphia Amtrak', -4, -3),
            ('Bridesburg', 4, -3),
            ('Trenton Transit Center', 14, -3),
        ],
    },
    'CHW': {
        'color': '#a3ff12',
        'side': 'left',
        'track': [
            ('North Philadelphia Amtrak',),
            (-6, -3),
            ('Chestnut Hill West', -16, -13),
        ],
    },
    'CYN': {
        'color': '#c8a2ff',
        'side': 'left',
        'track': [('Gray 30th St Station',), ('Cynwyd', -6, -2)],
    },
    'PAO': {
        'color': '#ffd60a',
        'side': 'left',
        'level': 'below',
        'track': [
            ('Gray 30th St Station',),
            ('Paoli', -25, 0),
            ('Thorndale', -29, 4),
        ],
    },
    'MED': {
        'color': '#00e5c0',
        'side': 'left',
        'level': 'below',
        'track': [
            ('Penn Medicine Station',),
            (-8, 7),
            ('Wawa', -19, 7),
        ],
    },
    'WIL': {
        'color': '#ff7a9c',
        'side': 'right',
        'track': [
            ('Penn Medicine Station',),
            (-4, 12),
            ('Newark DE', -12, 20),
        ],
    },
    'AIR': {
        'color': '#e0b080',
        'side': 'right',
        'track': [
            ('Penn Medicine Station',),
            (0.5, 3),
            ('Airport Terminals E & F', 0.5, 10),
        ],
    },
}

# Station names on the map, where SEPTA's are long or unclear.
LABELS = {
    'Gray 30th St Station': '30th Street',
    'Penn Medicine Station': 'Penn Medicine',
    'Suburban Station': 'Suburban',
    'Jefferson Station': 'Jefferson',
    'Fern Rock Transit Center': 'Fern Rock TC',
    'Norristown Transit Center': 'Norristown TC',
    'Chester Transit Center': 'Chester TC',
    'Trenton Transit Center': 'Trenton',
    'Claymont Transit Center': 'Claymont',
    'North Philadelphia Amtrak': 'North Philadelphia',
    'North Philadelphia Septa': 'North Phila (CHW)',
    'Delaware Valley University': 'Delaware Valley U',
    'Airport Terminal A': 'Terminal A',
    'Airport Terminal B': 'Terminal B',
    'Airport Terminals C & D': 'Terminals C & D',
    'Airport Terminals E & F': 'Terminals E & F',
    'Norristown Elm Street': 'Elm Street',
}

# Stations whose name must go on a given side, skipping the automatic
# placement.
LABEL_SIDES = {'Penn Medicine Station': 'left'}

# Name sizes, in grid units. These must match labelFor() and the .label
# font size in templates/map.html.
FONT = 0.42
CHAR = 0.6 * FONT
GAP = 0.42
DIAG = math.sqrt(0.5)
# How close a name may come to another name, a track, or a station dot.
CLEAR_NAME = 0.42
CLEAR_TRACK = 0.26
CLEAR_DOT = 0.4

# The legend: its top-left corner, in an empty part of the map, and its
# size. ROW and SWATCH must match drawLegend() in templates/map.html.
LEGEND = (-29, -28)
LEGEND_ROW = 0.75
LEGEND_SWATCH = 0.7


def download_release() -> bytes:
    """The latest gtfs_public.zip from SEPTA's GitHub releases."""
    request = urllib.request.Request(
        RELEASES, headers={'User-Agent': USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    asset = next(a for a in release['assets'] if a['name'] == 'gtfs_public.zip')
    print(
        f'Downloading {asset["name"]} from release {release["tag_name"]} '
        f'({asset["size"] / 1e6:.1f} MB)'
    )
    request = urllib.request.Request(
        asset['browser_download_url'], headers={'User-Agent': USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def parse_station_list(page: str) -> list[dict[str, str]]:
    """Station names and API names from SEPTA's station list page.

    The page has a table whose rows are the station's name and the
    parameter the API takes, such as ``Fern Rock Transportation Center``
    and ``Fern Rock TC``.
    """
    rows = re.findall(
        r'<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>', page, re.DOTALL
    )
    stations = [
        {'name': html.unescape(name).strip(), 'api': html.unescape(api).strip()}
        for name, api in rows
    ]
    return sorted(
        (s for s in stations if s['name'] and s['api']),
        key=lambda s: s['name'].lower(),
    )


def download_station_list() -> list[dict[str, str]]:
    request = urllib.request.Request(
        STATION_LIST, headers={'User-Agent': USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return parse_station_list(response.read().decode('utf-8', 'replace'))


def read_rail_feed(release: bytes) -> dict[str, list[dict]]:
    """The rail feed's tables, by file name without the .txt."""
    with zipfile.ZipFile(io.BytesIO(release)) as outer:
        rail = outer.read('google_rail.zip')
    tables = {}
    with zipfile.ZipFile(io.BytesIO(rail)) as feed:
        for name in ('stops', 'routes', 'directions', 'route_stops'):
            text = feed.read(f'{name}.txt').decode('utf-8-sig')
            tables[name] = list(csv.DictReader(io.StringIO(text)))
        if 'feed_info.txt' in feed.namelist():
            text = feed.read('feed_info.txt').decode('utf-8-sig')
            tables['feed_info'] = list(csv.DictReader(io.StringIO(text)))
    return tables


def outbound_sequences(tables) -> dict[str, list[str]]:
    """Each line's stop ids in order, leaving Center City."""
    outbound = {
        (row['route_id'], row['direction_id'])
        for row in tables['directions']
        if row['direction'] == 'Outbound'
    }
    sequences: dict[str, list[tuple[int, str]]] = {}
    for row in tables['route_stops']:
        key = (row['route_id'], row['direction_id'])
        if key in outbound:
            sequences.setdefault(row['route_id'], []).append(
                (int(row['route_stop_sort_order']), row['stop_id'])
            )
    return {
        route: [stop for _, stop in sorted(stops)]
        for route, stops in sequences.items()
    }


def along(points: list[Point], distance: float) -> Point:
    """The point a distance along a polyline."""
    for (x1, y1), (x2, y2) in pairwise(points):
        piece = math.hypot(x2 - x1, y2 - y1)
        if distance <= piece or (x2, y2) == points[-1]:
            t = 0 if piece == 0 else min(distance / piece, 1)
            return (x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
        distance -= piece
    return points[-1]


def length(points: list[Point]) -> float:
    return sum(
        math.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in pairwise(points)
    )


def place_line(route, sequence, layout, ids, placed) -> list[Point]:
    """Place a line's new stations; return its track as points."""
    track = layout['track']
    start_name = track[0][0]
    start = ids[start_name]
    if start not in placed:
        raise SystemExit(f'{route}: {start_name} is not on the map yet')
    new = [stop for stop in sequence if stop not in placed]
    section = [start, *new]

    # The track's points, and which of them are pinned stations.
    points: list[Point] = [placed[start]]
    pins = {start: 0}
    for item in track[1:]:
        if len(item) == 3:
            name, x, y = item
            stop = ids.get(name)
            if stop not in section:
                raise SystemExit(f'{route}: {name} is not a new stop here')
            pins[stop] = len(points)
            points.append((x, y))
        else:
            points.append(item)
    if section[-1] not in pins or pins[section[-1]] != len(points) - 1:
        raise SystemExit(f'{route}: the track must end at the last stop')

    # Space the stations between each pair of pinned ones.
    pinned = [i for i, stop in enumerate(section) if stop in pins]
    for a, b in pairwise(pinned):
        piece = points[pins[section[a]] : pins[section[b]] + 1]
        total = length(piece)
        for i in range(a, b + 1):
            if section[i] not in placed:
                x, y = along(piece, total * (i - a) / (b - a))
                placed[section[i]] = (round(x, 3), round(y, 3))
    return points


def name_points(x: float, y: float, side: str, text: str) -> list[Point]:
    """Points along where a station's name would be drawn."""
    width = len(text) * CHAR
    if side == 'right':
        start, step = (x + GAP, y), (1, 0)
    elif side == 'left':
        start, step = (x - GAP - width, y), (1, 0)
    elif side == 'above':
        start, step = (x + GAP * DIAG, y - GAP * DIAG), (DIAG, -DIAG)
    elif side == 'below':
        start, step = (x + GAP * DIAG, y + GAP * DIAG), (DIAG, DIAG)
    elif side == 'above-left':
        step = (DIAG, DIAG)
        start = (x - (GAP + width) * DIAG, y - (GAP + width) * DIAG)
    else:  # below-left
        step = (DIAG, -DIAG)
        start = (x - (GAP + width) * DIAG, y + (GAP + width) * DIAG)
    count = max(1, round(width / 0.2))
    return [
        (
            start[0] + step[0] * width * i / count,
            start[1] + step[1] * width * i / count,
        )
        for i in range(count + 1)
    ]


def segment_distance(p: Point, a: Point, b: Point) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    t = (
        0
        if span == 0
        else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / span))
    )
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def legend_points(names: list[str]) -> list[Point]:
    """Points covering the legend, so station names keep clear of it.

    Its rows are each line's name, then a gap row and a row for unlit
    stations.
    """
    left, top = LEGEND
    width = LEGEND_SWATCH + max(len(name) for name in names) * CHAR
    height = (len(names) + 2) * LEGEND_ROW
    return [
        (left + width * i / 20, top + height * j / 20)
        for i in range(21)
        for j in range(21)
    ]


def place_names(
    placed, labels, preferred, tracks, blocked=()
) -> dict[str, str]:
    """Pick a side for each station's name that collides with the least.

    A first pass gives each station the first side, in its order of
    preference, that is clear of names already placed, tracks and dots.
    Later passes let any station still colliding try every side again
    against all the other names, until nothing improves.
    """
    segments = [seg for points in tracks for seg in pairwise(points)]
    every = ['right', 'left', 'above', 'below', 'above-left', 'below-left']
    options = {
        stop: preferred[stop] + [s for s in every if s not in preferred[stop]]
        for stop in placed
    }
    # Name points by grid cell, tagged with their station.
    taken: dict[tuple[int, int], list[tuple[str, Point]]] = {}
    for point in blocked:
        taken.setdefault(
            (math.floor(point[0]), math.floor(point[1])), []
        ).append(('', point))

    def cell(point: Point) -> tuple[int, int]:
        return (math.floor(point[0]), math.floor(point[1]))

    def add(stop: str, points: list[Point]) -> None:
        for p in points:
            taken.setdefault(cell(p), []).append((stop, p))

    def remove(stop: str, points: list[Point]) -> None:
        for p in points:
            taken[cell(p)].remove((stop, p))

    fixed: dict[tuple[str, str], tuple[int, list[Point]]] = {}

    def track_and_dot_hits(stop: str, side: str) -> tuple[int, list[Point]]:
        if (stop, side) not in fixed:
            x, y = placed[stop]
            points = name_points(x, y, side, labels[stop])
            hits = 0
            for p in points:
                if any(
                    segment_distance(p, a, b) < CLEAR_TRACK for a, b in segments
                ):
                    hits += 1
                if any(
                    math.dist(p, dot) < CLEAR_DOT
                    for other, dot in placed.items()
                    if other != stop
                ):
                    hits += 1
            fixed[stop, side] = (hits, points)
        return fixed[stop, side]

    def cost(stop: str, side: str) -> tuple[int, list[Point]]:
        hits, points = track_and_dot_hits(stop, side)
        for p in points:
            cx, cy = cell(p)
            if any(
                other != stop and math.dist(p, q) < CLEAR_NAME
                for dx in (-1, 0, 1)
                for dy in (-1, 0, 1)
                for other, q in taken.get((cx + dx, cy + dy), ())
            ):
                hits += 1
        return hits, points

    def best(stop: str) -> tuple[int, str, list[Point]]:
        found = None
        for side in options[stop]:
            score, points = cost(stop, side)
            if found is None or score < found[0]:
                found = (score, side, points)
            if score == 0:
                break
        return found

    chosen: dict[str, tuple[int, str, list[Point]]] = {}
    for stop in placed:
        chosen[stop] = best(stop)
        add(stop, chosen[stop][2])

    for _ in range(8):
        improved = False
        for stop in placed:
            score, side, points = chosen[stop]
            if score == 0:
                continue
            remove(stop, points)
            score, points = cost(stop, side)
            found = best(stop)
            if found[0] < score:
                chosen[stop] = found
                improved = True
            else:
                chosen[stop] = (score, side, points)
            add(stop, chosen[stop][2])
        # Scores of other stations change as names move; refresh them.
        for stop in placed:
            score, side, points = chosen[stop]
            remove(stop, points)
            chosen[stop] = (cost(stop, side)[0], side, points)
            add(stop, points)
        if not improved:
            break

    left = sorted(labels[s] for s, (score, _, _) in chosen.items() if score)
    if left:
        print(f'Names that still touch something: {", ".join(left)}')
    return {stop: side for stop, (_, side, _) in chosen.items()}


def build(tables) -> dict:
    stops = {row['stop_id']: row for row in tables['stops']}
    ids = {row['stop_name']: row['stop_id'] for row in tables['stops']}
    routes = {row['route_id']: row for row in tables['routes']}
    sequences = outbound_sequences(tables)

    placed: dict[str, Point] = {}
    for name, x, y in TRUNK:
        placed[ids[name]] = (x, y)
    tracks = [[(x, y) for _, x, y in TRUNK]]
    # The sides each station's name may take, best first.
    preferred = {ids[name]: ['below', 'above'] for name, _, _ in TRUNK}

    lines = {}
    for route, layout in LAYOUT.items():
        sequence = sequences[route]
        before = set(placed)
        tracks.append(place_line(route, sequence, layout, ids, placed))
        section = [ids[layout['track'][0][0]]] + [
            stop for stop in sequence if stop not in before
        ]
        for i, stop in enumerate(section[1:], 1):
            after = section[min(i + 1, len(section) - 1)]
            (x1, y1), (x2, y2) = placed[section[i - 1]], placed[after]
            level = abs(y2 - y1) < 0.1 * abs(x2 - x1)
            preferred[stop] = (
                [layout.get('level', 'below')] if level else [layout['side']]
            )
        lines[route] = {
            'name': routes[route]['route_long_name'].removesuffix(' Line'),
            'color': layout['color'],
            'stops': sequence,
        }

    missing = {s for seq in sequences.values() for s in seq} - placed.keys()
    if missing:
        names = ', '.join(sorted(stops[s]['stop_name'] for s in missing))
        raise SystemExit(f'Stations not placed: {names}')

    labels = {
        stop: LABELS.get(stops[stop]['stop_name'], stops[stop]['stop_name'])
        for stop in placed
    }
    for name, side in LABEL_SIDES.items():
        preferred[ids[name]] = [side]
    legend_names = [line['name'] for line in lines.values()] + ['No train']
    sides = place_names(
        placed, labels, preferred, tracks, legend_points(legend_names)
    )

    stations = {}
    for stop, (x, y) in placed.items():
        name = stops[stop]['stop_name']
        stations[stop] = {
            'name': name,
            'label': labels[stop],
            'side': sides[stop],
            'x': x,
            'y': y,
            'lat': float(stops[stop]['stop_lat']),
            'lon': float(stops[stop]['stop_lon']),
        }
    feed = (tables.get('feed_info') or [{}])[0]
    return {
        'feed_version': feed.get('feed_version', ''),
        'legend': {'x': LEGEND[0], 'y': LEGEND[1]},
        'stations': stations,
        'lines': lines,
        'tracks': [
            [[round(x, 3), round(y, 3)] for x, y in points] for points in tracks
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        '--zip',
        type=Path,
        help='use this gtfs_public.zip instead of downloading the latest',
    )
    args = parser.parse_args()
    release = args.zip.read_bytes() if args.zip else download_release()
    result = build(read_rail_feed(release))
    OUTPUT.write_text(json.dumps(result, indent=1) + '\n')
    print(
        f'Wrote {len(result["stations"])} stations on '
        f'{len(result["lines"])} lines to {OUTPUT.relative_to(ROOT)}'
    )
    try:
        stations = download_station_list()
    except OSError as error:
        print(f'Kept the old station list; could not download it: {error}')
        return
    if not stations:
        print('Kept the old station list; the page had no stations in it')
        return
    STATIONS_OUTPUT.write_text(json.dumps(stations, indent=1) + '\n')
    print(
        f'Wrote {len(stations)} stations to {STATIONS_OUTPUT.relative_to(ROOT)}'
    )


if __name__ == '__main__':
    main()
