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

from typing import Callable, Optional

from PIL import ImageDraw

from .. import draw, theme
from ..core.layer import Layer
from ..utils import now_local


class ClockLayer(Layer):
    """
    Local time and date
    """

    def __init__(self, x: int, y: int, w: int, h: int,
                 min_interval: float = 1.0, scale: float = 1.0,
                 get_next: Optional[Callable] = None):
        """
        Build the clock

        @param x: int Left edge within the frame
        @param y: int Top edge within the frame
        @param w: int Surface width
        @param h: int Surface height
        @param min_interval: float Shortest gap between redraws
        @param scale: float The output scale factor
        @param get_next: Callable|None Returns the next page's title
        """

        # the surface, plus the last string we drew
        super().__init__(x, y, w, h, min_interval, scale)
        self.get_next = get_next
        self._last: Optional[tuple] = None

    def tick(self, now: float) -> bool:
        """
        Redraw when the minute, the date, or the next page rolls over

        @param now: float Current wall clock time
        @return bool: True when the surface changed
        """

        # build the strings
        moment = now_local()
        clock = moment.strftime("%I:%M %p").lstrip("0")
        date = moment.strftime("%a, %b %d").replace(" 0", " ")
        upcoming = ""
        if self.get_next is not None:
            upcoming = str(self.get_next() or "").strip()

        # nothing to do when none of them have moved
        key = (clock, date, upcoming)
        if key == self._last:
            return False
        self._last = key

        # draw them right aligned against the column edge
        self.clear()
        pen = ImageDraw.Draw(self.surface)
        width, height = self.surface.size

        # the faces, measured so the stack centres as one on the band
        time_face = draw.fit_face(pen, clock, "black", self.s(46, 14), width)
        time_size = getattr(time_face, "size", self.s(46, 14))
        date_face = draw.fit_face(pen, date, "medium", self.s(26, 10), width)
        date_size = getattr(date_face, "size", self.s(26, 10))
        gap = self.s(8, 2)

        # the next page line only takes room when there is one to print
        next_label = f"NEXT: {upcoming.upper()}" if upcoming else ""
        next_face = draw.fit_face(pen, next_label, "semibold", self.s(18, 8),
                                  width) if next_label else None
        next_size = getattr(next_face, "size", 0) if next_face else 0

        # stack them from the top of the centred block
        block = time_size + gap + date_size
        if next_face:
            block += gap + next_size
        cursor = (height - block) // 2

        # the time
        draw.text(pen, (width, cursor + time_size // 2), clock, time_face,
                  theme.TEXT, anchor="rm")
        cursor += time_size + gap

        # the date under it
        draw.text(pen, (width, cursor + date_size // 2), date, date_face,
                  theme.TEXT_DIM, anchor="rm")
        cursor += date_size + gap

        # and what is coming up next, smaller again
        if next_face:
            draw.text(pen, (width, cursor + next_size // 2), next_label,
                      next_face, theme.HIGHLIGHT, anchor="rm")
        return True
        