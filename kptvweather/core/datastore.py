#!/usr/bin/env python3
"""
Datastore Module

Runs the upstream fetch on a background thread and hands the render layers a
snapshot they can read without ever blocking on the network.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import logging
import threading
from typing import Callable, Dict

logger = logging.getLogger(__name__)


class DataStore:
    """
    Background refresher holding the most recent good snapshot
    """

    def __init__(self, fetcher: Callable[[], dict], interval_sec: float = 60.0):
        """
        Build the store

        @param fetcher: Callable Produces a fresh snapshot dict
        @param interval_sec: float How often to call the fetcher
        """

        # what to call and how often
        self.fetcher = fetcher
        self.interval = max(5.0, float(interval_sec))

        # the snapshot and the guard around it
        self._lock = threading.Lock()
        self._data: Dict = {}

        # thread control
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def read(self) -> Dict:
        """
        The most recent snapshot

        @return dict: Whatever the last successful fetch produced
        """

        # hand back the live dict, layers only ever read from it
        with self._lock:
            return self._data

    def start(self) -> None:
        """
        Fetch once inline, then keep refreshing in the background

        @return None
        """

        # already running
        if self._thread and self._thread.is_alive():
            return

        # do one pass up front so the first frame is not empty
        self._refresh()

        # then let the thread take over
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="datastore",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """
        Stop refreshing

        @return None
        """

        # signal it and wait briefly for it to unwind
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        """
        Refresh on the configured interval until stopped

        @return None
        """

        # wait returns true when we were told to stop, so this exits cleanly
        while not self._stop.wait(self.interval):
            self._refresh()

    def _refresh(self) -> None:
        """
        Run the fetcher and swap the snapshot in

        @return None
        """

        # a failed fetch keeps the previous snapshot rather than blanking out
        try:
            fresh = self.fetcher()
        except Exception:
            logger.exception("data refresh failed")
            return

        # only swap when we actually got something usable
        if isinstance(fresh, dict):
            with self._lock:
                self._data = fresh
