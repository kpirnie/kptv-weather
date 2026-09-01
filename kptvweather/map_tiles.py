#!/usr/bin/env python3
"""
Map Tiles Module

Builds the OpenStreetMap backdrop the map and radar pages sit on. Tiles are
fetched once, cached in memory, and stitched into a single image whose real
bounds snap to the tile grid.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import io
import logging
import math
import threading
from dataclasses import dataclass
from typing import Optional

import requests
from PIL import Image

logger = logging.getLogger(__name__)

# where the tiles come from, and what has to be credited on screen
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
ATTRIBUTION = "\u00a9 OpenStreetMap contributors"

# a tile is always this many pixels square
TILE_SIZE = 256

# how far in we are willing to zoom
MIN_ZOOM = 2
MAX_ZOOM = 10

# fetched tiles, keyed by zoom and position
_TILES: dict = {}
_LOCK = threading.Lock()

# a bounded cache, since a long running channel would otherwise creep
MAX_TILES = 600


@dataclass
class MapView:
    """
    A stitched base map and the bounds it actually covers
    """

    image: Image.Image
    bounds: tuple


def _lon_to_x(lon: float, zoom: int) -> float:
    """
    Convert a longitude to a fractional tile x

    @param lon: float Longitude in decimal degrees
    @param zoom: int The zoom level
    @return float: The fractional tile column
    """

    # the standard web mercator transform
    return (lon + 180.0) / 360.0 * (2 ** zoom)


def _lat_to_y(lat: float, zoom: int) -> float:
    """
    Convert a latitude to a fractional tile y

    @param lat: float Latitude in decimal degrees
    @param zoom: int The zoom level
    @return float: The fractional tile row
    """

    # clamp to the mercator limit before projecting
    clamped = max(-85.0511, min(85.0511, lat))
    radians = math.radians(clamped)
    projected = math.log(math.tan(radians) + 1.0 / math.cos(radians))
    return (1.0 - projected / math.pi) / 2.0 * (2 ** zoom)


def _x_to_lon(x: float, zoom: int) -> float:
    """
    Convert a fractional tile x back to a longitude

    @param x: float The fractional tile column
    @param zoom: int The zoom level
    @return float: Longitude in decimal degrees
    """

    # straight inverse of the projection
    return x / (2 ** zoom) * 360.0 - 180.0


def _y_to_lat(y: float, zoom: int) -> float:
    """
    Convert a fractional tile y back to a latitude

    @param y: float The fractional tile row
    @param zoom: int The zoom level
    @return float: Latitude in decimal degrees
    """

    # straight inverse of the projection
    n = math.pi * (1.0 - 2.0 * y / (2 ** zoom))
    return math.degrees(math.atan(math.sinh(n)))


def _pick_zoom(south: float, west: float, north: float, east: float,
               width: int, height: int) -> int:
    """
    Choose the deepest zoom whose tiles still fit the requested pixel size

    @param south: float Southern edge
    @param west: float Western edge
    @param north: float Northern edge
    @param east: float Eastern edge
    @param width: int Target width in pixels
    @param height: int Target height in pixels
    @return int: The chosen zoom level
    """

    # walk down from the deepest and take the first that fits
    for zoom in range(MAX_ZOOM, MIN_ZOOM - 1, -1):
        span_x = abs(_lon_to_x(east, zoom) - _lon_to_x(west, zoom)) * TILE_SIZE
        span_y = abs(_lat_to_y(south, zoom) - _lat_to_y(north, zoom)) * TILE_SIZE
        if span_x <= width * 1.6 and span_y <= height * 1.6:
            return zoom
    return MIN_ZOOM


def _fetch_tile(zoom: int, x: int, y: int, user_agent: str) -> Optional[Image.Image]:
    """
    Fetch one tile, serving it from the cache when we already have it

    @param zoom: int The zoom level
    @param x: int The tile column
    @param y: int The tile row
    @param user_agent: str Sent with the request, required by the tile server
    @return Image|None: The tile, or None when it could not be fetched
    """

    # cached tiles never change, so this is a permanent hit
    key = (zoom, x, y)
    with _LOCK:
        hit = _TILES.get(key)
        if hit is not None:
            return hit

    # go get it
    url = TILE_URL.format(z=zoom, x=x, y=y)
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=15)
        resp.raise_for_status()
        with Image.open(io.BytesIO(resp.content)) as handle:
            tile = handle.convert("RGBA")
    except (requests.RequestException, OSError, ValueError) as exc:
        logger.warning("tile %s/%s/%s failed: %s", zoom, x, y, exc)
        return None

    # stash it, trimming the cache when it gets large
    with _LOCK:
        if len(_TILES) >= MAX_TILES:
            _TILES.clear()
        _TILES[key] = tile
    return tile


def compose_base_map(south: float, west: float, north: float, east: float,
                     width: int, height: int,
                     user_agent: str = "kptv-weather/1.0") -> Optional[MapView]:
    """
    Stitch a base map covering a bounding box

    The returned bounds are the real ones, snapped out to whole tiles, and
    any overlay drawn on top has to be requested for those rather than the
    ones that were asked for.

    @param south: float Southern edge
    @param west: float Western edge
    @param north: float Northern edge
    @param east: float Eastern edge
    @param width: int Target width in pixels
    @param height: int Target height in pixels
    @param user_agent: str Sent with every tile request
    @return MapView|None: The stitched map, or None when nothing loaded
    """

    # work out the grid we need
    zoom = _pick_zoom(south, west, north, east, width, height)
    x_min = int(math.floor(_lon_to_x(west, zoom)))
    x_max = int(math.floor(_lon_to_x(east, zoom)))
    y_min = int(math.floor(_lat_to_y(north, zoom)))
    y_max = int(math.floor(_lat_to_y(south, zoom)))

    # keep it to something sane, a runaway box would fetch hundreds of tiles
    if (x_max - x_min + 1) * (y_max - y_min + 1) > 64:
        zoom = max(MIN_ZOOM, zoom - 1)
        x_min = int(math.floor(_lon_to_x(west, zoom)))
        x_max = int(math.floor(_lon_to_x(east, zoom)))
        y_min = int(math.floor(_lat_to_y(north, zoom)))
        y_max = int(math.floor(_lat_to_y(south, zoom)))

    # the exact pixel window the requested box occupies at this zoom
    px_left = _lon_to_x(west, zoom) * TILE_SIZE
    px_right = _lon_to_x(east, zoom) * TILE_SIZE
    px_top = _lat_to_y(north, zoom) * TILE_SIZE
    px_bottom = _lat_to_y(south, zoom) * TILE_SIZE

    # widen whichever axis is short so the window matches the output aspect
    # exactly - without this the resize below would stretch the projection
    target = max(1, width) / max(1, height)
    window_w = max(1.0, px_right - px_left)
    window_h = max(1.0, px_bottom - px_top)
    if window_w / window_h < target:
        wanted = window_h * target
        center = (px_left + px_right) / 2.0
        px_left, px_right = center - wanted / 2.0, center + wanted / 2.0
    else:
        wanted = window_w / target
        center = (px_top + px_bottom) / 2.0
        px_top, px_bottom = center - wanted / 2.0, center + wanted / 2.0

    # the tile grid has to cover the widened window, not the original box
    x_min = int(math.floor(px_left / TILE_SIZE))
    x_max = int(math.floor((px_right - 1) / TILE_SIZE))
    y_min = int(math.floor(px_top / TILE_SIZE))
    y_max = int(math.floor((px_bottom - 1) / TILE_SIZE))

    # stitch whatever comes back
    columns = x_max - x_min + 1
    rows = y_max - y_min + 1
    canvas = Image.new("RGBA", (columns * TILE_SIZE, rows * TILE_SIZE),
                       (16, 22, 40, 255))
    loaded = 0
    for column in range(columns):
        for row in range(rows):
            tile = _fetch_tile(zoom, x_min + column, y_min + row, user_agent)
            if tile is None:
                continue
            canvas.paste(tile, (column * TILE_SIZE, row * TILE_SIZE))
            loaded += 1

    # a map with no tiles at all is worse than no map
    if loaded == 0:
        return None

    # crop the window back out of the grid, then scale it down uniformly
    origin_x = x_min * TILE_SIZE
    origin_y = y_min * TILE_SIZE
    cropped = canvas.crop((
        int(round(px_left - origin_x)), int(round(px_top - origin_y)),
        int(round(px_right - origin_x)), int(round(px_bottom - origin_y)),
    ))

    # the bounds are now the window's, which is what any overlay has to use
    bounds = (
        _y_to_lat(px_bottom / TILE_SIZE, zoom),
        _x_to_lon(px_left / TILE_SIZE, zoom),
        _y_to_lat(px_top / TILE_SIZE, zoom),
        _x_to_lon(px_right / TILE_SIZE, zoom),
    )

    return MapView(image=cropped.resize((max(1, width), max(1, height)),
                                        Image.LANCZOS),
                   bounds=bounds)


def project(lat: float, lon: float, bounds: tuple, width: int,
            height: int) -> tuple:
    """
    Place a coordinate onto a rendered map

    @param lat: float Latitude in decimal degrees
    @param lon: float Longitude in decimal degrees
    @param bounds: tuple The map's south, west, north, and east edges
    @param width: int The rendered map width
    @param height: int The rendered map height
    @return tuple: The x and y pixel position
    """

    # project both the point and the box at a fixed zoom, then scale
    south, west, north, east = bounds
    zoom = 8
    x_left = _lon_to_x(west, zoom)
    x_right = _lon_to_x(east, zoom)
    y_top = _lat_to_y(north, zoom)
    y_bottom = _lat_to_y(south, zoom)

    # guard against a degenerate box
    span_x = x_right - x_left
    span_y = y_bottom - y_top
    if span_x == 0 or span_y == 0:
        return (width // 2, height // 2)

    # and map it into pixels
    x = (_lon_to_x(lon, zoom) - x_left) / span_x * width
    y = (_lat_to_y(lat, zoom) - y_top) / span_y * height
    return (int(round(x)), int(round(y)))
