#!/bin/bash
set -e

# -----------------------------
# Environment variables
# -----------------------------
if [ -z "$SOURCE" ] || [ -z "$LATLONQUERY" ] || [ -z "$TXTLOCATION" ] || [ -z "$LATLON" ] || [ -z "$UNITS" ]; then
    echo "[ERROR] Please set SOURCE, LATLONQUERY, TXTLOCATION, LATLON, and UNITS environment variables."
    exit 1
fi

CHROMIUM_BIN=/usr/bin/chromium

# URL-encode
urlencode() {
    local raw="$1"
    local length="${#raw}"
    local i c
    for (( i=0; i<length; i++ )); do
        c="${raw:i:1}"
        case "$c" in
            [a-zA-Z0-9.~_-]) printf "$c" ;;
            *) printf '%%%02X' "'$c"
        esac
    done
}

LATLONQUERY_ENC=$(urlencode "$LATLONQUERY")
TXTLOCATION_ENC=$(urlencode "$TXTLOCATION")
LATLON_ENC=$(urlencode "{\"lat\":${LATLON%,*},\"lon\":${LATLON#*,}}")

URL="$SOURCE/index.html?settings-wide-checkbox=true&settings-kiosk-checkbox=true&travel-checkbox=true&extended-forecast-checkbox=true&regional-forecast-checkbox=true&latLonQuery=${LATLONQUERY_ENC}&settings-stickyKiosk-checkbox=false&hourly-graph-checkbox=true&settings-units-select=${UNITS}&latLon=${LATLON_ENC}&settings-speed-select=1.00&hazards-checkbox=true&current-weather-checkbox=true&hourly-checkbox=true&settings-customFeedEnable-checkbox=true&almanac-checkbox=true&radar-checkbox=true&settings-scanLineMode-select=auto&local-forecast-checkbox=true&txtLocation=${TXTLOCATION_ENC}&latest-observations-checkbox=true&settings-scanLines-checkbox=false&spc-outlook-checkbox=true"

echo "[INFO] Weather stream URL: $URL"

# -----------------------------
# Stream settings
# -----------------------------
PORT=8080
FRAMERATE=24
BITRATE=1200k  # Reduced for better encoding speed
BUFSIZE=4096k
VIDEO_SIZE="1280x720"
HLS_PATH="/opt/weather/hls"
HLS_NAME="playlist.m3u8"
DISPLAY_NUM=99

mkdir -p "$HLS_PATH"

# Clean up any old X locks
rm -f /tmp/.X${DISPLAY_NUM}-lock /tmp/.X11-unix/X${DISPLAY_NUM} 2>/dev/null || true

# -----------------------------
# Start HTTP server in background
# -----------------------------
echo "[INFO] Starting HTTP server on port $PORT..."
cd /opt/weather
python3 -m http.server $PORT &
HTTP_PID=$!

sleep 2
echo "[INFO] HTTP server started. Stream will be available at: http://localhost:$PORT/hls/$HLS_NAME"

# -----------------------------
# Start Xvfb (virtual display)
# -----------------------------
echo "[INFO] Starting virtual display :$DISPLAY_NUM at ${VIDEO_SIZE}..."
Xvfb :$DISPLAY_NUM -screen 0 ${VIDEO_SIZE}x24 -ac -nolisten tcp -nolisten unix &
XVFB_PID=$!
export DISPLAY=:$DISPLAY_NUM

sleep 3

# Verify Xvfb is running
if ! xdpyinfo -display :$DISPLAY_NUM >/dev/null 2>&1; then
    echo "[ERROR] Xvfb failed to start properly"
    exit 1
fi

echo "[INFO] Virtual display ready"

# -----------------------------
# Start Chromium in kiosk mode
# -----------------------------
echo "[INFO] Starting Chromium in kiosk mode..."
$CHROMIUM_BIN \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-software-rasterizer \
    --disable-gpu \
    --no-proxy-server \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI \
    --start-maximized \
    --window-size=${VIDEO_SIZE} \
    --window-position=0,0 \
    --force-device-scale-factor=1 \
    "$URL" 2>/dev/null &
CHROME_PID=$!

echo "[INFO] Waiting for Chromium to fully load..."
sleep 3

# -----------------------------
# Start FFmpeg continuous capture with HEVC
# -----------------------------
echo "[INFO] Starting continuous HLS stream capture at ${FRAMERATE}fps (HEVC/CPU veryfast)..."

# Trap to cleanup
trap "kill $CHROME_PID $XVFB_PID $HTTP_PID 2>/dev/null; exit" INT TERM

ffmpeg \
    -f x11grab \
    -draw_mouse 0 \
    -video_size $VIDEO_SIZE \
    -framerate $FRAMERATE \
    -i :$DISPLAY_NUM \
    -c:v libx265 \
    -preset veryfast \
    -x265-params keyint=60:min-keyint=60:scenecut=0 \
    -b:v $BITRATE \
    -maxrate $BITRATE \
    -bufsize $BUFSIZE \
    -pix_fmt yuv420p \
    -g 60 \
    -tag:v hvc1 \
    -f hls \
    -hls_time 6 \
    -hls_list_size 10 \
    -hls_flags delete_segments+independent_segments \
    -hls_segment_type mpegts \
    -hls_segment_filename "$HLS_PATH/segment_%03d.ts" \
    "$HLS_PATH/$HLS_NAME"