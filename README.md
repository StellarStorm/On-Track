# On Track

![](imgs/main.png)

An LED-style departure board for one SEPTA Regional Rail station, in the
style of the Jefferson Station platform signs. A small server fetches live
departures from SEPTA, and any browser on the network shows the board. An
old iPad in kiosk mode works well.

A second page shows a live map of the whole Regional Rail system, in the
style of a Metroboard: every station is a dot, lit in its line's color while
a train is there.

Departures come from SEPTA's public
[Arrivals API](https://www3.septa.org/api/Arrivals/index.php), and train
positions from its
[TrainView API](https://www3.septa.org/api/TrainView/index.php). No account
or API key is needed.

| Path          | What it is                           |
| ------------- | ------------------------------------ |
| `/`           | The departure board                  |
| `/departures` | The same data as JSON                |
| `/map`        | The live Regional Rail map           |
| `/trains`     | Every train and its station, as JSON |

## Getting Started

### Install

```sh
cd On-Track
uv sync
```

### Configure

```sh
cp config.example.toml config.toml
```

Set `station` to SEPTA's name for your station, such as
`"Jefferson Station"`, `"Suburban Station"` or `"Gray 30th Street"`. SEPTA's
[station list](https://www3.septa.org/VIRegionalRail.html) has the exact
spellings. A misspelled station shows "NO DEPARTURES LISTED".

| Setting           | Default               | Description                                         |
| ----------------- | --------------------- | --------------------------------------------------- |
| `station`         | `"Jefferson Station"` | SEPTA's name for the station.                       |
| `title`           | station name          | Header text. Defaults to the name without "Station".|
| `direction`       | `"both"`              | `both`, `northbound` or `southbound`.               |
| `rows`            | `8`                   | Departures on the board (1–12).                     |
| `refresh_seconds` | `30`                  | How often to ask SEPTA for new data (15 or more).   |
| `time_format`     | `"12"`                | `"12"` or `"24"` hour times.                        |
| `map_look`        | `"light"`             | Colors of `/map`: `light` or `dark`.                |
| `host`, `port`    | `0.0.0.0`, `8000`     | Address the server listens on.                      |
| `log_level`       | `"INFO"`              | Python logging level.                               |

Any setting can be overridden with an `OT_` environment variable, such as
`OT_STATION="Suburban Station"`. To read the configuration from another
file, set `ON_TRACK_CONFIG` to its path.

### Run

```sh
uv run python main.py
```

Open `http://localhost:8000/`, or `http://<this computer's address>:8000/`
from another device.

## Reading the Board

- **Status:** green ON TIME; amber for 1–4 minutes late; red for 5 or more
  minutes late, and for anything else SEPTA reports, such as SUSPENDED.
- **Track:** track and platform together, as on the station signs (`3B`). A
  track or platform change blinks in yellow.
- **Footer:** DELAYED DATA means SEPTA did not answer the last request, so
  the board is showing the last good data. OFFLINE means the display cannot
  reach this server.

However many displays are open, the server asks SEPTA at most once per
`refresh_seconds`.

## Reading the Map

Each station lights in its line's color while a train is there or has just
left it, and goes dark when the train moves on. The legend in the top-left
corner gives each line's color. The map is updated every
`refresh_seconds`, from the same single request to SEPTA however many
displays are open. A train can be through-routed onto another line, so the
color is the line SEPTA reports for it, which may not be the line the
station is on.

The bottom corner shows the time, DELAYED DATA when SEPTA did not answer
the last request, and OFFLINE when the display cannot reach this server.

## Using an iPad as the Display

1. Open the board in Safari, then Share → Add to Home Screen. Opened from
   the Home Screen, it runs full screen.
2. Turn on Guided Access (Settings → Accessibility) to lock the iPad to the
   board, and set Auto-Lock to Never.

The page uses older JavaScript and CSS so it runs on older iPads, and it
reloads itself every 6 hours.

The board works either way up. On a wide screen each departure takes one
line. On a tall one, such as a phone or an upright iPad, it takes two: time,
destination and track, then train, service and status. The board picks
whichever layout gives the bigger text, and switches when the screen
rotates.

## Development

```sh
uv run pytest
uv run ruff check .
```

The tests use a saved SEPTA response in `tests/fixtures/`.

`scripts/redraw_glyphs.py` redraws a few characters in the board's font
file. The new shapes are drawn as dot grids at the top of the script; edit
them and run:

```sh
uv run scripts/redraw_glyphs.py
```

`scripts/logo_dots.py` turns the SEPTA logo (`scripts/septa-logo.svg`) into
the LED dots in the title bar, and writes them into `templates/board.html`.
Rerun it after changing the logo's size or colors, which are set at the top
of the script:

```sh
uv run scripts/logo_dots.py
```

`scripts/build_map.py` builds the map's stations and tracks
(`static/map.json`) from SEPTA's GTFS schedule data. It downloads SEPTA's
latest release from [GitHub](https://github.com/septadev/GTFS/releases),
takes each line's stations in order, lays them out on the schematic set at
the top of the script, and places every station name where it doesn't run
into anything. Run it again when SEPTA publishes new data, such as a new or
renamed station, then restart the server:

```sh
uv run scripts/build_map.py
```

To use a GTFS zip you already have, pass `--zip path/to/gtfs_public.zip`.
The script lists any names it couldn't place cleanly; moving a line's
corners or pinned stations in `LAYOUT` usually fixes them.

## Credits

The board uses the [Doto](https://github.com/oliverlalan/Doto) font, under
the SIL Open Font License (`static/fonts/OFL.txt`). The copy in
`static/fonts/` is modified: `0` is redrawn as an oval in place of Doto's
diamond, and `:` `;` `.` `,` use single dots (see
`scripts/redraw_glyphs.py`).

The SEPTA logo in the title bar is drawn from
[SEPTA.svg](https://commons.wikimedia.org/wiki/File:SEPTA.svg) on Wikimedia
Commons. SEPTA's name and logo are SEPTA's trademarks; this project is not
affiliated with SEPTA.

The map's stations and line orders come from SEPTA's
[GTFS data](https://github.com/septadev/GTFS).
