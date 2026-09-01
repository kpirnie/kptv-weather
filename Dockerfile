# kptv-weather
#
# ffmpeg is deliberately NOT installed here. A static ffmpeg build must be
# bind mounted in at runtime and its path passed as KPTVW_FFMPEG_PATH.

FROM docker.io/library/python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# everything installs into a venv so the final stage copies one directory
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt


FROM docker.io/library/python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# certificates for the outbound https calls, a timezone database so the
# on-screen clock can be pinned to the station's own zone, and the VA-API
# stack. The Mesa drivers cover Intel and AMD in-image, so those hosts only
# have to pass /dev/dri through. NVIDIA ships no redistributable userspace,
# so those hosts bind mount libcuda and libnvidia-encode themselves.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    ca-certificates \
    libva-drm2 \
    libva2 \
    mesa-va-drivers \
    tzdata \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man

# just the dependencies, without pip or the toolchain behind them
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# the application
COPY kptvweather /app/kptvweather
COPY assets /app/assets

# the music mount point, empty unless something is bind mounted over it
RUN mkdir -p /music

# the host's video and render GIDs, so the passed-through /dev/dri nodes are
# accessible. These differ between distributions - render is 992 on some and
# 107 on others - so prefer group_add with a numeric GID at runtime over
# relying on these matching.
ARG VIDEO_GID=44
ARG RENDER_GID=992

# run as a normal user, in the groups that own the render nodes
RUN (getent group ${VIDEO_GID} || groupadd --system --gid ${VIDEO_GID} video) \
    && (getent group ${RENDER_GID} || groupadd --system --gid ${RENDER_GID} render) \
    && groupadd --system --gid 10001 kptvw \
    && useradd --system --uid 10001 --gid 10001 --create-home \
    --home-dir /home/kptvw kptvw \
    && usermod -a -G $(getent group ${VIDEO_GID} | cut -d: -f1),$(getent group ${RENDER_GID} | cut -d: -f1) kptvw \
    && chown -R kptvw:kptvw /app /music
USER kptvw

EXPOSE 8000

CMD ["python", "-m", "kptvweather.main"]