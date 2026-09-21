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
        self.front = Image.new("RGB", (self.w, self.h), (0, 0, 0))
        self.back = Image.new("RGB", (self.w, self.h), (0, 0, 0))

        # the flattened backdrop of everything that is not animating
        self._base = None
        self._base_key = None

        # buffers still owing a full repaint, and the boxes the animating
        # layers covered on the last two passes
        self._full = 2
        self._prev: list = []
        self._stale: list = []

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
                self._base = Image.new("RGB", (self.w, self.h), (0, 0, 0))
            self._base.paste((0, 0, 0), (0, 0, self.w, self.h))
            self._full = 2
            for layer in layers:
                if getattr(layer, "per_frame", False):
                    continue
                if not getattr(layer, "visible", True):
                    continue
                x, y, w, h = layer.bounds
                if w <= 0 or h <= 0:
                    continue
                self._base.paste(layer.surface, (x, y), layer.surface)

        # the animating layers, and the boxes of backdrop they sit on
        moving: list = []
        for layer in layers:
            if not getattr(layer, "per_frame", False):
                continue
            if not getattr(layer, "visible", True):
                continue
            x, y, w, h = layer.bounds
            if w <= 0 or h <= 0:
                continue
            box = (max(0, x), max(0, y), min(self.w, x + w),
                   min(self.h, y + h))
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            moving.append((layer, (x, y), box))

        # a rebuilt backdrop has to go down whole, and both buffers carry the
        # old one. otherwise only the boxes this buffer is still dirty from
        # two passes ago, plus the ones about to be painted, need restoring
        restore = self._stale + [entry[2] for entry in moving]
        covered = sum((b[2] - b[0]) * (b[3] - b[1]) for b in restore)
        if self._full > 0 or covered * 2 >= self.w * self.h:
            self._full = max(0, self._full - 1)
            self.back.paste(self._base, (0, 0))
        else:
            for box in restore:
                self.back.paste(self._base.crop(box), (box[0], box[1]))

        # then the animating layers over the top
        for layer, origin, _box in moving:
            self.back.paste(layer.surface, origin, layer.surface)

        # this buffer comes round again in two passes carrying these boxes
        self._stale = self._prev
        self._prev = [entry[2] for entry in moving]

    def present(self) -> Image.Image:
        """
        Swap the buffers and hand back the finished frame

        @return Image: The completed frame
        """

        # flip them and return whatever just became the front
        self.front, self.back = self.back, self.front
        return self.front
