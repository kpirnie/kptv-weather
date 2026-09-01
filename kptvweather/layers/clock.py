#!/usr/bin/env python3
"""
Clock Layer

The local time and date in the fourth header column. Redraws once a second,
and only when the printed string actually changes.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Optional

from PIL import ImageDraw

from .. import draw, theme
from ..core.layer import Layer
from ..utils import now_local


class ClockLayer(Layer):
    """
    Local time and date
    """

    def __init__(self, x: int, y: int, w: int, h: int,
                 min_interval: float = 1.0, scale: float = 1.0):
        """
        Build the clock

        @param x: int Left edge within the frame
        @param y: int Top edge within the frame
        @param w: int Surface width
        @param h: int Surface height
        @param min_interval: float Shortest gap between redraws
        @param scale: float The output scale factor
        """

        # the surface, plus the last string we drew
        super().__init__(x, y, w, h, min_interval, scale)
        self._last: Optional[tuple] = None

    def tick(self, now: float) -> bool:
        """
        Redraw when the minute or the date rolls over

        @param now: float Current wall clock time
        @return bool: True when the surface changed
        """

        # build the two strings
        moment = now_local()
        clock = moment.strftime("%I:%M %p").lstrip("0")
        date = moment.strftime("%a, %b %d").replace(" 0", " ")

        # nothing to do when neither has moved
        key = (clock, date)
        if key == self._last:
            return False
        self._last = key

        # draw them right aligned against the column edge
        self.clear()
        pen = ImageDraw.Draw(self.surface)
        width, height = self.surface.size

        # the time and the date, centred as a pair on the band's centre line
        center = height // 2
        time_face = draw.fit_face(pen, clock, "black", self.s(46, 14), width)
        time_size = getattr(time_face, "size", self.s(46, 14))
        date_face = draw.fit_face(pen, date, "medium", self.s(26, 10), width)
        date_size = getattr(date_face, "size", self.s(26, 10))
        gap = self.s(8, 2)

        # the time
        draw.text(pen, (width, center - (gap + date_size) // 2), clock,
                  time_face, theme.TEXT, anchor="rm")

        # and the date under it
        draw.text(pen, (width, center + (gap + time_size) // 2), date,
                  date_face, theme.TEXT_DIM, anchor="rm")
        return True