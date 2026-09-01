#!/usr/bin/env python3
"""
RSS Module

Fetches headline titles from the configured feeds for the ticker. Standard
library only: these are simple feeds and nothing here justifies a parser
dependency.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class RssTitleCache:
    """
    Fetches and caches headline titles from a set of feeds
    """

    def __init__(self, urls: list, refresh_sec: int = 300, max_items: int = 3,
                 user_agent: str = "kptv-weather/1.0"):
        """
        Build the cache

        @param urls: list The feed URLs to poll
        @param refresh_sec: int How often to re-poll them
        @param max_items: int How many titles to take from each feed
        @param user_agent: str Sent with every request
        """

        # what to fetch and how often
        self.urls = list(urls or [])
        self.refresh_sec = max(60, int(refresh_sec or 300))
        self.max_items = max(1, int(max_items or 3))
        self.user_agent = user_agent

        # the cached titles and when we last went out for them
        self._titles: list = []
        self._last = 0.0

    def titles(self) -> list:
        """
        The current headline titles

        @return list: Deduplicated titles across every configured feed
        """

        # nothing configured
        if not self.urls:
            return []

        # serve the cache while it is fresh
        now = time.time()
        if self._last and now - self._last < self.refresh_sec:
            return list(self._titles)

        # collect from every feed
        collected: list = []
        for url in self.urls:
            payload = self._get(url)
            if payload:
                collected.extend(self._titles_from(payload))

        # drop the duplicates that syndicated feeds always produce
        seen: set = set()
        unique: list = []
        for title in collected:
            key = title.lower()
            if key not in seen:
                seen.add(key)
                unique.append(title)

        # stash and hand back
        self._titles = unique
        self._last = now
        return list(unique)

    def _get(self, url: str) -> Optional[bytes]:
        """
        Fetch one feed

        @param url: str The feed URL
        @return bytes|None: The response body, or None on any failure
        """

        # a feed that will not load simply contributes nothing
        try:
            request = Request(url, headers={"User-Agent": self.user_agent})
            with urlopen(request, timeout=10) as resp:
                return resp.read()
        except (URLError, HTTPError, TimeoutError, ValueError, OSError) as exc:
            logger.warning("feed %s failed: %s", url, exc)
            return None

    def _titles_from(self, payload: bytes) -> list:
        """
        Pull the item titles out of a feed body

        @param payload: bytes The feed body
        @return list: The titles, capped at the configured maximum
        """

        # malformed xml is just an empty feed as far as we are concerned
        try:
            root = ET.fromstring(payload)
        except ET.ParseError:
            return []

        # rss puts them in items
        out: list = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            if title:
                out.append(title)
                if len(out) >= self.max_items:
                    return out

        # atom puts them in namespaced entries
        if not out:
            for entry in root.findall(".//{*}entry"):
                title = (entry.findtext("{*}title") or "").strip()
                if title:
                    out.append(title)
                    if len(out) >= self.max_items:
                        return out
        return out
