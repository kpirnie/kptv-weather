#!/usr/bin/env python3
"""
NWS Alerts Provider Module

Pulls active watches, warnings, and advisories for a point from the National
Weather Service. US only; everywhere else simply gets no alerts.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# where active alerts come from
ALERTS_URL = "https://api.weather.gov/alerts/active"

# alert statuses we will actually put on screen
LIVE_STATUS = {"actual"}

# and the message types worth showing, cancellations are not
LIVE_TYPES = {"alert", "update"}


class NWSAlertClient:
    """
    Thread-safe client for active NWS alerts at a point

    Cached on its own short TTL, separate from the forecast, since alerts
    matter far more urgently than the hourly numbers do.
    """

    def __init__(self, lat: float, lon: float, *,
                 user_agent: str = "kptv-weather/1.0",
                 cache_ttl: int = 120, timeout: int = 15):
        """
        Build the client

        @param lat: float Latitude in decimal degrees
        @param lon: float Longitude in decimal degrees
        @param user_agent: str Sent on every request, required by the api
        @param cache_ttl: int Seconds a fetched alert set stays fresh
        @param timeout: int Per-request timeout in seconds
        """

        # the point we watch
        self.lat = float(lat)
        self.lon = float(lon)
        self.user_agent = user_agent
        self.ttl = max(30, int(cache_ttl))
        self.timeout = int(timeout)

        # cache state
        self._lock = threading.RLock()
        self._alerts: list = []
        self._fetched_at = 0.0

    def alerts(self) -> list:
        """
        Active alerts for the configured point

        Never raises: a failed fetch keeps whatever was last known good, so
        an alert already on screen does not vanish because of one bad request.

        @return list: Normalized alert dicts, most severe first
        """

        # serve the cached set while it is fresh
        now = time.time()
        with self._lock:
            if self._fetched_at and now - self._fetched_at < self.ttl:
                return list(self._alerts)

        # go get them
        try:
            fetched = self._fetch()
        except Exception as exc:
            logger.warning("alert fetch failed: %s", exc)
            with self._lock:
                return list(self._alerts)

        # stash and hand back
        with self._lock:
            self._alerts = fetched
            self._fetched_at = time.time()
            return list(fetched)

    def _fetch(self) -> list:
        """
        Request and normalize the active alerts

        @return list: Normalized alert dicts
        @throws requests.RequestException: On a network failure
        """

        # the api wants a real user agent and its own json profile
        resp = requests.get(
            ALERTS_URL,
            params={"point": f"{self.lat:.4f},{self.lon:.4f}", "status": "actual"},
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/geo+json",
            },
            timeout=self.timeout,
        )

        # outside the US this legitimately comes back empty or 404s
        if resp.status_code == 404:
            return []
        resp.raise_for_status()

        # walk the features and keep the ones worth showing
        payload = resp.json()
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            return []

        out: list = []
        for feature in features:
            alert = self._normalize(feature)
            if alert:
                out.append(alert)

        # most severe first so the ticker leads with the worst of it
        out.sort(key=lambda a: _severity_rank(a.get("severity")))
        return out

    def _normalize(self, feature: Any) -> Optional[dict]:
        """
        Convert one alert feature into the shape the ticker consumes

        @param feature: mixed One entry from the api's feature list
        @return dict|None: The normalized alert, or None when it is not usable
        """

        # it has to be a feature with properties
        if not isinstance(feature, dict):
            return None
        props = feature.get("properties")
        if not isinstance(props, dict):
            return None

        # skip anything cancelled, expired, or otherwise not a live warning
        status = str(props.get("status") or "").strip().lower()
        msg_type = str(props.get("messageType") or "").strip().lower()
        if status and status not in LIVE_STATUS:
            return None
        if msg_type and msg_type not in LIVE_TYPES:
            return None

        # the event name is what we lead with
        event = str(props.get("event") or "").strip()
        if not event:
            return None

        # lay it out
        return {
            "title": event,
            "headline": str(props.get("headline") or "").strip(),
            "severity": str(props.get("severity") or "Unknown").title(),
            "urgency": str(props.get("urgency") or "").title(),
            "regions": str(props.get("areaDesc") or "").strip(),
            "expires": _epoch(props.get("expires")),
            "description": str(props.get("description") or "").strip(),
        }


def _epoch(value: Any) -> Optional[float]:
    """
    Parse an ISO 8601 timestamp into a unix timestamp

    @param value: mixed The raw timestamp string
    @return float|None: The timestamp, or None when unparseable
    """

    # nothing to parse
    raw = str(value or "").strip()
    if not raw:
        return None

    # python wants a plain offset rather than a trailing Z
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _severity_rank(severity: Any) -> int:
    """
    Sort key placing the most severe alerts first

    @param severity: mixed The severity string from the api
    @return int: A rank, lower being more severe
    """

    # the api's own severity vocabulary, in order
    order = {"extreme": 0, "severe": 1, "moderate": 2, "minor": 3, "unknown": 4}
    return order.get(str(severity or "").strip().lower(), 5)
