import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'build_map.py'
spec = importlib.util.spec_from_file_location('build_map', SCRIPT)
build_map = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_map)


def test_along_walks_a_bent_track():
    track = [(0, 0), (2, 0), (2, 2)]
    assert build_map.along(track, 1) == (1, 0)
    assert build_map.along(track, 3) == (2, 1)
    assert build_map.along(track, 10) == (2, 2)


def test_place_line_spaces_stations_between_pins():
    ids = {'A': 'a', 'B': 'b', 'C': 'c', 'D': 'd', 'E': 'e'}
    placed = {'a': (0, 0)}
    layout = {'track': [('A',), ('C', 2, 0), (2, 2), ('E', 0, 2)]}
    build_map.place_line('X', ['a', 'b', 'c', 'd', 'e'], layout, ids, placed)
    assert placed == {
        'a': (0, 0),
        'b': (1, 0),
        'c': (2, 0),
        'd': (2, 2),
        'e': (0, 2),
    }


def test_place_line_needs_the_track_to_end_at_the_last_stop():
    ids = {'A': 'a', 'B': 'b', 'C': 'c'}
    layout = {'track': [('A',), ('B', 1, 0)]}
    with pytest.raises(SystemExit):
        build_map.place_line('X', ['a', 'b', 'c'], layout, ids, {'a': (0, 0)})


def test_names_avoid_tracks():
    # A station on a level track: a name to its right would sit on the
    # track, so it is angled instead.
    placed = {'s': (0, 0)}
    tracks = [[(-5, 0), (5, 0)]]
    sides = build_map.place_names(
        placed, {'s': 'Station'}, {'s': ['right']}, tracks
    )
    assert sides['s'] in ('above', 'below', 'above-left', 'below-left')
