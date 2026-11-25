import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx2
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import Config, ConfigError
from src.logging_config import get_logger
from src.septa import Departure, DepartureBoard

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / 'templates'
STATIC_DIR = BASE_DIR / 'static'

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


if __name__ == '__main__':
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )
