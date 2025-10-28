# KPTV Weather Stream

A Docker container that captures a live weather website and streams it as an HLS video feed. Perfect for displaying real-time weather information on digital signage, media servers, or anywhere you need a continuous weather stream.

## Features

- 🌦️ **Continuous live streaming** of weather websites
- 📺 **HLS output** - Compatible with VLC, media servers, and most video players
- 🖥️ **Headless rendering** - Uses Xvfb and Chromium for browser capture
- ⚡ **Optimized encoding** - H.264 with ultrafast preset for low CPU usage
- 🎯 **Configurable** - Customize location, resolution, and streaming parameters
- 🐳 **Containerized** - Easy deployment with Docker/Podman

## Quick Start

### Using Docker Compose

1. Create a `docker-compose.yaml` file:

```yaml
services:
  kptv-weather:
    image: ghcr.io/kpirnie/kptv-weather:latest
    container_name: kptv-weather
    restart: unless-stopped
    network_mode: bridge
    ports:
      - 9600:8080/tcp
    environment:
      - SOURCE=https://your.url
      - LATLONQUERY=01030, Feeding Hills, MA, USA
      - TXTLOCATION=01030, Feeding Hills, MA, USA
      - LATLON=42.0738,-72.6733
      - UNITS=us
    dns:
      - 8.8.8.8
      - 8.8.4.4
```

2. Start the container:

```bash
docker-compose up -d
```

3. Access the stream at:

```
http://YOUR_HOST_IP:9600/hls/playlist.m3u8
```

### Using Docker CLI

```bash
docker run -d \
  --name kptv-weather \
  --restart unless-stopped \
  -p 9600:8080 \
  -e SOURCE=https://weather.kevp.us \
  -e LATLONQUERY="01030, Feeding Hills, MA, USA" \
  -e TXTLOCATION="01030, Feeding Hills, MA, USA" \
  -e LATLON=42.0738,-72.6733 \
  -e UNITS=us \
  --dns 8.8.8.8 \
  --dns 8.8.4.4 \
  ghcr.io/kpirnie/kptv-weather:latest
```

## Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `SOURCE` | Yes | Base URL of the weather website | `https://weather.kevp.us` |
| `LATLONQUERY` | Yes | Location query string | `01030, Feeding Hills, MA, USA` |
| `TXTLOCATION` | Yes | Text display location | `01030, Feeding Hills, MA, USA` |
| `LATLON` | Yes | Latitude and longitude | `42.0738,-72.6733` |
| `UNITS` | Yes | Units system (`us` or `metric`) | `us` |

## Viewing the Stream

### VLC Media Player

1. Open VLC
2. Go to **Media → Open Network Stream** (or press `Ctrl+N`)
3. Enter: `http://YOUR_HOST_IP:9600/hls/playlist.m3u8`
4. Click **Play**

### Command Line (ffplay)

```bash
ffplay http://YOUR_HOST_IP:9600/hls/playlist.m3u8
```

### Other Players

Any HLS-compatible player will work:
- MPV: `mpv http://YOUR_HOST_IP:9600/hls/playlist.m3u8`
- Media servers (Plex, Jellyfin, etc.) - Add as a live TV source
- Web browsers with HLS.js

## Stream Specifications

- **Resolution:** 854x480 (480p)
- **Framerate:** 24 fps
- **Codec:** H.264 (AVC)
- **Bitrate:** 1024 kbps
- **Segment Duration:** 6 seconds
- **Buffer Size:** 4096 KB
- **Playlist Size:** 10 segments (~60 seconds)

## Building from Source

```bash
git clone https://github.com/kpirnie/kptv-weather.git
cd kptv-weather
docker build -t kptv-weather .
```

## Troubleshooting

### Stream not available (404 error)

Wait 15-20 seconds after container startup for the stream to initialize. Check logs:

```bash
docker logs -f kptv-weather
```

### High CPU usage

The stream uses CPU encoding. Typical usage is 60-100% of one CPU core. To reduce:

- Lower framerate (edit `FRAMERATE` in entrypoint.sh)
- Reduce resolution (edit `VIDEO_SIZE` in entrypoint.sh)
- Lower bitrate (edit `BITRATE` in entrypoint.sh)

### "Site can't be reached" in stream

Check that the container has internet access:

```bash
docker exec kptv-weather curl -I https://weather.kevp.us
```

If it fails, verify DNS settings in docker-compose.yaml.

### Buffering or stuttering

Increase buffer size or reduce framerate for smoother playback on slower networks.

## Technical Details

### Architecture

1. **Xvfb** creates a virtual X11 display
2. **Chromium** renders the weather website in kiosk mode
3. **FFmpeg** captures the display using x11grab and encodes to HLS
4. **Python HTTP server** serves the HLS playlist and segments

### Container Image

- Base: Debian Bookworm Slim
- Size: ~350 MB
- Components: Chromium, Xvfb, FFmpeg, Python 3

## License

MIT License - See LICENSE file for details

## Credits

Created for streaming weather displays to local media systems.

Weather data provided by the configured SOURCE URL.

## Contributing

Pull requests welcome! Please open an issue first to discuss major changes.

## Support

For issues, questions, or suggestions, please open an issue on GitHub.