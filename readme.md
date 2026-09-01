# kptv-weather

[![Build Main](https://img.shields.io/github/actions/workflow/status/kpirnie/kptv-weather/build.yml?branch=main&label=Main&logoColor=white&logo=github&labelColor=000&style=for-the-badge)](https://github.com/kpirnie/kptv-weather/actions?query=workflow%3A%22build+image%22+branch%3Amain)
[![Build Develop](https://img.shields.io/github/actions/workflow/status/kpirnie/kptv-weather/build.yml?branch=develop&logoColor=white&label=Develop&logo=github&labelColor=000&style=for-the-badge)](https://github.com/kpirnie/kptv-weather/actions?query=workflow%3A%22build+image%22+branch%3Adevelop)
[![GitHub Issues](https://img.shields.io/github/issues/kpirnie/kptv-weather?style=for-the-badge&logo=github&color=006400&logoColor=white&labelColor=000)](https://github.com/kpirnie/kptv-weather/issues)
[![Last Commit](https://img.shields.io/github/last-commit/kpirnie/kptv-weather?style=for-the-badge&labelColor=000)](https://github.com/kpirnie/kptv-weather/commits/main)
[![License: MIT](https://img.shields.io/badge/License-MIT-orange.svg?style=for-the-badge&logo=opensourceinitiative&logoColor=white&labelColor=000)](LICENSE)

[![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white&style=for-the-badge&labelColor=000)](https://python.org)
[![Debian](https://img.shields.io/badge/Base-Debian%20Trixie-A81D33?logo=debian&logoColor=white&style=for-the-badge&labelColor=000)](https://www.debian.org/)
[![Kevin Pirnie](https://img.shields.io/badge/-KevinPirnie.com-000d2d?style=for-the-badge&labelColor=000&logoColor=white&logo=data:image/svg%2Bxml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJ3aGl0ZSIgc3Ryb2tlLXdpZHRoPSIxLjgiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCI+CiAgPGNpcmNsZSBjeD0iMTIiIGN5PSIxMiIgcj0iMTAiLz4KICA8ZWxsaXBzZSBjeD0iMTIiIGN5PSIxMiIgcng9IjQuNSIgcnk9IjEwIi8+CiAgPGxpbmUgeDE9IjIiIHkxPSIxMiIgeDI9IjIyIiB5Mj0iMTIiLz4KICA8bGluZSB4MT0iNC41IiB5MT0iNi41IiB4Mj0iMTkuNSIgeTI9IjYuNSIvPgogIDxsaW5lIHgxPSI0LjUiIHkxPSIxNy41IiB4Mj0iMTkuNSIgeTI9IjE3LjUiLz4KPC9zdmc+Cg==)](https://kevinpirnie.com/)


A self-hosted, TV-style weather channel in a container. It renders its own
broadcast graphics, encodes them to H.264, and serves one continuous MPEG-TS
channel over HTTP that any number of clients can pull at once.

One station per container. Everything is configured through the environment.

---

## ffmpeg is required and is not included

**This image does not ship ffmpeg and never will.** You must bind mount a
**static** ffmpeg build into the container and point `KPTVW_FFMPEG_PATH` at it.
The container will refuse to start without one.

```yaml
volumes:
  - /opt/ffmpeg/ffmpeg:/usr/local/bin/ffmpeg:ro
environment:
  KPTVW_FFMPEG_PATH: "/usr/local/bin/ffmpeg"
```

A static build is what is expected. A dynamically linked binary will need its
shared libraries mounted alongside it as well, and depending on the build that
can extend to the driver tree (`/usr/lib/x86_64-linux-gnu/dri`).

### Hardware encoding

Pass `/dev/dri` through and hardware encoding is detected and used
automatically. NVENC, QSV, and VAAPI are each probed by running a throwaway
one-frame encode, so a device that exists but whose driver stack does not work
falls back to software rather than failing at stream time.

```yaml
devices:
  - /dev/dri:/dev/dri
```

Set `KPTVW_ENCODER` to `libx264`, `h264_nvenc`, `h264_qsv`, or `h264_vaapi` to
pin one explicitly. `auto` is the default and is usually right.

---

## Endpoints

| Path | What it serves |
|---|---|
| `/stream.ts` | The continuous MPEG-TS channel |
| `/playlist.m3u8` | A one-entry playlist pointing at the stream |
| `/health`, `/status` | JSON: client count, bytes served, channel name |

The stream runs whether or not anybody is watching, which is what makes it a
real live channel rather than something started per viewer. Clients join at the
most recent program table, so a player attaching mid-stream has what it needs
to start decoding within about a second.

Add the playlist URL to your proxy, filter app, or player. Behind a reverse
proxy, set `KPTVW_BASE_URL` so the playlist advertises the URL clients should
actually use rather than the one they happened to reach the container on.

---

## Pages

The channel cycles through eight pages, about fourteen seconds each:

| Page | Contents |
|---|---|
| Current Conditions | Oversized temperature, condition icon, high and low, sun times, eight readings |
| 12-Hour Trend | Temperature curve with precipitation chance and cloud cover |
| 7-Day Forecast | Day cards with icons, highs and lows on a shared range bar, plus precipitation, humidity, wind and UV |
| Live Radar | Animated reflectivity over an OpenStreetMap base, with a dBZ key and a source credit |
| Regional Conditions | Current temperatures at nearby cities, plotted on a map |
| Forecast Highs | Tomorrow's highs at those same cities |
| Extended Forecast | Narrative panels for today and tomorrow, with a stat grid |
| Almanac | Sun times, a phase-accurate moon, and the secondary readings |

A header band carries the channel identity, the location, the page title, the
current temperature, and the local clock. A ticker runs along the bottom.

Set `KPTVW_RADAR_SOURCE=off` to drop the radar page entirely.

---

## The ticker

**Weather alerts override the news feeds completely.** Whenever any alert is
active for the configured point, the ticker carries the alerts and nothing
else, and the badge turns red. The configured RSS feeds only appear when the
weather is quiet.

Feeds are given as a comma separated list in `KPTVW_RSS_URLS`.

---

## Configuration

Every setting is an environment variable prefixed `KPTVW_`. See
`docker-compose-example.yaml` for a complete annotated example.

### Location

Give it a ZIP code, a latitude and longitude pair, or a place name. One of the
three is required.

| Variable | Default | Notes |
|---|---|---|
| `KPTVW_ZIP` | | Five digit US ZIP |
| `KPTVW_LAT`, `KPTVW_LON` | | Decimal degrees, for anywhere else |
| `KPTVW_LOCATION_NAME` | | On-screen name; also usable as a geocoding input |
| `KPTVW_TZ` | | IANA zone; taken from the provider when blank |

### Channel

| Variable | Default | Notes |
|---|---|---|
| `KPTVW_CHANNEL_NAME` | `Weather` | Shown in the header and the playlist |
| `KPTVW_CHANNEL_LOGO` | | A `tvg-logo` URL for the playlist entry |

### Encoder

| Variable | Default |
|---|---|
| `KPTVW_FFMPEG_PATH` | `/usr/local/bin/ffmpeg` |
| `KPTVW_ENCODER` | `auto` |
| `KPTVW_ENCODER_PRESET` | `veryfast` |
| `KPTVW_RESOLUTION` | `1920x1080` |
| `KPTVW_FPS` | `30` |
| `KPTVW_VIDEO_KBPS` | `3500` |
| `KPTVW_AUDIO_KBPS` | `128` |

### Service

| Variable | Default |
|---|---|
| `KPTVW_HTTP_HOST` | `0.0.0.0` |
| `KPTVW_HTTP_PORT` | `5960` |
| `KPTVW_STREAM_PATH` | `/stream.ts` |
| `KPTVW_PLAYLIST_PATH` | `/playlist.m3u8` |
| `KPTVW_BASE_URL` | | Set this behind a proxy |

### Data

| Variable | Default | Notes |
|---|---|---|
| `KPTVW_UNITS` | `us` | `us`, `ca`, `si`, or `uk` |
| `KPTVW_DATA_INTERVAL_SEC` | `600` | Forecast refresh |
| `KPTVW_REGIONAL_INTERVAL_SEC` | `5400` | Nearby city refresh |
| `KPTVW_REGIONAL_CITIES` | `6` | Markers on the map pages, `0` disables |
| `KPTVW_RADAR_SOURCE` | `noaa` | `noaa`, `rainviewer`, `auto`, `off` |

### Presentation

| Variable | Default |
|---|---|
| `KPTVW_PAGE_SECONDS` | `14` |
| `KPTVW_TICKER_SPEED` | `120` |
| `KPTVW_MUSIC_DIR` | `/music` |
| `KPTVW_MUSIC_VOLUME` | `50` |
| `KPTVW_RSS_URLS` | |
| `KPTVW_RSS_REFRESH_SEC` | `300` |
| `KPTVW_RSS_MAX_ITEMS` | `3` |

Set `DEBUG=true` for verbose logging.

---

## Music

No audio ships with the image. Bind mount a directory over `/music` and drop
`.mp3`, `.m4a`, `.aac`, `.flac`, `.ogg`, or `.wav` files into it; they are
shuffled and looped behind the channel. With nothing mounted, or with
`KPTVW_MUSIC_VOLUME=0`, the stream carries a silent audio track.

---

## Branding

The icons are drawn procedurally, so nothing has to be supplied and everything
stays sharp at any resolution. To override:

- `assets/logo.png` is picked up as the header logo if present.
- `assets/icons/<name>.png` overrides a drawn icon. The names are
  `clear-day`, `clear-night`, `partly-cloudy-day`, `partly-cloudy-night`,
  `cloudy`, `rain`, `snow`, `fog`, `wind`, `thunderstorm`.
- `assets/fonts/` is searched for Inter faces (`Inter-Black.ttf` and friends);
  any TrueType face in there will be used if those are absent.

Bind mount your own tree over `/app/assets`, or set `KPTVW_ASSET_DIR`.

---

## Data sources

- Forecast: [Open-Meteo](https://open-meteo.com/) — no API key
- Alerts: [NOAA / National Weather Service](https://www.weather.gov/documentation/services-web-api) — US only
- Radar: NOAA reflectivity, with [RainViewer](https://www.rainviewer.com/) worldwide
- Base maps: [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors
- ZIP lookup: [Zippopotam](https://zippopotam.us/)

Credit for the map and radar imagery is drawn on screen where it is used.

---

## Images

Published to `ghcr.io/kpirnie/kptv-weather`. `main` builds `:beta`; tags build
the release version and `:latest`. Both `linux/amd64` and `linux/arm64`.

---

## License

MIT. See [LICENSE](LICENSE).
