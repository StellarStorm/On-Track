import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx2
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from config import Config, ConfigError
from src.logging_config import get_logger
from src.septa import Departure, DepartureBoard
from src.trainview import StationMap, TrainMap

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / 'templates'
STATIC_DIR = BASE_DIR / 'static'
MAP_FILE = STATIC_DIR / 'map.json'
# iOS status bar styles for each map look: "default" is light.
STATUS_BARS = {'light': 'default', 'dark': 'black'}

try:
    config = Config.load()
except ConfigError as error:
    sys.exit(str(error))

logger = get_logger(__name__)


def format_time(moment: datetime, time_format: str) -> str:
    """Format a clock time the way the board shows it, such as ``10:15``."""
    if time_format == '24':
        return moment.strftime('%H:%M')
    return f'{moment.hour % 12 or 12}:{moment:%M}'


def departure_row(departure: Departure) -> dict:
    """One board row, ready for the page to draw."""
    return {
        'time': format_time(departure.departs, config.time_format),
        'destination': departure.destination,
        'train': departure.train_id,
        'service': departure.service,
        'status': departure.status,
        'minutes_late': departure.minutes_late,
        'track': departure.track,
        'track_changed': departure.track_changed,
        'line': departure.line,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    with httpx2.Client() as client:
        app.state.board = DepartureBoard(
            client,
            station=config.station,
            rows=config.rows,
            direction=config.direction,
            ttl_seconds=config.refresh_seconds,
        )
        logger.info('Showing departures for %s', config.station)
        app.state.trains = None
        if MAP_FILE.exists():
            app.state.trains = TrainMap(
                client,
                StationMap.load(MAP_FILE),
                ttl_seconds=config.refresh_seconds,
            )
        else:
            logger.warning(
                'No %s; run scripts/build_map.py to enable /map',
                MAP_FILE.relative_to(BASE_DIR),
            )
        yield


app = FastAPI(lifespan=lifespan)
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')


@app.middleware('http')
async def revalidate(request: Request, call_next):
    # Without this, a kiosk may keep using an old copy of the page after an
    # update.
    response = await call_next(request)
    response.headers.setdefault('Cache-Control', 'no-cache')
    return response


@app.get('/')
def board_view():
    return FileResponse(TEMPLATE_DIR / 'board.html')


@app.get('/departures')
def get_departures(request: Request):
    departures, updated, stale = request.app.state.board.snapshot()
    return {
        'title': config.board_title,
        'rows': config.rows,
        'refresh_seconds': config.refresh_seconds,
        'time_format': config.time_format,
        'updated': updated.isoformat() if updated else None,
        'stale': stale,
        'departures': [departure_row(departure) for departure in departures],
    }


@app.get('/map')
def map_view():
    # iOS reads the status bar style once, when the page opens, so it is
    # set here rather than by the page's script: a light bar over a light
    # map, black over a dark one. The page also starts in the right look,
    # so a dark map doesn't flash light while it loads.
    page = (TEMPLATE_DIR / 'map.html').read_text()
    page = page.replace(
        'content="STATUS_BAR"', f'content="{STATUS_BARS[config.map_look]}"'
    )
    page = page.replace(
        '<body class="LOOK">', f'<body class="{config.map_look}">'
    )
    return HTMLResponse(page)


@app.get('/trains')
def get_trains(request: Request):
    settings = {
        'look': config.map_look,
        'refresh_seconds': config.refresh_seconds,
        'time_format': config.time_format,
    }
    if request.app.state.trains is None:
        return {**settings, 'updated': None, 'stale': True, 'trains': []}
    trains, updated, stale = request.app.state.trains.snapshot()
    return {
        **settings,
        'updated': updated.isoformat() if updated else None,
        'stale': stale,
        'trains': [
            {
                'train': train.number,
                'line': train.line,
                'destination': train.destination,
                'minutes_late': train.minutes_late,
                'station': train.station,
            }
            for train in trains
            if train.station
        ],
    }


if __name__ == '__main__':
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )
