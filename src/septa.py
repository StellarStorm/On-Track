"""Regional Rail departures for one station, from SEPTA's Arrivals API.

The API needs no key. It returns the next trains in each direction, for
example::

    {"Jefferson Station Departures: November 24, 2026, 6:32 pm": [
        {"Northbound": [{"train_id": "4754", "destination": "Chestnut H East",
                         "status": "3 min", "depart_time": "...", ...}]},
        {"Southbound": [...]}
    ]}
"""

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from operator import attrgetter

import httpx2

from src.logging_config import get_logger

ARRIVALS_URL = 'https://www3.septa.org/api/Arrivals/index.php'
SEPTA_TIME_FORMAT = '%Y-%m-%d %H:%M:%S.%f'
DIRECTIONS = {'northbound': 'Northbound', 'southbound': 'Southbound'}
SERVICE_CODES = {'LOCAL': 'LOC', 'EXPRESS': 'EXP', 'LIMITED': 'LTD'}
# SEPTA reports 999 minutes late when it has no position for the train yet.
UNKNOWN_DELAY = 999

logger = get_logger(__name__)


class SourceError(Exception):
    """SEPTA could not be reached or sent data that could not be used."""


@dataclass
class Departure:
    train_id: str
    line: str
    destination: str
    direction: str
    service: str
    departs: datetime
    minutes_late: int | None
    status: str
    track: str
    track_changed: bool


def parse_status(text: str | None) -> tuple[int | None, str]:
    """Split SEPTA's status into minutes late and the text to display.

    Args:
        text: SEPTA's status, such as ``'On Time'``, ``'7 min'`` or
            ``'Suspended'``.

    Returns:
        Minutes late (None when the status is not a delay) and the display
        text, such as ``'ON TIME'``, ``'7 LATE'`` or ``'SUSPENDED'``.
    """
    text = (text or '').strip()
    if text.lower() == 'on time':
        return 0, 'ON TIME'
    number, _, unit = text.partition(' ')
    if number.isdigit() and unit.lower().startswith('min'):
        minutes = int(number)
        if minutes >= UNKNOWN_DELAY:
            return None, ''
        return minutes, 'ON TIME' if minutes == 0 else f'{minutes} LATE'
    return None, text.upper()


def track_label(raw: dict) -> tuple[str, bool]:
    """Combine track and platform the way station boards do, such as ``3B``.

    Args:
        raw: One train from the API.

    Returns:
        The label, and whether SEPTA reports a track or platform change.
    """
    changed = bool(raw.get('track_change') or raw.get('platform_change'))
    track = raw.get('track_change') or raw.get('track') or ''
    platform = raw.get('platform_change') or raw.get('platform') or ''
    return f'{track}{platform}'.strip(), changed


def parse_departure(raw: dict) -> Departure:
    """Turn one train from the API into a Departure."""
    minutes_late, status = parse_status(raw.get('status'))
    track, track_changed = track_label(raw)
    service = (raw.get('service_type') or '').upper()
    departs = raw.get('depart_time') or raw['sched_time']
    return Departure(
        train_id=raw.get('train_id') or '',
        line=raw.get('line') or '',
        destination=raw.get('destination') or '',
        direction=raw.get('direction') or '',
        service=SERVICE_CODES.get(service, service[:3]),
        departs=datetime.strptime(departs, SEPTA_TIME_FORMAT),
        minutes_late=minutes_late,
        status=status,
        track=track,
        track_changed=track_changed,
    )


def parse_arrivals(payload: dict, direction: str = 'both') -> list[Departure]:
    """Parse an Arrivals API response into departures sorted by time.

    Args:
        payload: The decoded JSON response.
        direction: ``'both'``, ``'northbound'`` or ``'southbound'``.

    Returns:
        The departures in the requested direction(s), soonest first.

    Raises:
        SourceError: The response is not in the expected shape.
    """
    try:
        (groups,) = payload.values()
        departures = []
        for group in groups:
            for name, trains in group.items():
                if direction != 'both' and name != DIRECTIONS[direction]:
                    continue
                departures.extend(parse_departure(raw) for raw in trains or [])
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise SourceError(
            f'Unexpected response from SEPTA: {str(payload)[:200]}'
        ) from error
    return sorted(departures, key=attrgetter('departs'))


def fetch_departures(
    client: httpx2.Client, station: str, results: int, direction: str = 'both'
) -> list[Departure]:
    """Fetch the next departures for a station.

    Args:
        client: HTTP client used for the request.
        station: SEPTA's name for the station, such as
            ``'Jefferson Station'``.
        results: How many trains to ask for in each direction.
        direction: ``'both'``, ``'northbound'`` or ``'southbound'``.

    Returns:
        The departures, soonest first.

    Raises:
        SourceError: SEPTA could not be reached or sent unusable data.
    """
    try:
        response = client.get(
            ARRIVALS_URL,
            params={'station': station, 'results': results},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx2.HTTPError, ValueError) as error:
        raise SourceError(f'SEPTA request failed: {error}') from error
    return parse_arrivals(payload, direction)


class DepartureBoard:
    """The latest departures, fetched from SEPTA at most once per TTL.

    Every display polls the server, but only one request per TTL goes to
    SEPTA. When SEPTA fails, the last good departures are kept and the
    snapshot is marked stale.
    """

    def __init__(
        self,
        client: httpx2.Client,
        station: str,
        rows: int,
        direction: str = 'both',
        ttl_seconds: int = 30,
    ):
        self._client = client
        self._station = station
        self._rows = rows
        self._direction = direction
        self._ttl = ttl_seconds
        self._departures: list[Departure] = []
        self._updated: datetime | None = None
        self._last_attempt: float | None = None
        self._failed = False
        self._lock = threading.Lock()

    def set_station(self, station: str, direction: str) -> None:
        """Show another station or direction from the next snapshot on.

        The departures for the old one are dropped, so the next snapshot
        fetches fresh ones rather than waiting out the TTL.
        """
        with self._lock:
            if (station, direction) == (self._station, self._direction):
                return
            self._station = station
            self._direction = direction
            self._departures = []
            self._updated = None
            self._last_attempt = None
            self._failed = False

    def snapshot(self) -> tuple[list[Departure], datetime | None, bool]:
        """Return the departures, when they were fetched, and staleness.

        Returns:
            Up to ``rows`` departures, the time of the last successful
            fetch (None if there has not been one), and whether the latest
            attempt to refresh failed.
        """
        with self._lock:
            now = time.monotonic()
            if (
                self._last_attempt is None
                or now - self._last_attempt >= self._ttl
            ):
                self._last_attempt = now
                self._refresh()
            return self._departures[: self._rows], self._updated, self._failed

    def _refresh(self) -> None:
        try:
            self._departures = fetch_departures(
                self._client, self._station, self._rows, self._direction
            )
        except SourceError as error:
            if not self._failed:
                logger.warning('%s', error)
            self._failed = True
            return
        if self._failed:
            logger.info('SEPTA data is back')
        self._failed = False
        self._updated = datetime.now()
