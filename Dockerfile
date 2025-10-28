# -----------------------------
# Final stage - Debian Bookworm slim
# -----------------------------
FROM docker.io/debian:bookworm-slim

# Install GPU drivers + Chromium + utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    mesa-va-drivers \
    mesa-vulkan-drivers \
    intel-media-va-driver \
    libva-drm2 \
    libva-x11-2 \
    vulkan-tools \
    va-driver-all \
    chromium \
    curl \
    unzip \
    xz-utils \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# we need the render group for hw accelleration
RUN groupadd --system --gid 107 render

# chromium test
RUN which chromium

# -----------------------------
# Copy static FFmpeg
# -----------------------------
COPY --from=docker.io/mwader/static-ffmpeg:latest /ffmpeg /usr/local/bin/
COPY --from=docker.io/mwader/static-ffmpeg:latest /ffprobe /usr/local/bin/
RUN chmod 755 /usr/local/bin/ffmpeg /usr/local/bin/ffprobe

# -----------------------------
# Non-root GPU user
# -----------------------------
RUN mkdir -p /dev/dri && \
    addgroup --gid 1000 kptv && \
    adduser --uid 1000 --gid 1000 --disabled-password --gecos "" kptv && \
    usermod -a -G video kptv && \
    usermod -a -G render kptv && \
    chmod 755 /usr/local/bin/ffmpeg /usr/local/bin/ffprobe && \
    mkdir -p /opt/weather/hls && chown -R 1000:1000 /opt/weather/hls

# -----------------------------
# Copy entrypoint
# -----------------------------
COPY entrypoint.sh /opt/weather/entrypoint.sh
RUN chmod +x /opt/weather/entrypoint.sh

USER kptv
WORKDIR /opt/weather

EXPOSE 8080/tcp
ENTRYPOINT ["/opt/weather/entrypoint.sh"]
