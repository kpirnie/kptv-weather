#!/bin/bash
set -e

# -----------------------------
# Environment variables
# -----------------------------
if [ -z "$LATLONQUERY" ] || [ -z "$TXTLOCATION" ] || [ -z "$LATLON" ] || [ -z "$UNITS" ]; then
    echo "[ERROR] Please set LATLONQUERY, TXTLOCATION, LATLON, and UNITS environment variables."
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

URL="https://weather.kevp.us/index.html?settings-wide-checkbox=true&settings-kiosk-checkbox=true&travel-checkbox=true&extended-forecast-checkbox=true&regional-forecast-checkbox=true&latLonQuery=${LATLONQUERY_ENC}&settings-stickyKiosk-checkbox=false&hourly-graph-checkbox=true&settings-units-select=${UNITS}&latLon=${LATLON_ENC}&settings-speed-select=1.00&hazards-checkbox=true&current-weather-checkbox=true&hourly-checkbox=true&settings-customFeedEnable-checkbox=true&almanac-checkbox=true&radar-checkbox=true&settings-scanLineMode-select=auto&local-forecast-checkbox=true&txtLocation=${TXTLOCATION_ENC}&latest-observations-checkbox=true&settings-scanLines-checkbox=false&spc-outlook-checkbox=true"

echo "[INFO] Weather stream URL: $URL"

# -----------------------------
# Stream settings
# -----------------------------
PORT=8080
FRAMERATE=30
BITRATE=1500k
VIDEO_SIZE="1280x720"
HLS_PATH="/opt/weather/hls"
HLS_NAME="playlist.m3u8"
mkdir -p "$HLS_PATH"

# -----------------------------
# Detect VA-API GPU
# -----------------------------
if [ -c /dev/dri/renderD128 ] && vainfo &>/dev/null; then
    echo "[INFO] VA-API GPU detected."
    HW_ENCODER="hevc_vaapi"
    HW_FLAGS="-vf 'format=nv12,hwupload'"
else
    echo "[INFO] No VA-API GPU detected. Using CPU HEVC."
    HW_ENCODER="libx265"
    HW_FLAGS=""
fi

# -----------------------------
# Start FFmpeg HLS in background
# -----------------------------
FRAME_FIFO=/tmp/frames.y4m
rm -f "$FRAME_FIFO"
mkfifo "$FRAME_FIFO"

ffmpeg -y -f yuv4mpegpipe -r $FRAMERATE -i "$FRAME_FIFO" \
    -c:v $HW_ENCODER -b:v $BITRATE $HW_FLAGS -pix_fmt yuv420p \
    -f hls -hls_time 5 -hls_list_size 5 -hls_flags delete_segments \
    "$HLS_PATH/$HLS_NAME" &

# -----------------------------
# Continuous Chromium capture -> stdout -> FFmpeg
# -----------------------------
echo "[INFO] Starting smooth continuous live stream..."

while true; do
    # Chromium headless renders directly to stdout as PNG
    $CHROMIUM_BIN --headless --disable-gpu --window-size=${VIDEO_SIZE} \
        --virtual-time-budget=500 --no-sandbox --screenshot-to-stdout "$URL" \
    | ffmpeg -hide_banner -loglevel error -f image2pipe -r $FRAMERATE -i - \
        -pix_fmt yuv420p -f yuv4mpegpipe "$FRAME_FIFO"
done
