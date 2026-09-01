#!/usr/bin/env python3
"""
Page Cycler Module

Owns which page is on screen. Pages are just groups of layers whose
visibility gets toggled on a fixed cadence.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import logging
import threading

from .core.layer import Layer

logger = logging.getLogger(__name__)


class PageCycler:
    """
    Rotates through the pages on a timer
    """

    def __init__(self, pages: list, interval_sec: float):
        """
        Build the cycler

        @param pages: list Page dicts of name and layers
        @param interval_sec: float How long each page holds the screen
        """

        # the pages and how long each gets
        self.pages = list(pages or [])
        self.interval = max(1.0, float(interval_sec or 1.0))

        # thread control and where we are in the rotation
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._index = 0

    def activate(self, index: int) -> None:
        """
        Put one page on screen and hide the rest

        @param index: int Which page to show, wrapped into range
        @return None
        """

        # nothing to activate
        if not self.pages:
            return

        # flip every layer's visibility to match
        self._index = index % len(self.pages)
        for position, page in enumerate(self.pages):
            visible = position == self._index
            for layer in page.get("layers", []):
                if isinstance(layer, Layer):
                    layer.set_visible(visible)
        logger.debug("page: %s", self.pages[self._index].get("name"))

    def start(self) -> None:
        """
        Begin rotating

        @return None
        """

        # nothing to rotate, or already going
        if not self.pages or (self._thread and self._thread.is_alive()):
            return

        # off it goes
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="page-cycler",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """
        Stop rotating

        @return None
        """

        # signal it and wait briefly
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _loop(self) -> None:
        """
        Advance to the next page on each interval

        @return None
        """

        # wait returns true when we were told to stop, so this exits cleanly
        while not self._stop.wait(self.interval):
            self.activate(self._index + 1)
