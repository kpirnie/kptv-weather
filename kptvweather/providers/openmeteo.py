#!/usr/bin/env python3
"""
Open-Meteo Provider Module

Fetches forecast data from Open-Meteo and reshapes it into the flat payload
the normalizer consumes. No API key is needed, and one call returns current
conditions, an hourly series, and a daily series together.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# where we pull forecasts and place names from
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# unit systems we accept, mapped onto what the api calls them
UNIT_PARAMS = {
    "us": {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
           "precipitation_unit": "inch"},
    "si": {"temperature_unit": "celsius", "wind_speed_unit": "ms",
           "precipitation_unit": "mm"},
    "ca": {"temperature_unit": "celsius", "wind_speed_unit": "kmh",
           "precipitation_unit": "mm"},
    "uk": {"temperature_unit": "celsius", "wind_speed_unit": "mph",
           "precipitation_unit": "mm"},
}

# the current conditions we ask for
CURRENT_FIELDS = (
    "temperature_2m", "apparent_temperature", "relative_humidity_2m",
    "dew_point_2m", "pressure_msl", "cloud_cover", "wind_speed_10m",
    "wind_direction_10m", "wind_gusts_10m", "precipitation", "weather_code",
    "is_day",
)

# the hourly series we ask for
HOURLY_FIELDS = (
    "temperature_2m", "apparent_temperature", "relative_humidity_2m",
    "dew_point_2m", "pressure_msl", "cloud_cover", "precipitation_probability",
    "weather_code", "visibility", "uv_index", "wind_speed_10m",
    "wind_direction_10m", "wind_gusts_10m", "is_day",
)

# the daily series we ask for
DAILY_FIELDS = (
    "weather_code", "temperature_2m_max", "temperature_2m_min",
    "apparent_temperature_max", "apparent_temperature_min", "sunrise",
    "sunset", "uv_index_max", "precipitation_sum", "rain_sum",
    "showers_sum", "snowfall_sum", "precipitation_probability_max",
    "wind_speed_10m_max", "wind_gusts_10m_max", "wind_direction_10m_dominant",
)

# wmo weather codes mapped to a short phrase and an icon family
WMO_CODES = {
    0: ("Clear", "clear"),
    1: ("Mostly Clear", "partly-cloudy"),
    2: ("Partly Cloudy", "partly-cloudy"),
    3: ("Overcast", "cloudy"),
    45: ("Fog", "fog"),
    48: ("Freezing Fog", "fog"),
    51: ("Light Drizzle", "rain"),
    53: ("Drizzle", "rain"),
    55: ("Heavy Drizzle", "rain"),
    56: ("Freezing Drizzle", "snow"),
    57: ("Freezing Drizzle", "snow"),
    61: ("Light Rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy Rain", "rain"),
    66: ("Freezing Rain", "snow"),
    67: ("Freezing Rain", "snow"),
    71: ("Light Snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy Snow", "snow"),
    77: ("Snow Grains", "snow"),
    80: ("Rain Showers", "rain"),
    81: ("Rain Showers", "rain"),
    82: ("Heavy Rain Showers", "rain"),
    85: ("Snow Showers", "snow"),
    86: ("Heavy Snow Showers", "snow"),
    95: ("Thunderstorms", "thunderstorm"),
    96: ("Thunderstorms with Hail", "thunderstorm"),
    99: ("Thunderstorms with Hail", "thunderstorm"),
}

# codes that mean frozen precipitation rather than liquid
SNOW_CODES = {56, 57, 66, 67, 71, 73, 75, 77, 85, 86}

# a synodic month, used to work the moon phase out ourselves since the api
# does not carry one
SYNODIC_MONTH = 29.530588853

# a known new moon, as a unix timestamp
KNOWN_NEW_MOON = 947182440.0


class WeatherError(RuntimeError):
    """
    Raised when a forecast cannot be retrieved at all
    """


class OpenMeteoClient:
    """
    Thread-safe Open-Meteo client with per-location caching

    The renderer polls far more often than the models actually update, so
    everything is served from a TTL cache and a stale copy is preferred over
    a blank screen when the network is down.
    """

    def __init__(self, lat: float, lon: float, *, units: str = "us",
                 cache_ttl: int = 600, secondary_ttl: int = 5400,
                 user_agent: str = "kptv-weather/1.0", timeout: int = 20):
        """
        Build the client

        @param lat: float Primary latitude in decimal degrees
        @param lon: float Primary longitude in decimal degrees
        @param units: str One of us, si, ca, uk
        @param cache_ttl: int Seconds a primary forecast stays fresh
        @param secondary_ttl: int Longer TTL for regional city lookups
        @param user_agent: str Sent on every request
        @param timeout: int Per-request timeout in seconds
        """

        # the location and how we want it formatted
        self.lat = float(lat)
        self.lon = float(lon)
        self.units = units if units in UNIT_PARAMS else "us"
        self.ttl = max(60, int(cache_ttl))
        self.secondary_ttl = max(self.ttl, int(secondary_ttl))
        self.user_agent = user_agent
        self.timeout = int(timeout)

        # cache state, touched from the refresh thread
        self._lock = threading.RLock()
        self._cache: Dict[str, tuple] = {}
        self._calls_made = 0
        self._last_error: Optional[str] = None

        # a pooled session with retries, since these are all the same host
        self._session = build_session(user_agent)

    # -- introspection ----------------------------------------------------

    @property
    def calls_made(self) -> int:
        """
        Requests actually sent this process lifetime

        @return int: The call count
        """

        # simple counter read
        with self._lock:
            return self._calls_made

    @property
    def last_error(self) -> Optional[str]:
        """
        The most recent failure, if any

        @return str|None: A short error description
        """

        # simple state read
        with self._lock:
            return self._last_error

    def status_summary(self) -> str:
        """
        Short human readable status line for diagnostics

        @return str: Call count, plus the last error when there was one
        """

        # roll it up
        with self._lock:
            if self._last_error:
                return f"{self._calls_made} calls sent, last error: {self._last_error}"
            return f"{self._calls_made} calls sent"

    # -- HTTP -------------------------------------------------------------

    def _params(self, lat: float, lon: float) -> Dict[str, str]:
        """
        Build the query string for a forecast request

        @param lat: float Latitude in decimal degrees
        @param lon: float Longitude in decimal degrees
        @return dict: Query parameters for the forecast endpoint
        """

        # coordinates, the field lists, and the unit system
        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "current": ",".join(CURRENT_FIELDS),
            "hourly": ",".join(HOURLY_FIELDS),
            "daily": ",".join(DAILY_FIELDS),
            "timezone": "auto",
            "timeformat": "unixtime",
            "forecast_days": "7",
        }
        params.update(UNIT_PARAMS[self.units])
        return params

    def _request(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Fetch and reshape one forecast

        @param lat: float Latitude in decimal degrees
        @param lon: float Longitude in decimal degrees
        @return dict: The reshaped payload
        @throws WeatherError: On any network or upstream failure
        """

        # ask for it
        try:
            resp = self._session.get(
                FORECAST_URL, params=self._params(lat, lon), timeout=self.timeout,
            )
        except requests.RequestException as exc:
            with self._lock:
                self._last_error = f"network error: {exc.__class__.__name__}"
            raise WeatherError(f"Open-Meteo request failed: {exc}") from exc

        # count it whatever came back
        with self._lock:
            self._calls_made += 1

        # anything but a 200 is a failure we cannot use
        if resp.status_code != 200:
            with self._lock:
                self._last_error = f"HTTP {resp.status_code}"
            raise WeatherError(f"Open-Meteo returned HTTP {resp.status_code}")

        # and it has to be json we can actually read
        try:
            payload = resp.json()
        except ValueError as exc:
            with self._lock:
                self._last_error = "malformed JSON response"
            raise WeatherError("Open-Meteo returned malformed JSON") from exc
        if not isinstance(payload, dict):
            raise WeatherError("Open-Meteo returned an unexpected payload")

        # clear the error state and hand back the reshaped version
        with self._lock:
            self._last_error = None
        return reshape(payload)

    def _cached(self, lat: float, lon: float, ttl: int) -> Dict[str, Any]:
        """
        Serve a forecast from cache when it is still fresh

        @param lat: float Latitude in decimal degrees
        @param lon: float Longitude in decimal degrees
        @param ttl: int How long a cached copy stays fresh
        @return dict: The reshaped payload
        @throws WeatherError: When the fetch fails and nothing is cached
        """

        # look for a fresh hit first
        cache_key = f"{lat:.3f},{lon:.3f}"
        now = time.time()
        with self._lock:
            hit = self._cache.get(cache_key)
            if hit and now - hit[0] < ttl:
                return hit[1]

        # go get it, falling back to a stale copy rather than blanking the screen
        try:
            payload = self._request(lat, lon)
        except WeatherError:
            with self._lock:
                hit = self._cache.get(cache_key)
            if hit:
                logger.warning("serving a stale forecast for %s", cache_key)
                return hit[1]
            raise

        # stash it and hand it over
        with self._lock:
            self._cache[cache_key] = (time.time(), payload)
        return payload

    # -- public API -------------------------------------------------------

    def forecast(self) -> Dict[str, Any]:
        """
        Full payload for the primary location

        @return dict: The reshaped payload
        """

        # straight through the cache
        return self._cached(self.lat, self.lon, self.ttl)

    def point_forecast(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        """
        Payload for a secondary location used by the map pages

        Returns None rather than raising, so one unreachable city never takes
        the regional page down with it.

        @param lat: float Latitude in decimal degrees
        @param lon: float Longitude in decimal degrees
        @return dict|None: The reshaped payload, or None on failure
        """

        # swallow the failure, the caller just skips this city
        try:
            return self._cached(float(lat), float(lon), self.secondary_ttl)
        except WeatherError:
            return None

    def timezone_name(self) -> Optional[str]:
        """
        The IANA timezone the api resolved for the primary location

        @return str|None: The timezone name, or None when unavailable
        """

        # it rides along in the forecast payload
        tz = self.forecast().get("timezone")
        return tz if isinstance(tz, str) and tz else None


def build_session(user_agent: str) -> requests.Session:
    """
    Build a pooled session with sane retry behaviour

    @param user_agent: str Value sent on every request
    @return Session: The configured session
    """

    # retry the transient stuff, never the client errors
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )

    # wire it up with a small connection pool
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": user_agent,
        "Accept": "application/json",
    })
    return session


# ---------------------------------------------------------------------------
# Reshaping
# ---------------------------------------------------------------------------

def _num(value: Any) -> Optional[float]:
    """
    Coerce a value to a float, treating anything unusable as missing

    @param value: mixed The raw value
    @return float|None: The number, or None
    """

    # booleans are numbers in python, and that is never what we want here
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _pick(series: dict, key: str, index: int) -> Optional[float]:
    """
    Read one entry out of an hourly or daily series

    @param series: dict The series block from the response
    @param key: str Which field to read
    @param index: int Which position in that field
    @return float|None: The value, or None when absent
    """

    # the field has to be there and long enough
    values = series.get(key)
    if not isinstance(values, list) or index >= len(values):
        return None
    return _num(values[index])


def _code_at(series: dict, index: int) -> Any:
    """
    Read a weather code out of a series without tripping over gaps

    @param series: dict The series block from the response
    @param index: int Which position to read
    @return mixed: The code, or None
    """

    # same bounds checking as _pick, but the value stays raw
    values = series.get("weather_code")
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]


def describe(code: Any, is_day: bool) -> tuple:
    """
    Turn a WMO weather code into a phrase and an icon key

    @param code: mixed The raw weather code
    @param is_day: bool Whether this is a daytime observation
    @return tuple: The summary phrase and the icon key
    """

    # look it up, defaulting to something harmless
    value = _num(code)
    phrase, family = WMO_CODES.get(int(value) if value is not None else -1,
                                   ("Unknown", "cloudy"))

    # the clear and partly cloudy families carry a day/night variant
    if family in ("clear", "partly-cloudy"):
        return phrase, f"{family}-{'day' if is_day else 'night'}"
    return phrase, family


def precip_type(code: Any) -> str:
    """
    Work out whether precipitation is frozen or liquid from the weather code

    @param code: mixed The raw weather code
    @return str: snow, rain, or none
    """

    # nothing to say without a code
    value = _num(code)
    if value is None:
        return "none"

    # the frozen codes are a known set, everything wet above the clear codes
    # is liquid
    numeric = int(value)
    if numeric in SNOW_CODES:
        return "snow"
    return "rain" if numeric >= 51 else "none"


def moon_phase(epoch: Optional[float]) -> Optional[float]:
    """
    Approximate the moon phase as a fraction of the synodic month

    Open-Meteo carries no lunar data, so this is derived from the elapsed
    time since a known new moon. It is accurate to well within the width of
    the phase names it feeds.

    @param epoch: float|None Unix timestamp of the day in question
    @return float|None: Phase from 0.0 to 1.0, or None
    """

    # nothing to work from
    if epoch is None:
        return None

    # elapsed synodic months since the reference new moon, keeping the remainder
    elapsed = (float(epoch) - KNOWN_NEW_MOON) / 86400.0
    phase = (elapsed / SYNODIC_MONTH) % 1.0
    return phase + 1.0 if phase < 0 else phase


def _visibility(raw: Optional[float], units: str) -> Optional[float]:
    """
    Convert a visibility reading into the display unit

    @param raw: float|None Visibility as returned by the api
    @param units: str The configured unit system
    @return float|None: Miles or kilometres, or None
    """

    # nothing to convert
    if raw is None:
        return None

    # imperial requests come back in feet, everything else in metres
    if units in ("us", "uk"):
        return raw / 5280.0
    return raw / 1000.0


def reshape(payload: dict) -> Dict[str, Any]:
    """
    Convert an Open-Meteo response into the flat payload we normalize from

    Humidity, cloud cover, and precipitation probability all arrive as whole
    percentages and are folded down to fractions here, so the normalizer sees
    one consistent shape.

    @param payload: dict The raw api response
    @return dict: The reshaped payload
    """

    # the unit system rides along in the response so we can convert distances
    units = "us"
    hourly_units = payload.get("hourly_units") or {}
    if str(hourly_units.get("temperature_2m") or "").startswith("\u00b0C"):
        units = "si"

    # build the three blocks and stitch them together
    return {
        "timezone": payload.get("timezone"),
        "elevation": _num(payload.get("elevation")),
        "currently": _reshape_current(payload, units),
        "hourly": {"data": _reshape_hourly(payload, units)},
        "daily": {"data": _reshape_daily(payload)},
        "alerts": [],
    }


def _reshape_current(payload: dict, units: str) -> Dict[str, Any]:
    """
    Flatten the current conditions block

    @param payload: dict The raw api response
    @param units: str The detected unit system
    @return dict: Current conditions in the normalized shape
    """

    # the current block itself, plus the hourly series a few fields come from
    cur = payload.get("current") or {}
    hourly = payload.get("hourly") or {}

    # the api carries no current visibility or uv, so borrow the nearest hour
    index = _nearest_hour_index(hourly, _num(cur.get("time")))
    visibility = _visibility(_pick(hourly, "visibility", index), units) \
        if index is not None else None
    uv = _pick(hourly, "uv_index", index) if index is not None else None
    precip_prob = _pick(hourly, "precipitation_probability", index) \
        if index is not None else None

    # describe it
    is_day = bool(_num(cur.get("is_day")))
    summary, icon = describe(cur.get("weather_code"), is_day)

    # and lay it out the way the normalizer expects
    humidity = _num(cur.get("relative_humidity_2m"))
    cloud = _num(cur.get("cloud_cover"))
    return {
        "time": _num(cur.get("time")),
        "summary": summary,
        "icon": icon,
        "temperature": _num(cur.get("temperature_2m")),
        "apparentTemperature": _num(cur.get("apparent_temperature")),
        "dewPoint": _num(cur.get("dew_point_2m")),
        "humidity": None if humidity is None else humidity / 100.0,
        "pressure": _num(cur.get("pressure_msl")),
        "cloudCover": None if cloud is None else cloud / 100.0,
        "windSpeed": _num(cur.get("wind_speed_10m")),
        "windGust": _num(cur.get("wind_gusts_10m")),
        "windBearing": _num(cur.get("wind_direction_10m")),
        "uvIndex": uv,
        "visibility": visibility,
        "precipProbability": None if precip_prob is None else precip_prob / 100.0,
        "precipType": precip_type(cur.get("weather_code")),
    }


def _nearest_hour_index(hourly: dict, when: Optional[float]) -> Optional[int]:
    """
    Find the hourly slot closest to a given moment

    @param hourly: dict The hourly block from the response
    @param when: float|None The timestamp to match
    @return int|None: The index into the hourly arrays, or None
    """

    # we need both a series and something to match against
    times = hourly.get("time")
    if not isinstance(times, list) or not times:
        return None
    if when is None:
        return 0

    # walk it and keep the closest
    best_index = 0
    best_delta = None
    for index, value in enumerate(times):
        stamp = _num(value)
        if stamp is None:
            continue
        delta = abs(stamp - when)
        if best_delta is None or delta < best_delta:
            best_index, best_delta = index, delta
    return best_index


def _reshape_hourly(payload: dict, units: str) -> list:
    """
    Flatten the hourly series

    @param payload: dict The raw api response
    @param units: str The detected unit system
    @return list: Hourly entries in the normalized shape
    """

    # nothing to do without a time axis
    hourly = payload.get("hourly") or {}
    times = hourly.get("time")
    if not isinstance(times, list):
        return []

    # start at the current hour rather than the top of the day
    start = _nearest_hour_index(hourly, time.time()) or 0

    # walk what remains
    out: list = []
    for index in range(start, len(times)):
        stamp = _num(times[index])
        if stamp is None:
            continue

        # describe the hour
        is_day = bool(_pick(hourly, "is_day", index))
        summary, icon = describe(_code_at(hourly, index), is_day)

        # fold the percentages down and lay the row out
        humidity = _pick(hourly, "relative_humidity_2m", index)
        cloud = _pick(hourly, "cloud_cover", index)
        precip = _pick(hourly, "precipitation_probability", index)
        out.append({
            "time": stamp,
            "summary": summary,
            "icon": icon,
            "temperature": _pick(hourly, "temperature_2m", index),
            "apparentTemperature": _pick(hourly, "apparent_temperature", index),
            "dewPoint": _pick(hourly, "dew_point_2m", index),
            "humidity": None if humidity is None else humidity / 100.0,
            "pressure": _pick(hourly, "pressure_msl", index),
            "cloudCover": None if cloud is None else cloud / 100.0,
            "precipProbability": None if precip is None else precip / 100.0,
            "uvIndex": _pick(hourly, "uv_index", index),
            "visibility": _visibility(_pick(hourly, "visibility", index), units),
            "windSpeed": _pick(hourly, "wind_speed_10m", index),
            "windGust": _pick(hourly, "wind_gusts_10m", index),
            "windBearing": _pick(hourly, "wind_direction_10m", index),
        })
    return out


def _reshape_daily(payload: dict) -> list:
    """
    Flatten the daily series

    Open-Meteo has no daily humidity, dew point, pressure, cloud cover, or
    visibility, so those are averaged out of the hourly series for whichever
    days the hourly window actually covers.

    @param payload: dict The raw api response
    @return list: Daily entries in the normalized shape
    """

    # nothing to do without a time axis
    daily = payload.get("daily") or {}
    times = daily.get("time")
    if not isinstance(times, list):
        return []

    # roll the hourly series up per day so the derived fields have something
    derived = _daily_from_hourly(payload.get("hourly") or {})

    # walk each day
    out: list = []
    for index, raw_time in enumerate(times):
        stamp = _num(raw_time)
        if stamp is None:
            continue

        # describe it, days are always drawn with the daytime icon
        code = _code_at(daily, index)
        summary, icon = describe(code, True)

        # the api gives probability as a whole percentage
        precip = _pick(daily, "precipitation_probability_max", index)

        # merge the api values with whatever the hourly rollup produced
        extra = derived.get(day_key(stamp), {})
        out.append({
            "time": stamp,
            "summary": summary,
            "icon": icon,
            "temperatureHigh": _pick(daily, "temperature_2m_max", index),
            "temperatureLow": _pick(daily, "temperature_2m_min", index),
            "apparentTemperatureHigh": _pick(daily, "apparent_temperature_max", index),
            "apparentTemperatureLow": _pick(daily, "apparent_temperature_min", index),
            "precipProbability": None if precip is None else precip / 100.0,
            "precipType": precip_type(code),
            "precipAccumulation": _pick(daily, "precipitation_sum", index),
            "liquidAccumulation": _pick(daily, "rain_sum", index),
            "snowAccumulation": _pick(daily, "snowfall_sum", index),
            "windSpeed": _pick(daily, "wind_speed_10m_max", index),
            "windGust": _pick(daily, "wind_gusts_10m_max", index),
            "windBearing": _pick(daily, "wind_direction_10m_dominant", index),
            "uvIndex": _pick(daily, "uv_index_max", index),
            "sunriseTime": _pick(daily, "sunrise", index),
            "sunsetTime": _pick(daily, "sunset", index),
            "moonPhase": moon_phase(stamp),
            "humidity": extra.get("humidity"),
            "dewPoint": extra.get("dewPoint"),
            "pressure": extra.get("pressure"),
            "cloudCover": extra.get("cloudCover"),
            "visibility": extra.get("visibility"),
        })
    return out


def day_key(epoch: float) -> int:
    """
    Bucket a timestamp down to its day

    @param epoch: float A unix timestamp
    @return int: The day number since the epoch
    """

    # whole days is all we need to group by
    return int(epoch // 86400)


def _daily_from_hourly(hourly: dict) -> Dict[int, Dict[str, float]]:
    """
    Average the hourly series into per-day values

    @param hourly: dict The hourly block from the response
    @return dict: Day bucket mapped to its averaged fields
    """

    # nothing to roll up
    times = hourly.get("time")
    if not isinstance(times, list):
        return {}

    # the fields we can meaningfully average, and what they are called
    wanted = {
        "relative_humidity_2m": "humidity",
        "dew_point_2m": "dewPoint",
        "pressure_msl": "pressure",
        "cloud_cover": "cloudCover",
        "visibility": "visibility",
    }

    # accumulate running totals per day
    totals: Dict[int, Dict[str, list]] = {}
    for index, raw_time in enumerate(times):
        stamp = _num(raw_time)
        if stamp is None:
            continue
        bucket = totals.setdefault(day_key(stamp), {})
        for source, target in wanted.items():
            value = _pick(hourly, source, index)
            if value is not None:
                bucket.setdefault(target, []).append(value)

    # then average each one out, folding the percentages down as we go
    result: Dict[int, Dict[str, float]] = {}
    for day, fields in totals.items():
        averaged: Dict[str, float] = {}
        for name, values in fields.items():
            mean = sum(values) / len(values)
            if name in ("humidity", "cloudCover"):
                mean /= 100.0
            averaged[name] = mean
        result[day] = averaged
    return result


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

def geocode(name: str, user_agent: str = "kptv-weather/1.0") -> Optional[dict]:
    """
    Look a place name up and return its coordinates

    Used for locations outside the bundled US ZIP lookup.

    @param name: str The place name to search for
    @param user_agent: str Sent with the request
    @return dict|None: A dict of lat, lon, city, and state, or None
    """

    # nothing to search for
    query = (name or "").strip()
    if not query:
        return None

    # ask for the single best match
    try:
        resp = requests.get(
            GEOCODE_URL,
            params={"name": query, "count": 1, "format": "json"},
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("geocoding %r failed: %s", query, exc)
        return None

    # and pull the first result out of it
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        return None
    hit = results[0]
    return {
        "lat": _num(hit.get("latitude")),
        "lon": _num(hit.get("longitude")),
        "city": str(hit.get("name") or "").strip(),
        "state": str(hit.get("admin1") or hit.get("country") or "").strip(),
    }
