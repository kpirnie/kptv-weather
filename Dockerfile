# syntax=docker/dockerfile:1

# kptv-weather
#
# ffmpeg is deliberately NOT installed here. A static ffmpeg build must be
# bind mounted in at runtime and its path passed as KPTVW_FFMPEG_PATH.

FROM python:3.14-slim

# the usual container hygiene
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# certificates for the outbound https calls, and a timezone database so the
# on-screen clock can be pinned to the station's own zone
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# dependencies first so the layer caches
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# then the application
COPY kptvweather /app/kptvweather
COPY assets /app/assets

# the music mount point, empty unless something is bind mounted over it
RUN mkdir -p /music

# run as a normal user
RUN useradd --system --uid 10001 --create-home --home-dir /home/kptvw kptvw \
    && chown -R kptvw:kptvw /app /music
USER kptvw

EXPOSE 5960

# a container with a dead encoder is worse than one that restarts
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,os,sys; \
port=os.environ.get('KPTVW_HTTP_PORT','5960'); \
sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "kptvweather.main"]
