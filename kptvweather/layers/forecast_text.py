#!/usr/bin/env python3
"""
Extended Forecast Layer

Narrative panels for the next couple of periods, each with a stat grid
beside the prose.

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

# the stat grid beside each narrative, as caption and data key
STATS = (
    ("High", "high"),
    ("Low", "low"),
    ("Wind", "wind"),
    ("Gusts", "gust"),
    ("Humidity", "humidity"),
    ("Dew Point", "dew"),
    ("Cloud", "cloud"),
    ("UV", "uv"),
)


class ForecastTextLayer(Layer):
    """
    The extended forecast page
    """

    def __init__(self, x: int, y: int, w: int, h: int, get_periods: Callable,
                 min_interval: float = 30.0, scale: float = 1.0):
        """
        Build the page

        @param x: int Left edge within the frame
        @param y: int Top edge within the frame
        @param w: int Surface width
        @param h: int Surface height
        @param get_periods: Callable Returns the forecast periods
        @param min_interval: float Shortest gap between redraws
        @param scale: float The output scale factor
        """

        # the surface, the data source, and the last state we drew
        super().__init__(x, y, w, h, min_interval, scale)
        self.get_periods = get_periods
        self._last: Optional[tuple] = None

    def tick(self, now: float) -> bool:
        """
        Redraw when the narrative changes

        @param now: float Current wall clock time
        @return bool: True when the surface changed
        """

        # the prose is what actually moves here
        periods = list(self.get_periods() or [])[:2]
        key = tuple((p.get("name"), p.get("detailed")) for p in periods)
        if key == self._last:
            return False
        self._last = key

        # start clean
        self.clear()
        pen = ImageDraw.Draw(self.surface)
        width, height = self.surface.size

        # nothing to show
        if not periods:
            draw.panel(pen, (0, 0, width, height))
            face = theme.font("medium", self.s(30, 12))
            draw.text(pen, (width // 2, height // 2), "Forecast unavailable",
                      face, theme.TEXT_DIM, anchor="mm")
            return True

        # stack the panels down the page
        gap = self.s(20, 6)
        panel_h = (height - gap * (len(periods) - 1)) // len(periods)
        for index, period in enumerate(periods):
            top = index * (panel_h + gap)
            self._draw_period(pen, period, top, width, panel_h)
        return True

    def _draw_period(self, pen: ImageDraw.ImageDraw, period: dict, top: int,
                     width: int, panel_h: int) -> None:
        """
        Draw one narrative panel

        @param pen: ImageDraw The drawing context
        @param period: dict The period's data
        @param top: int The panel's top edge
        @param width: int The surface width
        @param panel_h: int The panel height
        @return None
        """

        # the panel body
        bottom = top + panel_h
        draw.panel(pen, (0, top, width, bottom))
        rule = max(2, self.s(4))
        draw.accent_bar(pen, (0, top, width, top + rule))

        # the icon and the period name
        pad = self.s(28, 8)
        icon_size = min(self.s(96, 24), panel_h - pad * 2)
        art = icons.render(str(period.get("icon") or "cloudy"), icon_size, 0)
        self.surface.paste(art, (pad, top + pad), art)

        cursor = pad + icon_size + self.s(24)
        name_face = theme.font("black", self.s(34, 12))
        draw.text(pen, (cursor, top + pad), str(period.get("name") or ""),
                  name_face, theme.TEXT)

        # the prose, wrapped into the left two thirds
        prose_width = int(width * 0.60) - cursor
        body_face = theme.font("regular", self.s(24, 10))
        lines = self._wrap(pen, str(period.get("detailed") or ""), body_face,
                           max(self.s(120), prose_width))
        line_y = top + pad + self.s(48)
        step = self.s(32, 12)
        for line in lines:
            if line_y + step > bottom - self.s(12):
                break
            draw.text(pen, (cursor, line_y), line, body_face, theme.TEXT_DIM)
            line_y += step

        # and the stat grid on the right
        self._draw_stats(pen, period, int(width * 0.62), width - pad,
                         top + pad, bottom - pad)

    def _draw_stats(self, pen: ImageDraw.ImageDraw, period: dict, left: int,
                    right: int, top: int, bottom: int) -> None:
        """
        Draw the grid of figures beside the narrative

        @param pen: ImageDraw The drawing context
        @param period: dict The period's data
        @param left: int The grid's left edge
        @param right: int The grid's right edge
        @param top: int The grid's top edge
        @param bottom: int The grid's bottom edge
        @return None
        """

        # two columns, four rows
        columns = 2
        rows = 4
        gap = self.s(10, 3)
        cell_w = (right - left - gap * (columns - 1)) // columns
        cell_h = (bottom - top - gap * (rows - 1)) // rows
        if cell_w < self.s(60) or cell_h < self.s(30):
            return

        # lay them out
        for index, (label, field) in enumerate(STATS):
            row, column = divmod(index, columns)
            cell_left = left + column * (cell_w + gap)
            cell_top = top + row * (cell_h + gap)
            draw.stat_tile(
                pen,
                (cell_left, cell_top, cell_left + cell_w, cell_top + cell_h),
                label, str(period.get(field) or "--"), self.scale,
            )

    def _wrap(self, pen: ImageDraw.ImageDraw, text: str, face, width: int) -> list:
        """
        Wrap a paragraph to a pixel width

        @param pen: ImageDraw The drawing context
        @param text: str The paragraph
        @param face: FreeTypeFont The face it will be drawn in
        @param width: int The width to wrap inside
        @return list: The wrapped lines
        """

        # nothing to wrap
        words = str(text or "").split()
        if not words:
            return []

        # greedily fill each line
        lines: list = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if draw.measure(pen, candidate, face)[0] <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines
