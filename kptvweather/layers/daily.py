#!/usr/bin/env python3
"""
Seven Day Layer

One card per day: icon, high and low against a shared range bar, and the
secondary readings underneath.

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

# the small rows printed under each card's temperatures
ROWS = (
    ("precip_display", "Precip"),
    ("humidity_display", "Humid"),
    ("wind_display", "Wind"),
    ("uv_display", "UV"),
)


class DailyLayer(Layer):
    """
    The seven day forecast page
    """

    def __init__(self, x: int, y: int, w: int, h: int, get_days: Callable,
                 min_interval: float = 30.0, scale: float = 1.0):
        """
        Build the page

        @param x: int Left edge within the frame
        @param y: int Top edge within the frame
        @param w: int Surface width
        @param h: int Surface height
        @param get_days: Callable Returns the daily series
        @param min_interval: float Shortest gap between redraws
        @param scale: float The output scale factor
        """

        # the surface, the data source, and the last state we drew
        super().__init__(x, y, w, h, min_interval, scale)
        self.get_days = get_days
        self._last: Optional[tuple] = None

    def tick(self, now: float) -> bool:
        """
        Redraw when the forecast changes

        @param now: float Current wall clock time
        @return bool: True when the surface changed
        """

        # the whole strip as one comparable key
        days = list(self.get_days() or [])[:7]
        key = tuple((d.get("name"), d.get("high"), d.get("low"), d.get("icon"),
                     d.get("precip_display")) for d in days)
        if key == self._last:
            return False
        self._last = key

        # start clean
        self.clear()
        pen = ImageDraw.Draw(self.surface)
        width, height = self.surface.size

        # nothing to show
        if not days:
            draw.panel(pen, (0, 0, width, height))
            face = theme.font("medium", self.s(30, 12))
            draw.text(pen, (width // 2, height // 2), "Forecast unavailable",
                      face, theme.TEXT_DIM, anchor="mm")
            return True

        # the shared temperature range every card's bar is drawn against
        highs = [d.get("high") for d in days if d.get("high") is not None]
        lows = [d.get("low") for d in days if d.get("low") is not None]
        span_low = min(lows) if lows else 0.0
        span_high = max(highs) if highs else 1.0
        if span_high - span_low < 1.0:
            span_high = span_low + 1.0

        # lay the cards out across the page
        gap = self.s(14, 4)
        card_w = (width - gap * (len(days) - 1)) // len(days)
        for index, day in enumerate(days):
            left = index * (card_w + gap)
            self._draw_card(pen, day, left, card_w, height, span_low, span_high,
                            index == 0)
        return True

    def _draw_card(self, pen: ImageDraw.ImageDraw, day: dict, left: int,
                   card_w: int, height: int, span_low: float, span_high: float,
                   today: bool) -> None:
        """
        Draw one day's card

        @param pen: ImageDraw The drawing context
        @param day: dict The day's data
        @param left: int The card's left edge
        @param card_w: int The card width
        @param height: int The card height
        @param span_low: float The coldest low across the whole strip
        @param span_high: float The warmest high across the whole strip
        @param today: bool Whether this is today's card
        @return None
        """

        # the card body, with today picked out
        right = left + card_w
        draw.panel(pen, (left, 0, right, height),
                   fill=theme.PANEL if today else theme.PANEL_ALT)
        rule = max(2, self.s(4))
        draw.accent_bar(pen, (left, 0, right, rule),
                        color=theme.ACCENT if today else theme.ACCENT_DIM)

        # the day name and date
        pad = self.s(12, 4)
        name_face = draw.fit_face(pen, str(day.get("name") or ""), "black",
                                  self.s(26, 10), card_w - pad * 2)
        draw.text(pen, (left + card_w // 2, rule + self.s(12)),
                  str(day.get("name") or ""), name_face, theme.TEXT, anchor="ma")
        date_face = theme.font("medium", self.s(18, 8))
        draw.text(pen, (left + card_w // 2, rule + self.s(44)),
                  str(day.get("date") or ""), date_face, theme.TEXT_FAINT,
                  anchor="ma")

        # the icon
        icon_size = min(self.s(88, 20), card_w - pad * 2)
        art = icons.render(str(day.get("icon") or "cloudy"), icon_size, 0)
        self.surface.paste(art, (left + (card_w - icon_size) // 2, self.s(78)),
                           art)

        # the high and low
        temps_y = self.s(78) + icon_size + self.s(14)
        high_face = theme.font("black", self.s(34, 12))
        low_face = theme.font("semibold", self.s(26, 10))
        high = "--\u00b0" if day.get("high") is None else f"{int(round(day['high']))}\u00b0"
        low = "--\u00b0" if day.get("low") is None else f"{int(round(day['low']))}\u00b0"
        draw.text(pen, (left + card_w // 2, temps_y), high, high_face,
                  theme.temp_color(day.get("high_f")), anchor="ma")
        draw.text(pen, (left + card_w // 2, temps_y + self.s(40)), low, low_face,
                  theme.temp_color(day.get("low_f")), anchor="ma")

        # the shared range bar
        bar_y = temps_y + self.s(78)
        self._draw_range(pen, day, left + pad, right - pad, bar_y, span_low,
                         span_high)

        # and the small rows underneath
        row_y = bar_y + self.s(28)
        row_face = theme.font("medium", self.s(18, 8))
        for field, label in ROWS:
            if row_y > height - self.s(18):
                break
            draw.text(pen, (left + pad, row_y), label, row_face, theme.TEXT_FAINT)
            draw.text(pen, (right - pad, row_y), str(day.get(field) or "--"),
                      row_face, theme.TEXT_DIM, anchor="ra")
            row_y += self.s(26)

    def _draw_range(self, pen: ImageDraw.ImageDraw, day: dict, left: int,
                    right: int, y: int, span_low: float,
                    span_high: float) -> None:
        """
        Draw this day's slice of the shared temperature range

        @param pen: ImageDraw The drawing context
        @param day: dict The day's data
        @param left: int The bar's left edge
        @param right: int The bar's right edge
        @param y: int The bar's vertical position
        @param span_low: float The coldest low across the whole strip
        @param span_high: float The warmest high across the whole strip
        @return None
        """

        # the track
        thickness = max(4, self.s(8))
        pen.rectangle([left, y, right, y + thickness],
                      fill=theme.with_alpha(theme.PANEL_LINE, 180))

        # nothing to fill in
        high = day.get("high")
        low = day.get("low")
        if high is None or low is None:
            return

        # map this day's range onto the shared track
        span = span_high - span_low
        start = left + (right - left) * ((low - span_low) / span)
        end = left + (right - left) * ((high - span_low) / span)
        pen.rectangle([start, y, max(start + thickness, end), y + thickness],
                      fill=theme.temp_color(day.get("high_f")))
