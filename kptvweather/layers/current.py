#!/usr/bin/env python3
"""
Current Conditions Layer

The opening page: an oversized temperature, the condition icon, today's high
and low, sun times, and a grid of the secondary readings.

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

# the tiles across the bottom, as caption and data key
TILES = (
    ("Feels Like", "feels_display"),
    ("Humidity", "humidity_display"),
    ("Wind", "wind_display"),
    ("Dew Point", "dew_display"),
    ("Pressure", "pressure_display"),
    ("Visibility", "visibility_display"),
    ("Cloud Cover", "cloud_display"),
    ("UV Index", "uv_display"),
)


class CurrentLayer(Layer):
    """
    The current conditions page
    """

    def __init__(self, x: int, y: int, w: int, h: int, get_data: Callable,
                 min_interval: float = 5.0, scale: float = 1.0):
        """
        Build the page

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
        Redraw when any printed value changes

        @param now: float Current wall clock time
        @return bool: True when the surface changed
        """

        # everything this page prints, as one comparable key
        data = self.get_data() or {}
        key = tuple([
            data.get("temp_display"), data.get("summary"), data.get("icon"),
            data.get("high_display"), data.get("low_display"),
            data.get("sunrise"), data.get("sunset"),
        ] + [data.get(field) for _, field in TILES])
        if key == self._last:
            return False
        self._last = key

        # start clean
        self.clear()
        pen = ImageDraw.Draw(self.surface)
        width, height = self.surface.size

        # the page splits into a headline block and a tile grid
        tile_rows = 2
        tile_h = self.s(112, 40)
        grid_h = tile_h * tile_rows + self.s(16) * (tile_rows - 1)
        headline_h = max(self.s(160), height - grid_h - self.s(28))

        # the headline panel
        draw.panel(pen, (0, 0, width, headline_h))
        draw.accent_bar(pen, (0, 0, width, max(2, self.s(4))))

        # the icon
        pad = self.s(36, 10)
        icon_size = min(self.s(230, 40), headline_h - pad * 2)
        art = icons.render(str(data.get("icon") or "cloudy"), icon_size,
                           int(now * 8) % 24)
        self.surface.paste(art, (pad, (headline_h - icon_size) // 2), art)

        # the temperature, sized against whatever room is left
        cursor = pad + icon_size + self.s(28)
        temp = str(data.get("temp_display") or "--\u00b0")
        color = theme.temp_color(data.get("temp_f"))
        temp_face = draw.fit_face(pen, temp, "black", int(headline_h * 0.62),
                                  int(width * 0.40))
        draw.text(pen, (cursor, headline_h // 2 - self.s(10)), temp, temp_face,
                  color, anchor="lm")

        # the condition phrase and the rest of the headline detail
        detail_x = cursor + draw.measure(pen, temp, temp_face)[0] + self.s(36)
        self._draw_detail(pen, data, detail_x, width - pad, headline_h)

        # and the tile grid underneath
        self._draw_tiles(pen, data, width, headline_h + self.s(28), tile_h)
        return True

    def _draw_detail(self, pen: ImageDraw.ImageDraw, data: dict, left: int,
                     right: int, headline_h: int) -> None:
        """
        Draw the condition phrase, the high and low, and the sun times

        @param pen: ImageDraw The drawing context
        @param data: dict The current conditions
        @param left: int Where the block starts
        @param right: int Where the block must end
        @param headline_h: int The headline panel height
        @return None
        """

        # nothing would fit
        available = right - left
        if available < self.s(120):
            return

        # the condition phrase
        summary = str(data.get("summary") or "")
        face = draw.fit_face(pen, summary, "bold", self.s(40, 12), available)
        draw.text(pen, (left, self.s(44)), summary, face, theme.TEXT)

        # today's range
        high = str(data.get("high_display") or "--\u00b0")
        low = str(data.get("low_display") or "--\u00b0")
        range_face = theme.font("semibold", self.s(30, 11))
        draw.text(pen, (left, self.s(102)), f"High {high}    Low {low}",
                  range_face, theme.TEXT_DIM)

        # and the sun times
        sun_face = theme.font("medium", self.s(24, 10))
        sunrise = str(data.get("sunrise") or "--")
        sunset = str(data.get("sunset") or "--")
        draw.text(pen, (left, self.s(150)),
                  f"Sunrise {sunrise}    Sunset {sunset}", sun_face,
                  theme.TEXT_FAINT)

    def _draw_tiles(self, pen: ImageDraw.ImageDraw, data: dict, width: int,
                    top: int, tile_h: int) -> None:
        """
        Draw the grid of secondary readings

        @param pen: ImageDraw The drawing context
        @param data: dict The current conditions
        @param width: int The surface width
        @param top: int Where the grid starts
        @param tile_h: int The height of one tile
        @return None
        """

        # four across, two down
        columns = 4
        gap = self.s(16, 4)
        tile_w = (width - gap * (columns - 1)) // columns

        # lay them out in order
        for index, (label, field) in enumerate(TILES):
            row, column = divmod(index, columns)
            left = column * (tile_w + gap)
            box_top = top + row * (tile_h + gap)
            draw.stat_tile(
                pen,
                (left, box_top, left + tile_w, box_top + tile_h),
                label, str(data.get(field) or "--"), self.scale,
            )
