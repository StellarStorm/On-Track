"""Where every Regional Rail train is, from SEPTA's TrainView API.

The API needs no key. It returns every train running, for example::

    [{"trainno": "3232", "line": "Manayunk/Norristown",
      "currentstop": "Suburban Station", "nextstop": "Jefferson Station",
      "dest": "Norristown", "late": 1, "lat": "39.95", "lon": "-75.16",
      ...}]

Each train is matched to a station on the map built by
``scripts/build_map.py``. TrainView's station names don't always match the
map's (``Fern Rock T C`` for ``Fern Rock Transit Center``), so names are
compared loosely, and a train whose stop can't be matched is put at the
station on its line nearest to where it is.
"""

import json
import math
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx2

from src.logging_config import get_logger
from src.septa import SourceError

TRAINVIEW_URL = 'https://www3.septa.org/api/TrainView/index.php'

# Spellings that differ between TrainView and SEPTA's GTFS data, reduced to
# one form. Applied to whole words after lowercasing.
WORD_FORMS = {
    'street': 'st',
    'avenue': 'av',
    'ave': 'av',
    'lane': 'ln',
    'junction': 'jct',
    'station': '',
}
PHRASE_FORMS = {
    'transit center': 'tc',
    't c': 'tc',
}

logger = get_logger(__name__)


def station_key(name: str) -> str:
    """A station name reduced so different spellings compare equal.

    ``'Fern Rock T C'`` and ``'Fern Rock Transit Center'`` both become
    ``'fern rock tc'``; ``'Gray 30th Street'`` and
    ``'Gray 30th St Station'`` both become ``'gray 30th st'``.
    """
    text = re.sub(r'[^a-z0-9&]+', ' ', name.lower()).replace('&', ' and ')
    words = [WORD_FORMS.get(word, word) for word in text.split()]
    text = ' '.join(word for word in words if word)
    for phrase, form in PHRASE_FORMS.items():
        text = re.sub(rf'\b{phrase}\b', form, text)
    return text


@dataclass
class Train:
    number: str
    line: str
    destination: str
    minutes_late: int | None
    # The map station the train is at or last left, if it could be found.
    station: str | None


class StationMap:
    """The stations on the map, for matching trains to them."""

    def __init__(self, data: dict):
        self.stations = data['stations']
        self._by_key: dict[str, list[str]] = {}
        for stop, station in self.stations.items():
            self._by_key.setdefault(station_key(station['name']), []).append(
                stop
            )
        # Each line's stops, by the line name TrainView uses.
        self._lines = {
            line['name']: set(line['stops']) for line in data['lines'].values()
        }

    @classmethod
    def load(cls, path: Path) -> 'StationMap':
        return cls(json.loads(path.read_text()))

    def locate(
        self,
        line: str,
        stop_name: str | None,
        lat: float | None,
        lon: float | None,
    ) -> str | None:
        """The map station for a train, or None if it can't be placed.

        Args:
            line: The train's line, such as ``'Paoli/Thorndale'``.
            stop_name: TrainView's name for the train's current stop.
            lat: The train's latitude, if known.
            lon: The train's longitude, if known.
        """
        on_line = self._lines.get(line, set())
        if stop_name:
            matches = self._by_key.get(station_key(stop_name), [])
            # Two stations can share a name (North Philadelphia); prefer
            # the one on the train's line.
            for stop in matches:
                if stop in on_line:
                    return stop
            if matches:
                return matches[0]
        if lat is None or lon is None or not on_line:
            return None
        return min(
            on_line,
            key=lambda stop: _distance(self.stations[stop], lat, lon),
        )


def _distance(station: dict, lat: float, lon: float) -> float:
    dx = (station['lon'] - lon) * math.cos(math.radians(lat))
    return math.hypot(dx, station['lat'] - lat)


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_trains(payload, stations: StationMap) -> list[Train]:
    """Parse a TrainView response and place each train on the map.

    Raises:
        SourceError: The response is not in the expected shape.
    """
    if not isinstance(payload, list):
        raise SourceError(
            f'Unexpected response from SEPTA: {str(payload)[:200]}'
        )
    trains = []
    for raw in payload:
        try:
            line = raw.get('line') or ''
            late = raw.get('late')
            trains.append(
                Train(
                    number=str(raw.get('trainno') or ''),
                    line=line,
                    destination=raw.get('dest') or '',
                    minutes_late=late if isinstance(late, int) else None,
                    station=stations.locate(
                        line,
                        raw.get('currentstop'),
                        _number(raw.get('lat')),
                        _number(raw.get('lon')),
                    ),
                )
            )
        except AttributeError as error:
            raise SourceError(
                f'Unexpected train from SEPTA: {str(raw)[:200]}'
            ) from error
    return trains


def fetch_trains(client: httpx2.Client, stations: StationMap) -> list[Train]:
    """Fetch every running train and place it on the map.

    Raises:
        SourceError: SEPTA could not be reached or sent unusable data.
    """
    try:
        response = client.get(TRAINVIEW_URL, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except (httpx2.HTTPError, ValueError) as error:
        raise SourceError(f'SEPTA request failed: {error}') from error
    return parse_trains(payload, stations)


class TrainMap:
    """The latest train positions, fetched from SEPTA at most once per TTL.

    Works like DepartureBoard: one request to SEPTA per TTL however many
    displays are open, and the last good positions kept, marked stale,
    when SEPTA fails.
    """

    def __init__(
        self,
        client: httpx2.Client,
        stations: StationMap,
        ttl_seconds: int = 30,
    ):
        self._client = client
        self._stations = stations
        self._ttl = ttl_seconds
        self._trains: list[Train] = []
        self._updated: datetime | None = None
        self._last_attempt: float | None = None
        self._failed = False
        self._lock = threading.Lock()

    def snapshot(self) -> tuple[list[Train], datetime | None, bool]:
        """Return the trains, when they were fetched, and staleness."""
        with self._lock:
            now = time.monotonic()
            if (
                self._last_attempt is None
                or now - self._last_attempt >= self._ttl
            ):
                self._last_attempt = now
                self._refresh()
            return self._trains, self._updated, self._failed

    def _refresh(self) -> None:
        try:
            self._trains = fetch_trains(self._client, self._stations)
        except SourceError as error:
            if not self._failed:
                logger.warning('%s', error)
            self._failed = True
            return
        if self._failed:
            logger.info('SEPTA train positions are back')
        self._failed = False
        self._updated = datetime.now()
