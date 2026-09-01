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


def fetch_rainviewer(center_lat: float, center_lon: float, width: int,
                     height: int, user_agent: str = "kptv-weather/1.0",
                     span_degrees: float = 3.0, max_frames: int = 6) -> list:
    """
    Fetch a RainViewer loop centred on a point

    RainViewer serves single map images by centre and zoom rather than by
    bounding box, so the span is converted into the nearest zoom level.

    @param center_lat: float Centre latitude
    @param center_lon: float Centre longitude
    @param width: int Frame width in pixels
    @param height: int Frame height in pixels
    @param user_agent: str Sent with every request
    @param span_degrees: float How much latitude the frame should cover
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

    # work the zoom out from the span we were asked to cover
    zoom = _zoom_for_span(span_degrees, height)

    # take the tail of the loop and fetch each one
    out: list = []
    for entry in past[-max(1, int(max_frames)):]:
        path = str((entry or {}).get("path") or "").strip()
        stamp = entry.get("time") if isinstance(entry, dict) else None
        if not path:
            continue

        # RainViewer composes the whole frame for us
        url = (f"{host}{path}/{max(width, height)}/{zoom}/"
               f"{center_lat:.4f}/{center_lon:.4f}/{RAINVIEWER_OPTIONS}.png")
        try:
            frame = requests.get(url, headers={"User-Agent": user_agent},
                                 timeout=20)
            frame.raise_for_status()
            with Image.open(io.BytesIO(frame.content)) as handle:
                image = handle.convert("RGBA")
        except (requests.RequestException, OSError, ValueError) as exc:
            logger.debug("RainViewer frame %s failed: %s", path, exc)
            continue

        # crop the square frame down to the box we actually draw into
        image = _fit(image, width, height)
        out.append({
            "image": image,
            "label": _label(stamp),
            "timestamp": float(stamp) if isinstance(stamp, (int, float)) else 0.0,
            "coverage": _coverage(image),
        })
    return out


def _zoom_for_span(span_degrees: float, height: int) -> int:
    """
    Convert a latitude span into a web mercator zoom level

    @param span_degrees: float How much latitude to cover
    @param height: int The frame height in pixels
    @return int: A zoom level between two and ten
    """

    # a tile is 256 pixels and covers 360 degrees at zoom zero
    try:
        tiles = max(0.01, height / 256.0)
        zoom = math.log2(360.0 * tiles / max(0.01, span_degrees))
    except ValueError:
        return 6
    return max(2, min(10, int(round(zoom))))


def _fit(image: Image.Image, width: int, height: int) -> Image.Image:
    """
    Crop a square frame to the target aspect and size

    @param image: Image The fetched frame
    @param width: int Target width
    @param height: int Target height
    @return Image: The cropped and scaled frame
    """

    # already right
    if image.size == (width, height):
        return image

    # scale so the shorter side covers, then centre crop the excess
    scale = max(width / image.width, height / image.height)
    resized = image.resize(
        (max(1, int(round(image.width * scale))),
         max(1, int(round(image.height * scale)))),
        Image.LANCZOS,
    )
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


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
