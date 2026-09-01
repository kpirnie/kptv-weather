#!/usr/bin/env python3
"""
Header Current Layer

The current temperature and condition in the third header column, present on
every page so the headline number never leaves the screen.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Callable, Optional

from PIL import ImageDraw

from .. import draw, icons, theme
from ..core.layer import Layer


class HeaderCurrentLayer(Layer):
    """
    Current temperature, condition, and icon
    """

    def __init__(self, x: int, y: int, w: int, h: int, get_data: Callable,
                 min_interval: float = 5.0, scale: float = 1.0):
        """
        Build the header temperature block

        @param x: int Left edge within the frame
        @param y: int Top edge within the frame
        @param w: int Surface width
        @param h: int Surface height
        @param get_data: Callable Returns the current conditions dict
        @param min_interval: float Shortest gap between redraws
        @param scale: float The output scale factor
        """

        # the surface, the data source, and the last state we drew
        super().__init__(x, y, w, h, min_interval, scale)
        self.get_data = get_data
        self._last: Optional[tuple] = None

    def tick(self, now: float) -> bool:
        """
        Redraw when the temperature or condition changes

        @param now: float Current wall clock time
        @return bool: True when the surface changed
        """

        # what we would print
        data = self.get_data() or {}
        temp = str(data.get("temp_display") or "--\u00b0")
        summary = str(data.get("summary") or "")
        icon = str(data.get("icon") or "cloudy")

        # nothing to do when none of it moved
        key = (temp, summary, icon)
        if key == self._last:
            return False
        self._last = key

        # start clean
        self.clear()
        pen = ImageDraw.Draw(self.surface)
        width, height = self.surface.size

        # the icon on the left, on the band's centre line
        center = height // 2
        icon_size = self.s(72, 16)
        art = icons.render(icon, icon_size, 0)
        self.surface.paste(art, (0, center - icon_size // 2), art)

        # the temperature beside it, coloured by the ramp
        cursor = icon_size + self.s(14)
        available = max(self.s(60), width - cursor)
        color = theme.temp_color(data.get("temp_f"))
        temp_face = draw.fit_face(pen, temp, "black", self.s(58, 16), available)
        temp_size = getattr(temp_face, "size", self.s(58, 16))

        # with nothing under it, it takes the centre line on its own
        if not summary:
            draw.text(pen, (cursor, center), temp, temp_face, color,
                      anchor="lm")
            return True

        # otherwise the pair sits either side of it
        face = draw.fit_face(pen, summary, "medium", self.s(24, 9), available)
        summary_size = getattr(face, "size", self.s(24, 9))
        gap = self.s(8, 2)
        draw.text(pen, (cursor, center - (gap + summary_size) // 2), temp,
                  temp_face, color, anchor="lm")
        draw.text(pen, (cursor, center + (gap + temp_size) // 2), summary,
                  face, theme.TEXT_DIM, anchor="lm")
        return True