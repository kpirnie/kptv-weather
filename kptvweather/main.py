#!/usr/bin/env python3
"""
Renderer Entry Point

Resolves the location, starts the encoder and the http service, builds the
pages, and runs the render loop for as long as the container lives.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import logging
import math
import os
import random
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from PIL import Image

from . import draw, icons, layout, map_tiles, normalize, radar_sources, theme
from .config import BASE_HEIGHT, BASE_WIDTH, Config, from_env
from .core.compositor import Compositor
from .core.datastore import DataStore
from .core.layer import Layer
from .core.scheduler import Scheduler
from .data.cities import nearby_cities, nearest_city
from .data.zipcodes import resolve_zip
from .layers import (AlmanacLayer, ChromeLayer, ClockLayer, CurrentLayer,
                     DailyLayer, ForecastMapLayer, ForecastTextLayer,
                     HeaderCurrentLayer, HourlyGraphLayer, RadarLayer,
                     RegionalLayer, TickerLayer)
from .output.fanout import TSBroker
from .output.http_server import StreamServer
from .output.stream_ffmpeg import FFMPEGStreamer
from .pages import PageCycler
from .providers.nws import NWSAlertClient
from .providers.openmeteo import OpenMeteoClient, WeatherError, geocode
from .rss import RssTitleCache
from .utils import compute_bounds, set_timezone

logger = logging.getLogger(__name__)

# audio the music bed will actually accept
MUSIC_SUFFIXES = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".oga"}


def setup_logging() -> None:
    """
    Configure logging from the DEBUG environment variable

    @return None
    """

    # verbose format when debugging, clean one otherwise
    debug = (os.environ.get("DEBUG") or "").strip().lower() in ("1", "true", "yes")
    if debug:
        fmt = "%(asctime)s %(levelname)-7s %(name)s %(funcName)s:%(lineno)d - %(message)s"
        level = logging.DEBUG
    else:
        fmt = "%(asctime)s %(levelname)-7s %(message)s"
        level = logging.INFO
    logging.basicConfig(level=level, format=fmt, stream=sys.stdout, force=True)

    # the http libraries are far too chatty at info
    if not debug:
        for name in ("urllib3", "requests", "PIL"):
            logging.getLogger(name).setLevel(logging.WARNING)


def resolve_location(cfg: Config) -> bool:
    """
    Fill in the coordinates and the display name

    @param cfg: Config The runtime configuration, updated in place
    @return bool: True when a usable location was resolved
    """

    # a ZIP resolves to both coordinates and a name
    if (cfg.lat is None or cfg.lon is None) and cfg.zip:
        found = resolve_zip(cfg.zip, cfg.user_agent)
        if found:
            cfg.lat = cfg.lat if cfg.lat is not None else found.get("lat")
            cfg.lon = cfg.lon if cfg.lon is not None else found.get("lon")
            if not cfg.location_name:
                city = (found.get("city") or "").strip()
                state = (found.get("state") or "").strip()
                cfg.location_name = f"{city}, {state}".strip(", ")

    # a place name is the other way in for anywhere outside the US
    if (cfg.lat is None or cfg.lon is None) and cfg.location_name:
        found = geocode(cfg.location_name, cfg.user_agent)
        if found:
            cfg.lat = found.get("lat")
            cfg.lon = found.get("lon")

    # without coordinates there is nothing to render
    if cfg.lat is None or cfg.lon is None:
        return False

    # and put a name on it when one was not configured
    if not cfg.location_name:
        cfg.location_name = nearest_city(cfg.lat, cfg.lon) or "Local Weather"
    return True


def build_music_playlist(cfg: Config) -> Optional[str]:
    """
    Write an ffmpeg concat playlist for the background music bed

    Returns None when music is off or the mounted directory holds no audio,
    in which case the stream carries a silent track instead.

    @param cfg: Config The runtime configuration
    @return str|None: Path to the playlist, or None
    """

    # turned off outright
    if cfg.music_volume <= 0.0:
        logger.info("music disabled (volume is zero)")
        return None

    # nothing mounted
    if not cfg.music_dir:
        logger.info("no music directory mounted, the channel will be silent")
        return None

    # collect whatever audio is in there
    directory = Path(cfg.music_dir)
    tracks = [
        path for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix.lower() in MUSIC_SUFFIXES
    ]
    if not tracks:
        logger.info("no audio files in %s, the channel will be silent", directory)
        return None

    # shuffle so a looping channel does not always open the same way
    random.shuffle(tracks)

    # write the playlist somewhere writable
    playlist = Path(tempfile.gettempdir()) / f"kptvw_music_{os.getpid()}.txt"
    try:
        with playlist.open("w", encoding="utf-8") as handle:
            for track in tracks:
                escaped = track.as_posix().replace("'", "'\\''")
                handle.write("file '%s'\n" % escaped)
    except OSError as exc:
        logger.warning("could not write the music playlist: %s", exc)
        return None

    logger.info("music: %s track(s) from %s at %d%%", len(tracks), directory,
                int(cfg.music_volume * 100))
    return str(playlist)


def make_datastore(cfg: Config, client: OpenMeteoClient, alerts: NWSAlertClient,
                   units, render_w: int, render_h: int,
                   scale: float) -> DataStore:
    """
    Build the background refresher every layer reads from

    @param cfg: Config The runtime configuration
    @param client: OpenMeteoClient The forecast provider
    @param alerts: NWSAlertClient The alert provider
    @param units: Units The active unit system
    @param render_w: int The output width
    @param render_h: int The output height
    @param scale: float The output scale factor
    @return DataStore: The started refresher
    """

    # the home location, plus the ticker's news feeds
    lat, lon = client.lat, client.lon
    feeds = RssTitleCache(cfg.rss_urls, cfg.rss_refresh_sec, cfg.rss_max_items,
                          cfg.user_agent)

    # slow moving state that must not be refetched on every pass
    regional_state = {"at": 0.0, "current": [], "forecast": []}
    radar_state = {"at": 0.0, "frames": [], "served": 0, "source": None,
                   "base": None, "base_key": None, "base_bounds": None}

    def compose_map(points: list):
        """
        Build a base map covering a set of markers

        @param points: list The markers to enclose
        @return tuple: The map image and the bounds it covers
        """

        # nothing to enclose
        if not points:
            return None, None

        # work out a box around them all
        coords = [
            (p.get("lat"), p.get("lon")) for p in points
            if p.get("lat") is not None and p.get("lon") is not None
        ]
        bounds = compute_bounds(coords, lat, lon, pad_degrees=0.35, min_span=2.0)

        # these have to match the box the map layer actually draws into, or
        # the layer's cover-crop trims the edges back off again
        width = max(200, render_w - int(round(160 * scale)))
        height = max(200, render_h - int(round(438 * scale)))
        view = map_tiles.compose_base_map(bounds[0], bounds[1], bounds[2],
                                          bounds[3], width, height,
                                          cfg.user_agent)
        if view is not None:
            return view.image.copy(), view.bounds
        return None, bounds

    def refresh_regional(now: float) -> None:
        """
        Re-poll the nearby cities on their own slower cadence

        @param now: float The current wall clock time
        @return None
        """

        # turned off, or not due yet
        if cfg.regional_cities <= 0:
            return
        last = float(regional_state.get("at") or 0.0)
        if last and now - last < cfg.regional_interval_sec:
            return

        # ask each city in turn, skipping any that fail
        targets = nearby_cities(lat, lon, max_distance=360.0,
                                max_results=cfg.regional_cities)
        current_points: list = []
        forecast_points: list = []
        for target in targets:
            payload = client.point_forecast(target["lat"], target["lon"])
            if not payload:
                continue
            point = normalize.build_city_point(target["name"], target["lat"],
                                               target["lon"], payload, units)
            if point:
                current_points.append(point)
            forecast = normalize.build_city_forecast_point(
                target["name"], target["lat"], target["lon"], payload, units
            )
            if forecast:
                forecast_points.append(forecast)

        # only replace what we had when we actually got something
        if current_points or forecast_points:
            regional_state["current"] = current_points
            regional_state["forecast"] = forecast_points
            regional_state["at"] = now

    def radar_base(bounds: tuple, width: int, height: int):
        """
        The dimmed OpenStreetMap backdrop the radar sits on

        NOAA returns bare transparent reflectivity, so without this the
        echoes float over nothing.

        @param bounds: tuple The box to cover
        @param width: int The frame width
        @param height: int The frame height
        @return tuple: The backdrop and the bounds it really covers
        """

        # reuse the cached one when the box has not moved
        key = (tuple(round(v, 4) for v in bounds), width, height)
        if radar_state.get("base_key") == key and radar_state.get("base"):
            return radar_state["base"], radar_state["base_bounds"]

        # stitch a fresh one
        view = map_tiles.compose_base_map(bounds[0], bounds[1], bounds[2],
                                          bounds[3], width, height,
                                          cfg.user_agent)
        if view is None:
            return None, bounds

        # dim and cool it so the reflectivity colours stay dominant
        base = Image.alpha_composite(
            view.image.convert("RGBA"),
            Image.new("RGBA", view.image.size, (10, 15, 32, 140)),
        )
        radar_state["base"] = base
        radar_state["base_key"] = key
        radar_state["base_bounds"] = view.bounds
        return base, view.bounds

    def refresh_radar(now: float, width: int, height: int) -> None:
        """
        Refresh the radar loop from the configured source

        @param now: float The current wall clock time
        @param width: int The frame width
        @param height: int The frame height
        @return None
        """

        # turned off, or not due yet
        if cfg.radar_source == "off":
            return
        if radar_state["at"] and now - radar_state["at"] < 300:
            return

        # the box we want covered
        box = radar_sources.bounds_around(lat, lon, span_lat=3.0)
        frames: list = []
        source = None

        # NOAA first where it is wanted
        if cfg.radar_source in ("noaa", "auto"):

            # fetch the backdrop first, its snapped bounds are what the
            # overlay has to be requested for or the two will not line up
            base, aligned = radar_base(box, width, height)
            frames = radar_sources.fetch_noaa(aligned[0], aligned[1], aligned[2],
                                              aligned[3], width, height,
                                              cfg.user_agent)
            if frames and base is not None:
                for frame in frames:
                    overlay = frame["image"]
                    if overlay.size != base.size:
                        overlay = overlay.resize(base.size, Image.LANCZOS)
                    frame["image"] = Image.alpha_composite(base, overlay)
            if frames:
                source = radar_sources.NOAA_ATTRIBUTION

                # frames that came back completely empty almost always mean
                # we are outside the mosaic rather than in clear weather
                if not any(f.get("coverage", 0) > 0.0005 for f in frames):
                    if cfg.radar_source == "auto":
                        logger.info("NOAA returned no echoes, trying RainViewer")
                        frames, source = [], None

        # then RainViewer as the worldwide fallback
        if not frames and cfg.radar_source in ("rainviewer", "auto", "noaa"):
            frames = radar_sources.fetch_rainviewer(lat, lon, width, height,
                                                    cfg.user_agent)
            if frames:
                source = radar_sources.RAINVIEWER_ATTRIBUTION

        # keep whatever we ended up with
        if frames:
            if source != radar_state.get("source"):
                logger.info("radar source: %s", source)
            radar_state["frames"] = frames
            radar_state["source"] = source
            radar_state["at"] = now
            radar_state["served"] = 0

    def radar_getter() -> list:
        """
        Hand each newly fetched radar loop to the layer exactly once

        @return list: The new frames, or an empty list
        """

        # nothing new since the layer last asked
        frames = radar_state.get("frames") or []
        served = int(radar_state.get("served") or 0)
        if served >= len(frames):
            return []

        # mark them served and pass them along
        radar_state["served"] = len(frames)
        return [{"image": f["image"].copy(), "label": f.get("label") or ""}
                for f in frames[served:]]

    def ticker(active: list) -> tuple:
        """
        Decide what the ticker says

        Alerts take the ticker over completely: when any are active the
        configured news feeds are not shown at all.

        @param active: list The active alerts
        @return tuple: The ticker text and its category label
        """

        # alerts win outright
        if active:
            return (normalize.alerts_ticker_text(active), "ALERTS")

        # otherwise the news feeds get it
        headlines = feeds.titles()
        if headlines:
            return ("  \u2022  ".join(headlines), "NEWS")

        # and failing that, say the weather is quiet
        return (normalize.alerts_ticker_text([]), "WEATHER")

    def fetch_all() -> dict:
        """
        Build one complete snapshot for the layers

        @return dict: Everything the pages read from
        """

        # the forecast is the one call everything else hangs off
        data: dict = {}
        now = time.time()
        try:
            payload = client.forecast()
            data["error"] = None
        except WeatherError as exc:
            data["error"] = str(exc)
            data["ticker_text"] = f"Weather data unavailable \u2014 {exc}"
            data["ticker_label"] = "STATUS"
            return data

        # the alerts come from their own provider on their own cadence
        active = normalize.build_alerts(alerts.alerts())
        data["alerts"] = active

        # the page blocks
        data["current"] = normalize.build_current(payload, units,
                                                  cfg.location_name)
        data["daily_days"] = normalize.build_daily_days(payload, units)
        data["forecast_periods"] = normalize.build_forecast_periods(payload, units)
        data["hourly_points"] = normalize.build_hourly_points(payload, units,
                                                              limit=12)
        data["almanac_rows"] = normalize.build_almanac(payload, units)

        # the ticker
        text, label = ticker(active)
        data["ticker_text"] = text
        data["ticker_label"] = label

        # the regional markers, always including home so the maps are never bare
        refresh_regional(now)
        regional_points = list(regional_state.get("current") or [])
        forecast_points = list(regional_state.get("forecast") or [])
        current = data.get("current") or {}
        if isinstance(current, dict):
            home = {
                "name": cfg.location_name.split(",")[0].strip() or "Home",
                "lat": lat, "lon": lon,
                "temp": current.get("temp_display", "--"),
                "temp_f": current.get("temp_f"),
                "condition": current.get("summary", ""),
                "icon": current.get("icon", "clear-day"),
                "is_day": current.get("is_day", True),
            }
            if not any(p.get("name") == home["name"] for p in regional_points):
                regional_points.insert(0, home)

            # and the same for the forecast map
            days = data.get("daily_days") or []
            if days:
                home_forecast = dict(home)
                home_forecast["forecast_temp"] = (
                    "--\u00b0" if days[0].get("high") is None
                    else f"{int(round(days[0]['high']))}\u00b0"
                )
                home_forecast["temp_f"] = days[0].get("high_f")
                home_forecast["icon"] = days[0].get("icon", "clear-day")
                if not any(p.get("name") == home["name"] for p in forecast_points):
                    forecast_points.insert(0, home_forecast)

        data["regional_points"] = regional_points
        data["forecast_points"] = forecast_points

        # the map backdrops
        regional_image, regional_bounds = compose_map(regional_points)
        forecast_image, forecast_bounds = compose_map(forecast_points)
        data["regional_map_image"] = regional_image
        data["regional_map_bounds"] = regional_bounds
        data["forecast_map_image"] = forecast_image
        data["forecast_map_bounds"] = forecast_bounds

        # and the radar
        radar_w = max(200, render_w - int(round(160 * scale)))
        radar_h = max(200, render_h - int(round(452 * scale)))
        refresh_radar(now, radar_w, radar_h)
        data["radar_new_frames"] = radar_getter
        data["radar_source"] = radar_state.get("source") or ""
        return data

    # a quarter of the configured interval keeps the clock and ticker current
    # without going back out to the provider any more often than the cache
    store = DataStore(fetcher=fetch_all,
                      interval_sec=max(30, cfg.data_interval_sec // 4))
    store.start()
    return store


def build_layers(cfg: Config, store: DataStore, width: int, height: int,
                 scale: float) -> tuple:
    """
    Build every layer and group them into pages

    @param cfg: Config The runtime configuration
    @param store: DataStore The snapshot the layers read from
    @param width: int The output width
    @param height: int The output height
    @param scale: float The output scale factor
    @return tuple: The full layer list and the page cycler
    """

    # scaling and reading helpers the closures below share
    def s(value: float, minimum: int = 0) -> int:
        return max(minimum, int(round(value * scale)))

    def read(key: str, default=None):
        value = store.read().get(key)
        return default if value is None else value

    layers: list = []
    pages: list = []

    # the persistent header elements
    columns = layout.header_columns(width, s)

    # the temperature and clock blocks fill the band and centre inside it,
    # the same way the identity and title columns do
    band_top = 0
    band_h = max(1, s(layout.HEADER_H) - max(2, s(4)))
    
    # current temperature in column three
    temp_x, temp_w = columns[2]
    header_current = HeaderCurrentLayer(
        x=temp_x, y=band_top, w=temp_w, h=band_h,
        get_data=lambda: read("current", {}) or {},
        min_interval=5.0, scale=scale,
    )
    header_current.z = 200
    layers.append(header_current)

    # the clock in column four
    clock_x, clock_w = columns[3]
    clock = ClockLayer(x=clock_x, y=band_top, w=clock_w, h=band_h,
                       min_interval=1.0, scale=scale)
    clock.z = 200
    layers.append(clock)

    # and the ticker along the bottom
    ticker_h = s(layout.TICKER_H, 1)
    ticker = TickerLayer(
        x=s(layout.MARGIN), y=height - ticker_h - s(layout.TICKER_GAP),
        w=width - s(layout.MARGIN * 2), h=ticker_h,
        get_text=lambda: str(read("ticker_text", "") or ""),
        get_label=lambda: str(read("ticker_label", "WEATHER") or "WEATHER"),
        get_accent=lambda: theme.ALERT if read("alerts", []) else theme.ACCENT,
        px_per_sec=cfg.ticker_speed_px_per_sec,
        min_interval=1 / 30.0, scale=scale,
    )
    ticker.z = 200
    layers.append(ticker)

    def add_page(name: str, title: str, builder) -> None:
        """
        Register one page and its layers

        @param name: str The page's internal name
        @param title: str The title shown in the header
        @param builder: Callable Builds the page's body layers
        @return None
        """

        # the body sits inside the shared content box
        bounds = layout.content_bounds(width, height, s)

        # every page carries its own chrome so the title travels with it
        chrome = ChromeLayer(width=width, height=height,
                             location_name=cfg.location_name, page_title=title,
                             get_alerts=lambda: read("alerts", []) or [],
                             channel_name=cfg.channel_name, scale=scale)
        chrome.z = 0

        # then the body layers on top of it
        page_layers: list = [chrome]
        for layer in builder(bounds):
            layer.z = max(getattr(layer, "z", 50), 50)
            page_layers.append(layer)

        # everything starts hidden, the cycler turns one page on
        for layer in page_layers:
            layer.set_visible(False)
        pages.append({"name": name, "layers": page_layers})
        layers.extend(page_layers)

    # the pages, in the order they cycle
    add_page("current", "Current Conditions", lambda b: [
        CurrentLayer(x=b[0], y=b[1], w=b[2], h=b[3],
                     get_data=lambda: read("current", {}) or {},
                     min_interval=5.0, scale=scale)
    ])

    add_page("hourly", "12-Hour Trend", lambda b: [
        HourlyGraphLayer(x=b[0], y=b[1], w=b[2], h=b[3],
                         get_points=lambda: read("hourly_points", []) or [],
                         min_interval=15.0, scale=scale)
    ])

    add_page("daily", "7-Day Forecast", lambda b: [
        DailyLayer(x=b[0], y=b[1], w=b[2], h=b[3],
                   get_days=lambda: read("daily_days", []) or [],
                   min_interval=30.0, scale=scale)
    ])

    # radar is optional
    if cfg.radar_source != "off":
        add_page("radar", "Live Radar", lambda b: [
            RadarLayer(
                x=b[0], y=b[1], w=b[2], h=b[3],
                get_new_frames=lambda: (
                    lambda fn: fn() if callable(fn) else []
                )(store.read().get("radar_new_frames")),
                get_source=lambda: str(read("radar_source", "") or ""),
                frame_hold=3, min_interval=0.25, scale=scale,
            )
        ])

    add_page("regional", "Regional Conditions", lambda b: [
        RegionalLayer(
            x=b[0], y=b[1], w=b[2], h=b[3],
            get_points=lambda: read("regional_points", []) or [],
            get_map=lambda: (lambda im: im.copy() if im is not None else None)(
                store.read().get("regional_map_image")),
            get_bounds=lambda: store.read().get("regional_map_bounds"),
            min_interval=20.0, scale=scale,
        )
    ])

    add_page("forecast_map", "Forecast Highs", lambda b: [
        ForecastMapLayer(
            x=b[0], y=b[1], w=b[2], h=b[3],
            get_points=lambda: read("forecast_points", []) or [],
            get_map=lambda: (lambda im: im.copy() if im is not None else None)(
                store.read().get("forecast_map_image")),
            get_bounds=lambda: store.read().get("forecast_map_bounds"),
            min_interval=20.0, scale=scale,
        )
    ])

    add_page("forecast_text", "Extended Forecast", lambda b: [
        ForecastTextLayer(x=b[0], y=b[1], w=b[2], h=b[3],
                          get_periods=lambda: read("forecast_periods", []) or [],
                          min_interval=30.0, scale=scale)
    ])

    add_page("almanac", "Almanac", lambda b: [
        AlmanacLayer(x=b[0], y=b[1], w=b[2], h=b[3],
                     get_rows=lambda: read("almanac_rows", []) or [],
                     min_interval=20.0, scale=scale)
    ])

    # start on the first page
    cycler = PageCycler(pages, cfg.page_duration_sec)
    if pages:
        cycler.activate(0)
    return layers, cycler


def main() -> int:
    """
    Start the channel and run until the container stops

    @return int: A process exit code
    """

    # logging first, so every failure below is visible
    setup_logging()
    cfg = from_env()

    # nothing works without a location
    if not resolve_location(cfg):
        logger.error("no location configured - set KPTVW_ZIP, or KPTVW_LAT and "
                     "KPTVW_LON, or KPTVW_LOCATION_NAME")
        return 2

    # the providers
    units = normalize.units_for(cfg.units)
    client = OpenMeteoClient(lat=cfg.lat, lon=cfg.lon, units=cfg.units,
                             cache_ttl=cfg.data_interval_sec,
                             secondary_ttl=cfg.regional_interval_sec,
                             user_agent=cfg.user_agent)
    alerts = NWSAlertClient(lat=cfg.lat, lon=cfg.lon, user_agent=cfg.user_agent)

    # the timezone, preferring the configured one and asking the api otherwise
    tz_name = cfg.timezone
    if not tz_name:
        try:
            tz_name = client.timezone_name()
        except WeatherError as exc:
            logger.warning("initial fetch failed: %s", exc)
            tz_name = None
    set_timezone(tz_name, cfg.lat, cfg.lon)
    logger.info("location=%s (%.3f,%.3f) tz=%s units=%s", cfg.location_name,
                cfg.lat, cfg.lon, tz_name or "system", cfg.units)

    # the output surface, and how far everything scales from the design size
    width = cfg.width if cfg.width > 0 else BASE_WIDTH
    height = cfg.height if cfg.height > 0 else BASE_HEIGHT
    scale = min(width / BASE_WIDTH, height / BASE_HEIGHT)

    # the fanout, then the encoder that feeds it, then the service that
    # hands it out - in that order, so nothing is ever serving a dead broker
    broker = TSBroker()
    streamer = FFMPEGStreamer(
        ffmpeg_path=cfg.ffmpeg_path, width=width, height=height,
        fps=cfg.output_fps, on_output=broker.feed,
        music_playlist=build_music_playlist(cfg), music_volume=cfg.music_volume,
        vb_kbps=cfg.video_kbps, ab_kbps=cfg.audio_kbps,
        video_encoder=cfg.video_encoder, encoder_preset=cfg.encoder_preset,
    )
    try:
        streamer.start()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 2

    server = StreamServer(cfg, broker)
    server.start()

    # warm the icon loops so the first frames do not stall drawing them
    icons.prewarm(icons.SUPPORTED,
                  [int(round(v * scale)) for v in (62, 88, 96, 190)])

    # the data, the pages, and the loop that drives them
    store = make_datastore(cfg, client, alerts, units, width, height, scale)
    layers, cycler = build_layers(cfg, store, width, height, scale)
    compositor = Compositor(w=width, h=height)
    scheduler = Scheduler(layers=layers, cfr_hz=cfg.output_fps)
    cycler.start()

    # a clean shutdown on the usual container signals
    stopping = threading.Event()

    def handle_signal(signum, frame) -> None:
        """
        Ask the render loop to wind up

        @param signum: int The signal received
        @param frame: mixed The interrupted stack frame
        @return None
        """

        # just set the flag, the loop checks it between frames
        logger.info("signal %s received, shutting down", signum)
        stopping.set()

    for received in (signal.SIGTERM, signal.SIGINT):
        signal.signal(received, handle_signal)

    def present(image) -> None:
        """
        Hand a finished frame to the encoder

        @param image: Image The composited frame
        @return None
        """

        # a write failure must never take the render loop down with it
        try:
            streamer.send(image.tobytes())
        except Exception as exc:
            logger.warning("frame write failed: %r", exc)
        finally:
            # a write failure must never take the render loop down with it
            pass

    # and away it goes
    logger.info("channel '%s' is live", cfg.channel_name)
    try:
        scheduler.run_forever(compositor=compositor, on_present=present,
                              should_stop=stopping.is_set)
    except KeyboardInterrupt:
        pass
    finally:
        for shutdown in (cycler.stop, store.stop, server.stop, broker.shutdown,
                         streamer.stop):
            try:
                shutdown()
            except Exception:
                logger.exception("error during shutdown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
