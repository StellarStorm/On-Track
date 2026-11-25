import json

import pytest

from src.display import Display, DisplaySettings

DEFAULTS = DisplaySettings(
    view='board', station='Jefferson Station', direction='both'
)


def test_starts_from_defaults(tmp_path):
    display = Display(DEFAULTS, tmp_path / 'display.json')
    settings, _ = display.current()
    assert settings == DEFAULTS


def test_update_changes_saves_and_bumps_version(tmp_path):
    path = tmp_path / 'display.json'
    display = Display(DEFAULTS, path)
    _, before = display.current()
    settings, after = display.update(view='map', station='  Elkins Park ')
    assert settings.view == 'map'
    assert settings.station == 'Elkins Park'
    assert after == before + 1
    assert json.loads(path.read_text()) == {
        'view': 'map',
        'station': 'Elkins Park',
        'direction': 'both',
    }


def test_update_without_a_change_keeps_the_version(tmp_path):
    display = Display(DEFAULTS, tmp_path / 'display.json')
    _, before = display.current()
    _, after = display.update(view='board')
    assert after == before


def test_saved_settings_survive_a_restart(tmp_path):
    path = tmp_path / 'display.json'
    Display(DEFAULTS, path).update(direction='southbound')
    settings, _ = Display(DEFAULTS, path).current()
    assert settings.direction == 'southbound'


@pytest.mark.parametrize(
    'changes',
    [
        {'view': 'clock'},
        {'station': '   '},
        {'direction': 'sideways'},
        {'colour': 'red'},
    ],
)
def test_update_rejects_bad_settings(tmp_path, changes):
    display = Display(DEFAULTS, tmp_path / 'display.json')
    with pytest.raises(ValueError):
        display.update(**changes)
    assert display.current()[0] == DEFAULTS


def test_unusable_saved_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / 'display.json'
    path.write_text('{"view": "clock"}')
    assert Display(DEFAULTS, path).current()[0] == DEFAULTS
    path.write_text('not json')
    assert Display(DEFAULTS, path).current()[0] == DEFAULTS
