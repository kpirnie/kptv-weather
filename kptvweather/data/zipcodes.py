#!/usr/bin/env python3
"""
ZIP Code Module

Resolves a US ZIP code to coordinates and a place name. Nothing is bundled:
the lookup goes out to the public Zippopotam service and is cached for the
life of the process, since a station's ZIP never changes while it runs.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import logging
import re
import threading
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

# where we resolve them
ZIP_URL = "https://api.zippopotam.us/us"

# what a US ZIP actually looks like, plus-four and all
ZIP_PATTERN = re.compile(r"^(\d{5})(?:-\d{4})?$")

# resolved codes, kept for the life of the process
_CACHE: Dict[str, Optional[dict]] = {}
_LOCK = threading.Lock()


def resolve_zip(code: str, user_agent: str = "kptv-weather/1.0",
                timeout: int = 15) -> Optional[dict]:
    """
    Resolve a US ZIP code to coordinates and a place name

    @param code: str The ZIP code, with or without the plus-four
    @param user_agent: str Sent with the request
    @param timeout: int Request timeout in seconds
    @return dict|None: A dict of lat, lon, city, and state, or None
    """

    # it has to look like a ZIP before we bother asking
    match = ZIP_PATTERN.match(str(code or "").strip())
    if not match:
        return None
    base = match.group(1)

    # a resolved code never changes, so the cache is permanent
    with _LOCK:
        if base in _CACHE:
            return _CACHE[base]

    # go ask
    resolved = _fetch(base, user_agent, timeout)

    # cache the miss as well, so a bad ZIP is not retried on every refresh
    with _LOCK:
        _CACHE[base] = resolved
    return resolved


def _fetch(code: str, user_agent: str, timeout: int) -> Optional[dict]:
    """
    Fetch one ZIP code from the lookup service

    @param code: str A five digit ZIP
    @param user_agent: str Sent with the request
    @param timeout: int Request timeout in seconds
    @return dict|None: The resolved location, or None
    """

    # ask for it, treating every failure as simply unresolvable
    try:
        resp = requests.get(
            f"{ZIP_URL}/{code}",
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning("ZIP lookup for %s failed: %s", code, exc)
        return None

    # an unknown ZIP comes back as a 404
    if resp.status_code != 200:
        logger.warning("ZIP %s did not resolve (HTTP %s)", code, resp.status_code)
        return None

    # parse it out
    try:
        payload = resp.json()
    except ValueError:
        logger.warning("ZIP lookup for %s returned malformed JSON", code)
        return None

    # the interesting part is the first place in the list
    places = payload.get("places") if isinstance(payload, dict) else None
    if not isinstance(places, list) or not places:
        return None
    place = places[0]

    # coordinates arrive as strings
    try:
        lat = float(place.get("latitude"))
        lon = float(place.get("longitude"))
    except (TypeError, ValueError):
        return None

    # lay it out
    return {
        "lat": lat,
        "lon": lon,
        "city": str(place.get("place name") or "").strip(),
        "state": str(place.get("state abbreviation") or
                     place.get("state") or "").strip(),
    }
