#!/usr/bin/env python3
"""
Compositor Module

Flattens every visible layer into one frame. Double buffered so the encoder
is always handed a surface nothing is currently drawing onto.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Iterable

from PIL import Image


class Compositor:
    """
    Builds finished frames from a stack of layers
    """

    def __init__(self, w: int, h: int):
        """
        Allocate the two frame buffers

        @param w: int Frame width
        @param h: int Frame height
        """

        # the surface size and the pair of buffers we swap between
        self.w, self.h = int(w), int(h)
        self.front = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 255))
        self.back = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 255))

        # the flattened backdrop of everything that is not animating
        self._base = None
        self._base_key = None

    def compose(self, layers: Iterable, static_dirty: bool = True) -> None:
        """
        Rebuild the back buffer from the visible layers

        @param layers: Iterable The layer stack, already sorted by z
        @param static_dirty: bool Whether the cached backdrop must be rebuilt
        @return None
        """

        # a page flip moves no pixels of its own, so the backdrop has to
        # follow what is actually on screen as well
        visible_key = tuple(bool(getattr(layer, "visible", True))
                            for layer in layers)
        if visible_key != self._base_key:
            self._base_key = visible_key
            static_dirty = True

        # everything that is not animating gets flattened once and reused,
        # which is what makes compositing on every frame affordable
        if static_dirty or self._base is None:
            if self._base is None:
                self._base = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 255))
            self._base.paste((0, 0, 0, 255), (0, 0, self.w, self.h))
            for layer in layers:
                if getattr(layer, "per_frame", False):
                    continue
                if not getattr(layer, "visible", True):
                    continue
                x, y, w, h = layer.bounds
                if w <= 0 or h <= 0:
                    continue
                self._base.paste(layer.surface, (x, y), layer.surface)

        # then the backdrop, with only the animating layers over the top
        self.back.paste(self._base, (0, 0))
        for layer in layers:
            if not getattr(layer, "per_frame", False):
                continue
            if not getattr(layer, "visible", True):
                continue
            x, y, w, h = layer.bounds
            if w <= 0 or h <= 0:
                continue
            self.back.paste(layer.surface, (x, y), layer.surface)

    def present(self) -> Image.Image:
        """
        Swap the buffers and hand back the finished frame

        @return Image: The completed frame
        """

        # flip them and return whatever just became the front
        self.front, self.back = self.back, self.front
        return self.front
