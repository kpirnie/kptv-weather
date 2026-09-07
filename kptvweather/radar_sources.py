#!/usr/bin/env python3
"""
Radar Sources Module

Fetches the radar loop. NOAA covers the United States and is preferred there;
RainViewer is worldwide and is what the rest of the planet falls back to.
Both return frames already sized to the requested pixel box.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import io
import logging
import math
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Optional

import requests
from PIL import Image

from .utils import to_local

logger = logging.getLogger(__name__)

# NOAA's public reflectivity mosaic, served as a WMS
NOAA_WMS = "https://opengeo.ncep.noaa.gov/geoserver/conus/conus_bref_qcd/ows"
NOAA_LAYER = "conus_bref_qcd"
NOAA_ATTRIBUTION = "NOAA / National Weather Service"

# RainViewer's tile index and the tiles it points at
RAINVIEWER_INDEX = "https://api.rainviewer.com/public/weather-maps.json"
RAINVIEWER_ATTRIBUTION = "RainViewer"

# how the RainViewer tiles are asked for: colour scheme, smoothing, and snow
RAINVIEWER_OPTIONS = "2/1_1"

# their tiles are the standard square, and their public grid stops here,
# so anything deeper is fetched at this level and scaled up instead
RAINVIEWER_TILE = 256
RAINVIEWER_MAX_ZOOM = 7


def fetch_noaa(south: float, west: float, north: float, east: float,
               width: int, height: int, user_agent: str = "kptv-weather/1.0",
               frames: int = 6, step_minutes: int = 10) -> list:
    """
    Fetch a NOAA reflectivity loop for a bounding box

    @param south: float Southern edge
    @param west: float Western edge
    @param north: float Northern edge
    @param east: float Eastern edge
    @param width: int Frame width in pixels
    @param height: int Frame height in pixels
    @param user_agent: str Sent with every request
    @param frames: int How many frames to build
    @param step_minutes: int Minutes between frames
    @return list: Frame dicts of image, label, timestamp, and coverage
    """

    # walk backwards from the most recent completed scan
    now = datetime.now(dt_timezone.utc)
    anchor = now - timedelta(minutes=now.minute % step_minutes,
                             seconds=now.second,
                             microseconds=now.microsecond)

    # build each frame in chronological order
    out: list = []
    for step in range(frames - 1, -1, -1):
        moment = anchor - timedelta(minutes=step * step_minutes)
        image = _noaa_frame(south, west, north, east, width, height,
                            moment, user_agent)
        if image is None:
            continue
        out.append({
            "image": image,
            "label": to_local(moment).strftime("%I:%M %p").lstrip("0"),
            "timestamp": moment.timestamp(),
            "coverage": _coverage(image),
        })
    return out


def _noaa_frame(south: float, west: float, north: float, east: float,
                width: int, height: int, moment: datetime,
                user_agent: str) -> Optional[Image.Image]:
    """
    Fetch one NOAA frame at a specific time

    @param south: float Southern edge
    @param west: float Western edge
    @param north: float Northern edge
    @param east: float Eastern edge
    @param width: int Frame width in pixels
    @param height: int Frame height in pixels
    @param moment: datetime The scan time to request
    @param user_agent: str Sent with the request
    @return Image|None: The frame, or None when it could not be fetched
    """

    # a standard WMS GetMap against the time dimension
    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetMap",
        "layers": NOAA_LAYER,
        "styles": "",
        "format": "image/png",
        "transparent": "true",
        "crs": "CRS:84",
        "bbox": f"{west},{south},{east},{north}",
        "width": str(max(1, int(width))),
        "height": str(max(1, int(height))),
        "time": moment.strftime("%Y-%m-%dT%H:%M:00Z"),
    }

    # ask for it, treating any failure as simply no frame
    try:
        resp = requests.get(NOAA_WMS, params=params,
                            headers={"User-Agent": user_agent}, timeout=20)
        resp.raise_for_status()
        with Image.open(io.BytesIO(resp.content)) as handle:
            return handle.convert("RGBA")
    except (requests.RequestException, OSError, ValueError) as exc:
        logger.debug("NOAA frame at %s failed: %s", params["time"], exc)
        return None


def _coverage(image: Image.Image) -> float:
    """
    Roughly how much of a frame carries an echo

    Used to tell a genuinely quiet radar picture from a request that landed
    outside the mosaic's footprint entirely.

    @param image: Image The radar frame
    @return float: The fraction of pixels with any opacity
    """

    # sample the alpha channel on a small thumbnail rather than every pixel
    try:
        alpha = image.getchannel("A").resize((64, 64))
    except ValueError:
        return 0.0

    # count anything meaningfully opaque
    data = alpha.getdata()
    lit = sum(1 for value in data if value > 24)
    return lit / float(len(data) or 1)


def fetch_rainviewer(south: float, west: float, north: float, east: float,
                     width: int, height: int,
                     user_agent: str = "kptv-weather/1.0",
                     max_frames: int = 6) -> list:
    """
    Fetch a RainViewer loop for a bounding box

    Their tiles are served on the standard web mercator grid, so the loop is
    stitched and cropped to the same box the backdrop covers, which is what
    keeps the echoes sitting over the right ground.

    @param south: float Southern edge
    @param west: float Western edge
    @param north: float Northern edge
    @param east: float Eastern edge
    @param width: int Frame width in pixels
    @param height: int Frame height in pixels
    @param user_agent: str Sent with every request
    @param max_frames: int How many frames to build
    @return list: Frame dicts of image, label, timestamp, and coverage
    """

    # find out what is currently available
    try:
        resp = requests.get(RAINVIEWER_INDEX,
                            headers={"User-Agent": user_agent}, timeout=15)
        resp.raise_for_status()
        index = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("RainViewer index failed: %s", exc)
        return []

    # the past frames are the ones worth animating
    host = str(index.get("host") or "").rstrip("/")
    radar = index.get("radar") if isinstance(index, dict) else None
    past = (radar or {}).get("past") if isinstance(radar, dict) else None
    if not host or not isinstance(past, list) or not past:
        return []

    # the deepest level their grid will serve that still covers the box
    zoom = _tile_zoom(south, west, north, east, width, height)

    # take the tail of the loop and stitch each one
    out: list = []
    for entry in past[-max(1, int(max_frames)):]:
        path = str((entry or {}).get("path") or "").strip()
        stamp = entry.get("time") if isinstance(entry, dict) else None
        if not path:
            continue

        # stitch the tiles that cover the box and crop to it exactly
        image = _rainviewer_mosaic(host, path, zoom, south, west, north, east,
                                   width, height, user_agent)
        if image is None:
            continue
        out.append({
            "image": image,
            "label": _label(stamp),
            "timestamp": float(stamp) if isinstance(stamp, (int, float)) else 0.0,
            "coverage": _coverage(image),
        })
    return out


def _rainviewer_mosaic(host: str, path: str, zoom: int, south: float,
                       west: float, north: float, east: float, width: int,
                       height: int,
                       user_agent: str) -> Optional[Image.Image]:
    """
    Stitch one RainViewer frame across a bounding box

    @param host: str The tile host from the index
    @param path: str The frame's path from the index
    @param zoom: int The zoom level to fetch at
    @param south: float Southern edge
    @param west: float Western edge
    @param north: float Northern edge
    @param east: float Eastern edge
    @param width: int Frame width in pixels
    @param height: int Frame height in pixels
    @param user_agent: str Sent with every request
    @return Image|None: The frame, or None when nothing could be fetched
    """

    # where the box lands on the tile grid
    left_x = _lon_to_x(west, zoom)
    right_x = _lon_to_x(east, zoom)
    top_y = _lat_to_y(north, zoom)
    bottom_y = _lat_to_y(south, zoom)
    first_x, last_x = int(math.floor(left_x)), int(math.floor(right_x))
    first_y, last_y = int(math.floor(top_y)), int(math.floor(bottom_y))

    # the canvas those tiles fill
    span = 2 ** zoom
    columns = last_x - first_x + 1
    rows = last_y - first_y + 1
    mosaic = Image.new("RGBA", (columns * RAINVIEWER_TILE,
                                rows * RAINVIEWER_TILE), (0, 0, 0, 0))

    # fetch each one, treating a miss as simply an empty square
    fetched = 0
    for column in range(columns):
        for row in range(rows):
            tile_x = (first_x + column) % span
            tile_y = first_y + row
            if tile_y < 0 or tile_y >= span:
                continue
            tile = _rainviewer_tile(host, path, zoom, tile_x, tile_y,
                                    user_agent)
            if tile is None:
                continue
            mosaic.paste(tile, (column * RAINVIEWER_TILE,
                                row * RAINVIEWER_TILE), tile)
            fetched += 1

    # nothing came back at all
    if not fetched:
        return None

    # crop the canvas back to the box and scale it to the frame
    crop = (
        int(round((left_x - first_x) * RAINVIEWER_TILE)),
        int(round((top_y - first_y) * RAINVIEWER_TILE)),
        int(round((right_x - first_x) * RAINVIEWER_TILE)),
        int(round((bottom_y - first_y) * RAINVIEWER_TILE)),
    )
    if crop[2] <= crop[0] or crop[3] <= crop[1]:
        return None
    return mosaic.crop(crop).resize((max(1, int(width)), max(1, int(height))),
                                    Image.LANCZOS)


def _rainviewer_tile(host: str, path: str, zoom: int, tile_x: int, tile_y: int,
                     user_agent: str) -> Optional[Image.Image]:
    """
    Fetch one RainViewer tile

    @param host: str The tile host from the index
    @param path: str The frame's path from the index
    @param zoom: int The zoom level
    @param tile_x: int The tile column
    @param tile_y: int The tile row
    @param user_agent: str Sent with the request
    @return Image|None: The tile, or None when it could not be fetched
    """

    # their standard tile endpoint
    url = (f"{host}{path}/{RAINVIEWER_TILE}/{zoom}/{tile_x}/{tile_y}/"
           f"{RAINVIEWER_OPTIONS}.png")
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent},
                            timeout=20)
        resp.raise_for_status()
        with Image.open(io.BytesIO(resp.content)) as handle:
            return handle.convert("RGBA")
    except (requests.RequestException, OSError, ValueError) as exc:
        logger.debug("RainViewer tile %s failed: %s", url, exc)
        return None


def _tile_zoom(south: float, west: float, north: float, east: float,
               width: int, height: int) -> int:
    """
    Choose the deepest zoom that still covers a box at the requested size

    @param south: float Southern edge
    @param west: float Western edge
    @param north: float Northern edge
    @param east: float Eastern edge
    @param width: int Frame width in pixels
    @param height: int Frame height in pixels
    @return int: A zoom level their public grid will serve
    """

    # step back down from their deepest level until the box fits
    for zoom in range(RAINVIEWER_MAX_ZOOM, 1, -1):
        span_x = (_lon_to_x(east, zoom) - _lon_to_x(west, zoom)) * \
            RAINVIEWER_TILE
        span_y = (_lat_to_y(south, zoom) - _lat_to_y(north, zoom)) * \
            RAINVIEWER_TILE
        if span_x <= width * 1.6 and span_y <= height * 1.6:
            return zoom
    return 2


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


def _label(stamp) -> str:
    """
    Format a frame timestamp for the on-screen loop label

    @param stamp: mixed The unix timestamp from the index
    @return str: A wall clock time, or an empty string
    """

    # nothing to format
    if not isinstance(stamp, (int, float)):
        return ""

    # local wall clock, without the leading zero
    moment = datetime.fromtimestamp(float(stamp), tz=dt_timezone.utc)
    return to_local(moment).strftime("%I:%M %p").lstrip("0")


def bounds_around(lat: float, lon: float, span_lat: float = 3.0) -> tuple:
    """
    Build a radar bounding box around a point

    Longitude is widened by the cosine of the latitude so the box stays
    roughly square on screen rather than squashing toward the poles.

    @param lat: float Centre latitude
    @param lon: float Centre longitude
    @param span_lat: float How much latitude to cover
    @return tuple: South, west, north, and east edges
    """

    # widen the longitude span to match
    span_lon = span_lat / max(0.2, math.cos(math.radians(lat)))
    return (lat - span_lat / 2.0, lon - span_lon / 2.0,
            lat + span_lat / 2.0, lon + span_lon / 2.0)
            