#!/usr/bin/env python3
"""
Configuration Module

Environment-driven configuration for the renderer process. Every setting
arrives through the container environment, so there are no command line
flags and no config file to mount.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# the design surface everything is scaled from
BASE_WIDTH = 1920
BASE_HEIGHT = 1080

# every environment variable we read carries this prefix
ENV_PREFIX = "KPTVW_"

# unit systems we accept, matching the on-screen formatting in normalize
VALID_UNITS = ("us", "ca", "si", "uk")

# where radar imagery may come from
VALID_RADAR = ("noaa", "rainviewer", "auto", "off")


@dataclass
class Config:
    """
    Fully resolved runtime configuration

    Populated once at startup by from_env() and treated as read-only
    afterwards, apart from the location fields which get filled in when a
    ZIP code has to be resolved to coordinates.
    """

    # location
    zip: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    location_name: str
    timezone: Optional[str]

    # output surface
    width: int
    height: int
    output_fps: int
    video_kbps: int
    audio_kbps: int

    # encoder
    ffmpeg_path: str
    video_encoder: str
    encoder_preset: str

    # http service
    http_host: str
    http_port: int
    stream_path: str
    playlist_path: str
    base_url: str
    channel_name: str
    channel_logo: str
    max_clients: int

    # data refresh
    units: str
    data_interval_sec: int
    regional_interval_sec: int
    regional_cities: int
    radar_source: str

    # ui
    ticker_speed_px_per_sec: int
    page_duration_sec: int
    music_dir: Optional[str]
    music_volume: float
    user_agent: str

    # news ticker
    rss_urls: list = field(default_factory=list)
    rss_refresh_sec: int = 300
    rss_max_items: int = 3


def _env(name: str, default: str = "") -> str:
    """
    Read a prefixed environment variable as a trimmed string

    @param name: str Variable name without the KPTVW_ prefix
    @param default: str Value to fall back on when unset or empty
    @return str: The trimmed value, or the default
    """

    # pull it and trim it
    raw = (os.environ.get(ENV_PREFIX + name) or "").strip()

    # hand back whichever we actually have
    return raw or default


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """
    Read a prefixed environment variable as a clamped integer

    @param name: str Variable name without the KPTVW_ prefix
    @param default: int Value to fall back on when unset or unparseable
    @param minimum: int Lower bound applied to the result
    @param maximum: int Upper bound applied to the result
    @return int: The parsed and clamped value
    """

    # grab the raw string first
    raw = _env(name)

    # nothing set, so take the default as-is
    if not raw:
        return default

    # parse it, falling back when it is garbage
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return default

    # keep it inside the sane range
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float,
               maximum: float) -> float:
    """
    Read a prefixed environment variable as a clamped float

    @param name: str Variable name without the KPTVW_ prefix
    @param default: float Value to fall back on when unset or unparseable
    @param minimum: float Lower bound applied to the result
    @param maximum: float Upper bound applied to the result
    @return float: The parsed and clamped value
    """

    # grab the raw string first
    raw = _env(name)

    # nothing set, so take the default as-is
    if not raw:
        return default

    # parse it, falling back when it is garbage
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default

    # keep it inside the sane range
    return max(minimum, min(maximum, value))


def _env_choice(name: str, default: str, allowed: tuple) -> str:
    """
    Read a prefixed environment variable constrained to a fixed set

    @param name: str Variable name without the KPTVW_ prefix
    @param default: str Value to fall back on when unset or not allowed
    @param allowed: tuple Permitted lowercase values
    @return str: One of the allowed values
    """

    # normalize it down so casing in compose files does not matter
    raw = _env(name).lower()

    # only accept something we actually know about
    return raw if raw in allowed else default


def _parse_resolution(raw: str) -> tuple:
    """
    Split a WIDTHxHEIGHT string into its two dimensions

    @param raw: str Resolution string such as 1920x1080
    @return tuple: Width and height, falling back to the base surface
    """

    # split on the x and make sure we got two halves
    parts = raw.lower().split("x", 1)
    if len(parts) != 2:
        return BASE_WIDTH, BASE_HEIGHT

    # parse both sides, bailing out on anything non-numeric
    try:
        width, height = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return BASE_WIDTH, BASE_HEIGHT

    # negative or zero dimensions are meaningless
    if width <= 0 or height <= 0:
        return BASE_WIDTH, BASE_HEIGHT

    # h.264 wants even dimensions, so round them down to a multiple of two
    return width - (width % 2), height - (height % 2)


def _parse_rss(raw: str) -> list:
    """
    Split and validate the configured news ticker feed list

    Accepts commas, semicolons, and newlines as separators so the value can
    be written however is convenient in a compose file.

    @param raw: str The raw environment value
    @return list: Up to ten sanitized http(s) feed URLs
    """

    # nothing configured, nothing to do
    if not raw:
        return []

    # flatten every separator we accept down to a comma
    normalized = raw.replace("\r", "\n").replace(";", ",").replace("\n", ",")

    # walk each candidate and keep only the sane ones
    urls: list = []
    for item in normalized.split(","):

        # trim it and skip the empties and the absurdly long
        candidate = item.strip()
        if not candidate or len(candidate) > 500:
            continue

        # we only ever fetch over http(s)
        if urlparse(candidate).scheme not in {"http", "https"}:
            continue

        # keep it, and stop once we have plenty
        urls.append(candidate)
        if len(urls) >= 10:
            break

    return urls


def _normalize_path(raw: str, default: str) -> str:
    """
    Normalize a configured URL path so it always has a single leading slash

    @param raw: str The configured path
    @param default: str Path to use when nothing usable was configured
    @return str: A path beginning with exactly one slash
    """

    # trim it and fall back when it is empty
    candidate = (raw or "").strip()
    if not candidate:
        candidate = default

    # make sure it leads with a slash
    return "/" + candidate.lstrip("/")


def _music_dir() -> Optional[str]:
    """
    Resolve the background music directory

    The directory is expected to be bind mounted; when it is missing we
    return None and the stream carries a silent audio track instead.

    @return str|None: An existing directory path, or None
    """

    # default to the documented mount point
    configured = _env("MUSIC_DIR", "/music")

    # only hand it back when it is really there
    directory = Path(configured).expanduser()
    return str(directory) if directory.is_dir() else None


def from_env() -> Config:
    """
    Build the runtime configuration from the container environment

    @return Config: Fully populated configuration object
    """

    # output surface first, since a few other values scale off it
    width, height = _parse_resolution(_env("RESOLUTION", "1920x1080"))

    # location, either an explicit coordinate pair or a ZIP to resolve later
    raw_lat = _env("LAT")
    raw_lon = _env("LON")
    lat = _env_float("LAT", 0.0, -90.0, 90.0) if raw_lat else None
    lon = _env_float("LON", 0.0, -180.0, 180.0) if raw_lon else None

    # build it out
    return Config(
        zip=_env("ZIP") or None,
        lat=lat,
        lon=lon,
        location_name=_env("LOCATION_NAME"),
        timezone=_env("TZ") or None,
        width=width,
        height=height,
        output_fps=_env_int("FPS", 30, 1, 60),
        video_kbps=_env_int("VIDEO_KBPS", 3500, 500, 20000),
        audio_kbps=_env_int("AUDIO_KBPS", 128, 32, 512),
        ffmpeg_path=_env("FFMPEG_PATH", "/usr/local/bin/ffmpeg"),
        video_encoder=_env("ENCODER", "auto").lower(),
        encoder_preset=_env("ENCODER_PRESET", "veryfast").lower(),
        http_host=_env("HTTP_HOST", "0.0.0.0"),
        http_port=_env_int("HTTP_PORT", 8000, 1, 65535),
        stream_path=_normalize_path(_env("STREAM_PATH"), "/stream.ts"),
        playlist_path=_normalize_path(_env("PLAYLIST_PATH"), "/playlist.m3u8"),
        base_url=_env("BASE_URL").rstrip("/"),
        channel_name=_env("CHANNEL_NAME", "Weather"),
        channel_logo=_env("CHANNEL_LOGO"),
        max_clients=_env_int("MAX_CLIENTS", 2, 1, 1000),
        units=_env_choice("UNITS", "us", VALID_UNITS),
        data_interval_sec=_env_int("DATA_INTERVAL_SEC", 600, 120, 3600),
        regional_interval_sec=_env_int("REGIONAL_INTERVAL_SEC", 5400, 600, 86400),
        regional_cities=_env_int("REGIONAL_CITIES", 6, 0, 12),
        radar_source=_env_choice("RADAR_SOURCE", "noaa", VALID_RADAR),
        ticker_speed_px_per_sec=_env_int("TICKER_SPEED", 120, 10, 600),
        page_duration_sec=_env_int("PAGE_SECONDS", 14, 4, 120),
        music_dir=_music_dir(),
        music_volume=_env_float("MUSIC_VOLUME", 50.0, 0.0, 100.0) / 100.0,
        user_agent=_env("USER_AGENT", "kptv-weather/1.0"),
        rss_urls=_parse_rss(_env("RSS_URLS")),
        rss_refresh_sec=_env_int("RSS_REFRESH_SEC", 300, 60, 3600),
        rss_max_items=_env_int("RSS_MAX_ITEMS", 3, 1, 50),
    )
