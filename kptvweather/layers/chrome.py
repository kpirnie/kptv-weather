#!/usr/bin/env python3
"""
Chrome Layer

The full-frame backdrop, the header band, the location and page title, and
the alert strip. One instance belongs to each page so the title can change
with it.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Callable, Optional

from PIL import Image, ImageDraw

from .. import draw, layout, theme
from ..core.layer import Layer


class ChromeLayer(Layer):
    """
    The persistent frame every page is drawn inside
    """

    def __init__(self, width: int, height: int, location_name: str,
                 page_title: str, get_alerts: Callable, channel_name: str = "",
                 scale: float = 1.0):
        """
        Build the chrome for one page

        @param width: int Frame width
        @param height: int Frame height
        @param location_name: str The station's location label
        @param page_title: str This page's title
        @param get_alerts: Callable Returns the active alert list
        @param channel_name: str The channel identity shown in the header
        @param scale: float The output scale factor
        """

        # the chrome always covers the whole frame
        super().__init__(0, 0, width, height, min_interval=2.0, scale=scale)

        # what it prints
        self.location_name = location_name or ""
        self.page_title = page_title or ""
        self.channel_name = channel_name or ""
        self.get_alerts = get_alerts

        # the last alert state we drew, so we only redraw when it changes
        self._last_alert_key: Optional[str] = None
        self._drawn = False

        # the logo, if one was dropped into the assets folder
        self._logo = self._load_logo()

    def _load_logo(self) -> Optional[Image.Image]:
        """
        Load the station logo when one is present

        @return Image|None: The logo scaled to the header, or None
        """

        # entirely optional, the header falls back to an accent bar
        path = theme.asset_root() / "logo.png"
        if not path.is_file():
            return None

        # scale it to the header band height
        try:
            with Image.open(path) as handle:
                art = handle.convert("RGBA")
            target = self.s(72, 8)
            ratio = target / max(1, art.height)
            return art.resize(
                (max(1, int(art.width * ratio)), target), Image.LANCZOS
            )
        except Exception:
            return None

    def tick(self, now: float) -> bool:
        """
        Redraw the chrome when the alert state changes

        @param now: float Current wall clock time
        @return bool: True when the surface changed
        """

        # the alert banner is the only part of this that ever moves
        alerts = self.get_alerts() or []
        key = "|".join(str(a.get("title") or "") for a in alerts[:3])
        if self._drawn and key == self._last_alert_key:
            return False
        self._last_alert_key = key
        self._drawn = True

        # start clean
        self.clear()
        pen = ImageDraw.Draw(self.surface)
        width, height = self.surface.size

        # the backdrop
        pen.rectangle([0, 0, width, height], fill=theme.BACKGROUND)

        # the header band, with a heavier rule under it
        header_h = self.s(layout.HEADER_H, 40)
        draw.panel(pen, (0, 0, width, header_h), fill=theme.PANEL, outline=None)
        rule = max(2, self.s(4))
        draw.accent_bar(pen, (0, header_h - rule, width, header_h))

        # the identity column
        columns = layout.header_columns(width, self.s)
        self._draw_identity(pen, columns[0], header_h)

        # the page title
        self._draw_title(pen, columns[1], header_h)

        # and the alert strip, when there is anything to say
        if alerts:
            self._draw_alerts(pen, alerts, width, header_h)

        return True

    def _draw_identity(self, pen: ImageDraw.ImageDraw, column: tuple,
                       header_h: int) -> None:
        """
        Draw the logo, channel name, and location

        @param pen: ImageDraw The drawing context
        @param column: tuple The column's left edge and width
        @param header_h: int The header band height
        @return None
        """

        # every block in the band straddles this line
        left, col_width = column
        center = (header_h - max(2, self.s(4))) // 2

        # the logo, or an accent bar standing in for it
        cursor = left
        if self._logo is not None:
            self.surface.paste(self._logo,
                               (left, center - self._logo.height // 2),
                               self._logo)
            cursor = left + self._logo.width + self.s(20)
        else:
            bar = self.s(8, 2)
            bar_h = self.s(72, 8)
            draw.accent_bar(pen, (left, center - bar_h // 2, left + bar,
                                  center - bar_h // 2 + bar_h))
            cursor = left + bar + self.s(20)

        # the channel identity
        available = max(self.s(80), (left + col_width) - cursor)
        name = (self.channel_name or "WEATHER").upper()
        name_face = draw.fit_face(pen, name, "black", self.s(42, 12), available)
        name_size = getattr(name_face, "size", self.s(42, 12))

        # with nothing under it, it takes the centre line on its own
        if not self.location_name:
            draw.text(pen, (cursor, center), name, name_face, theme.TEXT,
                      anchor="lm")
            return

        # otherwise the pair sits either side of it
        location_face = draw.fit_face(pen, self.location_name, "medium",
                                      self.s(28, 10), available)
        location_size = getattr(location_face, "size", self.s(28, 10))
        gap = self.s(10, 2)
        draw.text(pen, (cursor, center - (gap + location_size) // 2), name,
                  name_face, theme.TEXT, anchor="lm")
        draw.text(pen, (cursor, center + (gap + name_size) // 2),
                  self.location_name, location_face, theme.TEXT_DIM,
                  anchor="lm")

    def _draw_title(self, pen: ImageDraw.ImageDraw, column: tuple,
                    header_h: int) -> None:
        """
        Draw the current page's title

        @param pen: ImageDraw The drawing context
        @param column: tuple The column's left edge and width
        @param header_h: int The header band height
        @return None
        """

        # the same centre line the rest of the band uses
        left, col_width = column
        center = (header_h - max(2, self.s(4))) // 2

        # the caption and the title, measured so the pair centres as one
        caption = theme.font("semibold", self.s(20, 9))
        caption_size = getattr(caption, "size", self.s(20, 9))
        face = draw.fit_face(pen, self.page_title, "bold", self.s(34, 11),
                             col_width)
        title_size = getattr(face, "size", self.s(34, 11))
        gap = self.s(10, 2)

        # a small caption over the title itself
        draw.text(pen, (left, center - (gap + title_size) // 2), "NOW SHOWING",
                  caption, theme.TEXT_FAINT, anchor="lm")

        # then the title
        draw.text(pen, (left, center + (gap + caption_size) // 2),
                  self.page_title, face, theme.TEXT, anchor="lm")

    def _draw_alerts(self, pen: ImageDraw.ImageDraw, alerts: list, width: int,
                     header_h: int) -> None:
        """
        Draw the strip that sits under the header when alerts are active

        @param pen: ImageDraw The drawing context
        @param alerts: list The active alerts
        @param width: int The frame width
        @param header_h: int The header band height
        @return None
        """

        # a full width bar in the alert colour
        strip_h = self.s(44, 16)
        top = header_h
        draw.panel(pen, (0, top, width, top + strip_h), fill=theme.ALERT_DIM,
                   outline=None)
        draw.accent_bar(pen, (0, top, self.s(10, 3), top + strip_h),
                        color=theme.ALERT)

        # the leading alert, with a count when there are more behind it
        headline = str(alerts[0].get("title") or "").strip()
        if len(alerts) > 1:
            headline = f"{headline}  (+{len(alerts) - 1} more)"
        face = draw.fit_face(pen, headline, "bold", self.s(24, 10),
                             width - self.s(layout.MARGIN * 2))
        draw.text(pen, (self.s(layout.MARGIN), top + strip_h // 2), headline,
                  face, theme.TEXT, anchor="lm")
