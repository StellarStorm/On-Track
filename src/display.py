"""What the display shows, as chosen on the control page.

The view (departure board or map), the board's station and its direction
start out as set in config.toml. Changes from the control page are saved to
a small JSON file, so they survive restarts. Each change bumps a version
number; the display pages watch it and reload when it moves.
"""

import json
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from src.logging_config import get_logger

VIEWS = ('board', 'map')
DIRECTIONS = ('both', 'northbound', 'southbound')

logger = get_logger(__name__)


@dataclass(frozen=True)
class DisplaySettings:
    view: str
    station: str
    direction: str

    def validated(self) -> 'DisplaySettings':
        """These settings, cleaned up.

        Raises:
            ValueError: A setting is not allowed. The message says which.
        """
        station = self.station.strip() if isinstance(self.station, str) else ''
        if self.view not in VIEWS:
            raise ValueError(f'view must be one of {", ".join(VIEWS)}')
        if not station:
            raise ValueError('station must not be empty')
        if self.direction not in DIRECTIONS:
            raise ValueError(
                f'direction must be one of {", ".join(DIRECTIONS)}'
            )
        return replace(self, station=station)


class Display:
    """The current display settings, shared by every request."""

    def __init__(self, defaults: DisplaySettings, path: Path | None = None):
        self._path = path
        self._lock = threading.Lock()
        self._settings = self._load(defaults.validated())
        # Starting from the clock means a restart counts as a change, so
        # open displays reload and pick up any new version of the pages.
        self._version = int(time.time() * 1000)

    def current(self) -> tuple[DisplaySettings, int]:
        """The settings and their version number."""
        with self._lock:
            return self._settings, self._version

    def update(self, **changes) -> tuple[DisplaySettings, int]:
        """Change some settings, save them, and return the new ones.

        Raises:
            ValueError: A setting is unknown or not allowed.
        """
        unknown = set(changes) - {'view', 'station', 'direction'}
        if unknown:
            raise ValueError(f'unknown setting: {", ".join(sorted(unknown))}')
        with self._lock:
            settings = replace(self._settings, **changes).validated()
            if settings != self._settings:
                self._settings = settings
                self._version += 1
                self._save()
            return self._settings, self._version

    def _load(self, defaults: DisplaySettings) -> DisplaySettings:
        if self._path is None or not self._path.exists():
            return defaults
        try:
            saved = json.loads(self._path.read_text())
            return replace(defaults, **saved).validated()
        except (OSError, TypeError, ValueError) as error:
            logger.warning(
                'Ignoring %s, which could not be used: %s',
                self._path.name,
                error,
            )
            return defaults

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.write_text(json.dumps(asdict(self._settings), indent=1))
        except OSError as error:
            logger.warning('Could not save %s: %s', self._path.name, error)
