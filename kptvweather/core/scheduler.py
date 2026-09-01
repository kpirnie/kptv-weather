#!/usr/bin/env python3
"""
Scheduler Module

Wakes each layer on its own cadence and presents a frame either when
something actually changed or when the constant frame rate deadline arrives,
whichever comes first.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import heapq
import logging
import time
from typing import Callable, List, Optional

from .compositor import Compositor
from .layer import Layer

logger = logging.getLogger(__name__)


class Scheduler:
    """
    Drives the render loop
    """

    def __init__(self, layers: List[Layer], cfr_hz: int = 30):
        """
        Build the scheduler and seed every layer's first wake

        @param layers: list The layers to drive
        @param cfr_hz: int Output frame rate the encoder expects
        """

        # sort once, the compositor relies on the ordering
        self.layers = sorted(layers, key=lambda item: getattr(item, "z", 0))
        self.cfr = max(1, int(cfr_hz or 30))
        self.interval = 1.0 / self.cfr

        # every layer wants a tick straight away
        now = time.time()
        self.heap: list[tuple[float, int]] = []
        for index, _ in enumerate(self.layers):
            heapq.heappush(self.heap, (now, index))
        self.next_frame = now + self.interval

    def run_forever(self, compositor: Compositor,
                    on_present: Callable,
                    should_stop: Optional[Callable[[], bool]] = None) -> None:
        """
        Run the render loop until told to stop

        @param compositor: Compositor Builds the finished frames
        @param on_present: Callable Receives every presented frame
        @param should_stop: Callable|None Polled to end the loop early
        @return None
        """

        # go until somebody tells us not to
        while True:

            # bail out cleanly when asked
            if should_stop and should_stop():
                break

            # sleep until either the next layer wake or the next frame deadline
            now = time.time()
            wake_at = min(self.heap[0][0], self.next_frame) if self.heap \
                else self.next_frame
            if now < wake_at:
                time.sleep(max(0.0, wake_at - now))
                now = time.time()

            # tick every layer that is due, noting whether any of them moved
            dirty = False
            while self.heap and self.heap[0][0] <= now:
                _, index = heapq.heappop(self.heap)
                layer = self.layers[index]

                # never let one bad layer take the whole channel down
                try:
                    if layer.tick(now) and layer.visible:
                        dirty = True
                except Exception:
                    logger.exception("layer %s failed to tick",
                                     layer.__class__.__name__)

                # and put it back for its next turn
                heapq.heappush(self.heap, (now + layer.min_interval, index))

            # recompose only when something actually changed, but always feed
            # the encoder on schedule so the stream stays constant rate
            if now >= self.next_frame:
                if dirty:
                    compositor.compose(self.layers)
                    frame = compositor.present()
                else:
                    frame = compositor.front
                on_present(frame)

                # keep the cadence even if we ran long
                self.next_frame = max(now + self.interval * 0.5,
                                      self.next_frame + self.interval)