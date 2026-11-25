import json
from datetime import datetime
from operator import attrgetter
from pathlib import Path

import httpx2
import pytest

from src.septa import (
    DepartureBoard,
    SourceError,
    parse_arrivals,
    parse_status,
    track_label,
)

FIXTURE = Path(__file__).parent / 'fixtures' / 'arrivals_jefferson.json'


@pytest.fixture
def payload() -> dict:
    return json.loads(FIXTURE.read_text())


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class FakeClient:
    """Stands in for httpx2.Client; fails when ``payload`` is None."""

    def __init__(self, payload: dict | None):
        self.payload = payload
        self.calls = 0

    def get(self, url, params=None, timeout=None) -> FakeResponse:
        self.calls += 1
        if self.payload is None:
            raise httpx2.ConnectError('no network')
        return FakeResponse(self.payload)


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('On Time', (0, 'ON TIME')),
        ('7 min', (7, '7 LATE')),
        ('0 min', (0, 'ON TIME')),
        ('999 min', (None, '')),
        ('Suspended', (None, 'SUSPENDED')),
        (None, (None, '')),
    ],
)
def test_parse_status(text, expected):
    assert parse_status(text) == expected


def test_track_label_combines_track_and_platform():
    assert track_label({'track': '3', 'platform': 'B'}) == ('3B', False)


def test_track_label_prefers_changes():
    raw = {'track': '3', 'platform': 'B', 'track_change': '4'}
    assert track_label(raw) == ('4B', True)


def test_parse_arrivals_sorts_both_directions(payload):
    departures = parse_arrivals(payload)
    assert len(departures) == 10
    assert departures == sorted(departures, key=attrgetter('departs'))
    first = departures[0]
    assert first.train_id == '9763'
    assert first.destination == 'Trenton'
    assert first.departs == datetime(2026, 11, 24, 18, 35)
    assert first.service == 'LOC'
    assert first.status == '1 LATE'
    assert first.track == '3A'


def test_parse_arrivals_filters_direction(payload):
    departures = parse_arrivals(payload, 'northbound')
    assert {d.direction for d in departures} == {'N'}


@pytest.mark.parametrize('bad', [{}, {'a': 1, 'b': 2}, {'x': 'oops'}])
def test_parse_arrivals_rejects_unexpected_shapes(bad):
    with pytest.raises(SourceError):
        parse_arrivals(bad)


def test_board_limits_rows_and_caches(payload):
    client = FakeClient(payload)
    board = DepartureBoard(client, 'Jefferson Station', rows=4)
    departures, updated, stale = board.snapshot()
    board.snapshot()
    assert len(departures) == 4
    assert updated is not None
    assert not stale
    assert client.calls == 1


def test_board_keeps_last_good_data_when_septa_fails(payload):
    client = FakeClient(payload)
    board = DepartureBoard(client, 'Jefferson Station', rows=4, ttl_seconds=0)
    good, _, _ = board.snapshot()
    client.payload = None
    departures, updated, stale = board.snapshot()
    assert departures == good
    assert updated is not None
    assert stale


def test_board_before_first_success():
    board = DepartureBoard(FakeClient(None), 'Jefferson Station', rows=4)
    assert board.snapshot() == ([], None, True)
