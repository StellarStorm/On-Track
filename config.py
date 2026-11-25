"""App configuration.

Settings are read from ``config.toml`` next to this file (all optional; see
``config.example.toml``). Any setting can be overridden at run time with an
``OT_``-prefixed environment variable, for example::

    OT_STATION="Suburban Station" OT_ROWS=8 python main.py
"""

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

ENV_PREFIX = 'OT_'
# Lets tests and unusual installs point at another file.
CONFIG_FILE = Path(
    os.environ.get(
        'ON_TRACK_CONFIG',
        Path(__file__).resolve().parent / 'config.toml',
    )
)


class ConfigError(Exception):
    """The configuration is invalid. The message is meant for end users."""


def describe_errors(error: ValidationError) -> str:
    """Turn a pydantic error into one short line per problem."""
    lines = []
    for problem in error.errors():
        name = '.'.join(str(part) for part in problem['loc'])
        if problem['type'] == 'extra_forbidden':
            message = 'unknown setting (check the spelling)'
        else:
            message = problem['msg']
        lines.append(f'  {name}: {message}')
    return '\n'.join(lines)


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra='forbid')

    # What to show
    station: str = Field('Jefferson Station', min_length=1)
    title: str | None = None
    direction: Literal['both', 'northbound', 'southbound'] = 'both'
    rows: int = Field(8, ge=1, le=12)
    refresh_seconds: int = Field(30, ge=15)

    # Display
    time_format: Literal['12', '24'] = '12'

    # Server
    host: str = '0.0.0.0'
    port: int = 8000
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = 'INFO'

    @field_validator('time_format', mode='before')
    @classmethod
    def _accept_int(cls, value):
        # Allow `time_format = 12` as well as `time_format = "12"` in TOML.
        return str(value) if isinstance(value, int) else value

    @field_validator('direction', mode='before')
    @classmethod
    def _lower(cls, value):
        return value.lower() if isinstance(value, str) else value

    @field_validator('log_level', mode='before')
    @classmethod
    def _upper(cls, value):
        return value.upper() if isinstance(value, str) else value

    @property
    def board_title(self) -> str:
        """The header text: the title setting, or the station's short name."""
        return self.title or self.station.removesuffix(' Station')

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> 'Config':
        """Load settings from a TOML file (if it exists), then the environment.

        Args:
            path: The TOML file to read.

        Returns:
            The validated settings.

        Raises:
            ConfigError: A setting is unknown or invalid.
        """
        try:
            data = tomllib.loads(path.read_text()) if path.exists() else {}
        except tomllib.TOMLDecodeError as error:
            raise ConfigError(
                f'{path.name} is not valid TOML: {error}'
            ) from None
        try:
            return cls(**data)
        except ValidationError as error:
            raise ConfigError(
                f'Invalid settings in {path.name} or {ENV_PREFIX}* environment '
                f'variables:\n{describe_errors(error)}'
            ) from None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Environment variables win over values from the TOML file.
        return env_settings, init_settings
