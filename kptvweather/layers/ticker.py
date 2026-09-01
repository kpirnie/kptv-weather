#!/usr/bin/env python3
"""
Ticker Layer

The scrolling strip along the bottom. Weather alerts take it over entirely
whenever any are active; the configured news feeds only get it when the
weather is quiet.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Callable

from PIL import Image, ImageDraw

from .. import draw, theme
from ..core.layer import Layer

# how much blank space separates the end of the text from its next repeat
GAP_FRACTION = 0.25


class TickerLayer(Layer):
    """
    The scrolling text strip
    """

    def __init__(self, x: int, y: int, w: int, h: int, get_text: Callable,
                 get_label: Callable, get_accent: Callable,
                 px_per_sec: int = 120, min_interval: float = 1 / 30.0,
                 scale: float = 1.0):
        """
        Build the ticker

        @param x: int Left edge within the frame
        @param y: int Top edge within the frame
        @param w: int Surface width
        @param h: int Surface height
        @param get_text: Callable Returns the string to scroll
        @param get_label: Callable Returns the category label
        @param get_accent: Callable Returns the accent colour to use
        @param px_per_sec: int Scroll speed
        @param min_interval: float Shortest gap between redraws
        @param scale: float The output scale factor
        """

        # the surface and its data sources
        super().__init__(x, y, w, h, min_interval, scale)
        self.get_text = get_text
        self.get_label = get_label
        self.get_accent = get_accent
        self.px_per_sec = max(1, int(px_per_sec))

        # the rendered text strip, its cache key, and where we are in it
        self._strip: Image.Image = None
        self._strip_key = None
        self._offset = 0.0
        self._last_tick = None

    def _label_width(self) -> int:
        """
        How much room the category badge takes

        @return int: The badge width in pixels
        """

        # a fixed proportion of the strip, floored so it never vanishes
        return max(self.s(120, 40), int(self.surface.size[0] * 0.11))

    def _build_strip(self, text: str, key) -> None:
        """
        Render the scrolling text once, so each frame is only a paste

        @param text: str The string to scroll
        @param key: mixed The cache key this strip was built for
        @return None
        """

        # measure it in the face we will draw it in
        height = self.surface.size[1]
        face = theme.font("medium", max(10, int(round(height * 0.46))))
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        text_width = draw.measure(probe, text, face)[0]

        # lay it out twice with a gap, so the scroll can loop seamlessly
        gap = max(self.s(80, 20), int(text_width * GAP_FRACTION))
        span = text_width + gap
        strip = Image.new("RGBA", (max(1, span * 2), height), (0, 0, 0, 0))
        pen = ImageDraw.Draw(strip)
        draw.text(pen, (0, height // 2), text, face, theme.TEXT, anchor="lm")
        draw.text(pen, (span, height // 2), text, face, theme.TEXT, anchor="lm")

        # keep it, along with the loop length
        self._strip = strip
        self._strip_key = key
        self._span = span

    def tick(self, now: float) -> bool:
        """
        Advance the scroll and repaint the strip

        @param now: float Current wall clock time
        @return bool: True, the ticker is always moving
        """

        # what we are scrolling and how it should be styled
        text = str(self.get_text() or "").strip() or "No active weather alerts"
        label = str(self.get_label() or "WEATHER").upper()
        accent = self.get_accent() or theme.ACCENT

        # rebuild the strip whenever the text changes
        key = (text, self.surface.size)
        if self._strip is None or key != self._strip_key:
            self._build_strip(text, key)
            self._offset = 0.0

        # advance by however long it has actually been since the last frame
        if self._last_tick is not None:
            elapsed = max(0.0, now - self._last_tick)
            self._offset = (self._offset + elapsed * self.px_per_sec * self.scale)
            if self._span > 0:
                self._offset %= self._span
        self._last_tick = now

        # start clean
        self.clear()
        pen = ImageDraw.Draw(self.surface)
        width, height = self.surface.size

        # the strip body and the badge that heads it
        draw.panel(pen, (0, 0, width, height), fill=theme.PANEL,
                   outline=theme.PANEL_LINE)
        badge_w = self._label_width()
        draw.panel(pen, (0, 0, badge_w, height), fill=accent, outline=None)
        badge_face = draw.fit_face(pen, label, "black",
                                   max(10, int(round(height * 0.40))),
                                   badge_w - self.s(16, 4))
        draw.text(pen, (badge_w // 2, height // 2), label, badge_face,
                  theme.TEXT, anchor="mm")

        # then the scrolling text, clipped to what is left
        window_w = max(1, width - badge_w - self.s(16, 4))
        left = int(self._offset)
        window = self._strip.crop((left, 0, left + window_w, height))
        self.surface.paste(window, (badge_w + self.s(16, 4), 0), window)
        return True
