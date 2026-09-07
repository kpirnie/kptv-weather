#!/usr/bin/env python3
"""
Seven Day Layer

One full width row per day, scrolling vertically past the window: icon, day,
high and low against a shared range bar, and the secondary readings. The
strip is rendered once when the forecast changes and each frame is a crop of
it, so the motion costs a copy rather than a repaint.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Callable, Optional

from PIL import Image, ImageDraw

from .. import draw, icons, theme
from ..core.layer import Layer

# the small readings printed down the right of each row
ROWS = (
    ("precip_display", "Precip"),
    ("humidity_display", "Humid"),
    ("wind_display", "Wind"),
    ("uv_display", "UV"),
)

# how long the strip sits still at each end of its travel
HOLD_SEC = 2.5


class DailyLayer(Layer):
    """
    The seven day forecast page
    """

    # it scrolls, so the compositor pastes it every frame
    per_frame = True

    def __init__(self, x: int, y: int, w: int, h: int, get_days: Callable,
                 min_interval: float = 1 / 30.0, scale: float = 1.0,
                 px_per_sec: int = 60, base_duration: float = 14.0):
        """
        Build the page

        @param x: int Left edge within the frame
        @param y: int Top edge within the frame
        @param w: int Surface width
        @param h: int Surface height
        @param get_days: Callable Returns the daily series
        @param min_interval: float Shortest gap between redraws
        @param scale: float The output scale factor
        @param px_per_sec: int How fast the strip travels
        @param base_duration: float The hold used when nothing has to scroll
        """

        # the surface and the data source
        super().__init__(x, y, w, h, min_interval, scale)
        self.get_days = get_days
        self.base_duration = max(1.0, float(base_duration))

        # a whole number of pixels per frame, since the crop can only land on
        # one, and a fractional step reads as judder
        self.px_per_sec = max(1, int(px_per_sec))
        self._step = max(1.0, self.px_per_sec * self.scale)

        # the rendered strip, its cache key, and where we are in it
        self._strip: Optional[Image.Image] = None
        self._last: Optional[tuple] = None
        self._travel = 0
        self._offset = -1
        self._shown_at = 0.0

    def set_visible(self, visible: bool) -> None:
        """
        Show or hide the layer, restarting the scroll when it comes back

        @param visible: bool Whether the layer should be composited
        @return None
        """

        # every time the page comes up it starts from the top again
        was = self.visible
        super().set_visible(visible)
        if self.visible and not was:
            self._offset = -1

    def duration(self) -> float:
        """
        How long the page needs to hold the screen

        @return float: The hold in seconds
        """

        # build the strip if we have not yet, so the travel is known
        self._build()

        # nothing to travel means the page keeps the configured hold
        if self._travel <= 0:
            return self.base_duration
        return HOLD_SEC * 2.0 + (self._travel / self._step)

    def tick(self, now: float) -> bool:
        """
        Advance the scroll and repaint the window

        @param now: float Current wall clock time
        @return bool: True when the surface changed
        """

        # hidden pages cost nothing
        if not self.visible:
            return False

        # rebuild whenever the forecast changes
        self._build()
        if self._strip is None:
            return False

        # the first frame of a showing starts the clock
        if self._offset < 0:
            self._shown_at = now
            self._offset = 0
            return self._paste(0)

        # sit still at the top, travel, then sit still at the bottom
        elapsed = max(0.0, now - self._shown_at)
        if elapsed <= HOLD_SEC or self._travel <= 0:
            offset = 0
        else:
            offset = int(round((elapsed - HOLD_SEC) * self._step))
            offset = min(offset, self._travel)

        # only the frames that actually move have to be repainted
        if offset == self._offset:
            return False
        return self._paste(offset)

    def _paste(self, offset: int) -> bool:
        """
        Copy one window of the strip onto the surface

        @param offset: int How far down the strip the window sits
        @return bool: True, the surface changed
        """

        # a straight copy, the strip already carries its own transparency
        width, height = self.surface.size
        self._offset = offset
        self.surface.paste(self._strip.crop((0, offset, width,
                                             offset + height)), (0, 0))
        return True

    def _build(self) -> None:
        """
        Render the whole strip when the forecast changes

        @return None
        """

        # the whole strip as one comparable key
        days = list(self.get_days() or [])[:7]
        key = tuple((d.get("name"), d.get("high"), d.get("low"), d.get("icon"),
                     d.get("precip_display")) for d in days)
        if self._strip is not None and key == self._last:
            return
        self._last = key
        self._offset = -1

        # nothing to show, so the window carries the notice on its own
        width, height = self.surface.size
        if not days:
            strip = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            pen = ImageDraw.Draw(strip)
            draw.card(strip, (0, 0, width, height), self.scale)
            face = theme.font("medium", self.s(30, 12))
            draw.text(pen, (width // 2, height // 2), "Forecast unavailable",
                      face, theme.TEXT_DIM, anchor="mm")
            self._strip = strip
            self._travel = 0
            return

        # the shared temperature range every row's bar is drawn against
        highs = [d.get("high") for d in days if d.get("high") is not None]
        lows = [d.get("low") for d in days if d.get("low") is not None]
        span_low = min(lows) if lows else 0.0
        span_high = max(highs) if highs else 1.0
        if span_high - span_low < 1.0:
            span_high = span_low + 1.0

        # tall enough for every row, and never shorter than the window
        row_h = self.s(150, 60)
        gap = self.s(16, 4)
        content_h = len(days) * row_h + (len(days) - 1) * gap
        strip = Image.new("RGBA", (width, max(height, content_h)),
                          (0, 0, 0, 0))
        pen = ImageDraw.Draw(strip)

        # stack the rows down it
        for index, day in enumerate(days):
            top = index * (row_h + gap)
            self._draw_row(strip, pen, day, top, width, row_h, span_low,
                           span_high, index == 0)

        # keep it, along with how far it has to travel
        self._strip = strip
        self._travel = max(0, strip.size[1] - height)

    def _draw_row(self, strip: Image.Image, pen: ImageDraw.ImageDraw,
                  day: dict, top: int, width: int, row_h: int,
                  span_low: float, span_high: float, today: bool) -> None:
        """
        Draw one day's row

        @param strip: Image The strip being painted
        @param pen: ImageDraw The drawing context
        @param day: dict The day's data
        @param top: int The row's top edge within the strip
        @param width: int The row width
        @param row_h: int The row height
        @param span_low: float The coldest low across the whole strip
        @param span_high: float The warmest high across the whole strip
        @param today: bool Whether this is today's row
        @return None
        """

        # the row body, with today picked out in the warm accent
        bottom = top + row_h
        draw.card(strip, (0, top, width, bottom), self.scale,
                  accent=theme.HIGHLIGHT if today else theme.ACCENT_DIM)

        # the icon down the left
        pad = self.s(20, 6)
        icon_size = min(self.s(96, 24), row_h - pad * 2)
        art = icons.render(str(day.get("icon") or "cloudy"), icon_size, 0)
        strip.paste(art, (pad, top + (row_h - icon_size) // 2), art)

        # the day and its date beside it
        name_x = pad + icon_size + self.s(24, 8)
        name_w = self.s(250, 60)
        center = top + row_h // 2
        name_face = draw.fit_face(pen, str(day.get("name") or ""), "black",
                                  self.s(34, 12), name_w)
        draw.text(pen, (name_x, center - self.s(16)),
                  str(day.get("name") or ""), name_face,
                  theme.HIGHLIGHT if today else theme.TEXT, anchor="lm")
        date_face = theme.font("medium", self.s(20, 9))
        draw.text(pen, (name_x, center + self.s(18)),
                  str(day.get("date") or ""), date_face, theme.TEXT_FAINT,
                  anchor="lm")

        # the readings down the right, two to a column
        stats_w = self.s(400, 120)
        stats_x = width - pad - stats_w
        self._draw_stats(pen, day, stats_x, stats_w, top, row_h)

        # and the temperatures over the shared range bar in between
        bar_left = name_x + name_w + self.s(24, 8)
        bar_right = stats_x - self.s(24, 8)
        if bar_right > bar_left:
            self._draw_range(pen, day, bar_left, bar_right, center, span_low,
                             span_high)

    def _draw_stats(self, pen: ImageDraw.ImageDraw, day: dict, left: int,
                    stats_w: int, top: int, row_h: int) -> None:
        """
        Draw the small readings block

        @param pen: ImageDraw The drawing context
        @param day: dict The day's data
        @param left: int The block's left edge
        @param stats_w: int The block width
        @param top: int The row's top edge
        @param row_h: int The row height
        @return None
        """

        # two columns, two rows apiece
        column_w = stats_w // 2
        label_face = theme.font("semibold", self.s(17, 8))
        value_face = theme.font("bold", self.s(24, 10))
        for index, (field, label) in enumerate(ROWS):

            # where this pair sits in the block
            x = left + (index % 2) * column_w
            y = top + row_h // 2 - self.s(26) + (index // 2) * self.s(52)

            # the caption and the reading under it
            draw.text(pen, (x, y), label.upper(), label_face, theme.TEXT_FAINT,
                      anchor="lm")
            draw.text(pen, (x, y + self.s(26)), str(day.get(field) or "--"),
                      value_face, theme.TEXT_DIM, anchor="lm")

    def _draw_range(self, pen: ImageDraw.ImageDraw, day: dict, left: int,
                    right: int, center: int, span_low: float,
                    span_high: float) -> None:
        """
        Draw this day's slice of the shared temperature range

        @param pen: ImageDraw The drawing context
        @param day: dict The day's data
        @param left: int The bar's left edge
        @param right: int The bar's right edge
        @param center: int The row's centre line
        @param span_low: float The coldest low across the whole strip
        @param span_high: float The warmest high across the whole strip
        @return None
        """

        # the low and the high sit either side of the track
        low_face = theme.font("bold", self.s(30, 12))
        high_face = theme.font("black", self.s(38, 14))
        low = "--\u00b0" if day.get("low") is None else \
            f"{int(round(day['low']))}\u00b0"
        high = "--\u00b0" if day.get("high") is None else \
            f"{int(round(day['high']))}\u00b0"
        draw.text(pen, (left, center), low, low_face,
                  theme.temp_color(day.get("low_f")), anchor="lm")
        draw.text(pen, (right, center), high, high_face,
                  theme.temp_color(day.get("high_f")), anchor="rm")

        # the track itself, inset past both readings
        track_left = left + self.s(72, 24)
        track_right = right - self.s(84, 28)
        if track_right <= track_left:
            return
        thickness = max(4, self.s(10))
        pen.rounded_rectangle(
            [track_left, center - thickness // 2, track_right,
             center + thickness // 2],
            radius=thickness // 2,
            fill=theme.with_alpha(theme.PANEL_LINE, 180)
        )

        # nothing to fill in
        high_value = day.get("high")
        low_value = day.get("low")
        if high_value is None or low_value is None:
            return

        # map this day's range onto the shared track
        span = span_high - span_low
        start = track_left + (track_right - track_left) * \
            ((low_value - span_low) / span)
        end = track_left + (track_right - track_left) * \
            ((high_value - span_low) / span)
        pen.rounded_rectangle(
            [start, center - thickness // 2, max(start + thickness, end),
             center + thickness // 2],
            radius=thickness // 2,
            fill=theme.temp_color(day.get("high_f"))
        )
        