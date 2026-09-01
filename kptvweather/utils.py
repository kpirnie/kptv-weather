#!/usr/bin/env python3
"""
Utilities Module

Timezone handling, small geometry helpers, and the formatting odds and ends
the layers share.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone as dt_timezone, tzinfo
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

# the compass points, in the order sixteen-point bearings walk them
CARDINALS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)

# whatever the api told us the location's timezone is
_LOCAL_TZ: Optional[tzinfo] = None


def set_timezone(name: Optional[str], lat: Optional[float] = None,
                 lon: Optional[float] = None) -> None:
    """
    Pin the timezone every on-screen clock and date uses

    Falls back to a fixed offset estimated from the longitude when the name
    cannot be loaded, which is far better than silently showing UTC.

    @param name: str|None An IANA timezone name
    @param lat: float|None Latitude, unused but kept for symmetry
    @param lon: float|None Longitude, used to estimate an offset
    @return None
    """

    # try the name we were handed first
    global _LOCAL_TZ
    if name:
        try:
            _LOCAL_TZ = ZoneInfo(str(name))
            logger.info("timezone set to %s", name)
            return
        except (ZoneInfoNotFoundError, ValueError, OSError):
            logger.warning("unknown timezone %r, estimating from longitude", name)

    # fifteen degrees of longitude per hour is close enough to be useful
    if lon is not None:
        offset_hours = max(-12, min(14, int(round(float(lon) / 15.0))))
        _LOCAL_TZ = dt_timezone(_hours(offset_hours))
        logger.info("timezone estimated at UTC%+d", offset_hours)
        return

    # and if we have nothing at all, use whatever the container is set to
    _LOCAL_TZ = None


def _hours(count: int):
    """
    Build a timedelta of whole hours

    @param count: int How many hours
    @return timedelta: The offset
    """

    # keep the import local, this is the only place that needs it
    from datetime import timedelta
    return timedelta(hours=count)


def local_tzinfo() -> Optional[tzinfo]:
    """
    The timezone currently in effect

    @return tzinfo|None: The zone, or None to mean the system default
    """

    # just the module state
    return _LOCAL_TZ


def to_local(moment: datetime) -> datetime:
    """
    Convert a datetime into the display timezone

    @param moment: datetime The moment to convert
    @return datetime: The same moment, expressed locally
    """

    # a naive datetime is assumed to already be UTC
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt_timezone.utc)

    # no zone pinned means the container's own setting
    if _LOCAL_TZ is None:
        return moment.astimezone()
    return moment.astimezone(_LOCAL_TZ)


def now_local() -> datetime:
    """
    The current moment in the display timezone

    @return datetime: Right now, locally
    """

    # straight through the converter
    return to_local(datetime.now(dt_timezone.utc))


def format_cardinal(bearing: Optional[float]) -> str:
    """
    Turn a wind bearing into a compass point

    @param bearing: float|None Degrees clockwise from north
    @return str: A sixteen-point compass label, or two dashes
    """

    # nothing to convert
    if bearing is None:
        return "--"

    # each point covers 22.5 degrees, so round into the nearest bucket
    try:
        index = int(round(float(bearing) / 22.5)) % 16
    except (TypeError, ValueError):
        return "--"
    return CARDINALS[index]


def safe_round(value, digits: int = 0):
    """
    Round a value without ever raising

    @param value: mixed The value to round
    @param digits: int How many decimal places
    @return float|None: The rounded value, or None
    """

    # anything unusable comes back as missing rather than blowing up
    try:
        rounded = round(float(value), digits)
    except (TypeError, ValueError):
        return None
    return rounded


def compute_bounds(coords: Sequence[tuple], center_lat: float, center_lon: float,
                   pad_degrees: float = 0.35, min_span: float = 2.0,
                   max_span: Optional[float] = None) -> tuple:
    """
    Work out a lat/lon box that comfortably contains a set of points

    @param coords: Sequence Latitude and longitude pairs to enclose
    @param center_lat: float Fallback centre latitude
    @param center_lon: float Fallback centre longitude
    @param pad_degrees: float Padding added on every side
    @param min_span: float Smallest box we will produce
    @param max_span: float|None Largest box we will produce
    @return tuple: South, west, north, and east edges
    """

    # keep only the usable pairs
    points = [
        (float(lat), float(lon)) for lat, lon in coords
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float))
    ]

    # nothing to enclose, so build a default box around the centre
    if not points:
        half = max(0.5, min_span / 2.0)
        return (center_lat - half, center_lon - half,
                center_lat + half, center_lon + half)

    # the raw extent, padded out
    south = min(p[0] for p in points) - pad_degrees
    north = max(p[0] for p in points) + pad_degrees
    west = min(p[1] for p in points) - pad_degrees
    east = max(p[1] for p in points) + pad_degrees

    # widen anything too tight to read
    south, north = _enforce_span(south, north, min_span, max_span)
    west, east = _enforce_span(west, east, min_span, max_span)

    # and keep it on the actual planet
    south = max(-85.0, south)
    north = min(85.0, north)
    west = max(-180.0, west)
    east = min(180.0, east)
    return (south, west, north, east)


def _enforce_span(low: float, high: float, min_span: float,
                  max_span: Optional[float]) -> tuple:
    """
    Widen or narrow one axis of a bounding box to fit within limits

    @param low: float The lower edge
    @param high: float The upper edge
    @param min_span: float Smallest acceptable span
    @param max_span: float|None Largest acceptable span
    @return tuple: The adjusted low and high edges
    """

    # measure it and find the middle
    span = high - low
    center = (high + low) / 2.0

    # too small, so open it out around the centre
    if span < min_span:
        half = min_span / 2.0
        return (center - half, center + half)

    # too large, so pull it back in
    if max_span and span > max_span:
        half = max_span / 2.0
        return (center - half, center + half)

    return (low, high)


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great circle distance between two points, in miles

    @param lat1: float First latitude
    @param lon1: float First longitude
    @param lat2: float Second latitude
    @param lon2: float Second longitude
    @return float: The distance in statute miles
    """

    # the usual haversine, with the earth's mean radius in miles
    radius = 3958.7613
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (math.sin(d_phi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2)
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def truncate(text: str, limit: int) -> str:
    """
    Shorten a string to a character limit with an ellipsis

    @param text: str The string to shorten
    @param limit: int The most characters to keep
    @return str: The shortened string
    """

    # short enough already
    value = str(text or "")
    if len(value) <= limit or limit <= 1:
        return value

    # trim on a word boundary where we can
    clipped = value[: limit - 1].rstrip()
    return clipped + "\u2026"
