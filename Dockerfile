# -----------------------------
# Final stage - Debian Bookworm slim
# -----------------------------
FROM docker.io/debian:bookworm-slim

# Install only essential packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    xvfb \
    ffmpeg \
    python3 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# -----------------------------
# Non-root user
# -----------------------------
RUN mkdir -p /tmp/.X11-unix && \
    chmod 1777 /tmp/.X11-unix && \
    addgroup --gid 1000 kptv && \
    adduser --uid 1000 --gid 1000 --disabled-password --gecos "" kptv && \
    mkdir -p /opt/weather/hls && chown -R 1000:1000 /opt/weather/hls

# Suppress DBus errors
ENV DBUS_SESSION_BUS_ADDRESS=/dev/null

# -----------------------------
# Copy entrypoint
# -----------------------------
COPY entrypoint.sh /opt/weather/entrypoint.sh
RUN chmod +x /opt/weather/entrypoint.sh

USER kptv
WORKDIR /opt/weather

EXPOSE 8080/tcp
ENTRYPOINT ["/opt/weather/entrypoint.sh"]