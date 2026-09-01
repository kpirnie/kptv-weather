#!/usr/bin/env python3
"""
HTTP Service Module

Serves the continuous transport stream, a playlist pointing at it, and a
small status endpoint. Threaded so any number of clients can pull at once.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import json
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from ..config import Config
from .fanout import TSBroker

logger = logging.getLogger(__name__)


class _ThreadingServer(ThreadingHTTPServer):
    """
    Threaded server that lets us rebind straight after a restart
    """

    # come back up immediately rather than sitting in TIME_WAIT
    allow_reuse_address = True

    # a client hanging around must never hold shutdown up
    daemon_threads = True


class _StreamHandler(BaseHTTPRequestHandler):
    """
    Request handler for the stream, the playlist, and the status endpoint

    Class attributes _cfg and _broker are filled in by StreamServer when it
    builds its handler subclass.
    """

    # close delimited responses are what a live transport stream wants, and
    # 1.0 semantics give us that without chunking every packet
    protocol_version = "HTTP/1.0"

    # the fields StreamServer injects
    _cfg: Config = None
    _broker: TSBroker = None

    def log_message(self, fmt: str, *args) -> None:
        """
        Route access logging through our own logger

        @param fmt: str Printf style format from the base handler
        @return None
        """

        # debug only, otherwise every client reconnect spams the log
        logger.debug("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        """
        Dispatch a GET request

        @return None
        """

        # strip any query string off before matching
        path = self.path.split("?", 1)[0].rstrip("/") or "/"

        # the stream itself
        if path == self._cfg.stream_path.rstrip("/"):
            self._serve_stream()
            return

        # the playlist pointing at it, under either extension
        playlist = self._cfg.playlist_path.rstrip("/")
        if path in (playlist, playlist.replace(".m3u8", ".m3u")):
            self._serve_playlist()
            return

        # a small status blob
        if path in ("/health", "/status"):
            self._serve_status()
            return

        # anything else is simply not here
        self.send_error(404, "Not Found")

    def do_HEAD(self) -> None:
        """
        Answer a HEAD request with the headers a GET would carry

        @return None
        """

        # players probe the stream this way before committing to it
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == self._cfg.stream_path.rstrip("/"):
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Connection", "close")
            self.end_headers()
            return

        # everything else gets a 200 or a 404 to match do_GET
        known = (self._cfg.playlist_path.rstrip("/"), "/health", "/status")
        if path in known:
            self.send_response(200)
            self.send_header("Connection", "close")
            self.end_headers()
            return
        self.send_error(404, "Not Found")

    def _serve_stream(self) -> None:
        """
        Attach a client to the fanout and write to it until it goes away

        @return None
        """

        # register first so nothing is missed between headers and the loop
        sub, preroll = self._broker.subscribe()

        # a live stream has no length, so this runs until the socket dies
        try:
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            # hand over the catch-up bytes so the decoder has program tables
            if preroll:
                self.wfile.write(preroll)

            # then just relay whatever the broker pushes at us
            while not sub.closed:
                chunk = sub.read(timeout=5.0)
                if chunk is None:
                    continue
                self.wfile.write(chunk)

        # every one of these just means the player hung up
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
            pass

        # always let the broker know it lost one
        finally:
            self._broker.unsubscribe(sub)

    def _serve_playlist(self) -> None:
        """
        Serve the playlist that points back at the transport stream

        @return None
        """

        # build the absolute url the player should pull
        stream_url = f"{self._base_url()}{self._cfg.stream_path}"

        # one channel, with whatever metadata was configured for it
        name = self._cfg.channel_name
        attrs = f'tvg-name="{name}" tvg-id="{name}"'
        if self._cfg.channel_logo:
            attrs += f' tvg-logo="{self._cfg.channel_logo}"'
        body = (
            "#EXTM3U\n"
            f"#EXTINF:-1 {attrs},{name}\n"
            f"{stream_url}\n"
        ).encode("utf-8")

        # ship it
        self.send_response(200)
        self.send_header("Content-Type", "audio/x-mpegurl")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _serve_status(self) -> None:
        """
        Serve a small json health blob

        @return None
        """

        # just enough to tell whether the encoder is actually producing
        body = json.dumps({
            "status": "ok",
            "clients": self._broker.client_count(),
            "bytes_out": self._broker.bytes_out(),
            "channel": self._cfg.channel_name,
            "stream": self._cfg.stream_path,
            "playlist": self._cfg.playlist_path,
        }).encode("utf-8")

        # ship it
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _base_url(self) -> str:
        """
        Work out the base url the playlist should advertise

        Prefers whatever was configured, since behind a proxy the host we
        were reached on is not necessarily the host clients should use.

        @return str: An absolute base url with no trailing slash
        """

        # an explicit setting always wins
        if self._cfg.base_url:
            return self._cfg.base_url

        # otherwise take the host we were asked on
        host = self.headers.get("Host")
        if host:
            return f"http://{host}"

        # and fall back to the bind address if there was not even one of those
        return f"http://{self._cfg.http_host}:{self._cfg.http_port}"


class StreamServer:
    """
    Owns the listening socket and the handler bound to a broker
    """

    def __init__(self, cfg: Config, broker: TSBroker):
        """
        Build the server

        @param cfg: Config The runtime configuration
        @param broker: TSBroker The fanout the stream is pulled from
        """

        # everything the handler needs, since handlers get built per request
        self.cfg = cfg
        self.broker = broker
        self._server: Optional[_ThreadingServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """
        Bind the socket and begin serving in the background

        @return None
        """

        # already running
        if self._server is not None:
            return

        # the handler needs a route back to us, so close over it
        cfg = self.cfg
        broker = self.broker

        class _Handler(_StreamHandler):
            _cfg = cfg
            _broker = broker

        # bind and serve, reusing the address so a restart is not blocked
        self._server = _ThreadingServer((self.cfg.http_host, self.cfg.http_port),
                                        _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="http-server", daemon=True)
        self._thread.start()

        # say where we ended up
        logger.info(
            "serving %s and %s on %s:%s",
            self.cfg.stream_path, self.cfg.playlist_path,
            self.cfg.http_host, self.cfg.http_port,
        )

    def stop(self) -> None:
        """
        Stop serving and release the socket

        @return None
        """

        # nothing to stop
        if self._server is None:
            return

        # shut it down and wait for the thread to unwind
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._server = None
        self._thread = None
