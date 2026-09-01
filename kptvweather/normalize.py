#!/usr/bin/env python3
"""
Normalizer Module

Turns a provider payload into the flat structures the render layers consume.
Layers stay presentation only: they receive already formatted strings plus a
handful of raw numbers for colour ramps and graph scaling.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from typing import Any, Optional, Sequence

from .utils import format_cardinal, to_local


@dataclass(frozen=True)
class Units:
    """
    Display suffixes for one unit system
    """

    key: str
    temp: str
    wind: str
    pressure: str
    distance: str
    accumulation: str
    metric_temp: bool


# what each unit system prints alongside its numbers
UNIT_TABLE = {
    "us": Units("us", "F", "mph", "mb", "mi", "in", False),
    "si": Units("si", "C", "m/s", "hPa", "km", "cm", True),
    "ca": Units("ca", "C", "km/h", "hPa", "km", "cm", True),
    "uk": Units("uk", "C", "mph", "hPa", "mi", "cm", True),
}

# icon names we actually ship artwork for
ICON_ASSETS = {
    "clear-day", "clear-night", "rain", "snow", "wind", "fog", "cloudy",
    "partly-cloudy-day", "partly-cloudy-night", "thunderstorm",
}

# anything else degrades onto one of the above
ICON_ALIASES = {
    "sleet": "snow",
    "hail": "snow",
    "drizzle": "rain",
    "showers": "rain",
    "thunderstorms": "thunderstorm",
    "smoke": "fog",
    "haze": "fog",
    "mist": "fog",
    "breezy": "wind",
    "windy": "wind",
    "": "cloudy",
    "none": "cloudy",
}

# the moon phase names, keyed by the top of each fraction band
MOON_PHASES = (
    (0.02, "New Moon"), (0.22, "Waxing Crescent"), (0.28, "First Quarter"),
    (0.47, "Waxing Gibbous"), (0.53, "Full Moon"), (0.72, "Waning Gibbous"),
    (0.78, "Last Quarter"), (0.97, "Waning Crescent"), (1.01, "New Moon"),
)


def units_for(key: Optional[str]) -> Units:
    """
    Look up a unit system

    @param key: str|None The configured system name
    @return Units: The matching descriptor, defaulting to imperial
    """

    # normalize and look it up
    return UNIT_TABLE.get((key or "us").strip().lower(), UNIT_TABLE["us"])


def to_fahrenheit(value: Optional[float], units: Units) -> Optional[float]:
    """
    Convert a payload temperature to Fahrenheit for colour mapping

    @param value: float|None The temperature as delivered
    @param units: Units The active unit system
    @return float|None: The temperature in Fahrenheit
    """

    # nothing to convert
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None

    # only the metric systems need converting
    return (float(value) * 9.0 / 5.0) + 32.0 if units.metric_temp else float(value)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _num(value: Any) -> Optional[float]:
    """
    Coerce a value to a float, treating anything unusable as missing

    @param value: mixed The raw value
    @return float|None: The number, or None
    """

    # booleans count as numbers in python, which is never what we want
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _deg(value: Any, units: Units, digits: int = 0) -> str:
    """
    Format a temperature as a bare degree value

    @param value: mixed The temperature
    @param units: Units The active unit system
    @param digits: int Decimal places to show
    @return str: The formatted degrees
    """

    # missing values get a placeholder rather than a gap
    number = _num(value)
    if number is None:
        return "--\u00b0"
    if digits <= 0:
        return f"{int(round(number))}\u00b0"
    return f"{number:.{digits}f}\u00b0"


def _deg_unit(value: Any, units: Units) -> str:
    """
    Format a temperature with its unit letter

    @param value: mixed The temperature
    @param units: Units The active unit system
    @return str: The formatted degrees with a unit
    """

    # same idea, with the suffix attached
    number = _num(value)
    if number is None:
        return f"--\u00b0{units.temp}"
    return f"{int(round(number))}\u00b0{units.temp}"


def _pct(value: Any) -> str:
    """
    Format a zero to one fraction as a whole percentage

    @param value: mixed The fraction
    @return str: The formatted percentage
    """

    # the payload carries fractions, the screen wants percentages
    number = _num(value)
    if number is None:
        return "--"
    return f"{int(round(number * 100))}%"


def _measure(value: Any, suffix: str, digits: int = 1) -> str:
    """
    Format a number with a trailing unit

    @param value: mixed The number
    @param suffix: str The unit to append
    @param digits: int Decimal places to show
    @return str: The formatted measurement
    """

    # missing values get a placeholder
    number = _num(value)
    if number is None:
        return "--"
    if digits <= 0:
        return f"{int(round(number))} {suffix}"
    return f"{number:.{digits}f} {suffix}"


def _local_dt(epoch: Any) -> Optional[datetime]:
    """
    Turn a unix timestamp into a local datetime

    @param epoch: mixed The timestamp
    @return datetime|None: The local moment, or None
    """

    # nothing to convert
    number = _num(epoch)
    if number is None:
        return None

    # guard against timestamps far outside anything representable
    try:
        return to_local(datetime.fromtimestamp(number, tz=dt_timezone.utc))
    except (OverflowError, OSError, ValueError):
        return None


def _clock(epoch: Any, fmt: str = "%I:%M %p") -> str:
    """
    Format a timestamp as a wall clock time

    @param epoch: mixed The timestamp
    @param fmt: str A strftime format
    @return str: The formatted time
    """

    # drop the leading zero so twelve hour times read naturally
    moment = _local_dt(epoch)
    if not moment:
        return "--"
    return moment.strftime(fmt).lstrip("0")


def _hour_label(epoch: Any) -> str:
    """
    Short hour label for the trend graph

    @param epoch: mixed The timestamp
    @return str: Something like 3P, or an empty string
    """

    # build it from the hour and the first letter of the meridiem
    moment = _local_dt(epoch)
    if not moment:
        return ""
    hour = moment.strftime("%I").lstrip("0") or "12"
    return f"{hour}{moment.strftime('%p')[0]}"


def _is_daytime(icon: Any, epoch: Any = None) -> bool:
    """
    Whether an observation is a daytime one

    @param icon: mixed The icon name, which may carry the suffix
    @param epoch: mixed A timestamp to fall back on
    @return bool: True when it is daytime
    """

    # the icon name usually says so outright
    name = str(icon or "")
    if name.endswith("-night"):
        return False
    if name.endswith("-day"):
        return True

    # otherwise guess from the hour
    moment = _local_dt(epoch) if epoch is not None else None
    if moment:
        return 6 <= moment.hour < 19
    return True


def icon_key(raw: Any, is_day: bool = True) -> str:
    """
    Map an icon name onto a bundled asset

    @param raw: mixed The icon name from the provider
    @param is_day: bool Whether this is a daytime observation
    @return str: An asset name we actually ship
    """

    # an exact hit is the common case
    name = str(raw or "").strip().lower()
    if name in ICON_ASSETS:
        return name

    # then the alias table
    alias = ICON_ALIASES.get(name)
    if alias in ICON_ASSETS:
        return alias

    # then degrade on a keyword
    for token, target in (
        ("thunder", "thunderstorm"), ("snow", "snow"), ("sleet", "snow"),
        ("rain", "rain"), ("drizzle", "rain"), ("fog", "fog"),
        ("wind", "wind"), ("cloud", "cloudy"),
    ):
        if token in name:
            return target

    # and finally on the time of day
    return "clear-day" if is_day else "clear-night"


def summary_text(raw: Any, fallback: str = "Current conditions") -> str:
    """
    Tidy a condition phrase for display

    @param raw: mixed The phrase from the provider
    @param fallback: str Used when there is nothing to show
    @return str: The display phrase
    """

    # fall back when it is empty
    text = str(raw or "").strip()
    if not text:
        return fallback

    # some payloads hand back a slug rather than a phrase
    if "-" in text and " " not in text:
        return text.replace("-", " ").title()
    return text


def moon_phase_name(value: Any) -> str:
    """
    Name a moon phase from its fraction

    @param value: mixed The phase from 0.0 to 1.0
    @return str: The phase name
    """

    # nothing to name
    number = _num(value)
    if number is None:
        return "--"

    # walk the bands
    for threshold, name in MOON_PHASES:
        if number <= threshold:
            return name
    return "New Moon"


# ---------------------------------------------------------------------------
# Current conditions
# ---------------------------------------------------------------------------

def build_current(payload: dict, units: Units, location_name: str) -> dict:
    """
    Flatten current conditions, enriched with today's daily figures

    @param payload: dict The provider payload
    @param units: Units The active unit system
    @param location_name: str What to print as the location
    @return dict: The current conditions block
    """

    # the two blocks we draw from
    cur = payload.get("currently") or {}
    days = (payload.get("daily") or {}).get("data") or []
    today = days[0] if days else {}

    # the headline numbers
    temp = _num(cur.get("temperature"))
    feels = _num(cur.get("apparentTemperature"))
    is_day = _is_daytime(cur.get("icon"), cur.get("time"))

    # wind reads better as one composed phrase than three separate tiles
    wind_speed = _num(cur.get("windSpeed"))
    gust = _num(cur.get("windGust"))
    if wind_speed is None or wind_speed < 0.5:
        wind_display = "Calm"
    else:
        cardinal = format_cardinal(_num(cur.get("windBearing")))
        wind_display = f"{cardinal} {wind_speed:.0f} {units.wind}"
        if gust and gust > wind_speed * 1.3:
            wind_display += f" G{gust:.0f}"

    # lay it out
    uv = _num(cur.get("uvIndex"))
    return {
        "location": location_name,
        "summary": summary_text(cur.get("summary")),
        "icon": icon_key(cur.get("icon"), is_day),
        "is_day": is_day,
        "temp": temp,
        "temp_f": to_fahrenheit(temp, units),
        "feels_like": feels,
        "temp_display": _deg(temp, units),
        "temp_unit": units.temp,
        "feels_display": _deg_unit(feels, units),
        "dew_display": _deg_unit(cur.get("dewPoint"), units),
        "humidity_display": _pct(cur.get("humidity")),
        "wind_display": wind_display,
        "gust_display": _measure(gust, units.wind, 0),
        "pressure_display": _measure(cur.get("pressure"), units.pressure, 0),
        "visibility_display": _measure(cur.get("visibility"), units.distance, 1),
        "uv_display": "--" if uv is None else f"{uv:.0f}",
        "cloud_display": _pct(cur.get("cloudCover")),
        "precip_prob_display": _pct(cur.get("precipProbability")),
        "precip_type": str(cur.get("precipType") or "none").title(),
        "high_display": _deg(today.get("temperatureHigh"), units),
        "low_display": _deg(today.get("temperatureLow"), units),
        "high_f": to_fahrenheit(_num(today.get("temperatureHigh")), units),
        "low_f": to_fahrenheit(_num(today.get("temperatureLow")), units),
        "sunrise": _clock(today.get("sunriseTime")),
        "sunset": _clock(today.get("sunsetTime")),
        "observed_time": _clock(cur.get("time")),
    }


# ---------------------------------------------------------------------------
# Hourly
# ---------------------------------------------------------------------------

def build_hourly_points(payload: dict, units: Units, limit: int = 12) -> list:
    """
    Build the hourly series the trend graph plots

    @param payload: dict The provider payload
    @param units: Units The active unit system
    @param limit: int How many hours to include
    @return list: One dict per hour
    """

    # take the leading window of the series
    rows = (payload.get("hourly") or {}).get("data") or []
    points: list[dict] = []
    for entry in rows[: max(1, int(limit))]:

        # the three series the graph draws, plus a label and an icon
        temp = _num(entry.get("temperature"))
        precip = _num(entry.get("precipProbability"))
        cloud = _num(entry.get("cloudCover"))
        points.append({
            "epoch": _num(entry.get("time")),
            "label": _hour_label(entry.get("time")),
            "temp": temp,
            "temp_f": to_fahrenheit(temp, units),
            "precip": None if precip is None else precip * 100.0,
            "cloud": None if cloud is None else cloud * 100.0,
            "icon": icon_key(entry.get("icon"),
                             _is_daytime(entry.get("icon"), entry.get("time"))),
        })
    return points


# ---------------------------------------------------------------------------
# Daily
# ---------------------------------------------------------------------------

def build_daily_days(payload: dict, units: Units, limit: int = 7) -> list:
    """
    Build the seven day strip

    @param payload: dict The provider payload
    @param units: Units The active unit system
    @param limit: int How many days to include
    @return list: One dict per day, today first
    """

    # walk the daily series
    rows = (payload.get("daily") or {}).get("data") or []
    out: list[dict] = []
    for index, entry in enumerate(rows[: max(1, int(limit))]):

        # today is labelled as such, everything else takes its weekday
        moment = _local_dt(entry.get("time"))
        if index == 0:
            name = "TODAY"
        elif moment:
            name = moment.strftime("%a").upper()
        else:
            name = f"DAY {index + 1}"

        # the numbers the card draws
        high = _num(entry.get("temperatureHigh"))
        low = _num(entry.get("temperatureLow"))
        precip = _num(entry.get("precipProbability"))
        wind = _num(entry.get("windSpeed"))
        gust = _num(entry.get("windGust"))
        uv = _num(entry.get("uvIndex"))

        # a day with no precipitation still needs a label for its tile
        precip_type = str(entry.get("precipType") or "").strip().lower()
        if precip_type in ("", "none"):
            precip_type = "precip"

        out.append({
            "name": name,
            "date": moment.strftime("%b %d").replace(" 0", " ") if moment else "",
            "high": high,
            "low": low,
            "high_f": to_fahrenheit(high, units),
            "low_f": to_fahrenheit(low, units),
            "unit": units.temp,
            "short": summary_text(entry.get("summary"), ""),
            "icon": icon_key(entry.get("icon"), True),
            "precip": None if precip is None else precip * 100.0,
            "is_day": True,
            "precip_type": precip_type,
            "precip_display": _pct(entry.get("precipProbability")),
            "humidity_display": _pct(entry.get("humidity")),
            "wind_display": (
                "Calm" if wind is None or wind < 0.5
                else f"{format_cardinal(_num(entry.get('windBearing')))} {wind:.0f}"
            ),
            "wind_unit": units.wind,
            "gust_display": "--" if gust is None else f"{gust:.0f}",
            "cloud_display": _pct(entry.get("cloudCover")),
            "uv_display": "--" if uv is None else f"{uv:.0f}",
            "dew_display": _deg_unit(entry.get("dewPoint"), units),
            "pressure_display": _measure(entry.get("pressure"), units.pressure, 0),
            "visibility_display": _measure(entry.get("visibility"),
                                           units.distance, 1),
            "feels_high_display": _deg(entry.get("apparentTemperatureHigh"), units),
            "feels_low_display": _deg(entry.get("apparentTemperatureLow"), units),
            "accumulation_display": _accumulation(entry, units),
            "sunrise": _clock(entry.get("sunriseTime")),
            "sunset": _clock(entry.get("sunsetTime")),
            "moon_phase": moon_phase_name(entry.get("moonPhase")),
        })
    return out


def _accumulation(day: dict, units: Units) -> str:
    """
    The most notable accumulation figure for a day

    @param day: dict One daily entry
    @param units: Units The active unit system
    @return str: The formatted accumulation
    """

    # snow beats ice beats liquid, since it is the one people care about
    for key in ("snowAccumulation", "iceAccumulation", "liquidAccumulation",
                "precipAccumulation"):
        value = _num(day.get(key))
        if value is not None and value > 0.005:
            return _measure(value, units.accumulation, 2)
    return "--"


def build_forecast_periods(payload: dict, units: Units, limit: int = 2) -> list:
    """
    Build the narrative panels for the extended forecast page

    @param payload: dict The provider payload
    @param units: Units The active unit system
    @param limit: int How many periods to include
    @return list: One dict per period
    """

    # walk the leading days
    rows = (payload.get("daily") or {}).get("data") or []
    out: list[dict] = []
    for index, entry in enumerate(rows[: max(1, int(limit))]):

        # name them relative to today where that reads better
        moment = _local_dt(entry.get("time"))
        if index == 0:
            name = "Today"
        elif index == 1:
            name = "Tomorrow"
        else:
            name = moment.strftime("%A") if moment else f"Day {index + 1}"

        # the stat grid values
        wind = _num(entry.get("windSpeed"))
        gust = _num(entry.get("windGust"))
        precip = _num(entry.get("precipProbability"))
        uv = _num(entry.get("uvIndex"))

        out.append({
            "name": name,
            "high": _deg(entry.get("temperatureHigh"), units),
            "low": _deg(entry.get("temperatureLow"), units),
            "high_f": to_fahrenheit(_num(entry.get("temperatureHigh")), units),
            "unit": units.temp,
            "wind": "--" if wind is None else f"{wind:.0f} {units.wind}",
            "wind_dir": format_cardinal(_num(entry.get("windBearing"))),
            "gust": "--" if gust is None else f"{gust:.0f} {units.wind}",
            "precip": None if precip is None else precip * 100.0,
            "precip_type": str(entry.get("precipType") or "none").title(),
            "accumulation": _accumulation(entry, units),
            "humidity": _pct(entry.get("humidity")),
            "dew": _deg_unit(entry.get("dewPoint"), units),
            "cloud": _pct(entry.get("cloudCover")),
            "pressure": _measure(entry.get("pressure"), units.pressure, 0),
            "visibility": _measure(entry.get("visibility"), units.distance, 1),
            "feels_high": _deg(entry.get("apparentTemperatureHigh"), units),
            "feels_low": _deg(entry.get("apparentTemperatureLow"), units),
            "uv": "--" if uv is None else f"{uv:.0f}",
            "moon_phase": moon_phase_name(entry.get("moonPhase")),
            "sunrise": _clock(entry.get("sunriseTime")),
            "sunset": _clock(entry.get("sunsetTime")),
            "short": summary_text(entry.get("summary"), ""),
            "detailed": _narrative(entry, units),
            "icon": icon_key(entry.get("icon"), True),
            "is_day": True,
        })
    return out


def _narrative(day: dict, units: Units) -> str:
    """
    Compose a readable paragraph out of a day's numbers

    The provider gives a short phrase rather than prose, so the longer text
    is built here from the figures that came with it.

    @param day: dict One daily entry
    @param units: Units The active unit system
    @return str: The composed paragraph
    """

    # lead with the condition phrase
    parts: list[str] = []
    summary = summary_text(day.get("summary"), "")
    if summary:
        parts.append(summary.rstrip(".") + ".")

    # temperatures
    high = _num(day.get("temperatureHigh"))
    low = _num(day.get("temperatureLow"))
    if high is not None and low is not None:
        parts.append(
            f"Highs near {int(round(high))}\u00b0{units.temp} with overnight "
            f"lows around {int(round(low))}\u00b0{units.temp}."
        )
    elif high is not None:
        parts.append(f"Highs near {int(round(high))}\u00b0{units.temp}.")

    # precipitation, with an accumulation when there is one worth stating
    precip = _num(day.get("precipProbability"))
    if precip is not None and precip > 0.05:
        kind = str(day.get("precipType") or "precipitation").lower()
        if kind in ("none", ""):
            kind = "precipitation"
        accum = _num(day.get("precipAccumulation"))
        sentence = f"About a {int(round(precip * 100))}% chance of {kind}"
        if accum and accum > 0.01:
            sentence += f", with up to {accum:.2f} {units.accumulation} possible"
        parts.append(sentence + ".")
    elif precip is not None:
        parts.append("Little to no precipitation expected.")

    # wind
    wind = _num(day.get("windSpeed"))
    gust = _num(day.get("windGust"))
    if wind is not None:
        cardinal = format_cardinal(_num(day.get("windBearing")))
        sentence = f"Winds {cardinal} near {int(round(wind))} {units.wind}"
        if gust and gust > wind * 1.3:
            sentence += f", gusting to {int(round(gust))} {units.wind}"
        parts.append(sentence + ".")

    # humidity and dew point
    humidity = _num(day.get("humidity"))
    dew = _num(day.get("dewPoint"))
    if humidity is not None:
        sentence = f"Humidity around {int(round(humidity * 100))}%"
        if dew is not None:
            sentence += f" with a dew point near {int(round(dew))}\u00b0{units.temp}"
        parts.append(sentence + ".")

    # sky cover, described rather than just quoted
    cloud = _num(day.get("cloudCover"))
    if cloud is not None:
        percent = int(round(cloud * 100))
        if percent <= 20:
            descriptor = "mostly clear skies"
        elif percent <= 50:
            descriptor = "partly cloudy skies"
        elif percent <= 80:
            descriptor = "mostly cloudy skies"
        else:
            descriptor = "overcast skies"
        parts.append(f"Expect {descriptor} at about {percent}% cloud cover.")

    # and a UV warning when it is worth one
    uv = _num(day.get("uvIndex"))
    if uv is not None and uv >= 6:
        descriptor = "very high" if uv >= 8 else "high"
        parts.append(
            f"UV index peaking at {int(round(uv))} ({descriptor}); "
            f"sun protection advised."
        )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Almanac
# ---------------------------------------------------------------------------

def build_almanac(payload: dict, units: Units) -> list:
    """
    Build the rows for the almanac page

    @param payload: dict The provider payload
    @param units: Units The active unit system
    @return list: One dict per row
    """

    # the blocks the rows come from
    cur = payload.get("currently") or {}
    days = (payload.get("daily") or {}).get("data") or []
    today = days[0] if days else {}

    # the fixed rows
    uv = _num(cur.get("uvIndex"))
    rows: list[tuple[str, str]] = [
        ("Sunrise", _clock(today.get("sunriseTime"))),
        ("Sunset", _clock(today.get("sunsetTime"))),
        ("Moon Phase", moon_phase_name(today.get("moonPhase"))),
        ("Feels Like", _deg_unit(cur.get("apparentTemperature"), units)),
        ("Dew Point", _deg_unit(cur.get("dewPoint"), units)),
        ("Humidity", _pct(cur.get("humidity"))),
        ("Pressure", _measure(cur.get("pressure"), units.pressure, 0)),
        ("Visibility", _measure(cur.get("visibility"), units.distance, 1)),
        ("Cloud Cover", _pct(cur.get("cloudCover"))),
        ("UV Index", "--" if uv is None else f"{uv:.0f}"),
    ]

    # accumulations, only where there is actually something to report
    for label, key in (("Rain Today", "liquidAccumulation"),
                       ("Snow Today", "snowAccumulation"),
                       ("Ice Today", "iceAccumulation")):
        value = _num(today.get(key))
        if value is not None and value > 0.005:
            rows.append((label, _measure(value, units.accumulation, 2)))

    # elevation, converted to whichever unit suits the system
    elevation = _num(payload.get("elevation"))
    if elevation is not None:
        if units.metric_temp:
            rows.append(("Elevation", f"{int(round(elevation))} m"))
        else:
            rows.append(("Elevation", f"{int(round(elevation * 3.28084))} ft"))

    # the moon row carries its raw fraction too, so the icon can be drawn
    result = [{"name": name, "value": value} for name, value in rows]
    fraction = _num(today.get("moonPhase"))
    if fraction is not None:
        for row in result:
            if row["name"] == "Moon Phase":
                row["moon_phase"] = fraction
                break
    return result


# ---------------------------------------------------------------------------
# Alerts and the ticker
# ---------------------------------------------------------------------------

def build_alerts(alerts: Sequence[dict]) -> list:
    """
    Tidy the alert list for display

    @param alerts: Sequence Alerts as the provider returned them
    @return list: Normalized alert dicts
    """

    # keep only the ones with something to say
    out: list[dict] = []
    for item in alerts or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "headline": str(item.get("headline") or "").strip(),
            "severity": str(item.get("severity") or "Unknown").title(),
            "regions": str(item.get("regions") or "").strip(),
            "expires": _clock(item.get("expires")),
            "description": str(item.get("description") or "").strip(),
        })
    return out


def alerts_ticker_text(alerts: Sequence[dict], limit: int = 6) -> str:
    """
    Condense the active alerts into one ticker string

    @param alerts: Sequence The normalized alerts
    @param limit: int How many to include before truncating
    @return str: The ticker text
    """

    # nothing active is itself worth saying
    if not alerts:
        return "No active weather alerts"

    # lead each one with its severity where the api gave us a useful one
    chunks: list[str] = []
    for alert in list(alerts)[: max(1, int(limit))]:
        headline = str(alert.get("title") or "").strip()
        regions = str(alert.get("regions") or "").strip()
        severity = str(alert.get("severity") or "").strip()
        text = headline
        if regions:
            text = f"{headline} for {regions}"
        if severity and severity.lower() not in ("unknown", ""):
            text = f"{severity.upper()}: {text}"
        chunks.append(text)
    return "  \u2022  ".join(chunks)


# ---------------------------------------------------------------------------
# Map points
# ---------------------------------------------------------------------------

def build_city_point(name: str, lat: float, lon: float, payload: dict,
                     units: Units) -> Optional[dict]:
    """
    Build one marker for the regional conditions map

    @param name: str The city name
    @param lat: float Its latitude
    @param lon: float Its longitude
    @param payload: dict That city's provider payload
    @param units: Units The active unit system
    @return dict|None: The marker, or None when there is no reading
    """

    # no temperature means no marker worth drawing
    cur = (payload or {}).get("currently") or {}
    temp = _num(cur.get("temperature"))
    if temp is None:
        return None

    # lay it out
    is_day = _is_daytime(cur.get("icon"), cur.get("time"))
    return {
        "name": name,
        "lat": float(lat),
        "lon": float(lon),
        "temp": _deg(temp, units),
        "temp_f": to_fahrenheit(temp, units),
        "condition": summary_text(cur.get("summary"), ""),
        "icon": icon_key(cur.get("icon"), is_day),
        "is_day": is_day,
    }


def build_city_forecast_point(name: str, lat: float, lon: float, payload: dict,
                              units: Units) -> Optional[dict]:
    """
    Build one marker for the forecast highs map

    @param name: str The city name
    @param lat: float Its latitude
    @param lon: float Its longitude
    @param payload: dict That city's provider payload
    @param units: Units The active unit system
    @return dict|None: The marker, or None when there is no forecast
    """

    # no daily data means nothing to plot
    days = ((payload or {}).get("daily") or {}).get("data") or []
    if not days:
        return None
    day = days[0]
    high = _num(day.get("temperatureHigh"))
    if high is None:
        return None

    # lay it out
    return {
        "name": name,
        "lat": float(lat),
        "lon": float(lon),
        "forecast_temp": _deg(high, units),
        "temp_f": to_fahrenheit(high, units),
        "forecast_short": summary_text(day.get("summary"), ""),
        "icon": icon_key(day.get("icon"), True),
        "is_day": True,
    }
