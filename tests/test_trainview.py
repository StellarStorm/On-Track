import httpx2
import pytest

from src.septa import SourceError
from src.trainview import StationMap, TrainMap, parse_trains, station_key

# A tiny map in the shape scripts/build_map.py writes: two lines that share
# 30th Street, and two stations both called North Philadelphia.
MAP = {
    'stations': {
        '30': {'name': 'Gray 30th St Station', 'lat': 39.9567, 'lon': -75.1817},
        'FR': {
            'name': 'Fern Rock Transit Center',
            'lat': 40.0406,
            'lon': -75.1310,
        },
        'NPA': {
            'name': 'North Philadelphia Amtrak',
            'lat': 39.9970,
            'lon': -75.1553,
        },
        'NPS': {
            'name': 'North Philadelphia Septa',
            'lat': 39.9989,
            'lon': -75.1560,
        },
        'BR': {'name': 'Bridesburg', 'lat': 40.0103, 'lon': -75.0716},
    },
    'lines': {
        'TRE': {'name': 'Trenton', 'stops': ['30', 'NPA', 'BR']},
        'CHW': {'name': 'Chestnut Hill West', 'stops': ['30', 'NPS']},
        'LAN': {'name': 'Lansdale/Doylestown', 'stops': ['30', 'FR']},
    },
}


@pytest.fixture
def stations() -> StationMap:
    return StationMap(MAP)


def raw_train(**fields) -> dict:
    train = {
        'trainno': '9999',
        'line': 'Trenton',
        'dest': 'Trenton',
        'currentstop': 'Bridesburg',
        'late': 0,
        'lat': '40.0103',
        'lon': '-75.0716',
    }
    train.update(fields)
    return train


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


class FakeClient:
    """Stands in for httpx2.Client; fails when ``payload`` is None."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def get(self, url, params=None, timeout=None) -> FakeResponse:
        self.calls += 1
        if self.payload is None:
            raise httpx2.ConnectError('no network')
        return FakeResponse(self.payload)


@pytest.mark.parametrize(
    ('trainview', 'gtfs'),
    [
        ('Fern Rock T C', 'Fern Rock Transit Center'),
        ('Gray 30th Street', 'Gray 30th St Station'),
        ('Holmesburg Jct', 'Holmesburg Junction'),
        ('Jenkintown Wyncote', 'Jenkintown-Wyncote'),
        ('Washington Lane', 'Washington Ln'),
        ('49th Street', '49th St'),
        ('Chester TC', 'Chester Transit Center'),
    ],
)
def test_station_key_matches_spellings(trainview, gtfs):
    assert station_key(trainview) == station_key(gtfs)


def test_station_key_keeps_different_stations_apart():
    assert station_key('St. Martins') != station_key('Martins')
    assert station_key('North Philadelphia Amtrak') != station_key(
        'North Philadelphia Septa'
    )


def test_locate_by_name(stations):
    assert stations.locate(
        'Lansdale/Doylestown', 'Fern Rock T C', None, None
    ) == ('FR')


def test_locate_falls_back_to_nearest_station_on_line(stations):
    # TrainView sometimes says just "North Philadelphia"; each line has its
    # own station by that name, so the train's position decides.
    assert stations.locate(
        'Trenton', 'North Philadelphia', 39.997, -75.155
    ) == ('NPA')
    assert stations.locate(
        'Chestnut Hill West', 'North Philadelphia', 39.997, -75.155
    ) == ('NPS')


def test_locate_without_name_or_position(stations):
    assert stations.locate('Trenton', 'Nowhere', None, None) is None
    assert stations.locate('Unknown Line', None, 40.0, -75.1) is None


def test_parse_trains(stations):
    (train,) = parse_trains([raw_train(late=4)], stations)
    assert train.number == '9999'
    assert train.line == 'Trenton'
    assert train.minutes_late == 4
    assert train.station == 'BR'


def test_parse_trains_rejects_unexpected_shapes(stations):
    with pytest.raises(SourceError):
        parse_trains({'error': 'down'}, stations)
    with pytest.raises(SourceError):
        parse_trains(['not a train'], stations)


def test_train_map_caches(stations):
    client = FakeClient([raw_train()])
    trains_map = TrainMap(client, stations)
    trains, updated, stale = trains_map.snapshot()
    trains_map.snapshot()
    assert [train.station for train in trains] == ['BR']
    assert updated is not None
    assert not stale
    assert client.calls == 1


def test_train_map_keeps_last_good_data_when_septa_fails(stations):
    client = FakeClient([raw_train()])
    trains_map = TrainMap(client, stations, ttl_seconds=0)
    good, _, _ = trains_map.snapshot()
    client.payload = None
    trains, updated, stale = trains_map.snapshot()
    assert trains == good
    assert updated is not None
    assert stale
