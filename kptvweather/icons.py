#!/usr/bin/env python3
"""
Condition Icons Module

Draws the weather icons procedurally rather than loading artwork, so nothing
has to be bundled and every icon stays crisp at any output resolution. A PNG
dropped into the assets icon folder under the matching name overrides the
drawn version.

Each icon has a short animation loop: drifting cloud, falling drops, that
sort of thing. Frames are rendered once at each size and then reused.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import logging
import math
import threading
from typing import Optional

from PIL import Image, ImageDraw

from . import theme

logger = logging.getLogger(__name__)

# how many frames each animation loop carries
FRAME_COUNT = 24

# the icon names we know how to draw
SUPPORTED = (
    "clear-day", "clear-night", "partly-cloudy-day", "partly-cloudy-night",
    "cloudy", "rain", "snow", "fog", "wind", "thunderstorm",
)

# the palette the drawings use
SUN = (255, 198, 72, 255)
SUN_CORE = (255, 226, 138, 255)
MOON = (226, 234, 248, 255)
CLOUD = (206, 218, 236, 255)
CLOUD_DARK = (150, 166, 192, 255)
DROP = (96, 176, 240, 255)
FLAKE = (222, 238, 255, 255)
BOLT = (255, 208, 84, 255)
GUST = (188, 204, 228, 255)

# rendered loops, keyed by name and size
_CACHE: dict = {}
_LOCK = threading.Lock()


def render(name: str, size: int, frame: int = 0) -> Image.Image:
    """
    Get one animation frame of an icon at a given size

    @param name: str The icon name
    @param size: int The square size to draw at
    @param frame: int Which frame of the loop to return
    @return Image: An RGBA image of exactly the requested size
    """

    # build the loop once, then just index into it
    frames = loop(name, size)
    return frames[frame % len(frames)]


def loop(name: str, size: int) -> list:
    """
    Get the whole animation loop for an icon at a given size

    @param name: str The icon name
    @param size: int The square size to draw at
    @return list: The frames of the loop, in order
    """

    # normalize the inputs so the cache key is stable
    key = (str(name or "cloudy").strip().lower(), max(8, int(size)))

    # hand back a cached loop when we have one
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached

    # an override on disk wins over anything we would draw
    frames = _from_assets(key[0], key[1])
    if frames is None:
        frames = _draw_loop(key[0], key[1])

    # stash it and hand it over
    with _LOCK:
        _CACHE[key] = frames
    return frames


def prewarm(names, sizes) -> None:
    """
    Build the loops for a set of icons up front

    Called before the first frame goes out so playback never stalls halfway
    through drawing an icon nobody had asked for yet.

    @param names: Iterable The icon names to build
    @param sizes: Iterable The sizes to build them at
    @return None
    """

    # just touch each combination
    for name in names:
        for size in sizes:
            try:
                loop(name, int(size))
            except Exception:
                logger.exception("could not prewarm icon %s at %s", name, size)


def _from_assets(name: str, size: int) -> Optional[list]:
    """
    Load an icon override from the assets folder

    A static PNG becomes a single frame loop, which is fine: the animation
    is a nicety, not something the layout depends on.

    @param name: str The icon name
    @param size: int The square size to scale to
    @return list|None: A single frame loop, or None when there is no override
    """

    # look for artwork under the matching name
    path = theme.icon_dir() / f"{name}.png"
    if not path.is_file():
        return None

    # load and scale it, falling back to the drawn version on any trouble
    try:
        with Image.open(path) as handle:
            art = handle.convert("RGBA").resize((size, size), Image.LANCZOS)
        return [art]
    except Exception:
        logger.warning("could not load icon override %s", path)
        return None


def _draw_loop(name: str, size: int) -> list:
    """
    Draw every frame of an icon's loop

    @param name: str The icon name
    @param size: int The square size to draw at
    @return list: The frames of the loop
    """

    # render each phase of the loop in turn
    frames: list = []
    for index in range(FRAME_COUNT):
        phase = index / float(FRAME_COUNT)
        frames.append(_draw_frame(name, size, phase))
    return frames


def _draw_frame(name: str, size: int, phase: float) -> Image.Image:
    """
    Draw one frame of an icon

    @param name: str The icon name
    @param size: int The square size to draw at
    @param phase: float Where in the loop this frame sits, 0.0 to 1.0
    @return Image: The drawn frame
    """

    # supersample so the curves come out smooth, then scale back down
    factor = 3
    canvas = Image.new("RGBA", (size * factor, size * factor), (0, 0, 0, 0))
    pen = ImageDraw.Draw(canvas)
    edge = size * factor

    # dispatch on the name, defaulting to a plain cloud
    if name == "clear-day":
        _sun(pen, edge, phase, 0.5, 0.5, 0.30)
    elif name == "clear-night":
        _moon(pen, edge, 0.5, 0.5, 0.30)
    elif name == "partly-cloudy-day":
        _sun(pen, edge, phase, 0.36, 0.36, 0.22)
        _cloud(pen, edge, phase, 0.56, 0.62, 0.42)
    elif name == "partly-cloudy-night":
        _moon(pen, edge, 0.36, 0.36, 0.22)
        _cloud(pen, edge, phase, 0.56, 0.62, 0.42)
    elif name == "fog":
        _cloud(pen, edge, phase, 0.5, 0.44, 0.44)
        _fog_bars(pen, edge, phase)
    elif name == "wind":
        _gusts(pen, edge, phase)
    elif name == "rain":
        _cloud(pen, edge, phase, 0.5, 0.40, 0.46)
        _drops(pen, edge, phase, DROP)
    elif name == "snow":
        _cloud(pen, edge, phase, 0.5, 0.40, 0.46)
        _flakes(pen, edge, phase)
    elif name == "thunderstorm":
        _cloud(pen, edge, phase, 0.5, 0.38, 0.46, dark=True)
        _bolt(pen, edge, phase)
    else:
        _cloud(pen, edge, phase, 0.5, 0.50, 0.48)

    # scale it down to the requested size
    return canvas.resize((size, size), Image.LANCZOS)


def _circle(pen: ImageDraw.ImageDraw, edge: int, cx: float, cy: float,
            radius: float, color: tuple) -> None:
    """
    Draw a filled circle in fractional coordinates

    @param pen: ImageDraw The drawing context
    @param edge: int The canvas edge length
    @param cx: float Centre x, as a fraction of the edge
    @param cy: float Centre y, as a fraction of the edge
    @param radius: float Radius, as a fraction of the edge
    @param color: tuple The fill colour
    @return None
    """

    # convert to pixels and draw it
    x, y, r = cx * edge, cy * edge, radius * edge
    pen.ellipse([x - r, y - r, x + r, y + r], fill=color)


def _sun(pen: ImageDraw.ImageDraw, edge: int, phase: float, cx: float,
         cy: float, radius: float) -> None:
    """
    Draw the sun with slowly rotating rays

    @param pen: ImageDraw The drawing context
    @param edge: int The canvas edge length
    @param phase: float Where in the loop this frame sits
    @param cx: float Centre x, as a fraction of the edge
    @param cy: float Centre y, as a fraction of the edge
    @param radius: float Disc radius, as a fraction of the edge
    @return None
    """

    # the rays sweep a twelfth of a turn across the loop
    spin = phase * (math.pi / 6.0)
    inner = radius * 1.35
    outer = radius * 1.85
    width = max(1, int(edge * 0.022))

    # eight rays, evenly spaced
    for step in range(8):
        angle = spin + step * (math.pi / 4.0)
        x1 = (cx + math.cos(angle) * inner) * edge
        y1 = (cy + math.sin(angle) * inner) * edge
        x2 = (cx + math.cos(angle) * outer) * edge
        y2 = (cy + math.sin(angle) * outer) * edge
        pen.line([x1, y1, x2, y2], fill=SUN, width=width)

    # the disc, with a lighter core so it does not read flat
    _circle(pen, edge, cx, cy, radius, SUN)
    _circle(pen, edge, cx, cy, radius * 0.68, SUN_CORE)


def _moon(pen: ImageDraw.ImageDraw, edge: int, cx: float, cy: float,
          radius: float) -> None:
    """
    Draw a crescent moon

    @param pen: ImageDraw The drawing context
    @param edge: int The canvas edge length
    @param cx: float Centre x, as a fraction of the edge
    @param cy: float Centre y, as a fraction of the edge
    @param radius: float Disc radius, as a fraction of the edge
    @return None
    """

    # a full disc with a transparent bite taken out of it
    _circle(pen, edge, cx, cy, radius, MOON)
    _circle(pen, edge, cx + radius * 0.42, cy - radius * 0.30, radius * 0.92,
            (0, 0, 0, 0))


def _cloud(pen: ImageDraw.ImageDraw, edge: int, phase: float, cx: float,
           cy: float, width: float, dark: bool = False) -> None:
    """
    Draw a cloud that drifts gently across the loop

    @param pen: ImageDraw The drawing context
    @param edge: int The canvas edge length
    @param phase: float Where in the loop this frame sits
    @param cx: float Centre x, as a fraction of the edge
    @param cy: float Centre y, as a fraction of the edge
    @param width: float Overall width, as a fraction of the edge
    @param dark: bool Whether to use the storm colour
    @return None
    """

    # a slow sideways drift, a couple of percent either way
    drift = math.sin(phase * 2 * math.pi) * width * 0.045
    color = CLOUD_DARK if dark else CLOUD
    base_x = cx + drift

    # three overlapping lobes plus a slab to flatten the bottom
    _circle(pen, edge, base_x - width * 0.28, cy + width * 0.06, width * 0.26, color)
    _circle(pen, edge, base_x + width * 0.02, cy - width * 0.10, width * 0.34, color)
    _circle(pen, edge, base_x + width * 0.30, cy + width * 0.06, width * 0.24, color)
    pen.rectangle([
        (base_x - width * 0.30) * edge, (cy + width * 0.00) * edge,
        (base_x + width * 0.30) * edge, (cy + width * 0.30) * edge,
    ], fill=color)


def _drops(pen: ImageDraw.ImageDraw, edge: int, phase: float,
           color: tuple) -> None:
    """
    Draw falling rain beneath a cloud

    @param pen: ImageDraw The drawing context
    @param edge: int The canvas edge length
    @param phase: float Where in the loop this frame sits
    @param color: tuple The drop colour
    @return None
    """

    # three columns, each offset so they do not fall in lockstep
    width = max(1, int(edge * 0.030))
    for index, offset in enumerate((-0.16, 0.0, 0.16)):
        travel = ((phase + index * 0.33) % 1.0)
        top = 0.62 + travel * 0.24
        x = (0.5 + offset) * edge
        pen.line([x, top * edge, x - edge * 0.02, (top + 0.10) * edge],
                 fill=color, width=width)


def _flakes(pen: ImageDraw.ImageDraw, edge: int, phase: float) -> None:
    """
    Draw drifting snow beneath a cloud

    @param pen: ImageDraw The drawing context
    @param edge: int The canvas edge length
    @param phase: float Where in the loop this frame sits
    @return None
    """

    # same three columns, but they sway as they fall
    radius = 0.026
    for index, offset in enumerate((-0.16, 0.0, 0.16)):
        travel = ((phase + index * 0.33) % 1.0)
        sway = math.sin((travel + index) * 2 * math.pi) * 0.03
        _circle(pen, edge, 0.5 + offset + sway, 0.64 + travel * 0.24, radius,
                FLAKE)


def _bolt(pen: ImageDraw.ImageDraw, edge: int, phase: float) -> None:
    """
    Draw a lightning bolt that flashes once per loop

    @param pen: ImageDraw The drawing context
    @param edge: int The canvas edge length
    @param phase: float Where in the loop this frame sits
    @return None
    """

    # dim for most of the loop, bright for a short flash
    bright = phase < 0.18
    color = BOLT if bright else theme.with_alpha(BOLT, 110)

    # a simple zigzag
    points = [
        (0.54, 0.58), (0.40, 0.80), (0.50, 0.80), (0.42, 0.98),
        (0.62, 0.74), (0.51, 0.74), (0.62, 0.58),
    ]
    pen.polygon([(x * edge, y * edge) for x, y in points], fill=color)


def _fog_bars(pen: ImageDraw.ImageDraw, edge: int, phase: float) -> None:
    """
    Draw the drifting bars that read as fog

    @param pen: ImageDraw The drawing context
    @param edge: int The canvas edge length
    @param phase: float Where in the loop this frame sits
    @return None
    """

    # three bars, each sliding at its own rate
    height = max(1, int(edge * 0.045))
    for index, y in enumerate((0.70, 0.80, 0.90)):
        drift = math.sin((phase + index * 0.3) * 2 * math.pi) * 0.06
        left = (0.20 + drift) * edge
        right = (0.80 + drift) * edge
        pen.rounded_rectangle([left, y * edge, right, y * edge + height],
                              radius=height / 2.0,
                              fill=theme.with_alpha(GUST, 210 - index * 40))


def _gusts(pen: ImageDraw.ImageDraw, edge: int, phase: float) -> None:
    """
    Draw the sweeping lines that read as wind

    @param pen: ImageDraw The drawing context
    @param edge: int The canvas edge length
    @param phase: float Where in the loop this frame sits
    @return None
    """

    # three strokes of different lengths, sliding sideways
    width = max(1, int(edge * 0.05))
    for index, (y, length) in enumerate(((0.34, 0.52), (0.50, 0.66), (0.66, 0.44))):
        drift = math.sin((phase + index * 0.25) * 2 * math.pi) * 0.05
        left = (0.16 + drift) * edge
        right = (0.16 + drift + length) * edge
        pen.line([left, y * edge, right, y * edge], fill=GUST, width=width)

        # a small hook on the end of each stroke
        pen.arc([right - width * 1.4, y * edge - width * 1.6,
                 right + width * 1.4, y * edge + width * 1.2],
                start=270, end=110, fill=GUST, width=width)


def moon_icon(size: int, fraction: Optional[float]) -> Image.Image:
    """
    Draw the moon at a specific phase

    Used by the almanac page, which shows the actual phase rather than a
    generic night icon.

    @param size: int The square size to draw at
    @param fraction: float|None The phase from 0.0 to 1.0
    @return Image: The drawn moon
    """

    # supersample, same as the animated icons
    factor = 3
    edge = max(8, int(size)) * factor
    canvas = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
    pen = ImageDraw.Draw(canvas)

    # the lit disc
    radius = 0.42
    _circle(pen, edge, 0.5, 0.5, radius, MOON)

    # no phase given means just show it full
    if fraction is None:
        return canvas.resize((size, size), Image.LANCZOS)

    # the shadow slides across the disc through the month, so its offset is
    # a cosine of the phase and its side flips at the full moon
    value = float(fraction) % 1.0
    offset = math.cos(value * 2 * math.pi) * radius * 2.0
    _circle(pen, edge, 0.5 + offset, 0.5, radius * 1.02, (0, 0, 0, 0))

    # anything past the halfway point shows the far limb instead
    if 0.25 < value < 0.75:
        _circle(pen, edge, 0.5, 0.5, radius, MOON)
        _circle(pen, edge, 0.5 - offset, 0.5, radius * 1.02, (0, 0, 0, 0))

    return canvas.resize((size, size), Image.LANCZOS)
